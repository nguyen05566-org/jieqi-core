#!/usr/bin/env python3
"""
Lightweight Facebook cookie liveness check.

- Reads ck*.txt in repo root (format: "name=value; name=value; ...").
- NEVER prints / writes cookie values. Only masked c_user (last 4) is reported.
- One plain HTTPS GET to https://www.facebook.com/ per *unique* cookie
  (duplicates reuse the result) + 2 control requests (no cookie / bogus
  cookie) so datacenter-IP blocks by Facebook can be told apart from
  actually-dead cookies.
- Classification:
    ALIVE       final URL is not login/checkpoint and the page knows the
                c_user id (strong logged-in signal)
    DEAD        redirected to /login, or c_user/xs deleted by server,
                or a logged-out login page with no trace of the account
    CHECKPOINT  redirected to /checkpoint, /recover, two-factor, etc.
                (session exists but Facebook wants verification)
    BLOCKED     HTTP 403 / "temporarily blocked" (IP-level, inconclusive)
    ERROR       network / unexpected response (inconclusive)
- Writes cookie_test_results.json + cookie_test_results.md in cwd and
  appends the markdown to $GITHUB_STEP_SUMMARY when present.
"""
import glob
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
URLS = ["https://www.facebook.com/", "https://www.facebook.com/me"]


def parse_cookie_string(raw):
    pairs = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        n, v = part.split("=", 1)
        pairs[n.strip()] = v.strip()
    return pairs


def probe(cookie_header, c_user):
    """Return dict(status, http, final, evidence). Retries once on network error."""
    last_err = None
    for attempt in range(2):
        for url in URLS:
            req = urllib.request.Request(url, method="GET")
            req.add_header("User-Agent", UA)
            req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
            req.add_header("Accept-Language", "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7")
            req.add_header("Upgrade-Insecure-Requests", "1")
            if cookie_header:
                req.add_header("Cookie", cookie_header)
            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    final = resp.geturl()
                    http = resp.status
                    headers = resp.headers
                    body = resp.read(400_000).decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                final = e.geturl() or url
                http = e.code
                headers = e.headers
                try:
                    body = e.read(400_000).decode("utf-8", "replace")
                except Exception:
                    body = ""
            except Exception as e:  # network error -> try next url / retry
                last_err = f"{type(e).__name__}: {e}"
                continue

            low_final = final.lower()
            low_body = body.lower()
            set_cookie = ",".join(headers.get_all("Set-Cookie") or []).lower()

            if "/checkpoint" in low_final or "checkpoint" in low_final:
                return {"status": "CHECKPOINT", "http": http, "final": final,
                        "evidence": "redirect to checkpoint"}
            if any(x in low_final for x in ("/recover/", "/two_factor", "/confirmemail", "/login/identify")):
                return {"status": "CHECKPOINT", "http": http, "final": final,
                        "evidence": f"redirect: {final.split('?')[0]}"}
            if "c_user=deleted" in set_cookie or "xs=deleted" in set_cookie:
                return {"status": "DEAD", "http": http, "final": final,
                        "evidence": "server deleted c_user/xs cookie"}
            if any(x in low_final for x in ("login.php", "/login/", "/login?")):
                return {"status": "DEAD", "http": http, "final": final,
                        "evidence": "redirect to login page"}
            if http == 403 or "temporarily blocked" in low_body or "bị chặn tạm thời" in low_body:
                return {"status": "BLOCKED", "http": http, "final": final,
                        "evidence": "HTTP 403 / temporarily blocked (IP level)"}

            knows_user = bool(c_user) and (
                f'"user_id":"{c_user}"' in low_body
                or f'"userid":"{c_user}"' in low_body
                or f'"account_id":"{c_user}"' in low_body
                or f'"viewerid":"{c_user}"' in low_body
                or f'"actorid":"{c_user}"' in low_body
                or (f'"{c_user}"' in body and '"is_logged_in":true' in low_body.replace(" ", ""))
            )
            if knows_user:
                return {"status": "ALIVE", "http": http, "final": final,
                        "evidence": "page contains logged-in USER_ID matching c_user"}
            if c_user and c_user in body and "/login" not in low_final:
                # id appears somewhere in a non-login page: weak-but-positive
                return {"status": "ALIVE", "http": http, "final": final,
                        "evidence": "c_user id present in page, no login redirect"}

            has_login_form = ('name="pass"' in low_body or 'id="login_form"' in low_body
                              or "login_form" in low_body)
            if has_login_form:
                return {"status": "DEAD", "http": http, "final": final,
                        "evidence": "logged-out login form served, account id absent"}
            if url.endswith("/me") or url == URLS[-1]:
                return {"status": "ERROR", "http": http, "final": final,
                        "evidence": "inconclusive response (no login redirect, no account id)"}
            # inconclusive on homepage -> fall through to /me probe
        time.sleep(1)
    return {"status": "ERROR", "http": None, "final": "",
            "evidence": f"network error: {last_err}"}


def main():
    files = sorted(glob.glob("ck*.txt"),
                   key=lambda p: (len(os.path.basename(p)), os.path.basename(p)))
    if not files:
        print("No ck*.txt found")
        return 1

    results = []
    by_hash = {}

    # Controls first: tells us if Facebook is blocking this IP wholesale.
    print("== controls ==", flush=True)
    for label, header, cu in [
        ("_control_no_cookie", "", ""),
        ("_control_bogus_cookie", "c_user=100000000000000; xs=bogusinvalidtoken", "100000000000000"),
    ]:
        r = probe(header, cu)
        print(f"{label}: {r['status']} http={r['http']} final={r['final'].split('?')[0]} :: {r['evidence']}", flush=True)
        results.append({"file": label, "c_user": "***0000" if cu else "-",
                        "status": r["status"], "http": r["http"],
                        "final": r["final"].split("?")[0], "evidence": r["evidence"]})
        time.sleep(2)

    print(f"\n== {len(files)} cookie files ==", flush=True)
    for path in files:
        raw = open(path, encoding="utf-8", errors="replace").read().strip()
        pairs = parse_cookie_string(raw)
        c_user = pairs.get("c_user", "")
        xs = pairs.get("xs", "")
        masked = ("***" + c_user[-4:]) if c_user else "MISSING"
        if not c_user or not xs:
            entry = {"file": path, "c_user": masked, "status": "INVALID_FORMAT",
                     "http": None, "final": "", "evidence": "missing c_user or xs in file"}
            results.append(entry)
            print(f"{path}: INVALID_FORMAT ({entry['evidence']})", flush=True)
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
        cookie_header = "; ".join(f"{k}={v}" for k, v in pairs.items())
        r = probe(cookie_header, c_user)
        entry = {"file": path, "c_user": masked, "status": r["status"],
                 "http": r["http"], "final": r["final"].split("?")[0],
                 "evidence": r["evidence"]}
        by_hash[digest] = entry
        results.append(entry)
        print(f"{path}: {r['status']} http={r['http']} final={entry['final']} :: {r['evidence']}", flush=True)
        time.sleep(2)

    with open("cookie_test_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    lines = ["| File | c_user | Status | HTTP | Evidence |",
             "|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['file']} | {r['c_user']} | **{r['status']}** | {r['http']} | {r['evidence']} |")
    md = "\n".join(lines) + "\n"
    with open("cookie_test_results.md", "w", encoding="utf-8") as f:
        f.write(md)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Cookie test results\n\n" + md)
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
