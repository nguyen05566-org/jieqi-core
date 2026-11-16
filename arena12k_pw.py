#!/usr/bin/env python3
"""arena12k chạy qua Playwright: login gamevh + bridge WebSocket của trang game.

- Login: HTTP form gamevh.net/login.jsp (USER_NAME/PASSWORD) trong executor
- Browser: Playwright Chromium, inject cookie gamevh, mở /play/caro/0
- Transport: PageWS adapter — gửi/nhận frame nhị phân qua connection.ws của trang
- Giữ nguyên toàn bộ logic game + engine AI của arena12k.py
"""
import asyncio, os, sys, time, subprocess, importlib

def _ensure(pkg):
    try:
        importlib.import_module(pkg)
    except ImportError:
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", pkg, "-q", "--break-system-packages"], check=True)
        except Exception:
            subprocess.run([sys.executable, "-m", "pip", "install", pkg, "-q"], check=True)

_ensure("playwright_stealth")

sys.path.insert(0, '.')
import arena12k as A
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

A.USER = os.environ.get("CARO_USER", "haidan_1608")
A.PASSWD = os.environ.get("CARO_PASSWD", "abc123")
A.AUTO_IDENTITY = os.environ.get("CARO_AUTO_IDENTITY", "0") == "1"
if os.environ.get("CARO_BET_XU"):
    A.BOT_BET_XU = int(os.environ["CARO_BET_XU"])
else:
    A.BOT_BET_XU = 12000

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0 Safari/537.36")

HOOK_JS = r"""() => {
  window.__pwRx = window.__pwRx || [];
  const c = window.connection;
  if (!c || !c.ws) return false;
  const ws = c.ws;
  try { ws.binaryType = 'arraybuffer'; } catch(e) {}
  if (!window.__pwHooked) {
    ws.addEventListener('message', function(ev) {
      try {
        const d = ev.data;
        let u8 = null;
        if (d instanceof ArrayBuffer) u8 = new Uint8Array(d);
        else if (d && d.buffer instanceof ArrayBuffer) u8 = new Uint8Array(d.buffer);
        if (u8) {
          let s = '';
          for (let i = 0; i < u8.length; i++) s += u8[i].toString(16).padStart(2, '0');
          window.__pwRx.push(s);
          if (window.__pwRx.length > 2000) window.__pwRx.shift();
        }
      } catch(e) {}
    });
    window.__pwHooked = true;
  }
  return true;
}"""

SEND_JS = r"""(hex) => {
  const c = window.connection;
  if (!c || !c.ws || c.ws.readyState !== 1) return false;
  const u8 = new Uint8Array(hex.match(/../g).map(h => parseInt(h, 16)));
  c.ws.send(u8.buffer);
  return true;
}"""

WS_READY_JS = "() => !!(window.connection && connection.ws && connection.ws.readyState === 1)"


class PageWS:
    def __init__(self, frame):
        self.frame = frame
        self.queue = asyncio.Queue()
        self.close_code = None
        self._task = None

    async def start(self):
        await self.frame.evaluate(HOOK_JS)
        self._task = asyncio.create_task(self._pump())

    async def _pump(self):
        try:
            while self.close_code is None:
                try:
                    hexes = await self.frame.evaluate(
                        "() => { const a = window.__pwRx || []; window.__pwRx = []; return a; }")
                except Exception:
                    self.close_code = 1006
                    break
                for h in hexes:
                    await self.queue.put(bytes.fromhex(h))
                await asyncio.sleep(0.03)
        finally:
            await self.queue.put(None)

    async def send(self, data: bytes):
        ok = await self.frame.evaluate(SEND_JS, data.hex())
        if not ok:
            raise ConnectionError("page ws not ready")

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.queue.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def close(self):
        self.close_code = 1000
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except BaseException:
                pass


class PWCaroBot(A.CaroBot):
    def __init__(self):
        super().__init__()
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None

    async def _http_login(self):
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, self.http_login)
        if not ok:
            raise RuntimeError("gamevh http login failed")

    async def connect_ws(self):
        await self._http_login()
        A.log.info(f"[PW] logged in as {self.nickname} | token={self.token}")

        self._pw = await async_playwright().start()
        self._stealth = Stealth()
        self._stealth.hook_playwright_context(self._pw)
        self._browser = await self._pw.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
        ])
        self._ctx = await self._browser.new_context(
            user_agent=UA, viewport={"width": 1280, "height": 720}, locale="vi-VN")
        cookies = []
        for part in (self.cookie or "").split("; "):
            if "=" in part:
                k, v = part.split("=", 1)
                cookies.append({"name": k, "value": v, "domain": ".gamevh.net", "path": "/"})
        if cookies:
            await self._ctx.add_cookies(cookies)
        self._page = await self._ctx.new_page()
        await self._page.goto(A.GAME_URL, wait_until="domcontentloaded", timeout=60000)
        for _ in range(120):
            try:
                if await self._page.evaluate(WS_READY_JS):
                    break
            except Exception:
                pass
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError("page websocket not ready")

        ws = PageWS(self._page.main_frame)
        await ws.start()
        self.ws = ws
        A.log.info("[PW] game page bridged (connection.ws)")
        return True

    async def cleanup(self):
        try:
            if self._ctx:
                await self._ctx.close()
        except Exception:
            pass
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass


async def _run():
    bot = PWCaroBot()
    try:
        await bot.run()
    finally:
        await bot.cleanup()


def main():
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        A.log.info("[PW] stopped")


if __name__ == "__main__":
    main()
