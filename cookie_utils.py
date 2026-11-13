#!/usr/bin/env python3
"""
cookie_utils — cookie parsing helpers for ck2.py / ws_bot flow.
"""
import re
from http.cookies import SimpleCookie

def parse_cookie_string(cookie_text):
    """Parse a 'name=val; name2=val2' cookie string into a list of dicts
    with keys: name, value, domain, path."""
    cookies = []
    if not cookie_text:
        return cookies
    for part in cookie_text.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        cookies.append({
            "name": name.strip(),
            "value": value.strip(),
            "domain": ".facebook.com",
            "path": "/",
        })
    return cookies


def extend_cookie_expiry(cookies):
    """No-op placeholder for cookie expiry extension (kept for import compat)."""
    return cookies
