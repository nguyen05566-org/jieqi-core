#!/usr/bin/env python3
"""Tests cho cookie_utils (phiên bản chỉ đọc txt, không lưu/làm tươi cookie):

    python3 tests/test_cookie_utils.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cookie_utils as cu  # noqa: E402


CK_TXT = ("datr=abc123; sb=sb_value; c_user=61594838440865; "
          "xs=48%3AoldTOKEN%3A2%3A1791338376%3A-1%3A-1; fr=fr_value; locale=vi_VN")


class FakeCtx:
    """Context giả: chỉ cần cookies()/add_cookies() như Playwright."""

    def __init__(self, cookies=None, explode=False):
        self._cookies = [dict(c) for c in (cookies or [])]
        self.added = []
        self.explode = explode

    def cookies(self):
        if self.explode:
            raise RuntimeError("Target page, context or browser has been closed")
        return [dict(c) for c in self._cookies]

    def add_cookies(self, batch):
        self.added.extend(batch)
        self._cookies.extend(dict(c) for c in batch)


class FakePage:
    def __init__(self, url="https://www.facebook.com/gaming/play/gomoku-vh",
                 dom=None, frames=None):
        self.url = url
        self._dom = {"passwordInputs": 0, "loginForm": False, "loggedInHint": True} \
            if dom is None else dom
        self.frames = frames or []

    def evaluate(self, _js):
        return dict(self._dom)


class CookieTxtTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cookie-test-")
        cu._LAST_LOAD.clear()
        self.txt = os.path.join(self.tmp, "ck1.txt")
        with open(self.txt, "w", encoding="utf-8") as fh:
            fh.write(CK_TXT + "\n")

    def tearDown(self):
        cu._LAST_LOAD.clear()

    # ---- 1. không bịa expires -------------------------------------------
    def test_parse_does_not_fabricate_expires(self):
        cookies = cu.parse_cookie_string(CK_TXT)
        self.assertEqual(len(cookies), 6)
        for c in cookies:
            self.assertNotIn("expires", c)
            self.assertNotIn("expires_at", c)

    def test_prepare_keeps_real_expiry_only(self):
        no_exp = cu.prepare_cookie({"name": "xs", "value": "v"})
        self.assertNotIn("expires", no_exp)
        real = cu.prepare_cookie({"name": "xs", "value": "v", "expires": 1999999999})
        self.assertAlmostEqual(real["expires"], 1999999999.0)

    # ---- 2. round-trip txt ---------------------------------------------
    def test_txt_roundtrip_keeps_values(self):
        cookies = cu.parse_cookie_string(CK_TXT)
        text = cu.cookies_to_string(cookies)
        again = cu.parse_cookie_string(text)
        self.assertEqual({c["name"]: c["value"] for c in cookies},
                         {c["name"]: c["value"] for c in again})
        self.assertIn("xs=48%3AoldTOKEN%3A2%3A1791338376%3A-1%3A-1", text)

    def test_non_facebook_cookies_not_in_txt(self):
        mixed = cu.parse_cookie_string(CK_TXT) + [
            {"name": "sessionid", "value": "zz", "domain": "gamevh.net", "path": "/"}]
        self.assertNotIn("sessionid", cu.cookies_to_string(mixed))

    # ---- 3. load chỉ đọc txt, không lưu --------------------------------
    def test_load_cookies_reads_txt_only(self):
        cookies = cu.load_cookies(self.txt)
        self.assertEqual(len(cookies), 6)
        self.assertEqual(cu.last_load_summary(), "txt=6")
        self.assertEqual(cu.loaded_c_user(), "61594838440865")

    def test_loaded_c_user_none_before_load(self):
        cu._LAST_LOAD.clear()
        self.assertIsNone(cu.loaded_c_user())

    # ---- 4. apply_cookies ----------------------------------------------
    def test_apply_isolates_broken_cookie(self):
        class PickyCtx(FakeCtx):
            def add_cookies(self, batch):
                if any(c.get("name") == "bad" for c in batch):
                    raise ValueError("invalid cookie")
                super().add_cookies(batch)

        target = PickyCtx()
        added = cu.apply_cookies(target, [
            {"name": "ok1", "value": "1", "domain": ".facebook.com", "path": "/"},
            {"name": "bad", "value": "x", "domain": ".facebook.com", "path": "/"},
            {"name": "ok2", "value": "2", "domain": ".facebook.com", "path": "/"},
        ])
        self.assertEqual(added, 2)
        self.assertEqual([c["name"] for c in target.added], ["ok1", "ok2"])


class LoginStateTest(unittest.TestCase):
    def setUp(self):
        cu._LAST_LOAD.clear()

    def _session_cookies(self, c_user="61594838440865"):
        return [{"name": "c_user", "value": c_user, "domain": ".facebook.com", "path": "/"},
                {"name": "xs", "value": "48%3Atok", "domain": ".facebook.com", "path": "/"}]

    def test_logged_in_with_session_cookies(self):
        page = FakePage()
        st = cu.detect_login_state(page, ctx=FakeCtx(self._session_cookies()))
        self.assertEqual(st["state"], "logged_in")
        self.assertEqual(st["c_user"], "61594838440865")
        self.assertTrue(st["evidence"]["has_xs"])

    def test_false_positive_text_no_longer_kills_run(self):
        """Trang có chữ 'Đăng nhập' nhưng còn session → phải là logged_in."""
        page = FakePage(dom={"passwordInputs": 0, "loginForm": False,
                             "loggedInHint": True})
        st = cu.detect_login_state(page, ctx=FakeCtx(self._session_cookies()))
        self.assertEqual(st["state"], "logged_in")

    def test_logged_out_when_login_url_and_no_session(self):
        page = FakePage(url="https://www.facebook.com/login/?next=%2Fgaming",
                        dom={"passwordInputs": 1, "loginForm": True, "loggedInHint": False})
        st = cu.detect_login_state(page, ctx=FakeCtx())
        self.assertEqual(st["state"], "logged_out")
        self.assertIn("/login", st["evidence"]["url"])

    def test_unknown_instead_of_guessing(self):
        """Không cookie, không form, DOM chưa render → unknown (không kill run)."""
        page = FakePage(dom={"passwordInputs": 0, "loginForm": False,
                             "loggedInHint": False})
        st = cu.detect_login_state(page, ctx=FakeCtx())
        self.assertEqual(st["state"], "unknown")

    def test_checkpoint_detected(self):
        page = FakePage(url="https://www.facebook.com/checkpoint/1501092823525282/")
        st = cu.detect_login_state(page, ctx=FakeCtx(self._session_cookies()))
        self.assertEqual(st["state"], "checkpoint")

    def test_expired_session_cookie_on_login_url(self):
        page = FakePage(url="https://m.facebook.com/login.php?next=x",
                        dom={"passwordInputs": 1, "loginForm": True, "loggedInHint": False})
        st = cu.detect_login_state(page, ctx=FakeCtx())
        self.assertEqual(st["state"], "logged_out")

    def test_http_401_without_session_is_logged_out(self):
        class Resp:
            status = 401
            url = "https://www.facebook.com/gaming/play/gomoku-vh"
        st = cu.detect_login_state(FakePage(dom={"passwordInputs": 0, "loginForm": False,
                                                 "loggedInHint": False}),
                                   ctx=FakeCtx(), response=Resp())
        self.assertEqual(st["state"], "logged_out")
        self.assertEqual(st["evidence"]["http_status"], 401)

    def test_user_switched_flagged(self):
        st = cu.detect_login_state(FakePage(), ctx=FakeCtx(self._session_cookies("999")),
                                   expected_c_user="61594838440865")
        self.assertTrue(st["user_switched"])
        self.assertEqual(st["state"], "logged_in")

    def test_broken_context_does_not_raise(self):
        st = cu.detect_login_state(FakePage(), ctx=FakeCtx(explode=True))
        self.assertIn(st["state"], ("unknown", "logged_out"))


class LoadedAccountTest(unittest.TestCase):
    """c_user của file được dùng để phát hiện nhầm account (không cần truyền tay)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cookie-test-")
        cu._LAST_LOAD.clear()
        self.txt = os.path.join(self.tmp, "ck1.txt")
        with open(self.txt, "w", encoding="utf-8") as fh:
            fh.write(CK_TXT + "\n")

    def tearDown(self):
        cu._LAST_LOAD.clear()

    def test_loaded_c_user_from_txt(self):
        cu.load_cookies(self.txt)
        self.assertEqual(cu.loaded_c_user(), "61594838440865")

    def test_user_switched_detected_without_explicit_expected(self):
        cu.load_cookies(self.txt)          # file thuộc c_user 61594838440865
        page = FakePage()
        ctx = FakeCtx([{"name": "c_user", "value": "111222333", "domain": ".facebook.com",
                        "path": "/"},
                       {"name": "xs", "value": "tok", "domain": ".facebook.com", "path": "/"}])
        st = cu.detect_login_state(page, ctx=ctx)
        self.assertTrue(st["user_switched"])
        self.assertEqual(st["state"], "logged_in")   # phiên hợp lệ nhưng SAI account


class RepoConsistencyTest(unittest.TestCase):
    """Bảo vệ hành vi "session chết thì dừng, không retry" khỏi bị revert lẻ tẻ."""

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _scripts(self):
        import glob
        return sorted(glob.glob(os.path.join(self.ROOT, "auto_cycle*.py")))

    def test_every_script_defines_exit_session_dead(self):
        for path in self._scripts():
            text = open(path, encoding="utf-8").read()
            self.assertIn("EXIT_SESSION_DEAD = 3", text, path)
            self.assertGreaterEqual(text.count("return EXIT_SESSION_DEAD"), 2, path)
            self.assertNotIn('body_text or "Log in"', text, path)

    def test_no_workflow_points_to_missing_cookie_file(self):
        import glob
        import re
        for path in sorted(glob.glob(os.path.join(self.ROOT, ".github", "workflows", "*.yml"))):
            m = re.search(r"SINGLE_COOKIE_FILE: *'([^']+)'", open(path, encoding="utf-8").read())
            if m:
                self.assertTrue(os.path.exists(os.path.join(self.ROOT, m.group(1))),
                                "%s trỏ tới %s không tồn tại" % (path, m.group(1)))

    def test_no_two_active_workflows_share_the_same_account(self):
        """Hai workflow chạy song sync cùng một account FB sẽ tự đá session của nhau."""
        import glob
        import re
        seen = {}
        for wf in sorted(glob.glob(os.path.join(self.ROOT, ".github", "workflows", "*.yml"))):
            m = re.search(r"SINGLE_COOKIE_FILE: *'([^']+)'", open(wf, encoding="utf-8").read())
            if not m:
                continue
            cookie_path = os.path.join(self.ROOT, m.group(1))
            if not os.path.exists(cookie_path):
                continue
            d = {c["name"]: c["value"] for c in cu.parse_cookie_string(open(cookie_path).read())}
            uid = d.get("c_user")
            if not uid:
                continue
            self.assertNotIn(uid, seen, "%s dùng cùng account với %s (%s)"
                             % (wf, seen.get(uid), uid))
            seen[uid] = wf


if __name__ == "__main__":
    unittest.main(verbosity=2)
