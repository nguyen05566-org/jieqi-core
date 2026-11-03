#!/usr/bin/env python3
"""
auto_cycle_ws.py — Pure WebSocket bot (NO browser after token capture).

Flow:
  1. Load token from file (or capture via browser if expired).
  2. WS connect → LOGIN → ENTER_PLACE Lobby.caro.0.
  3. CLAIM loop: VIDEO_REWARD(1) × N with 10s delay until balance >= 50k.
     (Logic from auto_cycle.py claim_until_threshold)
  4. SURRENDER: CREATE_RULE → SET_READY → wait opponent → SURRENDER.
  5. Disconnect.

NO browser, NO Facebook ad, NO Playwright — pure WebSocket!

Usage:
  python3 auto_cycle_ws.py --token-file state/tokens/ck1_token.json \\
    --target-id 72682865 --claim-min 50000
"""
import argparse
import asyncio
import json
import os
import struct
import sys
import time
import random
from pathlib import Path

import websockets

# ======================== BINARY PROTOCOL ========================
CMD_MAP = {
    300: "PONG", 301: "PING", 302: "LOGIN", 303: "ALERT",
    315: "CONFIG", 316: "REQUEST_FREE_CHIP", 317: "TRANSFER",
    401: "ENTER_PLACE", 405: "CREATE_RULE", 406: "PLAYER_ENTERED",
    413: "LIST_BET_AMT", 417: "START_MATCH", 418: "GAMEOVER",
    420: "SET_TURN", 431: "BALANCE_CHANGED", 433: "GET_TABLE_DATA_EX",
    434: "SET_READY", 437: "CREATE_SECRET_TABLE", 438: "ENTER_SECRET_TABLE",
    534: "SURRENDER",
}

class BW:
    def __init__(self): self.p = []
    def u8(self, v): self.p.append(struct.pack('>B', v & 0xFF))
    def i8(self, v): self.p.append(struct.pack('>b', v))
    def i16(self, v): self.p.append(struct.pack('>h', v))
    def i32(self, v): self.p.append(struct.pack('>i', v))
    def i64(self, v): self.p.append(struct.pack('>q', v))
    def wa(self, s): e = s.encode('ascii','replace'); self.u8(len(e)); self.p.append(e)
    def wu(self, s): e = s.encode('utf-16-be'); self.i16(len(e)//2); self.p.append(e)
    def wc(self, n):
        cid = next((k for k,v in CMD_MAP.items() if v == n), None)
        if cid: self.p.append(struct.pack('>H', cid))
        else:
            b = n.encode('ascii'); self.i8(-len(b)); self.p.append(b)
    def build(self): return b''.join(self.p)

class BR:
    def __init__(self, d): self.d = d; self.pos = 0
    def rem(self): return len(self.d) - self.pos
    def u8(self): v = self.d[self.pos]; self.pos += 1; return v
    def i8(self): v = struct.unpack_from('>b', self.d, self.pos)[0]; self.pos += 1; return v
    def i16(self): v = struct.unpack_from('>h', self.d, self.pos)[0]; self.pos += 2; return v
    def i32(self): v = struct.unpack_from('>i', self.d, self.pos)[0]; self.pos += 4; return v
    def i64(self):
        hi = struct.unpack_from('>i', self.d, self.pos)[0]
        lo = struct.unpack_from('>I', self.d, self.pos+4)[0]
        self.pos += 8; return (hi << 32) | lo
    def ra(self): n = self.u8(); s = self.d[self.pos:self.pos+n].decode('ascii','replace'); self.pos += n; return s
    def ru(self):
        n = self.i16()
        if n <= 0: return ""
        s = self.d[self.pos:self.pos+n*2].decode('utf-16-be','replace'); self.pos += n*2; return s
    def rc(self):
        f = self.i8()
        if f < 0: n = -f; s = self.d[self.pos:self.pos+n].decode('ascii','replace'); self.pos += n; return s
        s = self.u8(); cid = (f << 8) | s; return CMD_MAP.get(cid, f"CMD_{cid}")

def log(msg=""): print(msg, flush=True)

# ======================== WS BOT ========================
class WSBot:
    def __init__(self, ws):
        self.ws = ws
        self.balance = 0
        self.slot = -1

    async def send(self, data): await self.ws.send(data)

    async def recv_cmd(self, timeout=3):
        """Receive one frame, return (cmd_name, reader, raw_bytes). None on timeout/error."""
        try:
            r = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
            if isinstance(r, bytes):
                br = BR(r)
                cmd = br.rc()
                return cmd, br, r
        except (asyncio.TimeoutError, Exception):
            pass
        return None, None, None

    async def send_pong(self):
        try: await self.ws.send(BW().wc("PONG").build())
        except Exception: pass

    async def drain(self, seconds=2):
        """Drain pending messages for N seconds, handling PING."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            cmd, br, raw = await self.recv_cmd(timeout=1)
            if cmd is None: break
            if cmd == "PING": await self.send_pong()
            elif cmd == "BALANCE_CHANGED" and br.rem() >= 9:
                self.slot = br.i8(); self.balance = br.i64()

    async def login_replay(self, frames):
        """Replay captured LOGIN + setup frames."""
        log("[WS] Replaying login frames...")
        for fb in frames:
            await self.send(fb)
            await asyncio.sleep(0.3)
            try:
                cmd, br, raw = await self.recv_cmd(timeout=1)
                if cmd == "PING": await self.send_pong()
            except: pass

    async def enter_lobby(self):
        """ENTER_PLACE Lobby.caro.0."""
        log("[WS] ENTER_PLACE Lobby.caro.0...")
        ew = BW(); ew.wc("ENTER_PLACE"); ew.wa("Lobby.caro.0"); ew.wu(""); ew.i8(1)
        await self.send(ew.build())
        await self.drain(3)

    async def read_balance(self):
        """Send GET_TABLE_DATA_EX, extract balance."""
        w = BW(); w.wc("GET_TABLE_DATA_EX"); w.wa("")
        await self.send(w.build())
        for _ in range(5):
            cmd, br, raw = await self.recv_cmd(timeout=3)
            if cmd is None: break
            if cmd == "BALANCE_CHANGED" and br.rem() >= 9:
                self.slot = br.i8(); self.balance = br.i64()
                return self.balance
            elif cmd == "PING": await self.send_pong()
        return self.balance

    # ======================== CLAIM (VIDEO_REWARD) ========================
    async def claim_once(self):
        """Send one VIDEO_REWARD(1), return (success, amount)."""
        # VIDEO_REWARD as string command: i8(-12) + "VIDEO_REWARD" + byte(1)
        vr = struct.pack('b', -12) + b"VIDEO_REWARD" + struct.pack('B', 1)
        await self.send(vr)

        got_response = False
        claim_amount = 0
        deadline = time.time() + 15
        while time.time() < deadline:
            cmd, br, raw = await self.recv_cmd(timeout=2)
            if cmd is None: break
            if cmd == "VIDEO_REWARD":
                got_response = True
                if br.rem() >= 9:
                    status = br.i8()
                    amount = br.i64()
            elif cmd == "BALANCE_CHANGED" and br.rem() >= 9:
                self.slot = br.i8()
                new_bal = br.i64()
                if new_bal > self.balance:
                    claim_amount = new_bal - self.balance
                self.balance = new_bal
            elif cmd == "PING":
                await self.send_pong()
            if got_response and claim_amount > 0:
                break

        return got_response, claim_amount

    async def claim_until_threshold(self, claim_min, claim_max, max_claims=200):
        """Claim VIDEO_REWARD until balance in [claim_min, claim_max].
        Logic from auto_cycle.py claim_until_threshold:
          - 10s cooldown between claims (server requires this)
          - Stop if 6 consecutive fails
          - Stop if server returns "no response"
        """
        log(f"\n[CLAIM] claiming until balance in [{claim_min:,}, {claim_max:,}] (max {max_claims})...")
        claims_ok = 0
        claims_fail = 0
        consec_fail = 0
        total_claimed = 0

        for i in range(max_claims):
            if self.balance >= claim_min:
                log(f"  [t={i}] balance {self.balance:,} >= {claim_min:,} ✓ stopping")
                break

            got_resp, amount = await self.claim_once()

            if amount > 0:
                claims_ok += 1
                consec_fail = 0
                total_claimed += amount
                log(f"  [t={i}] ✓ claim +{amount} | balance: {self.balance:,} | total: {total_claimed:,}")
            else:
                claims_fail += 1
                consec_fail += 1
                err = "no response" if not got_resp else "no balance change"
                log(f"  [t={i}] ✗ claim FAIL ({err}) | consec={consec_fail}")
                if not got_resp:
                    log(f"  [stop] server rejected VIDEO_REWARD")
                    break
                if consec_fail >= 6:
                    log(f"  [stop] 6 consecutive failures")
                    break

            # Cooldown: 10s + jitter (server requires ~10s between claims)
            # (auto_cycle.py uses 3s + JS overhead ~6s = ~10s effective)
            jitter = random.uniform(0.5, 1.5)
            cooldown = 10.0 + jitter
            await asyncio.sleep(cooldown)

        log(f"[CLAIM done] {claims_ok} OK / {claims_fail} fail | final: {self.balance:,} | claimed: {total_claimed:,}")
        return claims_ok, total_claimed

    # ======================== SURRENDER ========================
    async def create_table(self, bet_amt_id=5):
        """CREATE_RULE to create a table. bet_amt_id=5 = 1000 xu."""
        log(f"[SURRENDER] creating table (bet_id={bet_amt_id})...")
        w = BW(); w.wc("CREATE_RULE"); w.i8(bet_amt_id)
        args = [("matchDuration","1800"),("turnDuration","60"),("accDuration","2"),("blockSoftware","0")]
        w.i8(len(args))
        for n, v in args: w.wa(n); w.wu(v)
        await self.send(w.build())

        deadline = time.time() + 10
        while time.time() < deadline:
            cmd, br, raw = await self.recv_cmd(timeout=3)
            if cmd is None: continue
            if cmd == "PLAYER_ENTERED":
                log(f"  ✓ Table created! (PLAYER_ENTERED)")
                await self.drain(3)
                return True
            elif cmd == "PING": await self.send_pong()
            elif cmd == "BALANCE_CHANGED" and br.rem() >= 9:
                self.slot = br.i8(); self.balance = br.i64()
        return False

    async def ready_wait_surrender(self, max_wait=120):
        """Detect seated vs spectating. If seated → SET_READY → wait START_MATCH → 3s → SURRENDER.
        If spectating → wait GAMEOVER → return 'spectating'.
        Returns (status, lost): status = 'surrendered'/'spectating'/'timeout'."""
        bal_before = self.balance
        log(f"  balance: {bal_before:,} | slot={self.slot}")

        # Check if seated (slot >= 0) or spectating (slot < 0)
        if self.slot < 0:
            log(f"  [SPECTATING] slot={self.slot} — waiting for GAMEOVER to get a seat...")
            deadline = time.time() + max_wait
            while time.time() < deadline:
                cmd, br, raw = await self.recv_cmd(timeout=3)
                if cmd is None: continue
                if cmd == "PING": await self.send_pong()
                elif cmd == "GAMEOVER":
                    log(f"  Game over — trying to join seat...")
                    # After GAMEOVER, table might have a free seat — re-ENTER_PLACE
                    await asyncio.sleep(2)
                    return "spectating", 0
                elif cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                    self.slot = br.i8(); self.balance = br.i64()
                    if self.slot >= 0:
                        log(f"  ✓ Got seat! slot={self.slot}")
                        break
            if self.slot < 0:
                log(f"  [!] Still spectating after {max_wait}s")
                return "spectating", 0

        # Seated (slot >= 0) → SET_READY → wait START_MATCH → SURRENDER
        log(f"  [SEATED] slot={self.slot} → SET_READY")
        w = BW(); w.wc("SET_READY")
        await self.send(w.build())

        # Wait for START_MATCH (max 120s — target needs to ready)
        log(f"  Waiting for START_MATCH (max {max_wait}s)...")
        deadline = time.time() + max_wait
        game_started = False
        while time.time() < deadline:
            cmd, br, raw = await self.recv_cmd(timeout=2)
            if cmd is None: continue
            if cmd == "START_MATCH":
                game_started = True
                log(f"  ✓ GAME STARTED!")
                break
            elif cmd == "PING": await self.send_pong()
            elif cmd == "SET_TURN" and not game_started:
                # Lobby countdown — re-SET_READY
                w2 = BW(); w2.wc("SET_READY"); await self.send(w2.build())
            elif cmd == "PLAYER_ENTERED":
                w2 = BW(); w2.wc("SET_READY"); await self.send(w2.build())
            elif cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                self.slot = br.i8(); self.balance = br.i64()
            elif cmd == "GAMEOVER":
                log(f"  Game over (without us?) — retry")
                return "spectating", 0

        if not game_started:
            log(f"  [!] Game didn't start in {max_wait}s")
            return "timeout", 0

        # SURRENDER after 3s (let game state settle)
        await asyncio.sleep(3)
        log(f"  Sending SURRENDER...")
        w = BW(); w.wc("SURRENDER")
        await self.send(w.build())

        # Wait for balance change (confirm xu lost)
        deadline = time.time() + 15
        while time.time() < deadline:
            cmd, br, raw = await self.recv_cmd(timeout=2)
            if cmd is None: continue
            if cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                self.slot = br.i8(); self.balance = br.i64()
                if self.balance < bal_before:
                    lost = bal_before - self.balance
                    log(f"  ✓✓ SURRENDER SUCCESS! lost {lost:,} xu ✓✓")
                    return "surrendered", lost
            elif cmd == "PING": await self.send_pong()
            elif cmd == "GAMEOVER":
                log(f"  Game over")

        log(f"  [!] No balance change after surrender")
        return "timeout", 0

    async def find_target_table(self, target_name, target_id):
        """Find target's table via LIST_ZONE_TABLE — search for name (UTF-16-BE).
        Returns table_id (int) or None."""
        import struct as _struct
        w = BW(); w.wc("LIST_ZONE_TABLE"); w.wa("")
        await self.send(w.build())

        raw = b""
        for _ in range(5):
            cmd, br, r = await self.recv_cmd(timeout=3)
            if cmd is None: break
            raw += r
            if cmd == "PING": await self.send_pong()
            elif cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                self.slot = br.i8(); self.balance = br.i64()

        if not raw:
            log(f"  No lobby data")
            return None

        # Search for target name (UTF-16-BE)
        name_bytes = target_name.encode('utf-16-be')
        pos = raw.find(name_bytes)
        if pos < 0:
            # Also try target_id as i64
            if target_id and target_id > 0:
                pid_bytes = _struct.pack('>q', target_id)
                pos = raw.find(pid_bytes)
            if pos < 0:
                log(f"  Target '{target_name}' not found in lobby ({len(raw)}B)")
                return None

        log(f"  ✓ Found '{target_name}' at offset {pos}")

        # Extract table ID: search backwards for i16 in range 9000-9999
        for i in range(pos - 2, max(0, pos - 50), -1):
            val = _struct.unpack_from('>H', raw, i)[0]
            if 9000 <= val <= 9999:
                log(f"  Table ID: {val}")
                return val

        # Wider range
        for i in range(pos - 2, max(0, pos - 100), -1):
            val = _struct.unpack_from('>H', raw, i)[0]
            if 1000 <= val <= 99999:
                log(f"  Table ID (wide): {val}")
                return val

        log(f"  Could not extract table ID")
        return None

    async def join_table(self, table_id):
        """ENTER_PLACE to join a specific table."""
        path = f"Lobby.caro.0.{table_id}"
        log(f"  ENTER_PLACE → {path}")
        w = BW(); w.wc("ENTER_PLACE"); w.wa(path); w.wu(""); w.i8(1)
        await self.send(w.build())

        for _ in range(8):
            cmd, br, r = await self.recv_cmd(timeout=3)
            if cmd is None: break
            if cmd == "ENTER_PLACE" and br and br.rem() > 0:
                status = br.i8()
                log(f"  ENTER_PLACE status={status}")
                if status == 0:
                    await self.drain(3)
                    return True
            elif cmd == "PING": await self.send_pong()
            elif cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                self.slot = br.i8(); self.balance = br.i64()
            elif cmd == "START_MATCH":
                return True  # already in game
        return False

# ======================== MAIN ========================
async def main():
    parser = argparse.ArgumentParser(description="Pure WS bot — continuous claim + surrender")
    parser.add_argument("--token-file", required=True, help="Path to token JSON file")
    parser.add_argument("--target-name", default=os.environ.get("TARGET_NAME", "nguyen123456"))
    parser.add_argument("--target-id", type=int, default=int(os.environ.get("TARGET_ID", "68982512")))
    parser.add_argument("--claim-min", type=int, default=int(os.environ.get("CLAIM_MIN", "40000")))
    parser.add_argument("--claim-max", type=int, default=int(os.environ.get("CLAIM_MAX", "55000")))
    parser.add_argument("--bet-id", type=int, default=int(os.environ.get("BET_ID", "10")))
    parser.add_argument("--max-claims", type=int, default=int(os.environ.get("MAX_CLAIMS", "30")))
    parser.add_argument("--runtime", type=int, default=int(os.environ.get("RUNTIME_SECONDS", "1800")),
                        help="Total runtime in seconds (default 1800 = 30 min)")
    args = parser.parse_args()

    data = json.loads(Path(args.token_file).read_text())
    ws_url = data["ws_url"]
    login_frames = [bytes.fromhex(h) for h in data["frames"]]

    log(f"{'='*60}")
    log(f"PURE WS BOT — continuous loop")
    log(f"  Token: {args.token_file}")
    log(f"  Target: {args.target_name} (id={args.target_id})")
    log(f"  Claim range: [{args.claim_min:,}, {args.claim_max:,}]")
    log(f"  Runtime: {args.runtime}s ({args.runtime//60} min)")
    log(f"{'='*60}")

    deadline = time.time() + args.runtime
    cycle = 0
    total_surrendered = 0
    total_claimed = 0

    async with websockets.connect(ws_url, ping_interval=None, max_size=2**20, open_timeout=15) as ws:
        bot = WSBot(ws)
        await bot.login_replay(login_frames)
        await bot.enter_lobby()
        await bot.read_balance()
        log(f"\nInitial balance: {bot.balance:,}")

        while time.time() < deadline:
            cycle += 1
            log(f"\n{'='*40} CYCLE {cycle} {'='*40}")

            # Phase 1: CLAIM until ≥ claim_min
            if bot.balance < args.claim_min:
                log(f"\n[Phase 1] Claim until {args.claim_min:,} xu...")
                claims_ok, claimed = await bot.claim_until_threshold(
                    args.claim_min, args.claim_max, args.max_claims)
                total_claimed += claimed
            else:
                log(f"\n[Phase 1] Balance {bot.balance:,} ≥ {args.claim_min:,} — skip claim")
                claims_ok = 0

            if bot.balance < args.claim_min:
                log(f"[STOP] Can't claim enough xu (balance {bot.balance:,} < {args.claim_min:,})")
                break

            # Phase 2: FIND TARGET
            log(f"\n[Phase 2] Find target '{args.target_name}'...")
            table_id = await bot.find_target_table(args.target_name, args.target_id)

            if not table_id:
                log(f"  Target not found — waiting 30s then retry...")
                await asyncio.sleep(30)
                continue

            # Phase 3: JOIN TABLE
            log(f"\n[Phase 3] Join table {table_id}...")
            joined = await bot.join_table(table_id)
            if not joined:
                log(f"  Join failed — retry next cycle")
                await asyncio.sleep(10)
                continue

            # Phase 4: SURRENDER (with seated/spectating detection)
            log(f"\n[Phase 4] Surrender...")
            status, lost = await bot.ready_wait_surrender(max_wait=120)

            if status == "surrendered":
                total_surrendered += lost
                log(f"\n  ✓ Cycle {cycle} done: surrendered {lost:,} xu")
            elif status == "spectating":
                log(f"\n  Was spectating — retry join after GAMEOVER...")
                # Re-join the same table
                await asyncio.sleep(3)
                joined2 = await bot.join_table(table_id)
                if joined2:
                    status2, lost2 = await bot.ready_wait_surrender(max_wait=120)
                    if status2 == "surrendered":
                        total_surrendered += lost2
                        log(f"\n  ✓ Cycle {cycle} retry: surrendered {lost2:,} xu")
            elif status == "timeout":
                log(f"\n  Timeout — next cycle")

            # Check runtime
            remaining = deadline - time.time()
            if remaining < 30:
                log(f"\n[Runtime ending] {remaining:.0f}s left — stopping")
                break

            # Brief pause between cycles
            log(f"\n  Next cycle in 5s... ({remaining:.0f}s remaining)")
            await asyncio.sleep(5)

    log(f"\n{'='*60}")
    log(f"FINAL SUMMARY")
    log(f"{'='*60}")
    log(f"  Cycles: {cycle}")
    log(f"  Total claimed: {total_claimed:,} xu")
    log(f"  Total surrendered: {total_surrendered:,} xu")
    log(f"  Final balance: {bot.balance:,}")
    log(f"  Runtime: {(time.time() - (deadline - args.runtime)):.0f}s")

if __name__ == "__main__":
    asyncio.run(main())
