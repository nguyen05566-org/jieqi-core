#!/usr/bin/env python3
"""
ws_bot_ck2.py — Pure WebSocket bot (NO browser after token capture).
Cờ Caro — tạo bàn tự chơi + surrender (không cần tìm target).

Flow:
  1. Load token từ state/tokens/ck2_token.json (ws_url + frames).
     Nếu chưa có token, tự động chạy capture_token.py từ ck2.txt (cookie)
     để sinh token trước khi chạy bot.
  2. WS connect → LOGIN (replay frames) → ENTER_PLACE Lobby.caro.0.
  3. CLAIM VIDEO_REWARD cho đủ balance (tùy chọn).
  4. TẠO BÀN (CREATE_RULE) → SET_READY → chờ START_MATCH → SURRENDER.
  5. Lặp lại cho đến khi hết runtime.

NO browser, NO Facebook ad, NO Playwright — pure WebSocket!
Dùng cookie ck2.txt → capture token → websocket. Không cần tìm target.

Usage:
  python3 ws_bot_ck2.py --cookie-file ck2.txt --token-file state/tokens/ck2_token.json
  (nếu token chưa có, bot sẽ tự chạy capture_token.py để sinh từ cookie)
"""
import argparse
import asyncio
import json
import os
import struct
import subprocess
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
        return self
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
        await self.ws.send(data)

    async def recv_cmd(self, timeout=3):
        try:
            r = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            return None, None, None
        if isinstance(r, bytes):
            br = BR(r)
            cmd = br.rc()
            return cmd, br, r
        return None, None, None

    async def keepalive_ping(self):
        try:
            w = BW(); w.wc("PING")
            await self.ws.send(w.build())
        except Exception:
            raise

    async def wait_with_keepalive(self, seconds):
        deadline = time.time() + seconds
        last_ping = 0
        while time.time() < deadline:
            remaining = min(deadline - time.time(), 3)
            try:
                cmd, br, raw = await self.recv_cmd(timeout=max(0.5, remaining))
            except asyncio.TimeoutError:
                cmd = None
            if time.time() - last_ping > 15:
                await self.keepalive_ping()
                last_ping = time.time()
            if cmd is not None:
                if cmd == "PING":
                    try: await self.send(BW().wc("PONG").build())
                    except: raise
                elif cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                    self.slot = br.i8(); self.balance = br.i64()
                return cmd, br, raw
        return None, None, None

    async def send_pong(self):
        await self.ws.send(BW().wc("PONG").build())

    async def drain(self, seconds=2):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                cmd, br, raw = await self.recv_cmd(timeout=1)
            except asyncio.TimeoutError:
                continue
            except Exception:
                raise
            if cmd is None: break
            if cmd == "PING": await self.send_pong()
            elif cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                self.slot = br.i8(); self.balance = br.i64()

    async def login_replay(self, frames):
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
        log("[WS] ENTER_PLACE Lobby.caro.0...")
        ew = BW(); ew.wc("ENTER_PLACE"); ew.wa("Lobby.caro.0"); ew.wu(""); ew.i8(1)
        await self.send(ew.build())
        await self.drain(3)
        if self.balance == 0:
            await self.read_balance()

    async def read_balance(self):
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
                log(f"  [t={i}] balance {self.balance:,} >= {claim_min:,} ✓ enough, go create table")
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
                    log(f"  [blocked] VIDEO_REWARD blocked → go create table now!")
                    video_reward_blocked = True
                    break
                if consec_fail >= 3:
                    log(f"  [stop] 3 consecutive failures → go create table")
                    break
            jitter = random.uniform(0.5, 1.5)
            await asyncio.sleep(10.0 + jitter)
        log(f"[CLAIM done] {claims_ok} OK / {claims_fail} fail | final: {self.balance:,} | claimed: {total_claimed:,}")
        return claims_ok, total_claimed

    # ======================== CREATE TABLE ========================
    async def create_table(self, bet_amt_id=5):
        log(f"[CREATE] creating table (bet_id={bet_amt_id})...")
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

    async def ready_wait_surrender(self, runtime_deadline):
        bal_before = self.balance
        log(f"  balance: {bal_before:,} | slot={self.slot}")
        await self.send(BW().wc("SET_READY").build())
        log(f"  [SEATED] slot={self.slot} → SET_READY")
        log(f"  Chờ START_MATCH (ở lại trong bàn, không rời)...")
        last_ready = time.time()
        game_started = False
        while time.time() < runtime_deadline:
            try:
                cmd, br, raw = await self.recv_cmd(timeout=3)
            except Exception:
                raise
            if cmd is None:
                if time.time() - last_ready > 30:
                    await self.send(BW().wc("SET_READY").build())
                    last_ready = time.time()
                continue
            if cmd == "PING":
                await self.send_pong()
            elif cmd == "START_MATCH":
                game_started = True
                log(f"  ✓ GAME STARTED!")
                break
            elif cmd == "SET_TURN":
                await self.send(BW().wc("SET_READY").build())
            elif cmd == "PLAYER_ENTERED":
                await self.send(BW().wc("SET_READY").build())
            elif cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                self.slot = br.i8(); self.balance = br.i64()
            elif cmd == "GAMEOVER":
                if self.balance < bal_before:
                    lost = bal_before - self.balance
                    log(f"  ✓✓ GAMEOVER — lost {lost:,} xu ✓✓")
                    return "surrendered", lost
                log(f"  GAMEOVER (balance unchanged)")
                return "spectating", 0
        if not game_started:
            log(f"  Runtime hết — chưa có START_MATCH")
            return "timeout", 0
        log(f"  SURRENDER!")
        await self.send(BW().wc("SURRENDER").build())
        deadline = time.time() + 120
        surrendered = False
        while time.time() < deadline and time.time() < runtime_deadline:
            try:
                cmd, br, raw = await self.recv_cmd(timeout=2)
            except Exception:
                raise
            if cmd is None: continue
            if cmd == "PING":
                await self.send_pong()
            elif cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                self.slot = br.i8(); self.balance = br.i64()
                if not surrendered and self.balance < bal_before:
                    lost = bal_before - self.balance
                    log(f"  ✓✓ SURRENDER SUCCESS! lost {lost:,} xu ✓✓")
                    surrendered = True
                elif self.balance > bal_before + 100:
                    log(f"  [in-table] claim working! balance: {self.balance:,}")
                    bal_before = self.balance
            elif cmd == "GAMEOVER":
                log(f"  GAMEOVER — checking balance...")
                for _ in range(5):
                    try:
                        c2, b2, r2 = await self.recv_cmd(timeout=2)
                    except Exception:
                        raise
                    if c2 is None: continue
                    if c2 == "PING": await self.send_pong()
                    elif c2 == "BALANCE_CHANGED" and b2 and b2.rem() >= 9:
                        self.slot = b2.i8(); self.balance = b2.i64()
                        if not surrendered and self.balance < bal_before:
                            lost = bal_before - self.balance
                            log(f"  ✓✓ SURRENDER (post-GAMEOVER)! lost {lost:,} xu ✓✓")
                            surrendered = True
                            bal_before = self.balance
        if surrendered:
            return "surrendered", max(0, bal_before - self.balance)
        log(f"  [!] No surrender detected (balance: {self.balance:,})")
        return "timeout", 0

    async def _stay_and_claim(self, seconds, bal_after_surrender):
        log(f"  [stay] Staying in table {seconds}s — claim while spectating...")
        deadline = time.time() + seconds
        last_bal = self.balance
        while time.time() < deadline:
            vr = struct.pack('b', -12) + b"VIDEO_REWARD" + struct.pack('B', 1)
            await self.send(vr)
            resp_deadline = time.time() + 3
            while time.time() < resp_deadline:
                cmd, br, raw = await self.recv_cmd(timeout=1)
                if cmd is None: break
                if cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                    self.slot = br.i8(); self.balance = br.i64()
                    if self.balance > last_bal:
                        log(f"  [stay] claim +{self.balance - last_bal} | balance: {self.balance:,}")
                        last_bal = self.balance
                elif cmd == "PING": await self.send_pong()
                elif cmd == "VIDEO_REWARD": pass
            remaining = deadline - time.time()
            if remaining < 12: break
            sleep_end = time.time() + 10
            while time.time() < sleep_end:
                cmd, br, raw = await self.recv_cmd(timeout=2)
                if cmd == "PING": await self.send_pong()
                elif cmd == "BALANCE_CHANGED" and br and br.rem() >= 9:
                    self.slot = br.i8(); self.balance = br.i64()
                    if self.balance > last_bal:
                        log(f"  [stay] claim +{self.balance - last_bal} | balance: {self.balance:,}")
                        last_bal = self.balance
        log(f"  [stay] done — balance: {self.balance:,} (was {bal_after_surrender:,})")

DEFAULT_TOKEN_FILE = "state/tokens/ck2_token.json"
DEFAULT_COOKIE_FILE = "ck2.txt"


def ensure_token_from_cookie(cookie_file, token_file):
    """Nếu token chưa có, tự động chạy capture_token.py từ cookie để sinh token.
    Trả về đường dẫn token file nếu thành công, ngược lại None."""
    if os.path.exists(token_file):
        return token_file
    if not os.path.exists(cookie_file):
        log(f"[TOKEN] Chưa có {token_file} và cũng không có {cookie_file}")
        return None
    log(f"[TOKEN] Chưa có {token_file} — đang tự động capture từ {cookie_file} ...")
    try:
        subprocess.run(
            [sys.executable, "capture_token.py", "--cookie", cookie_file,
             "--output", token_file],
            check=True, timeout=120)
    except Exception as e:
        log(f"[TOKEN] Auto-capture thất bại: {e}")
        return None
    if os.path.exists(token_file):
        log(f"[TOKEN] ✓ Đã sinh token: {token_file}")
        return token_file
    log(f"[TOKEN] Không sinh được token từ {cookie_file}")
    return None


# ======================== MAIN ========================
async def main():
    parser = argparse.ArgumentParser(description="Pure WS bot — create table + surrender (cookie→token→websocket, no target search)")
    parser.add_argument("--token-file", default=DEFAULT_TOKEN_FILE,
                        help=f"Path to token JSON file (default: {DEFAULT_TOKEN_FILE})")
    parser.add_argument("--cookie-file", default=DEFAULT_COOKIE_FILE,
                        help=f"Path to cookie file used to auto-capture token if missing (default: {DEFAULT_COOKIE_FILE})")
    parser.add_argument("--claim-min", type=int, default=int(os.environ.get("CLAIM_MIN", "40000")))
    parser.add_argument("--claim-max", type=int, default=int(os.environ.get("CLAIM_MAX", "50000")))
    parser.add_argument("--bet-id", type=int, default=int(os.environ.get("BET_ID", "10")))
    parser.add_argument("--max-claims", type=int, default=int(os.environ.get("MAX_CLAIMS", "100")))
    parser.add_argument("--runtime", type=int, default=int(os.environ.get("RUNTIME_SECONDS", "21600")))
    parser.add_argument("--no-claim", action="store_true", help="Bỏ qua giai đoạn claim")
    args = parser.parse_args()

    token_path = Path(args.token_file)
    resolved = ensure_token_from_cookie(args.cookie_file, args.token_file)
    if not resolved:
        log(f"[FATAL] Không có token ({args.token_file}) và không thể sinh từ cookie ({args.cookie_file})")
        log(f"        Chạy trước: python3 capture_token.py --cookie {args.cookie_file} --output {args.token_file}")
        sys.exit(1)
    data = json.loads(token_path.read_text())
    ws_url = data["ws_url"]
    login_frames = [bytes.fromhex(h) for h in data["frames"]]

    log(f"{'='*60}")
    log(f"PURE WS BOT — create table + surrender (cookie→token→websocket, no target search)")
    log(f"  Cookie: {args.cookie_file}")
    log(f"  Token: {args.token_file}")
    log(f"  WS: {ws_url}")
    log(f"  Claim range: [{args.claim_min:,}, {args.claim_max:,}]")
    log(f"  Bet ID: {args.bet_id}")
    log(f"  Runtime: {args.runtime}s ({args.runtime//60} min)")
    log(f"{'='*60}")

    deadline = time.time() + args.runtime
    cycle = 0
    total_surrendered = 0
    total_claimed = 0
    reconnect_count = 0
    MAX_RECONNECTS = 3

    while time.time() < deadline and reconnect_count < MAX_RECONNECTS:
        try:
            async with websockets.connect(ws_url, ping_interval=None, max_size=2**20, open_timeout=15) as ws:
                bot = WSBot(ws)
                await bot.login_replay(login_frames)
                await bot.enter_lobby()
                await bot.read_balance()
                log(f"\nBalance: {bot.balance:,} (reconnects: {reconnect_count})")
                reconnect_count = 0

                while time.time() < deadline:
                    cycle += 1
                    log(f"\n{'='*40} CYCLE {cycle} {'='*40}")

                    # Phase 1: CLAIM (tùy chọn)
                    if not args.no_claim and 0 < bot.balance < args.claim_min:
                        log(f"\n[Phase 1] Claim until {args.claim_min:,} xu...")
                        claims_ok, claimed = await bot.claim_until_threshold(
                            args.claim_min, args.claim_max, args.max_claims)
                        total_claimed += claimed
                    elif not args.no_claim and bot.balance >= args.claim_min:
                        log(f"\n[Phase 1] Balance {bot.balance:,} ≥ {args.claim_min:,} — go create table")
                    elif not args.no_claim:
                        log(f"\n[Phase 1] Balance unknown — try claim...")
                        claims_ok, claimed = await bot.claim_until_threshold(
                            args.claim_min, args.claim_max, args.max_claims)
                        total_claimed += claimed

                    if 0 < bot.balance < args.claim_min and not args.no_claim:
                        log(f"\n[RECONNECT] Balance {bot.balance:,} < {args.claim_min:,}, claim blocked → WS dead?")
                        reconnect_count += 1
                        break

                    # Phase 2: TẠO BÀN (không cần tìm target)
                    log(f"\n[Phase 2] Create table (bet_id={args.bet_id})...")
                    created = await bot.create_table(args.bet_id)
                    if not created:
                        log(f"  Create table failed — retry cycle")
                        await asyncio.sleep(10)
                        continue

                    # Phase 3: SURRENDER
                    log(f"\n[Phase 3] Ready → wait START_MATCH → SURRENDER...")
                    status, lost = await bot.ready_wait_surrender(deadline)
                    if status == "surrendered":
                        total_surrendered += lost
                        log(f"  Cycle {cycle}: surrendered {lost:,} xu")
                    elif status == "timeout":
                        log(f"  Timeout → next cycle")
                    elif status == "spectating":
                        log(f"  Spectating → next cycle")

                    # Quay lại lobby
                    ret = BW(); ret.wc("ENTER_PLACE"); ret.wa("Lobby.caro.0"); ret.wu(""); ret.i8(1)
                    await bot.send(ret.build())
                    await bot.drain(3)

                    remaining = deadline - time.time()
                    if remaining < 30:
                        log(f"\n[Runtime] {remaining:.0f}s left — stopping")
                        break
                    await bot.wait_with_keepalive(5)

        except Exception as e:
            reconnect_count += 1
            log(f"\n[WS ERROR] {type(e).__name__}: {e} → reconnect {reconnect_count}/{MAX_RECONNECTS}")
            if reconnect_count < MAX_RECONNECTS:
                await asyncio.sleep(5)

    log(f"\n{'='*60}")
    log(f"FINAL SUMMARY")
    log(f"{'='*60}")
    log(f"  Cycles: {cycle}")
    log(f"  Total claimed: {total_claimed:,} xu")
    log(f"  Total surrendered: {total_surrendered:,} xu")
    log(f"  Reconnects: {reconnect_count}")

if __name__ == "__main__":
    asyncio.run(main())
