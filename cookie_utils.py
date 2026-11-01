"""Cookie utilities for jieqi-core automation scripts.

Chỉ ĐỌC cookie từ file ``ck*.txt`` và đưa vào Playwright context.
KHÔNG làm tươi, KHÔNG lưu/ghi đè file cookie, KHÔNG dùng jar.

Nguyên tắc:
1. KHÔNG bịa ``expires``: cookie từ file được giữ nguyên (session cookie
   như ``c_user``/``xs`` thì để nguyên, không set hạn 400 ngày).
2. Chỉ đọc txt, không ghi lại gì cả → file cookie không bị thay đổi bởi bot.
3. Phát hiện login dựa trên bằng chứng (cookie c_user/xs, URL checkpoint,
   form mật khẩu, HTTP 401/403), không dựa vào chữ "Đăng nhập" trên trang.
"""

import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))

# Tên cookie quyết định "còn đăng nhập hay không".
SESSION_COOKIE_NAMES = ("c_user", "xs")

# Chỉ cookie thuộc domain Facebook mới được nhận từ file txt.
FB_DOMAIN_SUFFIX = "facebook.com"


def _is_fb_domain(domain):
    d = (domain or "").lstrip(".").lower()
    return d == FB_DOMAIN_SUFFIX or d.endswith("." + FB_DOMAIN_SUFFIX)


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


# =====================================================================
# Parse / serialize ck*.txt  (KHÔNG set expires, KHÔNG ghi file)
# =====================================================================

def parse_cookie_string(raw, domain=".facebook.com", path="/", secure=True,
                        http_only=False, same_site="Lax"):
    """``name=value; name2=value2`` → list cookie dict cho Playwright.

    Không tự set ``expires``: cookie từ file là session cookie, đúng như
    Facebook cấp ``c_user``/``xs``.
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
    """list cookie dict → chuỗi phẳng ``a=b; c=d`` (chỉ cookie domain Facebook)."""
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

    ``expires`` chỉ truyền khi có giá trị thật > 0; session cookie không có
    trường ``expires``.
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


def apply_cookies(ctx, cookies):
    """Add cookie vào context, bỏ qua từng cookie lỗi thay vì chết cả lô."""
    if ctx is None:
        return 0
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
    return added


# =====================================================================
# Đọc cookie từ file txt (chỉ đọc, không lưu)
# =====================================================================

_LAST_LOAD = {"source": "txt", "txt_count": 0, "c_user": None}


def last_load_summary():
    """Chuỗi ngắn mô tả nguồn cookie của lần ``load_cookies`` gần nhất."""
    return "txt=%d" % _LAST_LOAD.get("txt_count", 0)


def loaded_c_user():
    """``c_user`` của cookie đã load cho run này (None nếu file không có)."""
    return _LAST_LOAD.get("c_user")


def load_cookies(cookie_path):
    """Đọc cookie từ file txt (chỉ đọc, không lưu, không jar).

    Trả về list cookie dict đã sẵn sàng cho ``apply_cookies``.
    """
    raw = _read_text(cookie_path)
    cookies = parse_cookie_string(raw)
    _LAST_LOAD.clear()
    _LAST_LOAD.update({"source": "txt", "txt_count": len(cookies),
                       "c_user": _c_user_of(cookies)})
    return cookies


def _c_user_of(cookies):
    for c in cookies or []:
        if c.get("name") == "c_user":
            return (c.get("value") or "").strip() or None
    return None


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
         "evidence": {...},
         "c_user": "...", "user_switched": bool}

    Chỉ trả ``logged_out``/``checkpoint`` khi có bằng chứng cứng. Mọi trường
    hợp mơ hồ → ``unknown``, để script tiếp tục chờ thay vì kill run.
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

    names = {c.get("name") for c in cookies if isinstance(c, dict)}
    has_c_user = "c_user" in names and any(
        c.get("name") == "c_user" and c.get("value") for c in cookies)
    has_xs = "xs" in names and any(
        c.get("name") == "xs" and c.get("value") for c in cookies)

    c_user_val = None
    for c in cookies:
        if c.get("name") == "c_user":
            c_user_val = (c.get("value") or "").strip() or None
            break

    ev["has_c_user"] = bool(has_c_user)
    ev["has_xs"] = bool(has_xs)
    ev["c_user"] = c_user_val

    user_switched = False
    if expected_c_user is None:
        expected_c_user = loaded_c_user()
    if expected_c_user and c_user_val and c_user_val != expected_c_user:
        user_switched = True
    ev["user_switched"] = bool(user_switched)

    # --- 2. URL ------------------------------------------------------------
    url = None
    if page is not None:
        try:
            url = page.url
        except Exception:
            pass
    if response is not None:
        try:
            url = getattr(response, "url", url) or url
        except Exception:
            pass
    ev["url"] = url

    verdict = _url_verdict(url)
    if verdict:
        ev["url_verdict"] = verdict

    # --- 3. DOM login form ------------------------------------------------
    dom = None
    if page is not None:
        try:
            dom = page.evaluate(JS_LOGIN_FORM)
        except Exception as exc:
            ev["dom_error"] = str(exc)
    ev.update(dom or {})

    # --- 4. HTTP status ----------------------------------------------------
    http_status = None
    if response is not None:
        try:
            http_status = getattr(response, "status", None)
        except Exception:
            pass
    if http_status:
        ev["http_status"] = http_status

    # --- 5. Kết luận -------------------------------------------------------
    now_logged_in = has_c_user and has_xs

    if verdict == "checkpoint":
        state = "checkpoint"
        reason = "URL là checkpoint/two-step verification"
    elif verdict == "logged_out" and not now_logged_in:
        state = "logged_out"
        reason = "URL login và không có session c_user/xs"
    elif http_status in (401, 403) and not now_logged_in:
        state = "logged_out"
        reason = "HTTP %d và không có session c_user/xs" % http_status
    elif dom and dom.get("loginForm") and not now_logged_in:
        state = "logged_out"
        reason = "Form mật khẩu đang hiển thị và không có session c_user/xs"
    elif now_logged_in:
        state = "logged_in"
        reason = "Có c_user + xs trong cookie"
    else:
        state = "unknown"
        reason = "Không đủ bằng chứng để kết luận"

    return {
        "state": state,
        "reason": reason,
        "evidence": ev,
        "c_user": c_user_val,
        "user_switched": bool(user_switched),
    }


def format_evidence(ev):
    """Chuỗi ngắn gộp bằng chứng để log."""
    parts = []
    if ev.get("url"):
        parts.append("url=%s" % ev["url"])
    if ev.get("http_status"):
        parts.append("http=%s" % ev["http_status"])
    parts.append("c_user=%s" % ("yes" if ev.get("has_c_user") else "no"))
    parts.append("xs=%s" % ("yes" if ev.get("has_xs") else "no"))
    if ev.get("passwordInputs") is not None:
        parts.append("pw=%s" % ev["passwordInputs"])
    if ev.get("loginForm") is not None:
        parts.append("loginForm=%s" % ev["loginForm"])
    if ev.get("loggedInHint") is not None:
        parts.append("loggedInHint=%s" % ev["loggedInHint"])
    if ev.get("reason"):
        parts.append("reason=%s" % ev["reason"])
    return "; ".join(parts)
