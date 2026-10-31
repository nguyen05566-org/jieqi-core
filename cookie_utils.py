"""Cookie utilities for jieqi-core automation scripts.

Provides helpers to parse raw cookie strings and to extend cookie expiry up to the
maximum lifetime allowed by Chromium-based browsers (400 days), so that login
sessions stay alive as long as possible on the client side.

Note: this only extends the *client-side* expiry. The server-side session may
still expire according to its own TTL; the automation must keep interacting with
the site periodically to keep the server session alive.
"""

import time

# Chromium caps cookie lifetime at 400 days (Chrome M104+).
MAX_COOKIE_EXPIRY_DAYS = 400
MAX_COOKIE_EXPIRY_SECONDS = MAX_COOKIE_EXPIRY_DAYS * 24 * 60 * 60

# Refresh threshold: if a cookie expires within this many seconds, bump it.
_REFRESH_THRESHOLD_SECONDS = 7 * 24 * 60 * 60


def extend_cookie_expiry(cookies, days=MAX_COOKIE_EXPIRY_DAYS):
    """Extend cookie expiry up to ``days`` (default 400) for each cookie.

    - Session cookies (no ``expires`` / ``expires <= 0``) become persistent.
    - Cookies expiring within the refresh threshold are bumped to the new max.
    - Cookies already valid beyond the threshold keep their existing expiry.
    - Existing attributes (domain, path, secure, httpOnly, sameSite) are preserved.

    Returns the same list (mutated in place) for convenience.
    """
    now = time.time()
    target = now + days * 24 * 60 * 60
    threshold = now + _REFRESH_THRESHOLD_SECONDS
    for c in cookies or []:
        exp = c.get("expires", None)
        try:
            exp = float(exp) if exp is not None else 0.0
        except (TypeError, ValueError):
            exp = 0.0
        if exp <= 0 or exp < threshold or exp < target:
            # Only bump if it would actually extend the lifetime.
            if exp <= 0 or target > exp:
                c["expires"] = target
    return cookies


def parse_cookie_string(raw, domain=".facebook.com", path="/", secure=True,
                        http_only=False, same_site="Lax"):
    """Parse a raw ``name=value; name2=value2`` cookie string into Playwright
    cookie dicts, extending expiry to the max allowed (400 days)."""
    out = []
    for part in (raw or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        n, v = part.split("=", 1)
        out.append({
            "name": n.strip(),
            "value": v.strip(),
            "domain": domain,
            "path": path,
            "secure": bool(secure),
            "httpOnly": bool(http_only),
            "sameSite": same_site,
        })
    extend_cookie_expiry(out)
    return out
