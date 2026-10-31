#!/usr/bin/env python3
"""
ck2.py — Auto claim + create-table surrender cycle for Gomoku (run locally).

Flow (each cycle):
  1. Check balance FIRST:
     - If balance is already >= claim_min (50k) -> SKIP claim, go straight
       to creating a table (da co xu 50k-55k thi tao ban, khong can claim)
     - Else -> claim reward until balance reaches [claim_min, claim_max]
       (stops early if server returns "no response" = claim rejected)
  2. Create the table with bet (default 40k) in the game's DEFAULT room —
     no lobby/room switching (khong ep Lobby.caro.0 nua; pass --lobby caro0
     if you ever want to force a specific room again)
  3. Wait for an opponent to join the table (default 3 minutes / 180s)
  4. Opponent joined (or timeout) -> press ready ("Bat dau" / "San sang")
     -> CLICK THE SURRENDER FLAG (🏳) exactly like the in-match UI does:
     the flag is a canvas button whose onAction fires
     app.fireStateCommand({code:"SURRENDER"...}) -> confirm msgBox -> OK
     (nhan vao bieu tuong dau hang ngay khi vao tran). If the flag path
     fails, falls back to the raw WS SURRENDER command.
  5. Back to lobby -> balance dropped below 50k -> next cycle claims again
     (sau khi surrender se claim lai o chu ky ke tiep)

Removed: the old "find target table by name/id + join target" logic.
The bot now only creates its own table and surrenders to whoever joins.

Usage:
  python3 ck2.py --cookie ck2.txt --cycles 3

  Or via env vars:
  SINGLE_COOKIE_FILE=ck2.txt CYCLES=3 python3 ck2.py

  Useful options:
    --claim-min 50000 --claim-max 55000    claim window (default 50k-55k)
    --bet-amount 40000                     bet for the created table
    --opponent-wait-seconds 180            wait time for opponent (default 3 min)
    --lobby caro0                          force a room (default: game default room)
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

# Keep background/headless timers running so the client heartbeat (PING)
# is never throttled and the server doesn't drop the WS session.
EXTRA_LAUNCH_ARGS = [
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]

# Liveness probe: send PING on the game WS and report readyState.
# NOTE: kept for reference — DO NOT use it periodically. Manual PINGs correlate
# with the server dropping the socket after 20-60s (probe_ws4). The client has
# its own keepalive (PONG every ~15s); passive monitoring is stable for 3+ min
# (probe_ws5).
JS_SEND_PING = """() => {
    try {
        if (!window.connection || !connection.ws) return {readyState: -1};
        const rs = connection.ws.readyState;
        if (rs === 1) {
            const msg = new OutboundMessage("PING");
            connection.send(msg, function(){});
        }
        return {readyState: rs};
    } catch(e) { return {readyState: -2, error: e.toString()}; }
}"""

# Passive socket state — NO traffic. Use this for monitoring.
JS_WS_STATE = """() => {
    try {
        if (!window.connection) return {readyState: -1};
        const ws = window.connection.ws;
        return {readyState: ws ? ws.readyState : -1,
                active: !!window.connection.wsIsActive};
    } catch(e) { return {readyState: -2, error: e.toString()}; }
}"""

# Active recovery: the client's socket (connection.ws, target wss://vh9.me/ws/gameServer)
# can drop and the client does NOT always re-establish it on its own —
# connection.ws stays null forever. It exposes connection.connect() — call it.
JS_WS_ENSURE = """() => {
    try {
        if (!window.connection) return {ok: false, error: 'no connection object'};
        const c = window.connection;
        if (c.ws && c.ws.readyState === 1) return {ok: true, rs: 1, already: true};
        if (c.ws && c.ws.readyState === 0) return {ok: true, rs: 0, connecting: true};
        if (typeof c.connect === 'function') {
            try { c.connect(); return {ok: true, called: true}; }
            catch(e) { return {ok: false, error: 'connect threw: ' + e.toString()}; }
        }
        return {ok: false, error: 'no connect method'};
    } catch(e) { return {ok: false, error: e.toString()}; }
}"""


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


def save_context_cookies(ctx, path):
    """Write live cookies from the browser context to a cookie file."""
    try:
        cookies = ctx.cookies()
        pairs = [f"{c.get('name')}={c.get('value')}" for c in cookies]
        content = "; ".join(pairs)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.strip() + "\n")
        log(f"[cookie] saved {len(cookies)} cookies -> {path}")
        return content.strip()
    except Exception as e:
        log(f"[cookie] save failed: {type(e).__name__}: {e}")
        return None


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

# Ready button — pressed after the opponent joins (vi + en UI)
JS_FIND_BAT_DAU = """() => {
    for (const b of document.querySelectorAll('button, input[type=button], [role=button], a')) {
        const r = b.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        const t = (b.innerText || b.textContent || b.value || '').trim();
        if (/^(Bắt đầu|Sẵn sàng|Start|Ready)\b/i.test(t) && t.length < 30) return {found: true, text: t};
    }
    return {found: false};
}"""

JS_CLICK_BAT_DAU = """() => {
    for (const b of document.querySelectorAll('button, input[type=button], [role=button], a')) {
        const r = b.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        const t = (b.innerText || b.textContent || b.value || '').trim();
        if (/^(Bắt đầu|Sẵn sàng|Start|Ready)\b/i.test(t) && t.length < 30) { b.click(); return {clicked: true, text: t}; }
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

# Click the in-match SURRENDER FLAG (🏳) the same way the UI does.
# The flag button is CANVAS-DRAWN (ftl.caro.App.createButtonCommand, asset
# 'surrender_bg' — images/surrender.png), so there is NO DOM node to click.
# A click on the canvas flag triggers: onAction -> app.fireStateCommand(cmd)
# where cmd = the server-provided state command {code:"SURRENDER", name:
# "Đầu hàng"/"Surrender", takeConfirmation, waitResult} (see stateById).
# fireStateCommand then shows the OK/Cancel confirm msgBox (if
# takeConfirmation) and sends OutboundMessage("SURRENDER") with the same
# waitResult error handling as a real tap. We replicate exactly that.
JS_FIRE_SURRENDER_FLAG = """() => {
    try {
        if (typeof app === 'undefined' || !app) return {ok: false, error: 'no app object (not in match?)'};
        if (typeof app.fireStateCommand !== 'function') return {ok: false, error: 'no fireStateCommand'};
        // find the SURRENDER command object exactly like the flag button uses:
        // current state first, then any state in the state machine
        let cmd = null, where = null;
        const scan = (states) => {
            for (const k in states) {
                const st = states[k];
                if (!st || !st.commands) continue;
                for (const c of st.commands) {
                    if (c && c.code === 'SURRENDER') return {cmd: c, state: st.code || st.sid};
                }
            }
            return null;
        };
        let hit = scan(app.state ? {cur: app.state} : {});
        if (!hit) hit = scan(app.stateById || {});
        if (!hit) hit = scan(app.stateByCode || {});
        if (!hit) return {ok: false, error: 'SURRENDER not in any state (match not active?)'};
        cmd = hit.cmd; where = hit.state;
        app.fireStateCommand(cmd);
        return {ok: true, state: where, name: cmd.name,
                takeConfirmation: !!cmd.takeConfirmation, waitResult: !!cmd.waitResult};
    } catch(e) { return {ok: false, error: e.toString()}; }
}"""

# Confirm the surrender msgBox that fireStateCommand opens when the state
# command has takeConfirmation=true (buttons are DOM: OK / Cancel).
JS_CLICK_SURRENDER_CONFIRM = """() => {
    for (const b of document.querySelectorAll('.msgBox a, .msgBox button, .msgBox input[type=button], button, input[type=button], a')) {
        if (b.offsetParent === null) continue;
        const t = (b.innerText || b.textContent || b.value || '').trim();
        if (/^(OK|Đồng ý|Dong y|Yes|Confirm|Xác nhận|Xac nhan|Sure)$/i.test(t)) {
            const r = b.getBoundingClientRect();
            const o = {bubbles: true, cancelable: true, view: window, clientX: r.x + r.width/2, clientY: r.y + r.height/2};
            b.dispatchEvent(new MouseEvent('mousedown', o));
            b.dispatchEvent(new MouseEvent('mouseup', o));
            b.dispatchEvent(new MouseEvent('click', o));
            return {clicked: true, text: t};
        }
    }
    return {clicked: false};
}"""

JS_CLICK_OK = """() => {
    for (const b of document.querySelectorAll('.popup_button.confirm-button, button, input[type=button], a')) {
        if (b.offsetParent === null) continue;
        const r = b.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        const t = (b.innerText || b.textContent || b.value || '').trim();
        if (/^(OK|Đồng ý|Tiếp tục|Đóng|Chơi lại|Về lobby|Về phòng chờ|Continue|Play again|Back to lobby|Close)$/i.test(t)) {
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
    // "Tạo" (vi) / "Create" (en) button of the create-table panel
    for (const b of document.querySelectorAll('a, button, input')) {
        if (b.offsetParent === null) continue;
        const t = (b.innerText || b.value || '').trim();
        if (/^(Tạo|Create)$/i.test(t)) { b.click(); return {clicked: true, text: t}; }
    }
    // Fallback: old CREATE input
    const b = document.querySelector('input[name="CREATE"]');
    if (b) { b.click(); return {clicked: true, text: 'input[CREATE]'}; }
    return {clicked: false};
}"""

# === WS tap: detect opponent joining via websocket ===
# Wire format: [2-byte big-endian command id][payload] (see CMD_MAP, arena10k.py).
# Heartbeat = PONG 300. Lobby noise = table-list refresh etc. — IGNORED.
# Real table activity = PLAYER_ENTERED 406, START_MATCH 417, GAMEOVER 418,
# ENTER_STATE 419, SET_TURN 420, SET_READY 434.
JS_INSTALL_WS_TAP = """() => {
    const ws = window.connection && window.connection.ws;
    if (!ws) return false;
    // client auto-reconnected -> (re)install the tap on the new socket
    if (window.__tap_installed && window.__tap_ws === ws) return true;
    window.__tap = [];
    window.__tap_installed = true;
    window.__tap_ws = ws;
    const orig = ws.onmessage;
    ws.binaryType = 'arraybuffer';
    ws.onmessage = function(ev) {
        let bytes = null;
        try {
            if (ev.data instanceof ArrayBuffer) bytes = Array.from(new Uint8Array(ev.data));
            else if (ev.data && ev.data.data) bytes = Array.from(new Uint8Array(ev.data.data));
        } catch(e) {}
        if (bytes) window.__tap.push({
            ts: Date.now(), len: bytes.length,
            b1: bytes.length > 1 ? bytes[1] : null,
            cmd: bytes.length > 1 ? bytes[0] * 256 + bytes[1] : null,
        });
        if (orig) return orig.call(ws, ev);
    };
    return true;
}"""

JS_CLEAR_TAP = "() => { window.__tap = []; return true; }"

JS_GET_TAP_SUMMARY = "() => (window.__tap || []).map(m => ({len: m.len, b1: m.b1, cmd: m.cmd}))"

JS_ENTER_LOBBY_ROOM = """(lobbyPath) => new Promise((resolve) => {
    try {
        if (!window.connection || !connection.ws || connection.ws.readyState !== 1) {
            resolve({entered: false, error: 'ws not connected'}); return;
        }
        if (place.thisPath === lobbyPath) { resolve({entered: true, already: true}); return; }
        // Same wire format as the game's own enterSuitableRoom():
        //   ENTER_PLACE | ascii path | utf empty password | mode byte (MODE_PLAY)
        const msg = new OutboundMessage("ENTER_PLACE");
        msg.writeAscii(lobbyPath);
        msg.writeString("");
        msg.writeByte(window.MODE_PLAY !== undefined ? window.MODE_PLAY : 1);
        let done = false;
        connection.send(msg, function(resp, ok) {
            if (done) return; done = true;
            if (!ok) { resolve({entered: false, error: 'server rejected'}); return; }
            // mirror the client: track the selected room
            try {
                const rid = parseInt(lobbyPath.split('.').pop(), 10);
                if (!isNaN(rid)) window.roomId = rid;
            } catch(e) {}
            resolve({entered: true, already: false});
        });
        setTimeout(() => { if (!done) { done = true; resolve({entered: false, error: 'timeout 12s'}); } }, 12000);
    } catch(e) { resolve({entered: false, error: e.toString()}); }
})"""


def find_game_frame(page, max_wait=60):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            frames = page.frames
        except Exception:
            # page is closed or detached
            return None
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
    except Exception as e:
        log(f"  [find_game_frame] diagnostic failed: {e}")
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


# "" = use the game's DEFAULT room (no room switch before creating the table).
# Pass --lobby caro0 (or 0/1/2/3) to force a specific room again.
DEFAULT_GOMOKU_LOBBY = ""


def normalize_lobby(raw):
    """Normalize lobby input.

    '' / 'default' / 'auto' / 'macdinh' -> ''  = game's default room (no switch)
    'caro0', 'lobby.caro.0', '0', 'Lobby.caro.0', ... -> 'Lobby.caro.<n>'
    Unrecognized input -> '' (default room) instead of failing.
    """
    if raw is None:
        return ""
    s = str(raw).strip().lower().replace(" ", "")
    if not s or s in ("default", "auto", "none", "macdinh"):
        return ""
    m = re.search(r"caro[._]?0*(\d+)$", s) or re.search(r"^(\d+)$", s)
    if m:
        return f"Lobby.caro.{int(m.group(1))}"
    return ""


def goto_lobby_path(game_frame, page, lobby_path="Lobby.caro.0", max_attempts=6):
    """Select a specific lobby room via WS ENTER_PLACE (only used when --lobby is set).

    The browser game keeps place.thisPath == 'Lobby' while browsing rooms —
    the selected room lives in window.roomId. The server-side place is switched
    by the ENTER_PLACE WS command (same as arena10k.py's make_enter), which
    decides where the created table will live ('Lobby.caro.0.<tableId>').
    """
    want_rid = None
    m = re.search(r"(\d+)$", lobby_path)
    if m:
        want_rid = int(m.group(1))
    log(f"  [nav] selecting lobby: {lobby_path} (room {want_rid})")
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
        # Root Lobby -> send ENTER_PLACE for the target room over the game WS
        r = game_frame.evaluate(JS_ENTER_LOBBY_ROOM, lobby_path)
        try:
            rid = game_frame.evaluate("() => window.roomId")
        except Exception:
            rid = None
        log(f"    attempt {attempt}/{max_attempts}: path={path}, roomId={rid} → ENTER_PLACE: {r}")
        if r.get("entered"):
            s = game_frame.evaluate(JS_GET_STATE)
            cur_path = s.get("path")
            if cur_path == lobby_path or rid == want_rid:
                log(f"    ✓ in {lobby_path} (path={cur_path}, roomId={rid})")
                return True
        time.sleep(3)
        new_gf = find_game_frame(page, max_wait=15)
        if new_gf:
            game_frame = new_gf
    try:
        final_path = game_frame.evaluate(JS_GET_STATE).get("path")
    except Exception:
        final_path = None
    log(f"    [!] could not confirm {lobby_path} (final path={final_path})")
    return False



def wait_ws_connected(game_frame, page, max_wait=60):
    """Wait for the game WS to be OPEN — passively, with gentle nudges.

    Lessons from probes (see scripts/probe_ws4.py, probe_ws5.py):
    - the client's own keepalive holds the socket up for minutes — do NOT send
      manual PINGs (server dropped sockets 20-60s after we started PINGing);
    - when the socket IS down, connection.connect() re-establishes it, but the
      server rate-limits rapid reconnect attempts — nudge at most 1/20s.
    Returns (game_frame, connected_bool); game_frame may be re-found if lost.
    """
    deadline = time.time() + max_wait
    gf = game_frame
    announced = False
    last_connect = 0.0
    while time.time() < deadline:
        try:
            st = gf.evaluate(JS_WS_STATE)
            if st.get("readyState") == 1:
                if announced:
                    log("    ✓ WS connected")
                return gf, True
            if not announced:
                announced = True
                log(f"    [ws] readyState={st.get('readyState')} — waiting/reconnecting...")
            # gentle reconnect nudge — max once per 20s (server rate-limit)
            if time.time() - last_connect >= 20:
                last_connect = time.time()
                try:
                    er = gf.evaluate(JS_WS_ENSURE)
                    if er.get("called"):
                        log("    [ws] called connection.connect()")
                except Exception:
                    pass
        except Exception:
            new_gf = find_game_frame(page, max_wait=5)
            if new_gf:
                gf = new_gf
        time.sleep(3)
    return gf, False


def surrender_via_flag(game_frame, page, confirm_timeout=8.0, verify_timeout=12.0):
    """Click the in-match surrender FLAG (🏳) like the UI does.

    The flag is a canvas-drawn button (images/surrender.png); its onAction is
    app.fireStateCommand(cmd) with cmd = the server-provided SURRENDER command.
    This fires the identical code path, then clicks OK on the confirm msgBox.

    Returns (ok: bool, detail: str). Verification: the GAMEOVER (418) signal
    on the WS tap (installed by the caller) and/or a confirm popup appearing.
    """
    gf = game_frame
    # baseline: only messages arriving AFTER the flag is fired count as proof
    try:
        baseline = len(gf.evaluate(JS_GET_TAP_SUMMARY) or [])
    except Exception:
        baseline = 0
    log("    [flag] firing the surrender flag (app.fireStateCommand SURRENDER)...")
    try:
        r = gf.evaluate(JS_FIRE_SURRENDER_FLAG)
    except Exception as e:
        return False, f"evaluate failed: {type(e).__name__}"
    log(f"    [flag] result: {r}")
    if not r or not r.get("ok"):
        return False, str(r.get("error") if r else "no result")

    # the state command usually has takeConfirmation -> OK/Cancel msgBox appears
    if r.get("takeConfirmation"):
        deadline = time.time() + confirm_timeout
        clicked = False
        while time.time() < deadline:
            try:
                c = gf.evaluate(JS_CLICK_SURRENDER_CONFIRM)
                if c.get("clicked"):
                    log(f"    [flag] confirm clicked: {c.get('text')}")
                    clicked = True
                    break
            except Exception:
                pass
            time.sleep(0.8)
        if not clicked:
            log("    [flag] no confirm popup — command may have gone through directly")

    # verify: tap shows GAMEOVER(418)/ENTER_STATE(419) among NEW messages
    if verify_timeout > 0:
        deadline = time.time() + verify_timeout
        while time.time() < deadline:
            try:
                msgs = gf.evaluate(JS_GET_TAP_SUMMARY) or []
                fresh = msgs[baseline:]
                if any(m.get("cmd") in (418, 419) for m in fresh):
                    log(f"    [flag] ✓ match end on WS after flag click: {fresh[-4:]}")
                    return True, "gameover on tap"
            except Exception:
                pass
            time.sleep(1.5)
        log("    [flag] no GAMEOVER seen yet (may still be valid — server accepted)")
    return True, "fired + confirmed"


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

        if result.get("error") == "ws not connected":
            log(f"  [t={i}] WS down — actively reconnecting before next claim...")
            game_frame, ws_ok = wait_ws_connected(game_frame, page, max_wait=45)
            if ws_ok:
                continue  # retry claim immediately

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
                                    opponent_wait_seconds=180, min_balance=1000,
                                    lobby=""):
    """Create own table with specified bet, wait for opponent, then SURRENDER.
    
    Flow:
      0. Refresh page
      1. Stay in the game's DEFAULT room (no lobby switch unless `lobby` given)
      2. Open create table panel
      3. Set bet_amount xu via the -/+ stepper (panel has no radios)
      4. Create table (button "Tạo")
      5. Wait for opponent (WS signal or ready button, default 3 minutes)
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
        # CRITICAL: after reload the client takes ~15-40s to establish the WS.
        # Creating a table before that leaves the table without an owner socket.
        game_frame, ws_ok = wait_ws_connected(game_frame, page, max_wait=75)
        if not ws_ok:
            log("    [!] WS never connected after refresh — aborting this table")
            return False, 0
    else:
        log("    [!] no game frame after refresh")
        return False, 0
    
    # Step 1: Lobby — DEFAULT = stay in whatever room the client opened with
    # (no ENTER_PLACE room switch). Only switch if a specific lobby was forced.
    if lobby:
        log(f"  [0.5] selecting lobby {lobby}...")
        if not goto_lobby_path(game_frame, page, lobby_path=lobby):
            log("    [!] couldn't select the lobby — trying ensure_in_lobby instead")
            ensure_in_lobby(game_frame, page)
    else:
        log("  [0.5] lobby: using game DEFAULT room (no room switch)")
        ensure_in_lobby(game_frame, page)
    
    # Step 1.5: make sure the WS is OPEN before clicking Tạo — without the
    # socket the creation request never reaches the server (balance unchanged,
    # no table). connection.ws can be null even while the UI looks alive.
    game_frame, ws_ok = wait_ws_connected(game_frame, page, max_wait=60)
    if not ws_ok:
        log("    [!] WS still down before Tạo — aborting this table")
        return False, 0
    
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
    log("  [3] clicking Tạo/Create (CREATE)...")
    tao_r = game_frame.evaluate(JS_CLICK_TAO)
    log(f"    click result: {tao_r}")
    time.sleep(6)
    # Verify the table was actually created: after Create succeeds the client
    # navigates INTO the table place (e.g. 'Lobby.caro.0.9239'). NOTE: the bet
    # is NOT escrowed at creation time (it is deducted when the match starts),
    # so balance-based checks give false negatives.
    import re as _re
    created = False
    for _ in range(20):
        try:
            p = str(game_frame.evaluate(JS_GET_STATE).get("path") or "")
        except Exception:
            p = ""
        if _re.match(r"^Lobby(caro)?\.\d+\.\d+$", p):
            created = True
            break
        time.sleep(1)
    if not created:
        log(f"    [!] no table place detected after Create — retrying once (WS check first)...")
        game_frame, ws_ok = wait_ws_connected(game_frame, page, max_wait=50)
        if ws_ok:
            game_frame.evaluate(JS_CREATE_TABLE)
            time.sleep(2)
            set_bet_stepper(game_frame, bet_amount)
            time.sleep(0.5)
            tao_r2 = game_frame.evaluate(JS_CLICK_TAO)
            log(f"    retry click result: {tao_r2}")
            for _ in range(20):
                try:
                    p = str(game_frame.evaluate(JS_GET_STATE).get("path") or "")
                except Exception:
                    p = ""
                if _re.match(r"^Lobby(caro)?\.\d+\.\d+$", p):
                    created = True
                    break
                time.sleep(1)
    log(f"    table creation: {'✓ verified (in table place)' if created else '⚠ unverified — proceeding anyway'}")
    # Confirm the selected room client-side. NOTE: the client only navigates
    # into the table place (Lobby.caro.X.<id>) once the match actually starts;
    # right after Tạo thisPath may still be 'Lobby'.
    try:
        tpath = game_frame.evaluate(JS_GET_STATE).get("path")
        rid = game_frame.evaluate("() => window.roomId")
        log(f"    table place: {tpath} (roomId={rid})")
        if lobby and tpath and "." in str(tpath) and str(tpath).startswith(("Lobby.caro.", "Loby.caro.")):
            room = str(tpath).split(".")[2]
            if room != str(lobby).split(".")[-1]:
                log(f"    [!] table in room {room}, wanted {lobby} — wrong room!")
    except Exception:
        pass
    
    # Step 5: Wait for opponent — precise WS signals or ready button
    # (see CMD_MAP: PLAYER_ENTERED 406, START_MATCH 417, GAMEOVER 418,
    #  ENTER_STATE 419, SET_TURN 420, SET_READY 434)
    WS_CMD_OPPONENT = {406, 417, 418, 419, 420, 434}
    opp_joined = False
    if wait_for_opponent:
        log(f"  [4] waiting for opponent (up to {opponent_wait_seconds}s)...")
        game_frame.evaluate(JS_INSTALL_WS_TAP)
        game_frame.evaluate(JS_CLEAR_TAP)
        deadline = time.time() + opponent_wait_seconds
        last_ws_check = time.time()
        ws_died = False
        while time.time() < deadline:
            # passive socket monitoring every ~10s — NO manual PING (the
            # client's own keepalive holds the connection; our PINGs made the
            # server drop it, see probe_ws4/probe_ws5)
            if time.time() - last_ws_check >= 10:
                last_ws_check = time.time()
                try:
                    st = game_frame.evaluate(JS_WS_STATE)
                    if st.get("readyState") != 1:
                        log(f"    [!] WS down (rs={st.get('readyState')}) — reconnecting gently...")
                        game_frame, ws_ok = wait_ws_connected(game_frame, page, max_wait=50)
                        if ws_ok:
                            # new socket -> re-install the tap
                            game_frame.evaluate(JS_INSTALL_WS_TAP)
                            game_frame.evaluate(JS_CLEAR_TAP)
                        # even if reconnect failed, keep polling the DOM —
                        # the table still exists server-side
                except Exception as e:
                    log(f"    [!] WS check failed: {type(e).__name__}")
                    ws_died = True
                    break
            msgs = game_frame.evaluate(JS_GET_TAP_SUMMARY)
            hit = [m for m in msgs if m.get("cmd") in WS_CMD_OPPONENT]
            if hit:
                log(f"    ✓ table activity: {hit[:4]} — opponent joined")
                opp_joined = True
                break
            # client navigates into the table place once the match starts
            try:
                p = game_frame.evaluate(JS_GET_STATE).get("path")
                if lobby and p and str(p).startswith(str(lobby) + "."):
                    log(f"    ✓ match place: {p} — opponent joined")
                    opp_joined = True
                    break
            except Exception:
                pass
            rdy = game_frame.evaluate(JS_FIND_BAT_DAU)
            if rdy.get("found"):
                log(f"    ✓ ready button appeared: {rdy.get('text')}")
                opp_joined = True
                break
            time.sleep(3)
        if opp_joined:
            log("    → opponent joined!")
        elif ws_died:
            log("    [!] WS died mid-wait — reloading page to recover the session...")
            try:
                page.reload(wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(10000)
                new_gf = find_game_frame(page, max_wait=60)
                if new_gf:
                    game_frame = new_gf
                    s = game_frame.evaluate(JS_GET_STATE)
                    log(f"    [recovery] path={s.get('path')} (table may still exist server-side)")
                    # wait for the client WS to come up before continuing
                    game_frame, ws_ok = wait_ws_connected(game_frame, page, max_wait=75)
                    if ws_ok:
                        game_frame.evaluate(JS_INSTALL_WS_TAP)
                else:
                    log("    [!] no game frame after recovery reload")
            except Exception as e:
                log(f"    [!] recovery reload failed: {type(e).__name__}")
        else:
            log("    [!] no opponent joined within timeout")
    
    # Step 6: Check if game started, then surrender
    # Click Bắt đầu if available
    log("  [5] looking for Bắt đầu / Sẵn sàng (ready) button...")
    # make sure WS is alive for the SURRENDER command
    game_frame, ws_ok = wait_ws_connected(game_frame, page, max_wait=30)
    # long scan if an opponent is at the table, quick scan otherwise
    # (the server drops idle sessions a few minutes after table creation)
    ready_scan = 30 if opp_joined else 5
    for i in range(ready_scan):
        r = game_frame.evaluate(JS_FIND_BAT_DAU)
        if r.get("found"):
            log(f"    ✓ Bắt đầu found (text: {r.get('text')})")
            game_frame.evaluate(JS_CLICK_BAT_DAU)
            time.sleep(5)
            break
        time.sleep(2)
    
    # SURRENDER — wait ~3s then retry until balance changes (confirm success)
    log("  [6] waiting ~3s, sending SURRENDER repeatedly until balance decreases...")
    time.sleep(3)
    bal_surr_check, _ = get_balance(game_frame)
    surrender_ok = False
    flag_used = False
    last_r = {}
    for s in range(40):
        # Try UI flag every 4 attempts to mimic human click
        if s % 4 == 0:
            try:
                okf, flag_detail = surrender_via_flag(game_frame, page)
                flag_used = flag_used or okf
                if okf:
                    log(f"    [flag {s+1}] ok ({flag_detail})")
            except Exception as e:
                log(f"    [flag {s+1}] err: {type(e).__name__}")
        # Fallback/raw WS SURRENDER
        try:
            last_r = game_frame.evaluate(JS_SEND_SURRENDER)
            log(f"    [ws {s+1}] {last_r}")
        except Exception as e:
            log(f"    [ws {s+1}] err: {e}")
            last_r = {}
        time.sleep(2)
        try:
            bal_now, _ = get_balance(game_frame)
        except Exception:
            bal_now = bal_surr_check
        if bal_now < bal_surr_check:
            lost = bal_surr_check - bal_now
            log(f"    ✓ SURRENDER confirmed - balance changed: -{lost:,} xu")
            surrender_ok = True
            bal_surr_check = bal_now
            break
        err_msg = str(last_r.get("err_msg", "")).lower()
        if "không tham gia" in err_msg or "chưa tham gia" in err_msg or "không được" in err_msg or "not a player" in err_msg:
            log("    [!] chưa là người chơi / chưa được phép - chờ 2-3s rồi thử lại...")
            time.sleep(3)
            # ensure WS alive
            try:
                game_frame, ws_ok = wait_ws_connected(game_frame, page, max_wait=15)
            except Exception:
                pass
            continue
        if last_r.get("error") == "ws not connected":
            log("    [!] WS dead - trying to reconnect...")
            try:
                game_frame, ws_ok = wait_ws_connected(game_frame, page, max_wait=30)
            except Exception:
                pass
            time.sleep(2)
            continue
        if last_r.get("ok") or last_r.get("err_code") == 22:
            time.sleep(3)
            continue
        time.sleep(2)
    if not surrender_ok:
        log("    [!] chưa thấy số dư thay đổi sau nhiều lần thử - vẫn tiếp tục xử lý dialog")
    
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
    
    # Final balance (the client's coin display updates LATE after a surrender —
    # re-read after a short wait when the first read shows no change)
    bal_after, _ = get_balance(game_frame)
    if bal_after == bal_before:
        time.sleep(6)
        bal_after, _ = get_balance(game_frame)
    delta = bal_after - bal_before
    log(f"  [done] balance: {bal_before:,} → {bal_after:,} (Δ={delta:+,})")
    if delta < 0:
        log(f"         ✓ lost {-delta:,} xu (transferred to opponent)")
    elif surrender_ok and delta == 0:
        log("         [i] balance display may still be stale — the next cycle's claim reads the real value")
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


def restart_browser(page, browser, p, cookies, fp, ctx, headless=True, save_path: str = ""):
    """Close and relaunch browser + context to prevent crashes.
    Returns (browser, ctx, page, game_frame)."""
    log("  [restart] closing browser context to prevent crash accumulation...")
    try:
        ctx.close()
    except: pass
    try:
        browser.close()
    except: pass
    browser = p.chromium.launch(headless=headless, args=al.stealth_launch_args(fp) + EXTRA_LAUNCH_ARGS)
    ctx = browser.new_context(
        viewport=fp["viewport"], locale=fp["locale"],
        user_agent=fp["user_agent"], timezone_id=fp["timezone"],
        color_scheme=fp.get("color_scheme", "light"),
    )
    ctx.add_init_script(al.build_stealth_js(fp))
    ctx.add_cookies([dict(c, domain=".facebook.com") for c in cookies])
    if save_path:
        save_context_cookies(ctx, save_path)
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
    parser.add_argument("--lobby", default=os.environ.get("LOBBY", "default"),
                        help="Lobby room to select before creating the table "
                             "(default: game's DEFAULT room — no switch; e.g. --lobby caro0 to force Lobby.caro.0)")
    parser.add_argument("--min-balance", type=int, default=int(os.environ.get("MIN_BALANCE", "1000")),
                        help="Stop if balance drops below this (default: 1000)")
    parser.add_argument("--max-claims-per-cycle", type=int, default=int(os.environ.get("MAX_CLAIMS_PER_CYCLE", "200")),
                        help="Max claim attempts per cycle (default: 200)")
    parser.add_argument("--claim-cooldown", type=float, default=float(os.environ.get("CLAIM_COOLDOWN", "3.0")),
                        help="Seconds between claims (default: 3.0)")
    parser.add_argument("--delay-between-cycles", type=float, default=float(os.environ.get("DELAY_BETWEEN_CYCLES", "10")),
                        help="Seconds between cycles (default: 10)")
    parser.add_argument("--wait-for-opponent", type=lambda v: v.lower() in ('true', '1', 'yes'),
                        default=os.environ.get("WAIT_FOR_OPPONENT", "true").lower() == "true",
                        help="Wait for opponent to join before ready+surrender")
    parser.add_argument("--opponent-wait-seconds", type=int, default=int(os.environ.get("OPPONENT_WAIT_SECONDS", "180")),
                        help="Seconds to wait for opponent after creating the table (default: 180 = 3 minutes)")
    parser.add_argument("--headless", default=os.environ.get("HEADLESS", "true").lower() == "true",
                        action="store_true", help="Run headless")
    parser.add_argument("--save-cookies", default=os.environ.get("SAVE_COOKIES", ""),
                        help="Save refreshed cookies from the browser context to this file (e.g. ck2.txt)")
    args = parser.parse_args()
    args.lobby = normalize_lobby(args.lobby)

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
    log(f"         lobby={args.lobby or '(game default room)'}, opponent_wait={args.opponent_wait_seconds}s")

    cycle_results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, args=al.stealth_launch_args(fp) + EXTRA_LAUNCH_ARGS)
        ctx = browser.new_context(
            viewport=fp["viewport"], locale=fp["locale"],
            user_agent=fp["user_agent"], timezone_id=fp["timezone"],
            color_scheme=fp.get("color_scheme", "light"),
        )
        ctx.add_init_script(al.build_stealth_js(fp))
        ctx.add_cookies([dict(c, domain=".facebook.com") for c in cookies])
        if args.save_cookies.strip():
            save_context_cookies(ctx, args.save_cookies.strip())
        page = ctx.new_page()
        page.set_default_timeout(45000)

        log(f"\n[setup] goto FB home → {GAME_URL}")
        page.goto(GAME_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(30000)

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

        # The socket (connection.ws -> wss://vh9.me/ws/gameServer) may be down
        # right after boot (client does not always reconnect by itself).
        # Actively re-establish it before the first cycle.
        game_frame, ws_ok = wait_ws_connected(game_frame, page, max_wait=90)
        if not ws_ok:
            log("[init] [!] WS could not be established — cycles may fail")

        for cycle_num in range(1, args.cycles + 1):
            log(f"\n{'#' * 60}")
            log(f"# CYCLE {cycle_num}/{args.cycles}")
            log(f"{'#' * 60}")

            # Proactive browser restart between cycles to prevent crash accumulation
            if cycle_num > 1:
                browser, ctx, page, game_frame = restart_browser(
                    page, browser, p, cookies, fp, ctx, headless=args.headless, save_path=args.save_cookies.strip()
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
                        browser = p.chromium.launch(headless=args.headless, args=al.stealth_launch_args(fp) + EXTRA_LAUNCH_ARGS)
                        ctx = browser.new_context(
                            viewport=fp["viewport"], locale=fp["locale"],
                            user_agent=fp["user_agent"], timezone_id=fp["timezone"],
                            color_scheme=fp.get("color_scheme", "light"),
                        )
                        ctx.add_init_script(al.build_stealth_js(fp))
                        ctx.add_cookies([dict(c, domain=".facebook.com") for c in cookies])
                        if args.save_cookies.strip():
                            save_context_cookies(ctx, args.save_cookies.strip())
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
