"""Cookie jar + login-state detection for jieqi-core automation scripts.

Ba nguyên tắc của module này (thay cho cơ chế "kéo dài expires" cũ):

1. KHÔNG bịa ``expires``.
   ``expires`` chỉ nói cho *trình duyệt* biết khi nào xoá cookie khỏi store.
   Facebook không đọc nó và nó không liên quan gì tới hạn của session phía
   server. Code cũ set mọi cookie thành ``now + 400 ngày`` → vừa vô nghĩa, vừa
   ghi đè hạn thật do server cấp (làm mất luôn tín hiệu "cookie này sắp hết
   hạn"). Bây giờ: cookie giữ nguyên ``expires`` do server cấp; cookie không có
   ``expires`` (session cookie — đúng như ``c_user``/``xs``) thì để nguyên là
   session cookie.

2. Lưu / khôi phục cookie THẬT giữa các run.
   ``ck*.txt`` vẫn là nguồn chính (định dạng phẳng ``a=b; c=d``, sửa tay được,
   pipeline cũ đọc được ngay). Mỗi lần chạy:
     - đọc cả ``ck*.txt`` và jar ``state/cookies/<ck>.jar.json``;
     - chọn bản mới nhất theo "lineage" (xem ``load_cookies``);
     - ghi lại cookie do server cấp trong lúc chạy vào cả hai (xem
       ``save_cookies``), qua ``atexit`` + SIGTERM/SIGINT + các mốc trong script.
   Nhờ vậy file cookie không còn "chỉ già đi" mà được làm mới bằng chính giá trị
   server gửi về.

3. Phát hiện login dựa trên BẰNG CHỨNG, không dựa vào chữ trên trang.
   ``detect_login_state()`` chỉ kết luận ``logged_out`` / ``checkpoint`` khi có
   bằng chứng cứng: thiếu cookie ``c_user``/``xs``, URL login/checkpoint, form
   mật khẩu đang hiển thị, hoặc HTTP 401/403 / redirect về login. Chuỗi
   "Đăng nhập" nằm đâu đó trong ``innerText`` không còn là căn cứ để kill run.

Module không import playwright: ``ctx`` được dùng theo kiểu duck-typing
(``ctx.cookies()`` / ``ctx.add_cookies()``), nhờ vậy test được bằng object giả.
"""

import atexit
import hashlib
import json
import os
import re
import signal
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

STATE_DIR = os.environ.get("STATE_DIR", os.path.join(_HERE, "state"))
JAR_DIR = os.environ.get("COOKIE_JAR_DIR", os.path.join(STATE_DIR, "cookies"))

JAR_VERSION = 3

# Tên cookie quyết định "còn đăng nhập hay không".
SESSION_COOKIE_NAMES = ("c_user", "xs")

# Chỉ những cookie thuộc domain này mới được ghi ra ck*.txt (cookie của
# gamevh.net / iframe không thuộc về file cookie FB).
FB_DOMAIN_SUFFIX = "facebook.com"

# Giới hạn tần suất ghi file (giây) — tránh ghi đĩa mỗi cycle.
AUTOSAVE_MIN_INTERVAL = float(os.environ.get("COOKIE_SAVE_INTERVAL", "300"))

# Số digest lịch sử giữ lại trong jar để nhận ra "txt này do bot ghi ra".
HISTORY_LIMIT = 32


# =====================================================================
# Helpers
# =====================================================================

def _sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:32]


def _is_fb_domain(domain):
    d = (domain or "").lstrip(".").lower()
    return d == FB_DOMAIN_SUFFIX or d.endswith("." + FB_DOMAIN_SUFFIX)


def _jar_path(cookie_path):
    name = os.path.basename(cookie_path or "unknown")
    safe = re.sub(r"[^\w.\-]", "_", name)
    return os.path.join(JAR_DIR, safe + ".jar.json")


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _atomic_write(path, text):
    """Ghi atomic (tmp + os.replace) — không để lại file cookie nửa vời."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".cookie")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# =====================================================================
# Parse / serialize ck*.txt  (KHÔNG set expires)
# =====================================================================

def parse_cookie_string(raw, domain=".facebook.com", path="/", secure=True,
                        http_only=False, same_site="Lax"):
    """``name=value; name2=value2`` → list cookie dict cho Playwright.

    - Không tự set ``expires``: cookie từ file là session cookie, đúng như
      Facebook cấp ``c_user``/``xs``. Nếu server cấp ``expires`` thật thì nó
      nằm trong jar (``load_cookies`` đọc jar và giữ nguyên).
    - Giữ nguyên value (kể cả dạng URL-encoded ``%3A``): Chrome lưu/ gửi lại
      đúng chuỗi server gửi.
    """
    out, seen = [], set()
    for part in (raw or "").replace("\r", "").replace("\n", ";").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append({
            "name": name,
            "value": value,
            "domain": domain,
            "path": path or "/",
            "secure": bool(secure),
            "httpOnly": bool(http_only),
            "sameSite": same_site,
        })
    return out


def cookies_to_string(cookies):
    """list cookie dict → chuỗi phẳng ``a=b; c=d`` (chỉ cookie domain Facebook).

    Giữ thứ tự xuất hiện, dedupe theo tên. Cookie có value chứa ``;`` hoặc
    newline không biểu diễn được trong format phẳng nên bị bỏ (những cookie đó
    vẫn còn nguyên trong jar).
    """
    pairs, seen = [], set()
    for c in cookies or []:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        value = c.get("value")
        if not name or name in seen or value is None:
            continue
        if not _is_fb_domain(c.get("domain")):
            continue
        value = str(value)
        if ";" in value or "\n" in value or "\r" in value:
            continue
        seen.add(name)
        pairs.append("%s=%s" % (name, value))
    return "; ".join(pairs)


# =====================================================================
# Chuẩn hoá cookie trước khi add vào context
# =====================================================================

_SAME_SITE = {"strict": "Strict", "lax": "Lax", "none": "None"}


def prepare_cookie(c, default_domain=".facebook.com"):
    """Chuẩn hoá 1 cookie dict thành payload hợp lệ cho ``ctx.add_cookies``.

    - ``domain``/``path`` giữ theo cookie (chỉ fallback khi thiếu).
    - ``expires``: chỉ truyền khi có giá trị thật > 0 (epoch giây). Không có
      nghĩa là session cookie → bỏ hẳn field, không bịa hạn.
    """
    if not isinstance(c, dict):
        return None
    name = (c.get("name") or "").strip()
    if not name:
        return None
    domain = (c.get("domain") or "").strip() or default_domain
    if " " in domain:
        return None
    out = {
        "name": name,
        "value": "" if c.get("value") is None else str(c.get("value")),
        "domain": domain,
        "path": (c.get("path") or "/") or "/",
    }
    secure = c.get("secure")
    out["secure"] = bool(secure) if secure is not None else _is_fb_domain(domain)
    http_only = c.get("httpOnly", c.get("http_only"))
    if http_only is not None:
        out["httpOnly"] = bool(http_only)
    same_site = _SAME_SITE.get(str(c.get("sameSite") or c.get("same_site") or "").lower())
    if same_site:
        out["sameSite"] = same_site

    expires = c.get("expires", c.get("expires_at"))
    if expires is not None:
        try:
            expires = float(expires)
        except (TypeError, ValueError):
            expires = None
        if expires is not None and expires > 0:
            out["expires"] = expires
    return out


def apply_cookies(ctx, cookies, prefer_disk=True):
    """Add cookie vào context, bỏ qua từng cookie lỗi thay vì chết cả lô.

    - Rebinding: nếu đã ``bind_context`` trước đó, context mới (``restart_browser``)
      tự động trở thành context được autosave.
    - ``prefer_disk``: nếu run này đã từng ghi jar (``last_save > 0``) thì dùng
      cookie trên đĩa thay cho list ``cookies`` truyền vào — vì list đó được đọc
      lúc đầu run và đã cũ so với cookie server cấp trong lúc chạy. Nhờ vậy
      ``restart_browser()`` không replay lại cookie cũ.
    """
    if ctx is None:
        return 0
    if prefer_disk and _BOUND.get("cookie_path") and _BOUND.get("last_save", 0) > 0:
        try:
            fresh = load_cookies(_BOUND["cookie_path"])
        except Exception:
            fresh = None
        if fresh:
            cookies = fresh
    prepared = [p for p in (prepare_cookie(c) for c in cookies or []) if p]
    added = 0
    for i in range(0, len(prepared), 20):
        batch = prepared[i:i + 20]
        try:
            ctx.add_cookies(batch)
            added += len(batch)
        except Exception:
            for c in batch:
                try:
                    ctx.add_cookies([c])
                    added += 1
                except Exception:
                    continue
    if _BOUND.get("cookie_path"):
        _BOUND["ctx"] = ctx
    return added


# =====================================================================
# Jar: lưu / khôi phục cookie thật
# =====================================================================

_LAST_LOAD = {}


def last_load_summary():
    """Chuỗi ngắn mô tả nguồn cookie của lần ``load_cookies`` gần nhất (để log)."""
    if not _LAST_LOAD:
        return "no-load"
    return "%s (txt=%d, jar=%d, lineage=%s)" % (
        _LAST_LOAD.get("source", "?"),
        _LAST_LOAD.get("txt_count", 0),
        _LAST_LOAD.get("jar_count", 0),
        "match" if _LAST_LOAD.get("txt_known") else "edited",
    )


def loaded_c_user():
    """``c_user`` của cookie đã load cho run này (None nếu file không có)."""
    return _LAST_LOAD.get("c_user")


def load_cookies(cookie_path):
    """Đọc cookie để dùng cho run này: merge ``ck*.txt`` + jar.

    Quy tắc chọn (deterministic, không dựa vào mtime — vì trên CI mtime luôn là
    thời điểm checkout):

    - Jar có ``history`` = danh sách digest của *những nội dung txt mà chính bot
      đã ghi ra*. Nếu digest của txt hiện tại nằm trong history ⇒ txt này do bot
      sinh ra ở một run trước ⇒ **jar mới hơn**, dùng jar (nó chứa giá trị
      server cấp mới nhất, kể cả khi txt chưa được commit).
    - Nếu digest không nằm trong history ⇒ người dùng vừa dán cookie mới vào txt
      ⇒ **txt thắng**; jar chỉ bù những cookie mà txt không có.

    Trả về list cookie dict (đã sẵn sàng cho ``apply_cookies``).
    """
    raw = _read_text(cookie_path)
    txt_cookies = parse_cookie_string(raw)
    jar = _read_json(_jar_path(cookie_path), None)

    _LAST_LOAD.clear()
    _LAST_LOAD.update({"source": "txt", "txt_count": len(txt_cookies),
                       "jar_count": 0, "txt_known": False})

    if not isinstance(jar, dict) or not isinstance(jar.get("cookies"), list):
        _LAST_LOAD["c_user"] = _c_user_of(txt_cookies)
        return txt_cookies

    jar_cookies = [c for c in jar["cookies"] if isinstance(c, dict) and c.get("name")]
    history = [h for h in (jar.get("history") or []) if isinstance(h, str)]
    txt_known = bool(history) and _sha(raw) in history

    _LAST_LOAD.update({"jar_count": len(jar_cookies), "txt_known": txt_known})

    if txt_known:
        merged = _merge(primary=jar_cookies, secondary=txt_cookies)
        _LAST_LOAD["source"] = "jar"
    else:
        merged = _merge(primary=txt_cookies, secondary=jar_cookies)
        _LAST_LOAD["source"] = "txt"

    # c_user của nguồn đã chọn — dùng để phát hiện "nhầm account" lúc detect login.
    _LAST_LOAD["c_user"] = _c_user_of(merged)
    return merged


def _merge(primary, secondary):
    """primary thắng khi trùng tên; secondary chỉ bù cookie còn thiếu."""
    out, seen = [], set()
    for c in primary:
        name = (c.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(dict(c))
    for c in secondary:
        name = (c.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(dict(c))
    return out


def _live_session_ok(live):
    """Chỉ ghi file khi context thật sự còn session (tránh xoá sạch cookie tốt)."""
    have = {}
    for c in live or []:
        name = (c.get("name") or "").strip()
        if name in SESSION_COOKIE_NAMES and (c.get("value") or ""):
            have[name] = c
    return all(n in have for n in SESSION_COOKIE_NAMES)


def _order_like(reference, live):
    """Sắp cookie theo thứ tự file cũ (dễ đọc diff), live thắng khi trùng tên.

    Cookie có trong file mà context không có vẫn được GIỮ LẠI: một run có thể
    không chạm tới ``sb``/``fr`` (chưa request tới domain tương ứng) — xoá khỏi
    file chỉ vì thế sẽ làm mất dữ liệu tốt.
    """
    by_name = {}
    for c in live:
        name = c.get("name")
        if name and name not in by_name:
            by_name[name] = c
    out = []
    for c in reference:
        name = c.get("name")
        if name in by_name:
            out.append(by_name.pop(name))
        else:
            fallback = prepare_cookie(c)
            if fallback:
                out.append(fallback)
    out.extend(by_name.values())
    return out


def save_cookies(ctx, cookie_path=None, force=False):
    """Đọc cookie THẬT từ browser context và ghi lại xuống đĩa.

    Ghi 2 nơi:
      - ``ck*.txt`` (định dạng phẳng cũ, chỉ cookie domain Facebook) — nguồn
        mà run sau / người dùng đọc.
      - ``state/cookies/<ck>.jar.json`` — đầy đủ domain/path/secure/httpOnly/
        sameSite/expires + ``history`` digest để lần sau biết bản nào mới hơn.

    Từ chối ghi nếu context không còn đủ ``c_user`` + ``xs`` (ví dụ đang ở trang
    login) — thà giữ file cũ còn hơn ghi đè bằng rỗng.

    Trả về dict mô tả kết quả để script log lại.
    """
    path = cookie_path or _BOUND.get("cookie_path")
    if ctx is None or not path:
        return {"saved": False, "reason": "no context/path"}

    now = time.time()
    if not force and (now - _BOUND.get("last_save", 0.0)) < AUTOSAVE_MIN_INTERVAL:
        return {"saved": False, "reason": "throttled"}

    try:
        live = ctx.cookies()
    except Exception as exc:                      # browser đã đóng / crash
        return {"saved": False, "reason": "ctx.cookies() failed: %s" % exc}

    live = [c for c in (prepare_cookie(x) for x in live or []) if c]
    # bỏ cookie đã hết hạn thật
    live = [c for c in live if not c.get("expires") or c["expires"] > now]

    if not _live_session_ok(live):
        return {"saved": False, "reason": "context không còn c_user+xs — giữ nguyên file cũ"}

    path = os.path.abspath(path)
    jar_path = _jar_path(path)
    old_jar = _read_json(jar_path, None) or {}
    history = [h for h in (old_jar.get("history") or []) if isinstance(h, str)]

    raw_txt = _read_text(path)
    reference = parse_cookie_string(raw_txt)
    ordered = _order_like(reference, live)

    new_txt = cookies_to_string(ordered) or raw_txt.strip()
    txt_changed = new_txt.strip() != raw_txt.strip()

    if txt_changed:
        _atomic_write(path, new_txt.strip() + "\n")

    digest = _sha(new_txt.strip() + "\n" if txt_changed else raw_txt)
    if digest not in history:
        history.append(digest)
    history = history[-HISTORY_LIMIT:]

    jar = {
        "version": JAR_VERSION,
        "cookie_file": os.path.basename(path),
        "saved_at": now,
        "saved_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "history": history,
        "cookies": ordered,
    }
    try:
        _atomic_write(jar_path, json.dumps(jar, ensure_ascii=False, indent=2) + "\n")
    except OSError as exc:
        return {"saved": txt_changed, "reason": "jar write failed: %s" % exc,
                "txt_changed": txt_changed, "count": len(ordered)}

    _BOUND["last_save"] = now
    return {"saved": True, "count": len(ordered), "txt_changed": txt_changed,
            "jar": jar_path, "c_user": _c_user_of(ordered)}


def _c_user_of(cookies):
    for c in cookies or []:
        if c.get("name") == "c_user":
            return (c.get("value") or "").strip() or None
    return None


# =====================================================================
# Autosave: bind context + flush khi thoát
# =====================================================================

_BOUND = {"ctx": None, "cookie_path": None, "last_save": 0.0,
          "hooked": False, "flushing": False}
_PREV_SIGNAL = {}


def bind_context(ctx, cookie_path=None):
    """Gắn context hiện tại với file cookie để autosave khi process kết thúc.

    Flush được kích hoạt bởi: ``atexit``, SIGTERM, SIGINT và các lời gọi
    ``save_cookies`` rải trong script. Trả về hàm ``flush()`` tiện dùng.
    """
    if ctx is not None:
        _BOUND["ctx"] = ctx
    if cookie_path:
        _BOUND["cookie_path"] = os.path.abspath(cookie_path)
    _install_exit_hooks()
    return flush_cookies


def current_context():
    """Context đang được theo dõi (dùng cho hàm không nhận ctx, vd find_game_frame)."""
    return _BOUND.get("ctx")


def flush_cookies(*_args, **_kwargs):
    """Ghi cookie ngay (bỏ throttle). An toàn khi gọi nhiều lần."""
    if _BOUND.get("flushing"):
        return {"saved": False, "reason": "already-flushing"}
    _BOUND["flushing"] = True
    try:
        return save_cookies(_BOUND.get("ctx"), _BOUND.get("cookie_path"), force=True)
    finally:
        _BOUND["flushing"] = False


def _atexit_flush():
    try:
        res = flush_cookies()
        if res.get("saved"):
            print("[cookie] flushed on exit: %s cookies (txt_changed=%s)"
                  % (res.get("count"), res.get("txt_changed")), flush=True)
        elif res.get("reason") not in (None, "no context/path"):
            print("[cookie] exit flush skipped: %s" % res.get("reason"), flush=True)
    except Exception as exc:                      # không để lỗi cookie che lỗi thật
        print("[cookie] exit flush failed: %s" % exc, flush=True)


def _handle_signal(signum, frame):
    try:
        res = flush_cookies()
        if res.get("saved"):
            print("[cookie] flushed on signal %s: %s cookies" % (signum, res.get("count")),
                  flush=True)
    except Exception as exc:
        print("[cookie] signal flush failed: %s" % exc, flush=True)
    prev = _PREV_SIGNAL.get(signum)
    try:
        if callable(prev) and prev not in (signal.SIG_DFL, signal.SIG_IGN):
            prev(signum, frame)
            return
    except Exception:
        pass
    try:
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
    except Exception:
        os._exit(128 + signum)


def _install_exit_hooks():
    if _BOUND.get("hooked"):
        return
    _BOUND["hooked"] = True
    atexit.register(_atexit_flush)
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            _PREV_SIGNAL[sig] = signal.getsignal(sig)
            signal.signal(sig, _handle_signal)
        except (ValueError, OSError, RuntimeError):
            # không ở main thread → chỉ còn atexit
            continue


# =====================================================================
# Login-state detection — dựa trên bằng chứng, không dựa vào chữ trên trang
# =====================================================================

JS_LOGIN_FORM = """() => {
    const visible = (el) => {
        try {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 1 && r.height > 1 && s.visibility !== 'hidden'
                   && s.display !== 'none' && s.opacity !== '0';
        } catch (e) { return false; }
    };
    const pw = [...document.querySelectorAll('input[type="password"]')].filter(visible);
    const form = document.querySelector(
        '#login_form, form[action*="login"], [data-testid="royal_login_form"]');
    // dấu hiệu "đã đăng nhập": nav/profile chrome của FB
    const loggedInHint = !!document.querySelector(
        '[data-pagelet="LeftNav"], [role="navigation"] a[href*="/friends"], ' +
        'a[aria-label][href*="/me/"], [data-testid="blue_bar_profile_link"]');
    return {
        passwordInputs: pw.length,
        loginForm: !!form && visible(form),
        loggedInHint: loggedInHint
    };
}"""


def _url_verdict(url):
    """Xét URL: 'logged_out' | 'checkpoint' | None."""
    low = (url or "").lower()
    if not low or "facebook.com" not in low:
        return None
    if "/checkpoint" in low or "/two_step_verification" in low or "/login/checkpoint" in low:
        return "checkpoint"
    if ("/login" in low or low.rstrip("/").endswith("login.php")
            or "/recover" in low or "/login.php" in low):
        return "logged_out"
    return None


def detect_login_state(page=None, ctx=None, response=None, expected_c_user=None):
    """Kết luận trạng thái đăng nhập kèm bằng chứng.

    Trả về dict::

        {"state": "logged_in"|"logged_out"|"checkpoint"|"unknown",
         "reason": "<chuỗi ngắn>",
         "evidence": {...},        # dữ liệu thô để log
         "c_user": "...", "user_switched": bool}

    Chỉ trả ``logged_out``/``checkpoint`` khi có bằng chứng cứng. Mọi trường
    hợp mơ hồ (trang chưa render, consent dialog, DOM lạ) → ``unknown``, để
    script tiếp tục chờ thay vì kill run.
    """
    ev = {}

    # --- 1. Cookie: bằng chứng mạnh nhất -----------------------------------
    cookies = []
    for owner in (ctx, getattr(page, "context", None)):
        if owner is None:
            continue
        try:
            cookies = owner.cookies() or []
            break
        except Exception as exc:
            ev["cookie_error"] = str(exc)
    cmap = {}
    for c in cookies:
        if isinstance(c, dict) and c.get("name"):
            cmap[c["name"]] = c.get("value") or ""
    c_user = (cmap.get("c_user") or "").strip()
    ev["has_c_user"] = bool(c_user)
    ev["has_xs"] = bool((cmap.get("xs") or "").strip())
    ev["cookie_count"] = len(cookies)
    has_session = ev["has_c_user"] and ev["has_xs"]

    # --- 2. URL -------------------------------------------------------------
    url = ""
    frames = []
    try:
        url = page.url if page is not None else ""
        frames = [f.url for f in page.frames][:8] if page is not None else []
    except Exception:
        pass
    ev["url"] = (url or "")[:160]
    ev["frames"] = frames
    url_state = _url_verdict(url)
    ev["url_state"] = url_state

    # --- 3. HTTP response của document -------------------------------------
    if response is not None:
        try:
            ev["http_status"] = response.status
            ev["http_url"] = (response.url or "")[:160]
        except Exception:
            pass

    # --- 4. DOM: form mật khẩu đang hiện + dấu hiệu đã login ---------------
    dom = {}
    if page is not None:
        try:
            dom = page.evaluate(JS_LOGIN_FORM) or {}
        except Exception as exc:
            ev["dom_error"] = str(exc)
    ev["dom"] = dom
    pw_prompt = bool(dom.get("passwordInputs")) or bool(dom.get("loginForm"))
    ev["password_prompt_visible"] = pw_prompt
    ev["logged_in_hint"] = bool(dom.get("loggedInHint"))

    # --- 5. c_user có khớp file cookie không -------------------------------
    if expected_c_user is None:
        expected_c_user = _LAST_LOAD.get("c_user")
    user_switched = False
    if expected_c_user and c_user and str(expected_c_user) != c_user:
        user_switched = True
    ev["user_switched"] = user_switched

    status = ev.get("http_status")
    http_auth_fail = status in (401, 403)

    # --- Kết luận -----------------------------------------------------------
    if url_state == "checkpoint":
        return _verdict("checkpoint",
                        "URL là checkpoint/two-step verification", ev, c_user, user_switched)
    if has_session:
        if pw_prompt and not ev["logged_in_hint"] and url_state == "logged_out":
            return _verdict("logged_out",
                            "đang ở URL login và có form mật khẩu dù vẫn còn c_user/xs", ev,
                            c_user, user_switched)
        if http_auth_fail and pw_prompt:
            return _verdict("logged_out", "HTTP %s + form mật khẩu" % status, ev,
                            c_user, user_switched)
        reason = "có c_user + xs, URL không phải login/checkpoint"
        if user_switched:
            reason += " (⚠ c_user khác file cookie: %s ≠ %s)" % (c_user, expected_c_user)
        return _verdict("logged_in", reason, ev, c_user, user_switched)

    # Không có session cookie
    if url_state == "logged_out":
        return _verdict("logged_out", "URL login + không có c_user/xs", ev, c_user, user_switched)
    if pw_prompt:
        return _verdict("logged_out", "form mật khẩu hiển thị + không có c_user/xs", ev,
                        c_user, user_switched)
    if http_auth_fail:
        return _verdict("logged_out", "HTTP %s + không có c_user/xs" % status, ev,
                        c_user, user_switched)
    return _verdict("unknown",
                    "thiếu c_user/xs nhưng không có dấu hiệu login (DOM chưa render?)", ev,
                    c_user, user_switched)


def _verdict(state, reason, ev, c_user, user_switched):
    return {"state": state, "reason": reason, "evidence": ev,
            "c_user": c_user or None, "user_switched": user_switched}


def format_evidence(state, limit=400):
    """Chuỗi 1 dòng gọn để log."""
    ev = dict(state.get("evidence") or {})
    ev.pop("frames", None)          # dài, không cần
    text = json.dumps(ev, ensure_ascii=False, sort_keys=True)
    return text[:limit]
