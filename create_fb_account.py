#!/usr/bin/env python3
"""Create a Facebook account via Playwright (email = Hotmail)."""
import os
import sys
import time
from playwright.sync_api import sync_playwright

FB_URL = "https://www.facebook.com/register.php"


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Create FB account via Playwright")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--first-name", required=True)
    ap.add_argument("--last-name", required=True)
    ap.add_argument("--headless", default="true")
    args = ap.parse_args()

    headless = str(args.headless).lower() == "true"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(locale="en_US", viewport={"width": 1440, "height": 900})
        ctx.add_init_script(
            "() => { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); }"
        )
        page = ctx.new_page()
        page.set_default_timeout(45000)
        page.goto(FB_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        first_name = args.first_name.strip()
        last_name = args.last_name.strip()
        email = args.email.strip()
        password = args.password

        first_name_sel = page.locator('input[name="first_name"]')
        last_name_sel = page.locator('input[name="last_name"]')
        email_sel = page.locator('input[name="reg_email"]')
        pass_sel = page.locator('input[name="reg_password"]')

        if first_name_sel.count() > 0:
            first_name_sel.fill(first_name)
        if last_name_sel.count() > 0:
            last_name_sel.fill(last_name)
        if email_sel.count() > 0:
            email_sel.fill(email)
        if pass_sel.count() > 0:
            pass_sel.fill(password)

        page.wait_for_timeout(1500)
        submit = page.locator('input[name="submit_reg"]').first
        if submit.count() > 0:
            submit.click()
        else:
            page.locator('button[type="submit"]').first.click()
        page.wait_for_timeout(8000)
        print(f"[CREATE] FB signup submitted for {email}")

        time.sleep(5)
        browser.close()


if __name__ == "__main__":
    main()
