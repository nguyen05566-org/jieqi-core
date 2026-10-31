#!/usr/bin/env python3
"""
auto_cycle.py — Combined claim + surrender cycle for Gomoku.

Flow:
  Loop:
    1. Claim reward (ck_new.py logic) until balance reaches [50k, 55k] range
       - Stops early if server returns "no response" (claim rejected)
       - Stops at 55k to avoid game's claim block kicking in too early
    2. Find table by target_name in Gomoku lobby
    3. Join table + send SURRENDER → lose bet amount to target
    4. Balance drops below 50k → can claim again
    5. Repeat

Why 50k-55k?
  - Server blocks claim when balance >= ~50k
  - But we want to safely reach 50k+ before surrender
  - Stopping at 55k gives a buffer so the surrender bet (40k) leaves us ~10-15k
    which is below 50k → next cycle's claim works
  - If surrender bet is 40k and we have 55k → after surrender: 15k (good, < 50k)

Usage:
  python3 auto_cycle.py \\
      --cookie ck.txt \\
      --target-name "nguyen123456" \\
      --target-id 72682865 \\
      --cycles 3 \\
      --claim-min 50000 \\
      --claim-max 55000 \\
      --bet-max 100000

  Or via env vars:
  SINGLE_COOKIE_FILE=ck.txt TARGET_NAME=nguyen123456 TARGET_ID=72682865 \\
  CYCLES=3 python3 auto_cycle.py
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

# Gomoku UI navigation (for surrender phase)
JS_CLICK_CHON_BAN = """() => {
    const vietnamese = ['Chọn bàn', 'Chọn ban', 'Chọn Bàn'];
    const english = ['Find Table', 'Find table', 'Select Table', 'Select table', 'Choose Table', 'Choose table'];
    const keywords = vietnamese.concat(english);
    for (const b of document.querySelectorAll('a, button')) {
        const t = (b.innerText || '').trim().toLowerCase();
        if (keywords.some(k => k.toLowerCase() === t) && b.offsetParent !== null) { b.click(); return true; }
    }
    return false;
}"""

JS_CLICK_FILTER_TAT_CA = """() => {
    // "Tất cả" (Vietnamese) / "All" (English)
    const texts = ['Tất cả', 'All'];
    for (const b of document.querySelectorAll('a, button')) {
        const t = (b.innerText || '').trim();
        if (texts.some(k => t === k) && b.offsetParent !== null) { b.click(); return true; }
    }
    // Fallback: filter buttons by id (original approach)
    const byId = document.getElementById('table_filter0');
    if (byId && byId.offsetParent !== null) { byId.click(); return true; }
    return false;
}"""

JS_CLICK_FILTER_CON_TRONG = """() => {
    // "Còn trống" (Vietnamese) / "Available" (English)
    const texts = ['Còn trống', 'Available', 'Open Seats'];
    for (const b of document.querySelectorAll('a, button')) {
        const t = (b.innerText || '').trim();
        if (texts.some(k => t === k) && b.offsetParent !== null) { b.click(); return true; }
    }
    // Fallback: filter buttons by id (original approach)
    const byId = document.getElementById('table_filter1');
    if (byId && byId.offsetParent !== null) { byId.click(); return true; }
    return false;
}"""

JS_FIND_TABLE_BY_NAME = """(playerName) => {
    const matches = [];
    document.querySelectorAll('div[id^=table_]').forEach(t => {
        if (t.offsetParent === null) return;
        const r = t.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return;
        const text = (t.innerText || '').trim();
        const parts = text.split('\\n');
        const id = parseInt(t.id.replace('table_', ''));
        if (isNaN(id)) return;
        const cls = (t.className || '').toString();
        const all_text = text.toLowerCase();
        if (all_text.includes(playerName.toLowerCase())) {
            matches.push({
                id, bet: parts[0] || '', player: parts[1] || '', cls,
                has_exceed: cls.includes('exceed')
            });
        }
    });
    return matches;
}"""

# Close the table-info popup (after clicking a table to look at player IDs)
JS_CLOSE_TABLE_POPUP = """() => {
    const closeBtn = document.querySelector('.msgBox .closeButton');
    if (closeBtn) { closeBtn.click(); return true; }
    return false;
}"""

# Get all showGameProfile(playerId) elements currently visible in popups.
# Returns array of {player_id, text} for each profile link.
JS_GET_VISIBLE_PROFILES = """() => {
    const out = [];
    document.querySelectorAll('[onclick*=showGameProfile]').forEach(el => {
        if (el.offsetParent === null) return;
        const onclick = el.getAttribute('onclick') || '';
        const m = onclick.match(/showGameProfile\\((\\d+)\\)/);
        if (m) {
            out.push({player_id: parseInt(m[1]), text: (el.textContent || '').trim().slice(0, 80)});
        }
    });
    return out;
}"""

# === WS tap approach (faster than DOM clicking) ===
# When we click a table, server sends PLAYER_ENTERED (cmd 0x019E) message via WS
# containing player_ids of all players in that table. We tap WS messages and
# search for target_id in the binary data — no DOM parsing needed.

JS_INSTALL_WS_TAP = """() => {
    if (window.__tap_installed) return true;
    window.__tap = [];
    window.__last_tap_count = 0;
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
        if (bytes) window.__tap.push({ts: Date.now(), bytes});
        if (orig) return orig.call(ws, ev);
    };
    window.__tap_installed = true;
    return true;
}"""

JS_CLEAR_TAP = "() => { window.__tap = []; window.__last_tap_count = 0; return true; }"

JS_GET_TAP = "() => window.__tap || []"

# Scan ALL tables (id, bet, player_name) without name filter
JS_SCAN_ALL_TABLES = """() => {
    const out = [];
    document.querySelectorAll('div[id^=table_]').forEach(t => {
        if (t.offsetParent === null) return;
        const r = t.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return;
        const text = (t.innerText || '').trim();
        const parts = text.split('\\n');
        const id = parseInt(t.id.replace('table_', ''));
        if (isNaN(id)) return;
        const cls = (t.className || '').toString();
        out.push({id, bet: parts[0] || '', player: parts[1] || '', cls, has_exceed: cls.includes('exceed')});
    });
    return out;
}"""

JS_CLICK_TABLE = """(tableId) => {
    const div = document.getElementById('table_' + tableId);
    if (div && div.offsetParent !== null) { div.click(); return {clicked: true}; }
    return {clicked: false};
}"""

JS_CLICK_VAO_CHOI = """() => {
    // "Vào chơi" (Vietnamese) / "Play" / "Join Game" / "Join" (English)
    const texts = ['Vào chơi', 'Play', 'Join Game', 'Join'];
    for (const b of document.querySelectorAll('input.msgButton, button, input[type=button]')) {
        const t = (b.value || b.innerText || '').trim();
        if (texts.some(k => t === k) && b.offsetParent !== null) { b.click(); return {clicked: true}; }
    }
    // Fallback: fuzzy match (contains) for English variants
    for (const b of document.querySelectorAll('input.msgButton, button, input[type=button]')) {
        if (b.offsetParent === null) continue;
        const t = (b.value || b.innerText || '').trim().toLowerCase();
        if (t === 'chơi' || t === 'vào' || t === 'play' || t === 'join') { b.click(); return {clicked: true}; }
    }
    return {clicked: false};
}"""

JS_FIND_BAT_DAU = """() => {
    for (const b of document.querySelectorAll('button, input[type=button], [role=button], a')) {
        const r = b.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        const t = (b.innerText || b.textContent || b.value || '').trim();
        if (t.includes('Bắt đầu')) return {found: true, text: t};
    }
    return {found: false};
}"""

JS_CLICK_BAT_DAU = """() => {
    for (const b of document.querySelectorAll('button, input[type=button], [role=button], a')) {
        const r = b.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        const t = (b.innerText || b.textContent || b.value || '').trim();
        if (t.includes('Bắt đầu')) { b.click(); return {clicked: true, text: t}; }
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

JS_SELECT_BET_BY_VALUE = """(betValue) => {
    // Select radio button by displayed value (e.g., 40000, 10000, etc.)
    const betValueStr = String(betValue);
    let radio = null;
    // Try matching by value attribute
    const radios = document.querySelectorAll('input[type="radio"]');
    for (const r of radios) {
        const val = (r.value || '').toString();
        if (val === betValueStr || val.replace(/[^\\d]/g, '') === betValueStr) {
            radio = r; break;
        }
    }
    // Try matching by nearby label text
    if (!radio) {
        for (const r of radios) {
            const label = r.closest('label') || document.querySelector('label[for=\"' + r.id + '\"]');
            if (label && label.innerText.includes(betValueStr)) { radio = r; break; }
        }
    }
    if (radio) { radio.checked = true; radio.dispatchEvent(new Event('change', {bubbles:true})); return {found: true, id: radio.id}; }
    return {found: false};
}"""

JS_GET_TABLE_INFO = """() => ({
    playerCount: document.querySelectorAll('.player-cell, .seat-player, [class*="player"]').length,
    seatInfo: (() => {
        const seats = [];
        document.querySelectorAll('.seat, .player-slot, [class*="seat"]').forEach(s => {
            seats.push({text: (s.innerText || '').trim(), visible: s.offsetParent !== null});
        });
        return seats;
    })(),
    gameText: document.body ? document.body.innerText.slice(0, 300) : '',
})"""

JS_ENTER_LOBBY_PATH = """(lobbyPath) => {
    try {
        if (typeof place !== 'undefined' && typeof place.enterPlace === 'function') {
            // Gomoku lobby path: "Loby.caro.0"
            if (typeof place.currentPlace !== 'undefined' && place.currentPlace === lobbyPath) {
                return {entered: true, already: true};
            }
            place.enterPlace(lobbyPath);
            return {entered: true, already: false};
        }
        return {entered: false, error: 'place.enterPlace not found'};
    } catch(e) { return {entered: false, error: e.toString()}; }
}"""

JS_FIND_PLAYER_COUNT_IN_TABLE = r"""() => {
    // Look for player count indicators in the game UI
    const text = document.body ? document.body.innerText : '';
    // Gomoku typically shows player count like "1/2 players" or similar
    const m = text.match(/(\d+)\s*[/\u2044]\s*2/);
    if (m) { return {count: parseInt(m[1]), text: m[0]}; }
    // Also check for seat elements
    const occupied = document.querySelectorAll('.seat-occupied, [class*="seat"][class*="occupied"], .player-cell').length;
    return {count: occupied, text: 'unknown', method: 'seat'};
}"""


def find_game_frame(page, max_wait=60):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            frames = page.frames
        except Exception:
            # page is closed or detached
            return None
        # Early login page check - fail fast if cookies are expired
        try:
            body_text = page.evaluate("() => document.body ? document.body.innerText.slice(0, 200) : ''")
            if "Đăng nhập" in body_text or "Log in" in body_text or "Sign in" in body_text or "Log In" in body_text:
                log("  [find_game_frame] ⚠ LOGIN PAGE DETECTED - cookies are expired or invalid!")
                log("  [find_game_frame] Please update the cookie file with fresh cookies.")
                return None  # Fail fast instead of waiting 60s
        except Exception:
            pass
        for f in frames:
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
        # Log diagnostic info every 10s
        if int(time.time()) % 10 < 2:
            try:
                url = page.url
                title = page.title()
                log(f"  [find_game_frame] url={url[:80]} title={title[:40]} frames={len(frames)}")
            except Exception:
                pass
        time.sleep(2)
    # Final diagnostic
    try:
        url = page.url
        title = page.title()
        log(f"  [find_game_frame] FINAL: url={url[:120]} title={title[:60]} frames={len(page.frames)}")
        # Dump frame URLs
        for i, f in enumerate(page.frames):
            log(f"    frame[{i}]: url={f.url[:80]}")
        # Check for login page
        content = page.content()
        if "login" in content.lower() or "sign in" in content.lower() or "log in" in content.lower():
            log("  [find_game_frame] ⚠ PAGE APPEARS TO BE A LOGIN PAGE - cookies may be expired!")
        if "error" in content.lower() or "blocked" in content.lower():
            log("  [find_game_frame] ⚠ PAGE MAY BE BLOCKED OR ERROR")
        # Dump first 500 chars of body text
        body_text = page.evaluate("() => document.body ? document.body.innerText.slice(0, 500) : ''")
        log(f"  [find_game_frame] body text: {body_text[:300]}")
    except Exception as e:
        log(f"  [find_game_frame] diagnostic failed: {e}")
    return None

def get_balance(game_frame):
    try:
        s = game_frame.evaluate(JS_GET_STATE)
        return parse_bet(s.get("balance")), s
    except Exception as e:
        log(f"  [warn] get_balance failed: {type(e).__name__}")
        return 0, {"path": None}


def is_browser_alive(page):
    """Check if the browser/page is still alive."""
    try:
        if page and page.is_closed():
            return False
        return True
    except Exception:
        return False


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


DEFAULT_GOMOKU_LOBBY = "Loby.caro.0"


def goto_lobby_path(game_frame, page, lobby_path=DEFAULT_GOMOKU_LOBBY, max_attempts=5):
    """Navigate to a specific lobby path (e.g. 'Loby.caro.0') and wait for it to load.
    
    On Facebook Gaming, the game URL already goes to the Gomoku lobby directly,
    so 'Lobby' path is equivalent to 'Loby.caro.0'. This function handles both
    cases gracefully, including Facebook Gaming's 'Lobby.caro' sub-paths.
    """
    log(f"  [nav] navigating to lobby: {lobby_path}")
    # Normalize: on Facebook Gaming, "Loby.caro.0" ≈ "Lobby.caro" ≈ "Lobby"
    # They all represent the Gomoku game lobby
    fb_equivalent_paths = {"Lobby", "Lobby.caro", "Lobby.caro.0", "Lobby.caro.1"}
    
    for attempt in range(1, max_attempts + 1):
        s = game_frame.evaluate(JS_GET_STATE)
        current_path = s.get("path")
        # Check if we're already at the target lobby or equivalent
        if current_path == lobby_path or (current_path and lobby_path in str(current_path)):
            log(f"    ✓ already at {current_path}")
            return True
        # Facebook Gaming equivalents: Lobby, Lobby.caro, Lobby.caro.0 all work for Gomoku
        if current_path in fb_equivalent_paths:
            log(f"    ✓ at Facebook Gaming lobby {current_path} (equivalent to {lobby_path})")
            return True
        # Partial match: check if the game type (caro) matches
        if current_path and "caro" in str(current_path).lower():
            log(f"    ✓ at caro lobby {current_path} (equivalent to {lobby_path})")
            return True
        log(f"    attempt {attempt}/{max_attempts}: current_path={current_path}")
        r = game_frame.evaluate(JS_ENTER_LOBBY_PATH, lobby_path)
        log(f"    enter result: {r}")
        if r.get("entered") is False and "not found" in str(r.get("error", "")):
            # place.enterPlace doesn't exist — likely Facebook Gaming where Lobby is default
            log(f"    [!] place.enterPlace not available — treating as lobby")
            if current_path is None or current_path in fb_equivalent_paths or "caro" in str(current_path).lower():
                log(f"    ✓ treating current path ({current_path}) as lobby")
                return True
        time.sleep(5)
        # Re-find game frame
        new_gf = find_game_frame(page, max_wait=15)
        if new_gf:
            game_frame = new_gf
        s = game_frame.evaluate(JS_GET_STATE)
        current_path = s.get("path")
        if current_path == lobby_path or (current_path and lobby_path in str(current_path)):
            log(f"    ✓ reached {current_path}")
            return True
        if current_path == "Lobby":
            log(f"    ✓ reached Lobby (equivalent to {lobby_path})")
            return True
    return False


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


def claim_until_threshold(game_frame, page, claim_min, claim_max, max_claims=200, cooldown=3.0):
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


def open_table_browser(game_frame, page, filter_name="Tất cả"):
    """Click 'Chọn bàn' → filter (Tất cả / Còn trống).
    Only operates in Gomoku lobby (Loby.caro.0); if not in Gomoku lobby, returns False.
    """
    s = game_frame.evaluate(JS_GET_STATE)
    current_path = s.get("path")
    fb_lobby_paths = {"Lobby", "Lobby.caro", "Lobby.caro.0", "Lobby.caro.1"}
    if current_path not in fb_lobby_paths:
        log(f"  [open_table_browser] NOT in Gomoku lobby (path={current_path}) — refusing to search here")
        return False
    game_frame.evaluate(JS_CLOSE_POPUPS)
    time.sleep(0.5)
    game_frame.evaluate(JS_CLICK_CHON_BAN)
    time.sleep(5)
    if filter_name == "Tất cả":
        game_frame.evaluate(JS_CLICK_FILTER_TAT_CA)
    elif filter_name == "Còn trống":
        game_frame.evaluate(JS_CLICK_FILTER_CON_TRONG)
    time.sleep(2)


def find_target_table(game_frame, target_name, bet_max):
    """Find a table hosted by target_name. Returns target table dict or None."""
    matches = game_frame.evaluate(JS_FIND_TABLE_BY_NAME, target_name)
    if not matches:
        return None
    # Sort by bet ascending
    matches.sort(key=lambda t: parse_bet(t.get("bet", "999999")))

    # First try: tables we can afford (no "exceed") AND bet <= bet_max
    joinable = [t for t in matches if not t.get("has_exceed") and parse_bet(t.get("bet", "999999")) <= bet_max]
    if joinable:
        return joinable[0]

    # Second try: tables with bet <= bet_max (even if "exceed" — we'll attempt anyway)
    by_bet = [t for t in matches if parse_bet(t.get("bet", "999999")) <= bet_max]
    if by_bet:
        log(f"  [scan] target found but all tables have 'exceed' (balance < bet):")
        for t in by_bet:
            log(f"    id={t['id']} bet={t['bet']} cls={t['cls']}")
        return by_bet[0]

    log(f"  [scan] found {len(matches)} tables for '{target_name}' but none with bet <= {bet_max}")
    for t in matches:
        log(f"    id={t['id']} bet={t['bet']} cls={t['cls']}")
    return None


def find_target_by_id(game_frame, target_id, bet_max, max_tables_to_scan=30, target_name=""):
    """Find a table where target_id is one of the players, or by player name.
    Uses WS tap approach (faster than DOM popup parsing):
      1. Install WS message tap (if not installed yet)
      2. For each table: clear tap, click table, check WS messages for target_id bytes
      3. If found, return table dict

    This works because when we click a table, server sends PLAYER_ENTERED (0x019E)
    message containing player_ids of all players in that table. We search the
    binary data for target_id (4-byte BE int32) — no DOM parsing needed.

    Also supports name-based matching from the initial scan (t['player']).
    """
    import struct
    target_be = struct.pack('>I', int(target_id))
    target_bytes_list = list(target_be)

    # Install WS tap (idempotent — if already installed, returns true)
    game_frame.evaluate(JS_INSTALL_WS_TAP)

    # Scan all tables visible in lobby
    tables = game_frame.evaluate(JS_SCAN_ALL_TABLES)
    if not tables:
        return None

    log(f"  [scan-by-id] {len(tables)} tables visible — clicking each, checking WS for target_id={target_id}")
    tables_to_scan = tables[:max_tables_to_scan]

    found_table = None

    # Name-based quick match from scan results
    tn = (target_name or "").strip().lower()
    if tn:
        for t in tables_to_scan:
            pname = (t.get('player') or '').lower()
            if tn and tn in pname:
                log(f"  ✓✓✓ FOUND target by name '{t.get('player')}' at table {t['id']} (bet: {t.get('bet')})")
                found_table = t
                break
        if found_table:
            bet_val = parse_bet(found_table.get("bet", "999999"))
            if bet_val <= bet_max:
                return found_table
            log(f"  [scan-by-id] found by name but bet {bet_val:,} > bet_max {bet_max:,} — skipping")

    found_table = None
    for t in tables_to_scan:
        # Close any existing popup
        game_frame.evaluate(JS_CLOSE_TABLE_POPUP)
        time.sleep(0.1)
        # Clear tap before click (so new messages are only from this click)
        game_frame.evaluate(JS_CLEAR_TAP)
        # Click this table
        game_frame.evaluate(JS_CLICK_TABLE, t["id"])
        time.sleep(0.3)  # wait for PLAYER_ENTERED to arrive (reduced from 1.0s)
        # Check tap messages for target_id
        tap = game_frame.evaluate(JS_GET_TAP)
        for msg in tap:
            b = msg.get('bytes') or []
            for off in range(len(b) - 3):
                if b[off:off+4] == target_bytes_list:
                    log(f"  ✓✓✓ FOUND target_id={target_id} at table {t['id']} (player: '{t['player']}', bet: {t['bet']})")
                    found_table = t
                    break
            if found_table:
                break
        if found_table:
            break

    # Close any popup before returning
    game_frame.evaluate(JS_CLOSE_TABLE_POPUP)
    time.sleep(0.1)

    if not found_table:
        log(f"  [scan-by-id] target_id={target_id} not found in any of the {len(tables_to_scan)} tables scanned")
        return None

    # Filter by bet_max
    bet_val = parse_bet(found_table.get("bet", "999999"))
    if bet_val > bet_max:
        log(f"  [scan-by-id] found but bet {bet_val:,} > bet_max {bet_max:,} — skipping")
        return None

    return found_table


def wait_for_target_with_retry(game_frame, page, target_name, target_id, bet_max, max_wait_seconds=60, max_tables_to_scan=30):
    """Open table browser + poll for target's table up to max_wait_seconds.
    Strategy:
      - If target_id is set (>0), search by ID (click each table to find player IDs)
      - Else if target_name is set (non-empty), search by name
      - Else error
    Returns target table dict or None if not found within the time budget.

    Only searches in Loby.caro.0 lobby — will not search if we're in a different lobby.
    """
    use_id = target_id and int(target_id) > 0
    use_name = bool(target_name and target_name.strip())

    if not use_id and not use_name:
        log("  [wait] neither target_name nor target_id set — cannot find target")
        return None

    # Verify we're in the Gomoku lobby (Loby.caro.0) before searching
    s = game_frame.evaluate(JS_GET_STATE)
    current_path = s.get("path")
    fb_equivalent_paths = {"Lobby", "Lobby.caro", "Lobby.caro.0", "Lobby.caro.1"}
    if current_path not in fb_equivalent_paths:
        log(f"  [wait] NOT in Gomoku lobby (path={current_path}) — only searching in Loby.caro.0")
        return None
    log(f"  [wait] at Gomoku lobby: {current_path}")

    search_mode = "ID" if use_id else "name"
    log(f"  [wait] polling for target (mode={search_mode}, target_id={target_id}, name={target_name!r}) up to {max_wait_seconds}s...")
    deadline = time.time() + max_wait_seconds
    attempt = 0
    # Open browser first with "Tất cả" filter
    open_table_browser(game_frame, page, filter_name="Tất cả")

    while time.time() < deadline:
        attempt += 1
        if use_id:
            target = find_target_by_id(game_frame, int(target_id), bet_max, max_tables_to_scan=max_tables_to_scan)
        else:
            target = find_target_table(game_frame, target_name, bet_max)
        if target:
            return target

        # Switch to "Còn trống" filter as alternative
        game_frame.evaluate(JS_CLICK_FILTER_CON_TRONG)
        time.sleep(2)
        if use_id:
            target = find_target_by_id(game_frame, int(target_id), bet_max, max_tables_to_scan=max_tables_to_scan)
        else:
            target = find_target_table(game_frame, target_name, bet_max)
        if target:
            return target

        # Switch back to "Tất cả"
        game_frame.evaluate(JS_CLICK_FILTER_TAT_CA)
        # Wait + try again (every 10s)
        wait = min(10, max(2, deadline - time.time()))
        log(f"  [wait] attempt #{attempt} (mode={search_mode}): target not found — retry in {wait:.0f}s...")
        time.sleep(wait)
        # Re-open table browser (in case lobby state changed)
        try:
            s = game_frame.evaluate(JS_GET_STATE)
            current_path = s.get("path")
            fb_lobby_paths = {"Lobby", "Lobby.caro", "Lobby.caro.0", "Lobby.caro.1"}
            if current_path not in fb_lobby_paths:
                log(f"  [wait] retry: not in Gomoku lobby (path={current_path}) — attempting to return")
                ensure_in_lobby(game_frame, page)
                if not goto_lobby_path(game_frame, page, lobby_path=DEFAULT_GOMOKU_LOBBY):
                    log(f"  [wait] retry: could not return to {DEFAULT_GOMOKU_LOBBY} — aborting search")
                    return None
            open_table_browser(game_frame, page, filter_name="Tất cả")
        except Exception as e:
            log(f"  [wait] re-open lobby err: {e}")
    return None


def surrender_one_round(game_frame, page, target_name, target_id, bet_max, target_wait_seconds=60, max_tables_to_scan=30):
    """Find target table → join → SURRENDER. Returns (success, balance_lost).
    If target_id > 0, search by ID (preferred). Else search by name.
    """
    log("\n[SURRENDER] starting surrender round...")
    bal_before, _ = get_balance(game_frame)
    log(f"  balance before: {bal_before:,}")

    # Step 0: Refresh page before looking for target (ensures fresh lobby state)
    log("  [0] refreshing page before target search...")
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
        game_frame.evaluate(JS_CLOSE_POPUPS)
        time.sleep(2)
        # Wait for game state to be fully loaded
        for _ in range(10):
            try:
                s = game_frame.evaluate(JS_GET_STATE)
                if s.get("path") and s.get("playerId"):
                    break
            except:
                pass
            time.sleep(2)
        bal_before, _ = get_balance(game_frame)
        log(f"    balance after refresh: {bal_before:,}")
    else:
        log("    [!] no game frame after refresh — using existing")

    # Step 1: Navigate to Gomoku lobby (Loby.caro.0) to find target's table
    log("  [0.5] navigating to Loby.caro.0...")
    if not goto_lobby_path(game_frame, page, lobby_path=DEFAULT_GOMOKU_LOBBY):
        log("    [!] couldn't reach Gomoku lobby — trying ensure_in_lobby instead")
        ensure_in_lobby(game_frame, page)
    open_table_browser(game_frame, page, filter_name="Tất cả")

    # Step 1+2: poll for target's table with retry (waits up to target_wait_seconds)
    log(f"  [1+2] looking for target (id={target_id}, name={target_name!r}) up to {target_wait_seconds}s...")
    target = wait_for_target_with_retry(game_frame, page, target_name, target_id, bet_max,
                                         max_wait_seconds=target_wait_seconds,
                                         max_tables_to_scan=max_tables_to_scan)
    if not target:
        log(f"    [!] target not found within {target_wait_seconds}s — skipping surrender")
        log(f"    [hint] make sure target has created a table with bet <= {bet_max} xu")
        return False, 0

    log(f"    ✓ found: table {target['id']} bet={target['bet']} player={target['player']}")

    # Close any popup before clicking the table again
    game_frame.evaluate(JS_CLOSE_TABLE_POPUP)
    time.sleep(0.5)

    # Step 3: click on target table
    log(f"  [3] clicking table {target['id']}...")
    game_frame.evaluate(JS_CLICK_TABLE, target["id"])
    time.sleep(5)

    # Step 4: click "Vào chơi"
    log("  [4] looking for 'Vào chơi' button...")
    clicked_vao_choi = False
    for i in range(10):
        r = game_frame.evaluate(JS_CLICK_VAO_CHOI)
        if r.get("clicked"):
            log(f"    ✓ clicked Vào chơi")
            clicked_vao_choi = True
            break
        time.sleep(0.5)
    if not clicked_vao_choi:
        log("    [!] Vào chơi not found — table may be full or rejected")
        return False, 0

    # Step 4.5: wait 15s after clicking Vào chơi for match to start
    log("  [4.5] waiting 15s for match to start...")
    time.sleep(15)

    # Step 5: detect if we're already in a match; if not, wait briefly for "Bắt đầu"
    log("  [5] checking match state...")
    in_match = False
    try:
        s = game_frame.evaluate(JS_GET_STATE)
        p = s.get("path") or ""
        import re as _re
        if _re.match(r'^Lobby\.caro\.\d+\.\d+$', p):
            in_match = True
            log(f"    ✓ already in match (path={p})")
    except Exception:
        pass

    if not in_match:
        log("  [5] waiting for Bắt đầu button (max 5s)...")
        found_start = False
        for i in range(3):
            r = game_frame.evaluate(JS_FIND_BAT_DAU)
            if r.get("found"):
                log(f"    ✓ Bắt đầu found (text: {r.get('text')})")
                game_frame.evaluate(JS_CLICK_BAT_DAU)
                log(f"    → clicked Bắt đầu")
                found_start = True
                break
            time.sleep(1)
        if not found_start:
            log("    [!] Bắt đầu not found — will try SURRENDER anyway")
        # Poll for match state (path change) up to 8s
        for i in range(8):
            try:
                s = game_frame.evaluate(JS_GET_STATE)
                p = s.get("path") or ""
                import re as _re
                if _re.match(r'^Lobby\.caro\.\d+\.\d+$', p):
                    in_match = True
                    log(f"    ✓ now in match (path={p})")
                    break
            except Exception:
                pass
            time.sleep(1)
    if not in_match:
        log("    [!] not in match yet — will try SURRENDER anyway")

    # Step 6: send SURRENDER immediately (2x quickly) then exit for claim
    log("  [*] gửi SURRENDER ngay (2 lần) rồi thoát để claim lại...")
    for s in range(2):
        try:
            r = game_frame.evaluate(JS_SEND_SURRENDER)
            log(f"    [surrender {s+1}] result: {r}")
            err_msg = str(r.get("err_msg", "")).lower()
            if "ván chơi đã kết thúc" in err_msg or "van choi da ket thuc" in err_msg:
                break
        except Exception as e:
            log(f"    [surrender {s+1}] err: {e}")
        time.sleep(1)
    time.sleep(1)
    try:
        if page and not page.is_closed():
            page.close()
    except Exception:
        pass
    try:
        if context:
            context.close()
    except Exception:
        pass
    try:
        if browser:
            browser.close()
    except Exception:
        pass
    raise BrowserCrashed("surrender done - restart for claim")


def create_own_table_and_surrender(game_frame, page, bet_amount=40000, wait_for_opponent=True, 
                                    opponent_wait_seconds=120, min_balance=1000):
    """Create own table with specified bet, wait for opponent, then SURRENDER.
    
    Flow:
      0. Refresh page
      1. Navigate to Loby.caro.0
      2. Open create table panel
      3. Select bet_amount xu
      4. Create table
      5. Wait for opponent to join (if wait_for_opponent)
      6. Start game + SURRENDER
    
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
    
    # Step 1: Navigate to Gomoku lobby (Loby.caro.0) before creating table
    log("  [0.5] navigating to Loby.caro.0...")
    if not goto_lobby_path(game_frame, page, lobby_path=DEFAULT_GOMOKU_LOBBY):
        log("    [!] couldn't reach Gomoku lobby — trying ensure_in_lobby instead")
        ensure_in_lobby(game_frame, page)
    
    # Step 2: Open create table panel
    log("  [1] opening create table panel...")
    game_frame.evaluate(JS_CREATE_TABLE)
    time.sleep(2)
    
    # Step 3: Select bet amount
    log(f"  [2] selecting bet: {bet_amount:,} xu")
    r = game_frame.evaluate(JS_SELECT_BET_BY_VALUE, bet_amount)
    log(f"    result: {r}")
    if not r.get("found"):
        log(f"    [!] bet {bet_amount:,} not found, trying radio_11 fallback")
        game_frame.evaluate(JS_SELECT_RADIO_11)
    time.sleep(0.5)
    
    # Step 4: Create table
    log("  [3] clicking CREATE...")
    game_frame.evaluate(JS_CLICK_CREATE)
    time.sleep(5)
    
    # Step 5: Wait for opponent (if requested)
    if wait_for_opponent:
        log(f"  [4] waiting for opponent (up to {opponent_wait_seconds}s)...")
        deadline = time.time() + opponent_wait_seconds
        while time.time() < deadline:
            # Check if game has started (opponent joined + started)
            table_info = game_frame.evaluate(JS_GET_TABLE_INFO)
            log(f"    table_info: {table_info}")
            
            # Check player count
            player_count = game_frame.evaluate(JS_FIND_PLAYER_COUNT_IN_TABLE)
            log(f"    player_count: {player_count}")
            
            # If player count is 2+, opponent has joined
            count = player_count.get("count", 0)
            if count >= 2:
                log(f"    ✓ opponent joined ({count} players)")
                break
            
            time.sleep(5)
        else:
            log("    [!] no opponent joined within timeout")
            # Try to start game anyway if auto-start is available
    
    # Step 6: Check if game started, then surrender
    # Click Bắt đầu if available
    log("  [5] looking for Bắt đầu button...")
    for i in range(10):
        r = game_frame.evaluate(JS_FIND_BAT_DAU)
        if r.get("found"):
            log(f"    ✓ Bắt đầu found (text: {r.get('text')})")
            game_frame.evaluate(JS_CLICK_BAT_DAU)
            time.sleep(5)
            break
        time.sleep(2)
    
        # Send SURRENDER - wait ~3s then retry until balance changes
    log("  [*] Chờ ~3s, gửi SURRENDER lặp lại đến khi số dư thay đổi (xác nhận thành công)...")
    time.sleep(3)
    bal_surr_check = bal_before
    surrender_ok = False
    for sv in range(30):
        try:
            r = game_frame.evaluate(JS_SEND_SURRENDER)
            log(f"    [surrender {sv+1}] result: {r}")
        except Exception as e:
            log(f"    [surrender {sv+1}] err: {e}")
            r = {}
        time.sleep(2)
        try:
            bal_now, _ = get_balance(game_frame)
        except Exception:
            bal_now = bal_surr_check
        if bal_now < bal_surr_check:
            log(f"    ✓ SURRENDER thành công - số dư thay đổi {bal_now - bal_surr_check:,}")
            surrender_ok = True
            bal_before = bal_surr_check
            break
        err_msg = str(r.get("err_msg", "")).lower()
        if "không tham gia" in err_msg or "chưa tham gia" in err_msg:
            log("    [!] chưa là người chơi - chờ 3s rồi thử lại...")
            time.sleep(3)
            continue
        if r.get("ok") or r.get("err_code") == 22:
            time.sleep(3)
            continue
        time.sleep(2)
    if not surrender_ok:
        log("    [!] chưa thấy thay đổi số dư, vẫn tiếp tục xử lý")
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

def _run_cycle(args, game_frame, page, browser, p, cycle_num, cycle_results,
               total_xu_to_target, cookies, fp, ctx):
    """Execute one claim → surrender cycle. Called from main() with error handling."""
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

    # PHASE 1: CLAIM until [claim_min, claim_max]
    log(f"\n=== Phase 1: CLAIM (target balance: [{args.claim_min:,}, {args.claim_max:,}]) ===")
    final_bal, n_ok, n_fail, server_rej = claim_until_threshold(
        game_frame, page, args.claim_min, args.claim_max,
        max_claims=args.max_claims_per_cycle,
        cooldown=args.claim_cooldown,
    )

    if final_bal < args.claim_min and not server_rej:
        log(f"\n[!] couldn't reach {args.claim_min:,} xu — claim exhausted")
        log(f"    current balance: {final_bal:,}")
        if final_bal >= args.bet_max // 4:
            log(f"    proceeding to surrender attempt anyway")
        else:
            log(f"    [STOP] balance too low")
            raise StopCycle

    # PHASE 2: SURRENDER
    if args.mode == "create_own_table":
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
            if cycle_num < args.cycles:
                time.sleep(args.delay_between_cycles)
            return
        log(f"\n=== Phase 2: CREATE OWN TABLE ({bet_amount:,} xu, wait for opponent) ===")
        ok, lost = create_own_table_and_surrender(
            game_frame, page, bet_amount=bet_amount,
            wait_for_opponent=args.wait_for_opponent,
            opponent_wait_seconds=args.opponent_wait_seconds,
            min_balance=args.min_balance,
        )
        target_label = "self-created table"
    else:
        log(f"\n=== Phase 2: SURRENDER to target (id={args.target_id}, name={args.target_name!r}) ===")
        ok, lost = surrender_one_round(game_frame, page, args.target_name, args.target_id, args.bet_max,
                                       target_wait_seconds=args.target_wait_seconds,
                                       max_tables_to_scan=args.max_tables_to_scan)
        target_label = f"target '{args.target_name}' (id={args.target_id})"

    total_xu_to_target += lost
    cycle_results.append({
        "cycle": cycle_num,
        "balance_after_claim": final_bal,
        "surrender_ok": ok,
        "xu_lost": lost,
    })
    log(f"\n[cycle {cycle_num}] surrender {'✓' if ok else '✗'} | lost {lost:,} xu | target: {target_label} | total: {total_xu_to_target:,}")

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
    page.goto(GAME_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(30000)
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
    parser = argparse.ArgumentParser(description="Gomoku auto-cycle: claim → surrender → claim → surrender ...")
    parser.add_argument("--cookie", default=os.environ.get("SINGLE_COOKIE_FILE", "ck20.txt"),
                        help="Cookie file (default: ck.txt)")
    parser.add_argument("--target-name", default="nguyen123456",
                        help="Player name to find in tables (optional — if target_id is set, name is ignored)")
    parser.add_argument("--target-id", type=int, default=72682865,
                        help="Player ID to find (preferred — unique, no name collision). Default: 0 (search by name)")
    parser.add_argument("--max-tables-to-scan", type=int, default=int(os.environ.get("MAX_TABLES_TO_SCAN", "30")),
                        help="Max tables to scan when searching by ID (default: 30 — each table click takes ~1.5s)")
    parser.add_argument("--cycles", type=int, default=int(os.environ.get("CYCLES", "3")),
                        help="Number of claim→surrender cycles (default: 3)")
    parser.add_argument("--claim-min", type=int, default=int(os.environ.get("CLAIM_MIN", "50000")),
                        help="Stop claiming when balance >= this (default: 50000)")
    parser.add_argument("--claim-max", type=int, default=int(os.environ.get("CLAIM_MAX", "55000")),
                        help="Hard stop claiming when balance >= this (default: 55000)")
    parser.add_argument("--bet-max", type=int, default=int(os.environ.get("BET_MAX", "100000")),
                        help="Max bet to accept (default: 100000)")
    parser.add_argument("--min-balance", type=int, default=int(os.environ.get("MIN_BALANCE", "1000")),
                        help="Stop if balance drops below this (default: 1000)")
    parser.add_argument("--max-claims-per-cycle", type=int, default=int(os.environ.get("MAX_CLAIMS_PER_CYCLE", "200")),
                        help="Max claim attempts per cycle (default: 200)")
    parser.add_argument("--claim-cooldown", type=float, default=float(os.environ.get("CLAIM_COOLDOWN", "3.0")),
                        help="Seconds between claims (default: 3.0)")
    parser.add_argument("--delay-between-cycles", type=float, default=float(os.environ.get("DELAY_BETWEEN_CYCLES", "10")),
                        help="Seconds between cycles (default: 10)")
    parser.add_argument("--target-wait-seconds", type=int, default=int(os.environ.get("TARGET_WAIT_SECONDS", "60")),
                        help="Seconds to wait for target's table to appear (default: 60)")
    parser.add_argument("--headless", default=os.environ.get("HEADLESS", "true").lower() == "true",
                        action="store_true", help="Run headless")
    parser.add_argument("--mode", default=os.environ.get("MODE", "surrender_to_target"),
                        choices=["surrender_to_target", "create_own_table"],
                        help="surrender_to_target: find target's table and surrender (default) | "
                             "create_own_table: create own 40k table, wait for opponent, surrender")
    parser.add_argument("--bet-amount", type=int, default=int(os.environ.get("BET_AMOUNT", "40000")),
                        help="Bet amount to use when creating own table (create_own_table mode)")
    parser.add_argument("--wait-for-opponent", type=lambda v: v.lower() in ('true', '1', 'yes'),
                        default=os.environ.get("WAIT_FOR_OPPONENT", "true").lower() == "true",
                        help="Wait for opponent to join before surrendering (create_own_table mode)")
    parser.add_argument("--opponent-wait-seconds", type=int, default=int(os.environ.get("OPPONENT_WAIT_SECONDS", "120")),
                        help="Seconds to wait for opponent when creating own table (default: 120)")
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
    log(f"[config] target='{args.target_name}' (id={args.target_id})")
    log(f"         claim_min={args.claim_min:,}, claim_max={args.claim_max:,}")
    log(f"         bet_max={args.bet_max:,}, cycles={args.cycles}, mode={args.mode}")

    cycle_results = []
    total_xu_to_target = 0
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
        page.goto(GAME_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(30000)
        try:
            body = page.evaluate("() => document.body ? document.body.innerText.slice(0, 200) : ''")
            if "Đăng nhập" in body or "Log in" in body or "Sign in" in body:
                log("[ERR] LOGIN PAGE DETECTED - cookies are expired or invalid!")
                log("[ERR] Please update the cookie file with fresh cookies.")
                browser.close()
                return 1
        except Exception:
            pass
        try:
            log(f"[setup] page url: {page.url[:100]}")
            log(f"[setup] page title: {page.title()[:60]}")
            body = page.evaluate("() => document.body ? document.body.innerText.slice(0, 300) : ''")
            log(f"[setup] body text: {body[:200]}")
        except Exception as e:
            log(f"[setup] diagnostic failed: {e}")

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

            # Catch browser crashes / page closed errors
            result = None
            try:
                result = _run_cycle(args, game_frame, page, browser, p, cycle_num, cycle_results, 
                           total_xu_to_target, cookies, fp, ctx)
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
                        page.goto(GAME_URL, wait_until="domcontentloaded", timeout=60000)
                        page.wait_for_timeout(30000)
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
            f"surrender={marker}, lost={c['xu_lost']:,}")
    log(f"\nFinal balance: {bal_final:,} xu")
    if args.mode == "create_own_table":
        log(f"Total cycles completed: {len(cycle_results)}/{args.cycles}")
    else:
        log(f"Total xu sent to '{args.target_name}': {total_xu_to_target:,} xu")
        log(f"Total cycles completed: {len(cycle_results)}/{args.cycles}")
    return 0 if cycle_results else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n[EXIT] user interrupt")
        sys.exit(130)
