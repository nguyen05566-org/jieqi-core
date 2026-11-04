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

    async def send(self, data):
        try: await self.ws.send(data)
        except Exception: pass  # connection closed — ignore

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
        """Replay captured LOGIN + setup frames. Parse BALANCE_CHANGED for initial balance."""
        log("[WS] Replaying login frames...")
        for fb in frames:
            await self.send(fb)
            await asyncio.sleep(0.3)
            try:
                cmd, br, raw = await self.recv_cmd(timeout=1)
                if cmd == "PING": await self.send_pong()
                elif cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                    self.slot = br.i8(); self.balance = br.i64()
                    log(f"  [login] balance: {self.balance:,}")
            except: pass

    async def enter_lobby(self):
        """ENTER_PLACE Lobby.caro.0. Parse BALANCE_CHANGED."""
        log("[WS] ENTER_PLACE Lobby.caro.0...")
        ew = BW(); ew.wc("ENTER_PLACE"); ew.wa("Lobby.caro.0"); ew.wu(""); ew.i8(1)
        await self.send(ew.build())
        await self.drain(3)
        # If balance still 0, try GET_TABLE_DATA_EX
        if self.balance == 0:
            await self.read_balance()

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
        video_reward_blocked = False

        for i in range(max_claims):
            if self.balance >= claim_max and self.balance > 0:
                log(f"  [t={i}] balance {self.balance:,} >= {claim_max:,} ✓ claim max reached")
                break
            if self.balance >= claim_min and self.balance > 0:
                log(f"  [t={i}] balance {self.balance:,} >= {claim_min:,} ✓ enough, go surrender")
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
                log(f"  [t={i}] ✗ claim FAIL ({err}) | balance: {self.balance:,}")
                if not got_resp:
                    # VIDEO_REWARD blocked → go surrender IMMEDIATELY
                    # (balance might be high but reads as 0 — don't waste time retrying)
                    log(f"  [blocked] VIDEO_REWARD blocked → go surrender now!")
                    video_reward_blocked = True
                    break
                if consec_fail >= 3:
                    log(f"  [stop] 3 consecutive failures → go surrender")
                    break

            # Cooldown: 10s + jitter
            jitter = random.uniform(0.5, 1.5)
            await asyncio.sleep(10.0 + jitter)

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

    async def ready_wait_surrender(self, max_wait=20):
        """Seated → SET_READY → wait START_MATCH (max 20s, game auto-starts after 10s)
        → SURRENDER → wait GAMEOVER + balance change (max 30s).
        If spectating → wait GAMEOVER (max 30s) → return 'spectating'."""
        bal_before = self.balance
        log(f"  balance: {bal_before:,} | slot={self.slot}")

        # Check if seated (slot >= 0) or spectating (slot < 0)
        if self.slot < 0:
            log(f"  [SPECTATING] slot={self.slot} — waiting for GAMEOVER (max 30s)...")
            deadline = time.time() + 30
            while time.time() < deadline:
                cmd, br, raw = await self.recv_cmd(timeout=3)
                if cmd is None: continue
                if cmd == "PING": await self.send_pong()
                elif cmd == "GAMEOVER":
                    log(f"  Game over — re-join to get seat")
                    await asyncio.sleep(2)
                    return "spectating", 0
                elif cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                    self.slot = br.i8(); self.balance = br.i64()
                    if self.slot >= 0:
                        log(f"  ✓ Got seat! slot={self.slot}")
                        break
            if self.slot < 0:
                return "spectating", 0

        # Seated → wait 3s → SET_READY (game auto-starts after ~10s, don't wait long)
        log(f"  [SEATED] slot={self.slot} → wait 3s → SET_READY")
        await asyncio.sleep(3)
        w = BW(); w.wc("SET_READY")
        await self.send(w.build())

        # Wait for START_MATCH (max 20s — game auto-starts after 10s)
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
                w2 = BW(); w2.wc("SET_READY"); await self.send(w2.build())
            elif cmd == "PLAYER_ENTERED":
                w2 = BW(); w2.wc("SET_READY"); await self.send(w2.build())
            elif cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                self.slot = br.i8(); self.balance = br.i64()
            elif cmd == "GAMEOVER":
                # Game might have started and ended quickly — check balance
                if self.balance < bal_before:
                    lost = bal_before - self.balance
                    log(f"  ✓✓ GAMEOVER — lost {lost:,} xu ✓✓")
                    return "surrendered", lost
                log(f"  Game over (balance unchanged) — retry")
                return "spectating", 0

        # Send SURRENDER regardless (game might have auto-started without START_MATCH msg)
        log(f"  Sending SURRENDER...")
        w = BW(); w.wc("SURRENDER")
        await self.send(w.build())

        # Wait for GAMEOVER + balance change (max 30s — game might take time to end)
        deadline = time.time() + 30
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
                # Check balance after GAMEOVER (balance might update after)
                log(f"  GAMEOVER — checking balance...")
                # Wait a bit more for balance update
                for _ in range(3):
                    cmd2, br2, raw2 = await self.recv_cmd(timeout=2)
                    if cmd2 == "BALANCE_CHANGED" and br2 and br2.rem() >= 9:
                        self.slot = br2.i8(); self.balance = br2.i64()
                        if self.balance < bal_before:
                            lost = bal_before - self.balance
                            log(f"  ✓✓ SURRENDER SUCCESS! lost {lost:,} xu ✓✓")
                            return "surrendered", lost
                    elif cmd2 == "PING": await self.send_pong()
                # Balance didn't change — but GAMEOVER means game ended
                if self.balance != bal_before:
                    lost = bal_before - self.balance if self.balance < bal_before else 0
                    if lost > 0:
                        log(f"  ✓✓ Balance changed: lost {lost:,} xu ✓✓")
                        return "surrendered", lost
                log(f"  Game over but no balance change detected")

        log(f"  [!] No balance change after surrender (balance: {self.balance:,} vs {bal_before:,})")
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
                log(f"  Target '{target_name}' (id={target_id}) not found in lobby ({len(raw)}B)")
                # Dump all names found for debugging
                i = 0
                while i < len(raw) - 3:
                    if raw[i] == 0 and 0 < raw[i+1] < 20:
                        nlen = raw[i+1]
                        if i + 2 + nlen * 2 <= len(raw):
                            try:
                                nm = raw[i+2:i+2+nlen*2].decode('utf-16-be', 'replace')
                                if nm.isprintable() and len(nm) >= 2:
                                    log(f"    lobby player: \"{nm}\"")
                            except: pass
                        i += 2 + nlen * 2
                    else:
                        i += 1
                return None

        log(f"  ✓ Found '{target_name}' at offset {pos}")

        # Extract table ID: it's exactly 4 bytes before the name
        # Format: <table_id_hi 1B> <table_id_lo 1B> <00 1B> <name_len 1B> <name UTF-16>
        # table_id (2 bytes big-endian) is at pos-4 and pos-3
        if pos >= 4:
            table_id = _struct.unpack_from('>H', raw, pos - 4)[0]
            # Verify: byte at pos-1 should be name length, pos-2 should be 0x00
            expected_len = len(target_name)
            actual_len = raw[pos - 1] if pos - 1 < len(raw) else 0
            separator = raw[pos - 2] if pos - 2 < len(raw) else 0xFF
            if actual_len == expected_len and separator == 0x00:
                log(f"  Table ID: {table_id} (verified: name_len={actual_len}, sep=0x00)")
                return table_id
            elif actual_len == expected_len:
                log(f"  Table ID: {table_id} (name_len OK, sep={separator:#x})")
                return table_id
            else:
                log(f"  Table ID candidate: {table_id} (name_len mismatch: {actual_len}≠{expected_len})")
                if 1000 <= table_id <= 99999:
                    return table_id

        # Fallback: search backwards for 019f pattern
        for i in range(pos - 2, max(0, pos - 50), -1):
            if raw[i] == 0x01 and i + 1 < len(raw) and raw[i+1] == 0x9f:
                table_id = _struct.unpack_from('>H', raw, i + 2)[0]
                log(f"  Table ID: {table_id} (from 019f pattern at offset {i})")
                return table_id

        # Last resort: wide range search
        for i in range(pos - 2, max(0, pos - 50), -1):
            val = _struct.unpack_from('>H', raw, i)[0]
            if 1000 <= val <= 99999:
                log(f"  Table ID (wide): {val}")
                return val

        log(f"  Could not extract table ID")
        return None

    async def join_table(self, table_id):
        """ENTER_PLACE to join a table. Wait 5s, then GET_TABLE_DATA_EX to check slot."""
        path = f"Lobby.caro.0.{table_id}"
        log(f"  ENTER_PLACE → {path}")
        w = BW(); w.wc("ENTER_PLACE"); w.wa(path); w.wu(""); w.i8(1)
        await self.send(w.build())

        # Wait for ENTER_PLACE response
        joined = False
        for _ in range(8):
            cmd, br, r = await self.recv_cmd(timeout=3)
            if cmd is None: break
            if cmd == "ENTER_PLACE" and br and br.rem() > 0:
                status = br.i8()
                log(f"  ENTER_PLACE status={status}")
                if status == 0: joined = True
            elif cmd == "PING": await self.send_pong()
            elif cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                self.slot = br.i8(); self.balance = br.i64()
            elif cmd == "START_MATCH":
                return True  # already in game

        if not joined:
            return False

        # Wait 5s for table state to settle, then GET_TABLE_DATA_EX
        log(f"  Waiting 5s for table state...")
        await asyncio.sleep(5)

        # Send GET_TABLE_DATA_EX to get slot info
        gw = BW(); gw.wc("GET_TABLE_DATA_EX"); gw.wa("")
        await self.send(gw.build())

        for _ in range(8):
            cmd, br, r = await self.recv_cmd(timeout=3)
            if cmd is None: break
            if cmd == "GET_TABLE_DATA_EX" and br:
                # Parse table data to extract slot
                try:
                    first = br.i8()  # status byte
                    if first == 0 and br.rem() > 0:
                        # Skip seats structure
                        seat_count = br.u8()
                        for _ in range(seat_count):
                            if br.rem() < 3: break
                            br.u8()  # seat id
                            br.ra()  # some ascii
                            br.u8()  # status
                            child_count = br.u8()
                            for _ in range(child_count):
                                if br.rem() < 5: break
                                br.u8(); br.ra(); br.ru(); br.u8(); br.u8()
                        if br.rem() >= 2:
                            br.u8()  # ???
                            self.slot = br.i8()  # SLOT NUMBER!
                            log(f"  Slot={self.slot} ({'seated' if self.slot >= 0 else 'spectating'})")
                except Exception as e:
                    log(f"  Table parse error: {e}")
            elif cmd == "PING": await self.send_pong()
            elif cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                self.slot = br.i8(); self.balance = br.i64()
            elif cmd == "PLAYER_ENTERED":
                log(f"  Player entered table")

        return True

# ======================== MAIN ========================
async def main():
    parser = argparse.ArgumentParser(description="Pure WS bot — continuous claim + surrender")
    parser.add_argument("--token-file", required=True, help="Path to token JSON file")
    parser.add_argument("--target-name", default=os.environ.get("TARGET_NAME", "nguyen123456"))
    parser.add_argument("--target-id", type=int, default=int(os.environ.get("TARGET_ID", "68982512")))
    parser.add_argument("--claim-min", type=int, default=int(os.environ.get("CLAIM_MIN", "40000")))
    parser.add_argument("--claim-max", type=int, default=int(os.environ.get("CLAIM_MAX", "50000")),
                        help="Max balance — game blocks VIDEO_REWARD above this (default 50000)")
    parser.add_argument("--bet-id", type=int, default=int(os.environ.get("BET_ID", "10")))
    parser.add_argument("--max-claims", type=int, default=int(os.environ.get("MAX_CLAIMS", "100")))
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

            # Phase 1: CLAIM (if balance readable and < claim_max)
            if 0 < bot.balance < args.claim_min:
                log(f"\n[Phase 1] Claim until {args.claim_min:,} xu...")
                claims_ok, claimed = await bot.claim_until_threshold(
                    args.claim_min, args.claim_max, args.max_claims)
                total_claimed += claimed
            elif bot.balance >= args.claim_min:
                log(f"\n[Phase 1] Balance {bot.balance:,} ≥ {args.claim_min:,} — skip claim, go surrender")
            else:
                # Balance = 0 (not read) — try claim once, if blocked go surrender
                log(f"\n[Phase 1] Balance unknown — try claim...")
                claims_ok, claimed = await bot.claim_until_threshold(
                    args.claim_min, args.claim_max, args.max_claims)
                total_claimed += claimed

            # ALWAYS proceed to surrender — BUT only if balance ≥ claim_min
            # (if balance too low, surrender won't transfer meaningful xu)
            if 0 < bot.balance < args.claim_min:
                log(f"\n[SKIP] Balance {bot.balance:,} < {args.claim_min:,} — can't surrender meaningful amount")
                log(f"  VIDEO_REWARD likely exhausted for today — wait 60s, retry")
                await asyncio.sleep(60)
                continue

            # Phase 2: FIND TARGET (retry scan 3 times)
            log(f"\n[Phase 2] Find target '{args.target_name}'...")
            table_id = None
            for scan_attempt in range(3):
                table_id = await bot.find_target_table(args.target_name, args.target_id)
                if table_id:
                    break
                if scan_attempt < 2:
                    log(f"  Retry scan in 20s... ({scan_attempt+1}/3)")
                    await asyncio.sleep(20)

            if not table_id:
                log(f"  Target not found after 3 scans — next cycle")
                await asyncio.sleep(15)
                continue

            # Phase 3: JOIN TABLE
            log(f"\n[Phase 3] Join table {table_id}...")
            joined = await bot.join_table(table_id)
            if not joined:
                log(f"  Join failed — retry next cycle")
                await asyncio.sleep(10)
                continue

            # Phase 4: SURRENDER (with seated/spectating detection)
            # Loop: if spectating → wait GAMEOVER → retry join → until seated or timeout
            surrender_done = False
            for attempt in range(5):  # max 5 attempts to get seated
                log(f"\n[Phase 4] Surrender (attempt {attempt+1}/5)...")
                status, lost = await bot.ready_wait_surrender(max_wait=120)

                if status == "surrendered":
                    total_surrendered += lost
                    log(f"\n  ✓ Cycle {cycle} done: surrendered {lost:,} xu")
                    surrender_done = True
                    break
                elif status == "spectating":
                    log(f"\n  [Spectating] Table full — wait GAMEOVER then retry join...")
                    await asyncio.sleep(3)
                    joined2 = await bot.join_table(table_id)
                    if not joined2:
                        log(f"  Re-join failed — retry next cycle")
                        break
                    # Loop back to ready_wait_surrender with new seat
                elif status == "timeout":
                    log(f"\n  Timeout — retry join...")
                    await asyncio.sleep(5)
                    joined2 = await bot.join_table(table_id)
                    if not joined2:
                        log(f"  Re-join failed — next cycle")
                        break
                # Continue loop to try again

            if not surrender_done:
                log(f"\n  Could not surrender this cycle — next cycle")

            # Return to lobby after surrender (bot might still be in ended table)
            log(f"\n  Return to lobby...")
            ret = BW(); ret.wc("ENTER_PLACE"); ret.wa("Lobby.caro.0"); ret.wu(""); ret.i8(1)
            await bot.send(ret.build())
            await bot.drain(3)

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
