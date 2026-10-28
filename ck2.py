#!/usr/bin/env python3
"""
ck2.py — Auto claim + create-table surrender cycle for Gomoku (run locally).

Flow (each cycle):
  1. Check balance FIRST:
     - If balance is already >= claim_min (50k) -> SKIP claim, go straight
       to creating a table (da co xu 50k-55k thi tao ban, khong can claim)
     - Else -> claim reward until balance reaches [claim_min, claim_max]
       (stops early if server returns "no response" = claim rejected)
  2. Select lobby "Lobby.caro.0" (caro0) via place.enterPlace and create
     the table there with bet (default 40k)
  3. Wait for an opponent to join the table
  4. Opponent joined -> press ready ("Bat dau" / "San sang") -> send SURRENDER
     -> lose the bet to the opponent
  5. Back to lobby -> balance dropped below 50k -> next cycle claims again

Removed: the old "find target table by name/id + join target" logic.
The bot now only creates its own table and surrenders to whoever joins.

Usage:
  python3 ck2.py --cookie ck2.txt --cycles 3

  Or via env vars:
  SINGLE_COOKIE_FILE=ck2.txt CYCLES=3 python3 ck2.py

  Useful options:
    --claim-min 50000 --claim-max 55000    claim window (default 50k-55k)
    --bet-amount 40000                     bet for the created table
    --opponent-wait-seconds 120            wait time for opponent to join
    HEADLESS=false python3 ck2.py          show browser window (local run)
"""
import argparse
import os
import re
import sys
import time
import random
import json
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anti_lock as al

from playwright.sync_api import sync_playwright

GAME_URL = "https://www.facebook.com/gaming/play/gomoku-vh"


def parse_cookie_string(raw):
    out = []
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        n, v = part.split("=", 1)
        out.append({"name": n.strip(), "value": v.strip(),
                    "domain": ".facebook.com", "path": "/",
                    "secure": True, "httpOnly": False, "sameSite": "Lax"})
    return out


def parse_bet(s):
    if not s or s == "?":
        return 0
    s = str(s).strip().lower().replace(",", "").replace(" ", "")
    s = "".join(c for c in s if c.isdigit() or c in ".km")
    try:
        if s.endswith("k"):
            return int(float(s[:-1]) * 1000)
        if s.endswith("m"):
            return int(float(s[:-1]) * 1000000)
        return int(float(s))
    except Exception:
        return 0


def log(msg=""):
    print(msg, flush=True)


# ---- JS helpers ----
JS_CLOSE_POPUPS = """() => {
    for (const b of document.querySelectorAll('.popup_button.confirm-button, button')) {
        const t = (b.innerText || '').trim();
        if (/^OK$|I understand|Đã hiểu|Tôi đã hiểu|Đồng ý|Agree|Got it|Đóng|Close$/i.test(t) && b.offsetParent !== null) { b.click(); return true; }
    }
    for (const b of document.querySelectorAll('a, button')) {
        if (b.id === 'closeLuckyWheelButton' && b.offsetParent !== null) { b.click(); return true; }
    }
    return false;
}"""

JS_GET_STATE = """() => ({
    path: window.place ? place.thisPath : null,
    balance: document.querySelector('.chipBalance')?.textContent || null,
    playerId: window.currentPlayerId || null,
    body: document.body ? document.body.innerText.slice(0, 600) : '',
})"""

# JS_CLAIM — matches ck_new.py's JS_CLAIM (simple, no v3 patch)
JS_CLAIM = """(timeoutMs) => new Promise((resolve) => {
    try {
        if (!window.connection || !connection.ws || connection.ws.readyState !== 1) {
            resolve({success:false, error:'ws not connected'}); return;
        }
        const msg = new OutboundMessage("VIDEO_REWARD");
        msg.writeByte(1);
        let resolved = false;
        connection.send(msg, function(response, success) {
            if (resolved) return; resolved = true;
            if (success) {
                try {
                    const amount = response.readLong();
                    if (window.Ads && window.Ads.RewardedVideo) {
                        window.Ads.RewardedVideo.videoIndex++;
                        if (window.Ads.RewardedVideo.updateRewardButton)
                            window.Ads.RewardedVideo.updateRewardButton();
                    }
                    resolve({success:true, amount:amount});
                } catch(e) { resolve({success:true, amount:0, error:e.toString()}); }
            } else {
                resolve({success:false, error:'no response'});
            }
        });
        setTimeout(() => { if (!resolved) { resolved = true;
            resolve({success:false, error:'timeout'}); } }, timeoutMs);
    } catch(e) { resolve({success:false, error:e.toString()}); }
})"""

JS_CLICK_WATCH = """() => {
    const dialogs = document.querySelectorAll('[class*=msgBox]');
    for (const d of dialogs) {
        if (d.offsetParent === null) continue;
        if ((d.textContent || '').includes('enough coin')) {
            const buttons = d.querySelectorAll('input[type="button"], button');
            for (const b of buttons) {
                const val = (b.value || b.textContent || '').toLowerCase();
                if (val.includes('watch') || val.includes('video')) { b.click(); return true; }
            }
        }
    }
    return false;
}"""

JS_CLOSE_DIALOGS = """() => {
    try { document.querySelectorAll('.msgBoxBackGround,.msgBox').forEach(el => el.remove()); return true; }
    catch(e) { return false; }
}"""

# trigger_and_claim — same logic as ck_new.py
JS_CREATE_TABLE = """() => { try { createTable(); } catch(e) {} }"""

JS_SELECT_RADIO_11 = """() => {
    const r = document.getElementById('radio_11');
    if (r) { r.checked = true; r.dispatchEvent(new Event('change', {bubbles:true})); }
}"""

JS_CLICK_CREATE = """() => {
    const b = document.querySelector('input[name="CREATE"]');
    if (b) b.click();
}"""

# Ready button — pressed after the opponent joins
JS_FIND_BAT_DAU = """() => {
    for (const b of document.querySelectorAll('button, input[type=button], [role=button], a')) {
        const r = b.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        const t = (b.innerText || b.textContent || b.value || '').trim();
        if (t.includes('Bắt đầu') || t.includes('Sẵn sàng')) return {found: true, text: t};
    }
    return {found: false};
}"""

JS_CLICK_BAT_DAU = """() => {
    for (const b of document.querySelectorAll('button, input[type=button], [role=button], a')) {
        const r = b.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        const t = (b.innerText || b.textContent || b.value || '').trim();
        if (t.includes('Bắt đầu') || t.includes('Sẵn sàng')) { b.click(); return {clicked: true, text: t}; }
    }
    return {clicked: false};
}"""

JS_SEND_SURRENDER = """() => new Promise((resolve) => {
    try {
        if (!window.connection || !connection.ws || connection.ws.readyState !== 1) {
            resolve({ok: false, error: 'ws not connected'}); return;
        }
        const msg = new OutboundMessage("SURRENDER");
        let done = false;
        connection.send(msg, function(resp, ok) {
            if (done) return; done = true;
            const out = {ok, command: resp.command};
            try {
                const d = resp.data;
                if (d && d.length >= 2) {
                    out.err_code = d[1];
                    if (d.length > 5) {
                        try {
                            let s = new TextDecoder('utf-16be', {fatal: false}).decode(d.slice(5));
                            s = s.replace(/\\u0000/g, ' | ').replace(/[\\u0000-\\u001F]+$/g, '');
                            out.err_msg = s.slice(0, 200);
                        } catch(e) {}
                    }
                }
            } catch(e) {}
            resolve(out);
        });
        setTimeout(() => { if (!done) { done = true; resolve({ok: false, error: 'timeout 12s'}); } }, 12000);
    } catch(e) { resolve({ok: false, error: e.toString()}); }
})"""

JS_CLICK_OK = """() => {
    for (const b of document.querySelectorAll('.popup_button.confirm-button, button, input[type=button], a')) {
        if (b.offsetParent === null) continue;
        const r = b.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        const t = (b.innerText || b.textContent || b.value || '').trim();
        if (/^(OK|Đồng ý|Tiếp tục|Đóng|Chơi lại|Về lobby|Về phòng chờ)$/i.test(t)) {
            b.click(); return {clicked: true, text: t};
        }
    }
    return {clicked: false};
}"""

JS_GO_LOBBY = """() => {
    try {
        if (typeof place.enterParent === 'function') { place.enterParent(); return 'enterParent'; }
        if (typeof place.leaveTable === 'function') { place.leaveTable(); return 'leaveTable'; }
        return 'no leave function';
    } catch(e) { return 'err: ' + e.toString(); }
}"""

# === Create table + wait for opponent (reverse surrender) ===

# === Create-table bet stepper ===
# This game's create-table panel has NO radios — only a -/+ stepper + "Tạo".
# Bet ladder: 100, 200, 400, 1000, 2000, 4000, 10k, 20k, 40k, ...
# (display switches to "10k" style above 4000)
JS_READ_BET_RAW = "() => { const l = document.querySelector('.entry label'); return l ? l.innerText.trim() : null; }"

JS_CLICK_PLUS = """() => {
    for (const b of document.querySelectorAll('a, button, input')) {
        if (b.offsetParent !== null && (b.innerText || b.value || '').trim() === '+') { b.click(); return true; }
    }
    return false;
}"""

JS_CLICK_MINUS = """() => {
    for (const b of document.querySelectorAll('a, button, input')) {
        if (b.offsetParent !== null && (b.innerText || b.value || '').trim() === '-') { b.click(); return true; }
    }
    return false;
}"""

JS_CLICK_TAO = """() => {
    // "Tạo" (Create) button of the create-table panel
    for (const b of document.querySelectorAll('a, button, input')) {
        if (b.offsetParent !== null && (b.innerText || b.value || '').trim() === 'Tạo') { b.click(); return true; }
    }
    // Fallback: old CREATE input
    const b = document.querySelector('input[name="CREATE"]');
    if (b) { b.click(); return true; }
    return false;
}"""

# === WS tap: detect opponent joining via websocket ===
# Heartbeat = len 2 / cmd 44. Any other message after table creation
# means table activity (opponent joined / game started).
JS_INSTALL_WS_TAP = """() => {
    if (window.__tap_installed) return true;
    window.__tap = [];
    const ws = window.connection && window.connection.ws;
    if (!ws) return false;
    const orig = ws.onmessage;
    ws.binaryType = 'arraybuffer';
    ws.onmessage = function(ev) {
        let bytes = null;
        try {
            if (ev.data instanceof ArrayBuffer) bytes = Array.from(new Uint8Array(ev.data));
            else if (ev.data && ev.data.data) bytes = Array.from(new Uint8Array(ev.data.data));
        } catch(e) {}
        if (bytes) window.__tap.push({ts: Date.now(), len: bytes.length, b1: bytes.length > 1 ? bytes[1] : null});
        if (orig) return orig.call(ws, ev);
    };
    window.__tap_installed = true;
    return true;
}"""

JS_CLEAR_TAP = "() => { window.__tap = []; return true; }"

JS_GET_TAP_SUMMARY = "() => (window.__tap || []).map(m => ({len: m.len, b1: m.b1}))"

JS_ENTER_LOBBY_PATH = """(lobbyPath) => {
    try {
        if (typeof place !== 'undefined' && typeof place.enterPlace === 'function') {
            // Gomoku caro0 lobby path: "Lobby.caro.0"
            if (typeof place.currentPlace !== 'undefined' && place.currentPlace === lobbyPath) {
                return {entered: true, already: true};
            }
            place.enterPlace(lobbyPath);
            return {entered: true, already: false};
        }
        return {entered: false, error: 'place.enterPlace not found'};
    } catch(e) { return {entered: false, error: e.toString()}; }
}"""

def find_game_frame(page, max_wait=60):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        for f in page.frames:
            try:
                if f.is_detached():
                    continue
                ok = f.evaluate(
                    "() => !!(window.connection || document.querySelector('.chipBalance') || typeof window.createTable === 'function')"
                )
                if ok:
                    return f
            except Exception:
                continue
        time.sleep(2)
    return None


def ensure_in_lobby(game_frame, page, max_attempts=3):
    """Make sure we're back at Lobby (not in a table).
    
    On Facebook Gaming, lobby paths include: Lobby, Lobby.caro, Lobby.caro.0, etc.
    """
    fb_lobby_paths = {"Lobby", "Lobby.caro", "Lobby.caro.0", "Lobby.caro.1"}
    for _ in range(max_attempts):
        s = game_frame.evaluate(JS_GET_STATE)
        path = s.get("path")
        if path in fb_lobby_paths or path == "Lobby":
            return True
        log(f"  [nav] path={path} — leaving table...")
        try:
            game_frame.evaluate(JS_GO_LOBBY)
        except Exception as e:
            log(f"  [nav] leave err: {type(e).__name__}")
        time.sleep(2)
        new_gf = find_game_frame(page, max_wait=15)
        if new_gf:
            game_frame = new_gf
    s = game_frame.evaluate(JS_GET_STATE)
    path = s.get("path")
    return path in fb_lobby_paths or path == "Lobby"


DEFAULT_GOMOKU_LOBBY = "Lobby.caro.0"


def goto_lobby_path(game_frame, page, lobby_path=DEFAULT_GOMOKU_LOBBY, max_attempts=6):
    """Select the target lobby (e.g. 'Lobby.caro.0' = caro0) BEFORE creating a table.

    STRICT: plain 'Lobby' is NOT treated as equivalent anymore — the bot must
    actually call place.enterPlace(lobby_path) and wait until place.thisPath
    equals the lobby path, so the table gets created inside the caro0 lobby.
    If we are inside a table of that lobby (path = Lobby.caro.0.<id>), leave it first.
    """
    log(f"  [nav] selecting lobby: {lobby_path}")
    for attempt in range(1, max_attempts + 1):
        s = game_frame.evaluate(JS_GET_STATE)
        path = s.get("path")
        if path == lobby_path:
            log(f"    ✓ at {path}")
            return True
        # Inside a table of this lobby (e.g. Lobby.caro.0.7899) -> leave it first
        if path and str(path).startswith(lobby_path + "."):
            log(f"    path={path} — still in a table, leaving first...")
            try:
                game_frame.evaluate(JS_GO_LOBBY)
            except Exception as e:
                log(f"    leave err: {type(e).__name__}")
            time.sleep(3)
            new_gf = find_game_frame(page, max_wait=15)
            if new_gf:
                game_frame = new_gf
            continue
        # Root Lobby or another lobby -> explicitly enter the target lobby
        r = game_frame.evaluate(JS_ENTER_LOBBY_PATH, lobby_path)
        log(f"    attempt {attempt}/{max_attempts}: path={path} → enterPlace({lobby_path}): {r}")
        if r.get("entered") is False and "not found" in str(r.get("error", "")):
            log("    [!] place.enterPlace not available — cannot select lobby")
            return False
        # Wait for the ENTER round-trip: thisPath must become the lobby path
        deadline = time.time() + 15
        reached = False
        while time.time() < deadline:
            time.sleep(2)
            try:
                s = game_frame.evaluate(JS_GET_STATE)
            except Exception:
                break
            if s.get("path") == lobby_path:
                log(f"    ✓ entered {lobby_path}")
                reached = True
                break
        if reached:
            return True
        new_gf = find_game_frame(page, max_wait=15)
        if new_gf:
            game_frame = new_gf
    try:
        final_path = game_frame.evaluate(JS_GET_STATE).get("path")
    except Exception:
        final_path = None
    log(f"    [!] failed to select {lobby_path} (final path={final_path})")
    return final_path == lobby_path



def parse_bet_text(raw):
    """Parse bet display like '100', '40k', '2m' -> int xu."""
    if not raw:
        return None
    s = str(raw).strip().lower().replace(',', '').replace('.', '').replace(' ', '')
    try:
        if s.endswith('k'):
            return int(float(s[:-1]) * 1000)
        if s.endswith('m'):
            return int(float(s[:-1]) * 1000000)
        return int(float(s))
    except Exception:
        digits = ''.join(ch for ch in str(raw) if ch.isdigit())
        return int(digits) if digits else None


def set_bet_stepper(game_frame, target, max_clicks=40):
    """Adjust the create-panel bet stepper (-/+) until displayed bet == target."""
    for _ in range(max_clicks):
        bet = parse_bet_text(game_frame.evaluate(JS_READ_BET_RAW))
        if bet is None:
            return None
        if bet == target:
            return bet
        game_frame.evaluate(JS_CLICK_PLUS if bet < target else JS_CLICK_MINUS)
        time.sleep(0.5)
    return parse_bet_text(game_frame.evaluate(JS_READ_BET_RAW))


def trigger_and_claim(game_frame):
    """Send VIDEO_REWARD claim — matches ck_new.py's trigger_and_claim()."""
    # Create table (triggers "enough coin" alert)
    game_frame.evaluate(JS_CREATE_TABLE)
    time.sleep(2)
    game_frame.evaluate(JS_SELECT_RADIO_11)
    time.sleep(0.5)
    game_frame.evaluate(JS_CLICK_CREATE)
    time.sleep(3)

    # Click "Watch" button if alert shows
    game_frame.evaluate(JS_CLICK_WATCH)
    time.sleep(1)

    # Send VIDEO_REWARD
    result = game_frame.evaluate(JS_CLAIM, 15000)
    if not isinstance(result, dict):
        result = {"success": False, "error": "bad result"}
    return result


def claim_until_threshold(game_frame, page, claim_min, claim_max, max_claims=200, cooldown=1.0):
    """Claim VIDEO_REWARD repeatedly until balance is in [claim_min, claim_max].
    Returns (final_balance, num_claims_ok, num_claims_fail, server_rejected)."""
    log(f"\n[CLAIM] claiming until balance in [{claim_min:,}, {claim_max:,}] (max {max_claims} claims)...")
    claims_ok = 0
    claims_fail = 0
    consec_fail = 0
    server_rejected = False

    for i in range(max_claims):
        # Close popups + watch button
        game_frame.evaluate(JS_CLOSE_POPUPS)
        game_frame.evaluate(JS_CLICK_WATCH)
        time.sleep(0.3)
        game_frame.evaluate(JS_CLOSE_DIALOGS)
        time.sleep(0.3)

        # Check balance
        bal, _ = get_balance(game_frame)
        if bal >= claim_min:
            log(f"  [t={i}] balance {bal:,} ≥ {claim_min:,} ✓ stopping claim loop")
            break
        if bal >= claim_max:
            log(f"  [t={i}] balance {bal:,} ≥ {claim_max:,} (max reached) ✓ stopping")
            break

        # Send claim
        result = trigger_and_claim(game_frame)

        if result.get("success") and result.get("amount", 0) > 0:
            amount = result["amount"]
            claims_ok += 1
            consec_fail = 0
            bal_after, _ = get_balance(game_frame)
            log(f"  [t={i}] ✓ claim +{amount} | {bal:,} → {bal_after:,}")
        else:
            claims_fail += 1
            consec_fail += 1
            err = result.get("error", "?")
            log(f"  [t={i}] ✗ claim FAIL ({err}) | consec={consec_fail}")
            # "no response" is the server's signal that claim is blocked (balance too high or quota)
            if err == "no response":
                server_rejected = True
                log(f"  [stop] server rejected claim (likely balance too high or quota)")
                # Re-check balance — may have hit >50k without us realizing
                bal, _ = get_balance(game_frame)
                if bal >= claim_min:
                    log(f"  balance {bal:,} ≥ {claim_min:,} — OK to proceed to surrender")
                break
            if consec_fail >= 6:
                log(f"  [stop] 6 consecutive failures — likely exhausted")
                break

        # Human-like delay between claims
        time.sleep(cooldown + random.uniform(0.5, 1.5))

    bal, _ = get_balance(game_frame)
    log(f"[CLAIM done] {claims_ok} OK / {claims_fail} fail | final balance: {bal:,}")
    return bal, claims_ok, claims_fail, server_rejected


def create_own_table_and_surrender(game_frame, page, bet_amount=40000, wait_for_opponent=True, 
                                    opponent_wait_seconds=120, min_balance=1000,
                                    lobby=DEFAULT_GOMOKU_LOBBY):
    """Create own table with specified bet, wait for opponent, then SURRENDER.
    
    Flow:
      0. Refresh page
      1. Select lobby (default: Lobby.caro.0 = caro0)
      2. Open create table panel
      3. Set bet_amount xu via the -/+ stepper (panel has no radios)
      4. Create table (button "Tạo")
      5. Wait for opponent (WS signal or ready button)
      6. Press ready (Bắt đầu / Sẵn sàng) then SURRENDER
    
     Returns (success, balance_lost).
    """
    log(f"\n[SURRENDER_SELF] creating table with {bet_amount:,} xu bet...")
    
    bal_before, _ = get_balance(game_frame)
    log(f"  balance before: {bal_before:,}")
    
    if bal_before < min_balance:
        log(f"  [SKIP] balance {bal_before:,} < min_balance {min_balance:,}")
        return False, 0
    
    # Step 0: Refresh page before creating table (ensures fresh UI state)
    log("  [0] refreshing page before table creation...")
    try:
        page.reload(wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(10000)
        log("    page refreshed")
    except Exception as e:
        log(f"    [!] page refresh failed: {e}")
    
    # Re-find game frame after refresh
    new_gf = find_game_frame(page, max_wait=60)
    if new_gf:
        game_frame = new_gf
        # Close any popups after refresh
        game_frame.evaluate(JS_CLOSE_POPUPS)
        time.sleep(2)
        # Re-fetch balance
        bal_before, _ = get_balance(game_frame)
        log(f"    balance after refresh: {bal_before:,}")
    else:
        log("    [!] no game frame after refresh")
        return False, 0
    
    # Step 1: Select the caro0 lobby (Lobby.caro.0) before creating the table
    log(f"  [0.5] selecting lobby {lobby}...")
    if not goto_lobby_path(game_frame, page, lobby_path=lobby):
        log("    [!] couldn't select the lobby — trying ensure_in_lobby instead")
        ensure_in_lobby(game_frame, page)
    
    # Step 2: Open create table panel
    log("  [1] opening create table panel...")
    game_frame.evaluate(JS_CREATE_TABLE)
    time.sleep(2)
    
    # Step 3: Select bet amount via the -/+ stepper
    log(f"  [2] selecting bet via -/+ stepper: {bet_amount:,} xu")
    bet_set = set_bet_stepper(game_frame, bet_amount)
    if bet_set != bet_amount:
        log(f"    [!] couldn't set bet to {bet_amount:,} (got {bet_set}) — aborting table creation")
        return False, 0
    log(f"    ✓ bet set to {bet_set:,} xu")
    time.sleep(0.5)
    
    # Step 4: Create table
    log("  [3] clicking Tạo (CREATE)...")
    game_frame.evaluate(JS_CLICK_TAO)
    time.sleep(5)
    
    # Step 5: Wait for opponent — WS signal (non-heartbeat msg) or ready button
    opp_joined = False
    if wait_for_opponent:
        log(f"  [4] waiting for opponent (up to {opponent_wait_seconds}s)...")
        game_frame.evaluate(JS_INSTALL_WS_TAP)
        game_frame.evaluate(JS_CLEAR_TAP)
        deadline = time.time() + opponent_wait_seconds
        while time.time() < deadline:
            msgs = game_frame.evaluate(JS_GET_TAP_SUMMARY)
            # heartbeat = len 2 / cmd 44 — any other message = table activity
            if any(m.get("len", 0) >= 3 and m.get("b1") != 44 for m in msgs):
                log(f"    ✓ WS activity detected ({len(msgs)} msg) — opponent likely joined")
                opp_joined = True
                break
            rdy = game_frame.evaluate(JS_FIND_BAT_DAU)
            if rdy.get("found"):
                log(f"    ✓ ready button appeared: {rdy.get('text')}")
                opp_joined = True
                break
            time.sleep(3)
        if opp_joined:
            log("    → opponent joined!")
        else:
            log("    [!] no opponent joined within timeout")
    
    # Step 6: Check if game started, then surrender
    # Click Bắt đầu if available
    log("  [5] looking for Bắt đầu / Sẵn sàng (ready) button...")
    for i in range(10):
        r = game_frame.evaluate(JS_FIND_BAT_DAU)
        if r.get("found"):
            log(f"    ✓ Bắt đầu found (text: {r.get('text')})")
            game_frame.evaluate(JS_CLICK_BAT_DAU)
            time.sleep(5)
            break
        time.sleep(2)
    
    # Send SURRENDER
    log("  [6] sending SURRENDER...")
    r = game_frame.evaluate(JS_SEND_SURRENDER)
    log(f"    result: {r}")
    surrender_ok = r.get("ok", False) or r.get("err_code") == 22
    
    # Close dialogs
    log("  [7] closing dialog + returning to lobby...")
    time.sleep(3)
    for _ in range(5):
        clicked = game_frame.evaluate(JS_CLICK_OK)
        if clicked.get("clicked"):
            time.sleep(1)
            break
        time.sleep(1)
    
    ensure_in_lobby(game_frame, page)
    
    # Final balance
    bal_after, _ = get_balance(game_frame)
    delta = bal_after - bal_before
    log(f"  [done] balance: {bal_before:,} → {bal_after:,} (Δ={delta:+,})")
    if delta < 0:
        log(f"         ✓ lost {-delta:,} xu (transferred to opponent)")
    return surrender_ok, max(0, -delta)


class StopCycle(Exception):
    """Raise to stop the current cycle but continue to next iteration."""
    pass


class BrowserCrashed(Exception):
    """Raise when browser/page/frame is closed unexpectedly."""
    pass


def get_balance(game_frame):
    try:
        s = game_frame.evaluate(JS_GET_STATE)
        return parse_bet(s.get("balance")), s
    except Exception as e:
        err_type = type(e).__name__
        log(f"  [warn] get_balance failed: {err_type}: {e}")
        if err_type in ('TargetClosedError', 'Error'):
            msg = str(e).lower()
            if 'closed' in msg or 'target' in msg or 'detached' in msg:
                raise BrowserCrashed(f"{err_type}: {e}")
        raise  # re-raise other exceptions

def _run_cycle(args, game_frame, page, cycle_num, cycle_results):
    """One cycle: check/claim -> create own table -> wait opponent -> ready -> surrender."""
    # Check min balance
    try:
        bal, _ = get_balance(game_frame)
    except BrowserCrashed:
        log(f"  [!] browser crashed during balance check")
        raise BrowserCrashed("browser closed during get_balance")

    if bal < args.min_balance:
        log(f"[STOP] balance {bal:,} < min {args.min_balance:,}")
        raise StopCycle

    # Ensure we're in Lobby
    if not ensure_in_lobby(game_frame, page):
        log("[!] couldn't return to Lobby — reloading game")
        try:
            page.goto(GAME_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(15000)
            game_frame = find_game_frame(page, max_wait=60)
            if not game_frame:
                log("[!] no game frame after reload — stopping")
                raise StopCycle
        except Exception as e:
            log(f"[!] reload failed: {e}")
            raise StopCycle

    # PHASE 1: skip claim if balance is already in [claim_min, claim_max]
    final_bal, _ = get_balance(game_frame)
    if getattr(args, "skip_claim", False):
        log(f"\n=== Phase 1: SKIP CLAIM (--skip-claim test mode, balance: {final_bal:,}) ===")
    elif final_bal >= args.claim_min:
        log(f"\n=== Phase 1: SKIP CLAIM (balance {final_bal:,} already >= {args.claim_min:,}) ===")
        log("    enough xu — going straight to table creation")
    else:
        log(f"\n=== Phase 1: CLAIM (target balance: [{args.claim_min:,}, {args.claim_max:,}]) ===")
        final_bal, n_ok, n_fail, server_rej = claim_until_threshold(
            game_frame, page, args.claim_min, args.claim_max,
            max_claims=args.max_claims_per_cycle,
            cooldown=args.claim_cooldown,
        )

        if final_bal < args.claim_min and not server_rej:
            log(f"\n[!] couldn't reach {args.claim_min:,} xu — claim exhausted")
            log(f"    current balance: {final_bal:,}")
            if final_bal < args.bet_amount:
                log(f"    [STOP] balance too low to create a {args.bet_amount:,} xu table")
                raise StopCycle

    # PHASE 2: create own table -> wait opponent -> ready -> SURRENDER
    bet_amount = args.bet_amount
    if final_bal < bet_amount:
        log(f"\n=== Phase 2: CREATE OWN TABLE ({bet_amount:,} xu) ===")
        log(f"  [SKIP] balance {final_bal:,} < bet {bet_amount:,} — not enough funds")
        cycle_results.append({
            "cycle": cycle_num,
            "balance_after_claim": final_bal,
            "surrender_ok": False,
            "xu_lost": 0,
        })
        return game_frame

    log(f"\n=== Phase 2: CREATE OWN TABLE ({bet_amount:,} xu, wait for opponent) ===")
    ok, lost = create_own_table_and_surrender(
        game_frame, page, bet_amount=bet_amount,
        wait_for_opponent=args.wait_for_opponent,
        opponent_wait_seconds=args.opponent_wait_seconds,
        min_balance=args.min_balance,
        lobby=args.lobby,
    )

    total_lost = sum(c["xu_lost"] for c in cycle_results) + lost
    cycle_results.append({
        "cycle": cycle_num,
        "balance_after_claim": final_bal,
        "surrender_ok": ok,
        "xu_lost": lost,
    })
    log(f"\n[cycle {cycle_num}] ready+surrender {'✓' if ok else '✗'} | lost {lost:,} xu | total lost: {total_lost:,}")

    # Re-find game frame for status reporting
    new_gf = find_game_frame(page, max_wait=10)
    if new_gf:
        game_frame = new_gf
    return game_frame


def restart_browser(page, browser, p, cookies, fp, ctx, headless=True):
    """Close and relaunch browser + context to prevent crashes.
    Returns (browser, ctx, page, game_frame)."""
    log("  [restart] closing browser context to prevent crash accumulation...")
    try:
        ctx.close()
    except: pass
    try:
        browser.close()
    except: pass
    browser = p.chromium.launch(headless=headless, args=al.stealth_launch_args(fp))
    ctx = browser.new_context(
        viewport=fp["viewport"], locale=fp["locale"],
        user_agent=fp["user_agent"], timezone_id=fp["timezone"],
        color_scheme=fp.get("color_scheme", "light"),
    )
    ctx.add_init_script(al.build_stealth_js(fp))
    ctx.add_cookies([dict(c, domain=".facebook.com") for c in cookies])
    page = ctx.new_page()
    page.set_default_timeout(45000)
    page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(5000)
    page.goto(GAME_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(20000)
    game_frame = find_game_frame(page, max_wait=60)
    if game_frame:
        # Wait for game state to be fully loaded
        log("  [restart] waiting for game state...")
        for _ in range(15):
            try:
                s = game_frame.evaluate(JS_GET_STATE)
                if s.get("path") and s.get("playerId"):
                    break
            except:
                pass
            time.sleep(2)
        log("  [restart] ✓ browser restarted, game frame ready")
    else:
        log("  [restart] ✗ no game frame after restart")
    return browser, ctx, page, game_frame


def main():
    parser = argparse.ArgumentParser(
        description="Gomoku auto: check/claim 50-55k -> create table -> wait opponent -> ready -> surrender -> repeat")
    parser.add_argument("--cookie", default=os.environ.get("SINGLE_COOKIE_FILE", "ck2.txt"),
                        help="Cookie file (default: ck2.txt)")
    parser.add_argument("--cycles", type=int, default=int(os.environ.get("CYCLES", "3")),
                        help="Number of claim→create→surrender cycles (default: 3)")
    parser.add_argument("--claim-min", type=int, default=int(os.environ.get("CLAIM_MIN", "50000")),
                        help="Skip claiming if balance >= this; else claim until balance >= this (default: 50000)")
    parser.add_argument("--claim-max", type=int, default=int(os.environ.get("CLAIM_MAX", "55000")),
                        help="Hard stop claiming when balance >= this (default: 55000)")
    parser.add_argument("--skip-claim", action="store_true",
                        default=os.environ.get("SKIP_CLAIM", "false").lower() == "true",
                        help="Test mode: skip Phase 1 (claim) entirely — go straight to table creation")
    parser.add_argument("--bet-amount", type=int, default=int(os.environ.get("BET_AMOUNT", "40000")),
                        help="Bet amount for the created table (default: 40000)")
    parser.add_argument("--lobby", default=os.environ.get("LOBBY", DEFAULT_GOMOKU_LOBBY),
                        help="Lobby to select before creating the table (default: Lobby.caro.0 = caro0)")
    parser.add_argument("--min-balance", type=int, default=int(os.environ.get("MIN_BALANCE", "1000")),
                        help="Stop if balance drops below this (default: 1000)")
    parser.add_argument("--max-claims-per-cycle", type=int, default=int(os.environ.get("MAX_CLAIMS_PER_CYCLE", "200")),
                        help="Max claim attempts per cycle (default: 200)")
    parser.add_argument("--claim-cooldown", type=float, default=float(os.environ.get("CLAIM_COOLDOWN", "1.0")),
                        help="Seconds between claims (default: 1.0)")
    parser.add_argument("--delay-between-cycles", type=float, default=float(os.environ.get("DELAY_BETWEEN_CYCLES", "10")),
                        help="Seconds between cycles (default: 10)")
    parser.add_argument("--wait-for-opponent", type=lambda v: v.lower() in ('true', '1', 'yes'),
                        default=os.environ.get("WAIT_FOR_OPPONENT", "true").lower() == "true",
                        help="Wait for opponent to join before ready+surrender")
    parser.add_argument("--opponent-wait-seconds", type=int, default=int(os.environ.get("OPPONENT_WAIT_SECONDS", "120")),
                        help="Seconds to wait for opponent after creating the table (default: 120)")
    parser.add_argument("--headless", default=os.environ.get("HEADLESS", "true").lower() == "true",
                        action="store_true", help="Run headless")
    args = parser.parse_args()

    cookie_path = args.cookie
    if not os.path.isabs(cookie_path):
        cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), cookie_path)
    if not os.path.exists(cookie_path):
        log(f"[ERR] cookie file not found: {cookie_path}")
        return 1

    cookie_raw = open(cookie_path, encoding="utf-8").read().strip()
    cookies = parse_cookie_string(cookie_raw)
    log(f"[cookie] parsed {len(cookies)} cookies from {os.path.basename(cookie_path)}")

    fp = al.get_or_create_fingerprint(os.path.basename(cookie_path))
    log(f"[fp] UA={fp['user_agent'][:50]}... viewport={fp['viewport']}")
    log(f"[config] claim_min={args.claim_min:,}, claim_max={args.claim_max:,}")
    log(f"         bet_amount={args.bet_amount:,}, cycles={args.cycles}, headless={args.headless}")
    log(f"         lobby={args.lobby}")

    cycle_results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, args=al.stealth_launch_args(fp))
        ctx = browser.new_context(
            viewport=fp["viewport"], locale=fp["locale"],
            user_agent=fp["user_agent"], timezone_id=fp["timezone"],
            color_scheme=fp.get("color_scheme", "light"),
        )
        ctx.add_init_script(al.build_stealth_js(fp))
        ctx.add_cookies([dict(c, domain=".facebook.com") for c in cookies])
        page = ctx.new_page()
        page.set_default_timeout(45000)

        log(f"\n[setup] goto FB home → {GAME_URL}")
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(5000)
        page.goto(GAME_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(20000)

        game_frame = find_game_frame(page, max_wait=60)
        if not game_frame:
            log("[ERR] no game frame after 60s")
            browser.close()
            return 1
        log(f"[setup] game frame ready")

        # Close any startup popups
        game_frame.evaluate(JS_CLOSE_POPUPS)
        time.sleep(2)

        # Wait for game state to be fully loaded
        log("[init] waiting for game state...")
        for _ in range(15):
            try:
                s = game_frame.evaluate(JS_GET_STATE)
                if s.get("path") and s.get("playerId"):
                    break
            except:
                pass
            time.sleep(2)

        try:
            bal, state = get_balance(game_frame)
            log(f"\n[init] balance: {bal:,}, player_id: {state.get('playerId')}, path: {state.get('path')}")
        except Exception as e:
            log(f"\n[init] FAILED to get balance: {type(e).__name__}: {e}")
            log("[init] browser may have crashed — stopping")
            try:
                browser.close()
            except: pass
            return 1

        for cycle_num in range(1, args.cycles + 1):
            log(f"\n{'#' * 60}")
            log(f"# CYCLE {cycle_num}/{args.cycles}")
            log(f"{'#' * 60}")

            # Proactive browser restart between cycles to prevent crash accumulation
            if cycle_num > 1:
                browser, ctx, page, game_frame = restart_browser(
                    page, browser, p, cookies, fp, ctx, headless=args.headless
                )
                if not game_frame:
                    log("[!] failed to restart browser — stopping")
                    break

            try:
                result = _run_cycle(args, game_frame, page, cycle_num, cycle_results)
                if result:
                    game_frame = result  # Update with refreshed game frame
            except StopCycle:
                log(f"  [STOP] cycle stopped early")
                continue
            except Exception as e:
                err_type = type(e).__name__
                log(f"\n[ERROR] Cycle {cycle_num} failed: {err_type}: {e}")
                if err_type in ('TargetClosedError', 'BrowserCrashed', 'Browser closed', 'Page closed'):
                    log("  Browser closed — attempting relaunch...")
                    try:
                        browser.close()
                    except: pass
                    try:
                        browser = p.chromium.launch(headless=args.headless, args=al.stealth_launch_args(fp))
                        ctx = browser.new_context(
                            viewport=fp["viewport"], locale=fp["locale"],
                            user_agent=fp["user_agent"], timezone_id=fp["timezone"],
                            color_scheme=fp.get("color_scheme", "light"),
                        )
                        ctx.add_init_script(al.build_stealth_js(fp))
                        ctx.add_cookies([dict(c, domain=".facebook.com") for c in cookies])
                        page = ctx.new_page()
                        page.set_default_timeout(45000)
                        page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=45000)
                        page.wait_for_timeout(5000)
                        page.goto(GAME_URL, wait_until="domcontentloaded", timeout=60000)
                        page.wait_for_timeout(20000)
                        game_frame = find_game_frame(page, max_wait=60)
                        if game_frame:
                            log("  ✓ browser relaunched, game frame ready")
                        else:
                            log("  ✗ failed to find game frame after relaunch")
                            break
                    except Exception as e2:
                        log(f"  ✗ relaunch failed: {e2}")
                        break
                else:
                    log(f"  Non-fatal error — continuing to next cycle")
                continue

            if cycle_num < args.cycles:
                time.sleep(args.delay_between_cycles)

        # Final summary
        try:
            bal_final, _ = get_balance(game_frame)
        except Exception:
            log("[WARN] couldn't get final balance — browser may have crashed")
            if cycle_results:
                bal_final = cycle_results[-1].get("balance_after_claim", 0)
            else:
                bal_final = 0
        try:
            browser.close()
        except Exception:
            pass

    log(f"\n{'=' * 60}")
    log(f"FINAL SUMMARY")
    log(f"{'=' * 60}")
    for c in cycle_results:
        marker = "✓" if c['surrender_ok'] else "✗"
        log(f"  Cycle {c['cycle']}: balance_after_claim={c['balance_after_claim']:,}, "
            f"ready+surrender={marker}, lost={c['xu_lost']:,}")
    log(f"\nFinal balance: {bal_final:,} xu")
    log(f"Total xu lost via surrender: {sum(c['xu_lost'] for c in cycle_results):,} xu")
    log(f"Total cycles completed: {len(cycle_results)}/{args.cycles}")
    return 0 if cycle_results else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n[EXIT] user interrupt")
        sys.exit(130)
