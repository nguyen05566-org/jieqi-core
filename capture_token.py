#!/usr/bin/env python3
"""
Batch capture tokens from all ck*.txt cookies.
For each cookie:
  1. Load Facebook game page with Playwright (20s timeout).
  2. Check if session alive (game iframe loads with `connection`).
  3. Capture WS login frames (game-server only).
  4. Save token to state/tokens/ckN_token.json.
  5. If dead → mark for deletion.

Output: summary of alive/dead cookies + saved tokens.
"""
import json
import os
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

REPO = Path(__file__).parent.resolve()
TOKEN_DIR = REPO / "state" / "tokens"
TOKEN_DIR.mkdir(parents=True, exist_ok=True)
GAME_URL = "https://www.facebook.com/gaming/play/gomoku-vh"

def load_cookies_flat(path):
    text = Path(path).read_text(encoding="utf-8").strip()
    cookies = []
    for part in text.split(";"):
        part = part.strip()
        if "=" not in part: continue
        name, _, value = part.partition("=")
        cookies.append({"name": name.strip(), "value": value.strip(),
                        "domain": ".facebook.com", "path": "/"})
    return cookies

def capture_token(cookie_file, timeout_s=25):
    """Try to capture WS login frames from a cookie. Returns dict or None."""
    cookies = load_cookies_flat(cookie_file)
    c_user = next((c["value"] for c in cookies if c["name"] == "c_user"), "?")

    ws_frames = []  # (url, bytes, is_game)
    ws_url = [None]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0 Safari/537.36",
            viewport={"width": 1280, "height": 720})
        context.add_cookies(cookies)
        page = context.new_page()

        def on_websocket(ws):
            url = ws.url
            is_game = ("gamevh" in url or "vh9.me" in url or "game8.io" in url)
            if is_game:
                ws_url[0] = url
            def on_sent(data):
                if isinstance(data, bytes) and len(data) > 0:
                    ws_frames.append((url, data, is_game))
            ws.on("framesent", on_sent)
        page.on("websocket", on_websocket)

        try:
            page.goto(GAME_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(timeout_s * 1000)
        except Exception:
            browser.close()
            return None

        # Find game frame
        game_frame = None
        for frame in page.frames:
            try:
                has = frame.evaluate("() => typeof connection !== 'undefined'")
                if has:
                    game_frame = frame
                    break
            except: pass

        browser.close()

    if not game_frame:
        return None  # session dead or game didn't load

    # Filter game-server frames only
    game_frames = [f for _, f, is_game in ws_frames if is_game and len(f) > 5]
    if not game_frames or not ws_url[0]:
        return None

    return {
        "ws_url": ws_url[0],
        "frames": [f.hex() for f in game_frames],
        "c_user": c_user,
    }

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Capture WS token from Facebook cookie")
    parser.add_argument("--cookie", help="Single cookie file (e.g. ck1.txt)")
    parser.add_argument("--output", help="Output token file path")
    args = parser.parse_args()

    if args.cookie:
        # Single cookie mode
        cookie_path = Path(args.cookie)
        if not cookie_path.is_absolute():
            cookie_path = REPO / args.cookie
        if not cookie_path.exists():
            print(f"[ERR] Cookie file not found: {cookie_path}")
            return 1

        name = cookie_path.stem
        print(f"[{name}] Capturing token...")
        result = capture_token(cookie_path)
        if result:
            output_path = Path(args.output) if args.output else TOKEN_DIR / f"{name}_token.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result))
            print(f"✓ ALIVE — c_user={result['c_user'][:12]}...")
            print(f"  WS URL: {result['ws_url']}")
            print(f"  Token saved: {output_path}")
            return 0
        else:
            print(f"✗ DEAD (no game frame / no token)")
            return 1
    else:
        # Batch mode (all cookies)
        cookie_files = sorted(REPO.glob("ck*.txt"))
        print(f"Found {len(cookie_files)} cookie files\n")

        alive = []
        dead = []

        for cf in cookie_files:
            name = cf.stem
            print(f"[{name}] ", end="", flush=True)
            result = capture_token(cf)
            if result:
                token_file = TOKEN_DIR / f"{name}_token.json"
                token_file.write_text(json.dumps(result))
                alive.append((name, result["c_user"], result["ws_url"]))
                print(f"✓ ALIVE — c_user={result['c_user'][:8]}... ws={result['ws_url'][:30]}")
            else:
                dead.append(name)
                print(f"✗ DEAD")

        print(f"\n{'='*60}")
        print(f"SUMMARY: {len(alive)} alive, {len(dead)} dead")
        print(f"{'='*60}")
        for name, cuser, ws in alive:
            print(f"  {name}: c_user={cuser[:12]}...")
        if dead:
            print(f"\nDead cookies:")
            for name in dead:
                print(f"  {name}")
        return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
