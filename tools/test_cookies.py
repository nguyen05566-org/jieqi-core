#!/usr/bin/env python3
"""
Facebook cookie liveness check v2 — real Chromium (Playwright).

Why v2: plain urllib requests get HTTP 400 from Facebook for every
request (including a no-cookie control) due to TLS/bot fingerprinting,
so v1 results were inconclusive. This version navigates like the bots
themselves do (Chromium + cookies on .facebook.com) and classifies from
browser-observable signals only:

  ALIVE       facebook.com loads logged-in: page HTML contains
              "USER_ID":"<c_user>" (or /me redirects to a profile)
              and no login redirect.
  DEAD        redirected to login, login form served with no trace of
              the account, or the c_user cookie is dropped/deleted
              by the server in the browser context.
  CHECKPOINT  redirected to /checkpoint, /recover, two-factor, etc.
              (session recognised but Facebook wants verification —
              common from datacenter IPs even for valid cookies)
  BLOCKED     Facebook anti-bot / temporarily-blocked page.
  ERROR       navigation/network failure or inconclusive signals.

Never prints or writes cookie values. Only masked c_user (last 4).
Duplicates (identical c_user+xs) are tested once and reused.
Writes cookie_test_results.json/.md and appends to $GITHUB_STEP_SUMMARY.
"""
import glob
import hashlib
import json
import os
import re
import sys
import time

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
FB_HOME = "https://www.facebook.com/"
FB_ME = "https://www.facebook.com/me"


def parse_cookie_string(raw):
    pairs, cookies = {}, []
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        n, v = part.split("=", 1)
        n, v = n.strip(), v.strip()
        pairs[n] = v
        cookies.append({"name": n, "value": v, "domain": ".facebook.com",
                        "path": "/", "secure": True, "httpOnly": False,
                        "sameSite": "Lax"})
    return pairs, cookies


def classify(page, context, c_user):
    """Inspect current page/context. Returns (status, evidence, final_url)."""
    final = page.url
    low = final.lower()
    try:
        html = page.content()
    except Exception:
        html = ""
    try:
        body = page.inner_text("body")[:3000]
    except Exception:
        body = ""
    low_html = html.lower()

    if "/checkpoint" in low:
        return "CHECKPOINT", "redirect to checkpoint", final
    if any(x in low for x in ("/recover/", "/two_factor", "/confirmemail",
                              "/login/identify", "checkpoint")):
        return "CHECKPOINT", f"redirect: {final.split('?')[0]}", final
    if "temporarily blocked" in low_html or "bị chặn tạm thời" in low_html:
        return "BLOCKED", "temporarily blocked page", final

    m = re.search(r'"USER_ID":"(\d+)"', html) or re.search(r'"ACCOUNT_ID":"(\d+)"', html)
    user_id_match = bool(m and c_user and m.group(1) == c_user)
    viewer_match = bool(c_user) and (f'"viewerID":"{c_user}"' in html)

    # cookies still present in context after navigation?
    try:
        ctx_cookies = {c["name"]: c["value"] for c in context.cookies()}
    except Exception:
        ctx_cookies = {}
    cookie_kept = bool(c_user) and ctx_cookies.get("c_user") == c_user
    cookie_deleted = ("c_user" in ctx_cookies and ctx_cookies.get("c_user") in ("", "deleted")) \
        or (bool(c_user) and "c_user" not in ctx_cookies and "/login" in low)

    has_login_form = False
    for sel in ('input[name="email"]', 'input[name="pass"]', '#login_form', 'form[action*="login"]'):
        try:
            if page.locator(sel).count() > 0:
                has_login_form = True
                break
        except Exception:
            pass
    login_text = ("đăng nhập" in body.lower() or "log in" in body.lower()) and has_login_form

    if user_id_match or viewer_match:
        return "ALIVE", "page HTML USER_ID matches c_user", final
    if "/login" in low or "login.php" in low:
        return "DEAD", "redirect to login page", final
    if cookie_deleted:
        return "DEAD", "c_user cookie dropped/deleted by server", final
    if login_text:
        return "DEAD", "logged-out login form served", final
    if cookie_kept and not has_login_form:
        return "ALIVE", "session cookie kept, no login form/redirect", final
    return "ERROR", (f"inconclusive: login_form={has_login_form} "
                     f"cookie_kept={cookie_kept} id_match={user_id_match}"), final


def probe(browser, cookies, c_user):
    context = browser.new_context(user_agent=UA, locale="vi-VN",
                                  viewport={"width": 1366, "height": 768})
    try:
        if cookies:
            try:
                context.add_cookies(cookies)
            except Exception as e:
                return {"status": "ERROR", "http": None, "final": "",
                        "evidence": f"add_cookies failed: {type(e).__name__}"}
        page = context.new_page()
        try:
            page.goto(FB_HOME, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            return {"status": "ERROR", "http": None, "final": page.url,
                    "evidence": f"navigation failed: {type(e).__name__}"}
        page.wait_for_timeout(4000)
        status, evidence, final = classify(page, context, c_user)
        if status == "ERROR" and c_user:
            # second signal: /me redirects to the profile when logged in
            try:
                page.goto(FB_ME, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3000)
                status2, evidence2, final2 = classify(page, context, c_user)
                low2 = final2.lower()
                if status2 != "ERROR":
                    return {"status": status2, "http": 200, "final": final2,
                            "evidence": f"/me probe: {evidence2}"}
                if "/login" not in low2 and "facebook.com/" in low2 and len(final2.rstrip("/")) > 25:
                    return {"status": "ALIVE", "http": 200, "final": final2,
                            "evidence": "/me redirected to a profile page"}
                status, evidence, final = status2, f"/me probe: {evidence2}", final2
            except Exception as e:
                evidence += f"; /me failed: {type(e).__name__}"
        return {"status": status, "http": 200 if final else None,
                "final": final, "evidence": evidence}
    finally:
        context.close()


def main():
    from playwright.sync_api import sync_playwright

    files = sorted(glob.glob("ck*.txt"),
                   key=lambda p: (len(os.path.basename(p)), os.path.basename(p)))
    if not files:
        print("No ck*.txt found")
        return 1

    results, by_hash = [], {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
        )

        print("== controls ==", flush=True)
        for label, cookies, cu in [
            ("_control_no_cookie", [], ""),
            ("_control_bogus_cookie",
             [{"name": "c_user", "value": "100000000000000", "domain": ".facebook.com",
               "path": "/", "secure": True, "httpOnly": False, "sameSite": "Lax"},
              {"name": "xs", "value": "bogusinvalidtoken", "domain": ".facebook.com",
               "path": "/", "secure": True, "httpOnly": False, "sameSite": "Lax"}],
             "100000000000000"),
        ]:
            r = probe(browser, cookies, cu)
            print(f"{label}: {r['status']} final={str(r['final']).split('?')[0]} :: {r['evidence']}", flush=True)
            results.append({"file": label, "c_user": "***0000" if cu else "-",
                            "status": r["status"], "http": r["http"],
                            "final": str(r["final"]).split("?")[0],
                            "evidence": r["evidence"]})
            time.sleep(2)

        print(f"\n== {len(files)} cookie files ==", flush=True)
        for path in files:
            raw = open(path, encoding="utf-8", errors="replace").read().strip()
            pairs, cookies = parse_cookie_string(raw)
            c_user, xs = pairs.get("c_user", ""), pairs.get("xs", "")
            masked = ("***" + c_user[-4:]) if c_user else "MISSING"
            if not c_user or not xs:
                entry = {"file": path, "c_user": masked, "status": "INVALID_FORMAT",
                         "http": None, "final": "", "evidence": "missing c_user or xs in file"}
                results.append(entry)
                print(f"{path}: INVALID_FORMAT", flush=True)
                continue
            digest = hashlib.sha256((c_user + ":" + xs).encode()).hexdigest()
            if digest in by_hash:
                orig = by_hash[digest]
                entry = {"file": path, "c_user": masked, "status": orig["status"],
                         "http": orig["http"], "final": orig["final"],
                         "evidence": f"identical cookie to {orig['file']} (not re-tested)"}
                results.append(entry)
                print(f"{path}: {entry['status']} (duplicate of {orig['file']})", flush=True)
                continue
            try:
                r = probe(browser, cookies, c_user)
            except Exception as e:  # browser died -> relaunch once
                print(f"{path}: browser error {e}, relaunching...", flush=True)
                try:
                    browser.close()
                except Exception:
                    pass
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage",
                          "--disable-blink-features=AutomationControlled"])
                r = probe(browser, cookies, c_user)
            entry = {"file": path, "c_user": masked, "status": r["status"],
                     "http": r["http"], "final": str(r["final"]).split("?")[0],
                     "evidence": r["evidence"]}
            by_hash[digest] = entry
            results.append(entry)
            print(f"{path}: {r['status']} final={entry['final']} :: {r['evidence']}", flush=True)
            time.sleep(2)
        browser.close()

    with open("cookie_test_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    lines = ["| File | c_user | Status | Final URL | Evidence |",
             "|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['file']} | {r['c_user']} | **{r['status']}** | {r['final']} | {r['evidence']} |")
    md = "\n".join(lines) + "\n"
    with open("cookie_test_results.md", "w", encoding="utf-8") as f:
        f.write(md)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Cookie test results (Playwright/Chromium)\n\n" + md)
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
