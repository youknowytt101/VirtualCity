"""Real-browser smoke test for the game workbench's core edit loop.

Unlike test_area_picker.py's string-matching "guard tests", this drives an
actual isolated server + Chromium instance through Playwright and asserts on
rendered state, so it catches behavioral regressions (e.g. undo/redo wiring,
scene-state/history/inspector integration) that source-text assertions can't.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SERVER_SCRIPT = ROOT / "Scripts" / "app" / "area_picker" / "server.py"

TEST_INVITE_CODE = "E2E-TEST-INVITE"
TEST_EMAIL = "e2e-workbench@example.com"
TEST_PASSWORD = "e2e-test-password"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.e2e
class TestGameWorkbenchBrowser(unittest.TestCase):
    """Starts an isolated area_picker instance (own port, NO_BROWSER=1) so this
    never touches a developer's already-running WorldBuilder session."""

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        # ignore_cleanup_errors: on Windows the sqlite3 file can stay briefly
        # locked after server_proc.terminate() returns, before the OS fully
        # releases the handle -- don't fail teardown over that race.
        cls._auth_db_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        env = dict(os.environ)
        env["VC_AREA_PICKER_PORT"] = str(cls.port)
        env["VC_AREA_PICKER_NO_BROWSER"] = "1"
        # The login gate is off by default (see AUTH_REQUIRED in server.py --
        # disabled during the current testing phase); turn it on here so this
        # suite still exercises the gated register/login round trip.
        env["VC_AREA_PICKER_REQUIRE_LOGIN"] = "1"
        # Isolate the login-gate's user store from the real Config/auth.db and
        # avoid depending on whatever invite code happens to be configured there.
        env["VC_AREA_PICKER_AUTH_DB"] = str(Path(cls._auth_db_dir.name) / "auth.db")
        env["VC_AREA_PICKER_INVITE_CODES"] = TEST_INVITE_CODE
        cls.server_proc = subprocess.Popen(
            [sys.executable, str(SERVER_SCRIPT)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cls._wait_for_health()
        cls._register_test_user()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def _register_test_user(cls):
        req = urllib.request.Request(
            f"{cls.base_url}/auth/register",
            data=json.dumps({
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
                "invite_code": TEST_INVITE_CODE,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            result = json.loads(resp.read())
        if not result.get("ok"):
            raise RuntimeError(f"e2e test user registration failed: {result}")

    @classmethod
    def _wait_for_health(cls, timeout=20.0):
        import urllib.request
        deadline = time.time() + timeout
        last_error = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{cls.base_url}/health", timeout=1.0) as resp:
                    if resp.status == 200:
                        return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            time.sleep(0.3)
        raise RuntimeError(f"area_picker server did not become healthy: {last_error}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server_proc.terminate()
        try:
            cls.server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server_proc.kill()
        cls._auth_db_dir.cleanup()

    def setUp(self):
        self.page = self.browser.new_page()
        # / now redirects anonymous visitors to /login; log in through the API
        # first so the page's cookie jar carries a valid session into goto().
        login_response = self.page.request.post(
            f"{self.base_url}/auth/login",
            data=json.dumps({"email": TEST_EMAIL, "password": TEST_PASSWORD}),
            headers={"Content-Type": "application/json"},
        )
        assert login_response.ok, f"e2e test login failed: {login_response.status}"
        self.page.goto(self.base_url)
        self.page.click('[data-workspace-target="game"]')
        self.page.wait_for_selector("#game-scene-host canvas")
        # The canvas mounts synchronously, but the outline's first render (empty
        # state or restored rows) waits on an async /scene-root fetch -- wait for
        # that to settle so tests don't race an empty '' outline body.
        self.page.wait_for_function(
            "document.querySelector('#game-scene-outline .action-outline-body').textContent.trim().length > 0"
        )

    def tearDown(self):
        self.page.close()

    def _outline_text(self):
        return self.page.inner_text("#game-scene-outline .action-outline-body")

    def _place_character(self):
        button = self.page.locator("#game-character-button")
        box = button.bounding_box()
        host = self.page.locator("#game-scene-host")
        host_box = host.bounding_box()
        self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        self.page.mouse.down()
        self.page.mouse.move(
            host_box["x"] + host_box["width"] / 2,
            host_box["y"] + host_box["height"] / 2,
            steps=5,
        )
        self.page.mouse.up()
        self.page.wait_for_function(
            "document.querySelector('#game-scene-outline .action-outline-body').textContent.includes('角色')"
        )

    def test_place_undo_redo_delete_round_trip(self):
        self.assertIn("场景为空", self._outline_text())

        self._place_character()
        self.assertIn("角色", self._outline_text())
        self.assertIn("角色已放置", self.page.inner_text("#game-status"))

        self.page.keyboard.press("Control+z")
        self.page.wait_for_function(
            "document.querySelector('#game-scene-outline .action-outline-body').textContent.includes('场景为空')"
        )
        self.assertIn("场景为空", self._outline_text())

        self.page.keyboard.press("Control+y")
        self.page.wait_for_function(
            "document.querySelector('#game-scene-outline .action-outline-body').textContent.includes('角色')"
        )
        self.assertIn("角色", self._outline_text())

        self.page.click("#game-scene-outline .scene-outline-row")
        self.page.keyboard.press("Delete")
        self.page.wait_for_function(
            "document.querySelector('#game-scene-outline .action-outline-body').textContent.includes('场景为空')"
        )
        self.assertIn("场景为空", self._outline_text())

    def test_inspector_transform_edit_commits_and_undoes(self):
        self._place_character()
        self.page.click("#game-scene-outline .scene-outline-row")
        self.page.wait_for_selector("#inspector-body:not([hidden])")

        pos_x = self.page.locator("#inspector-pos-x")
        original_x = pos_x.input_value()
        pos_x.fill("5")
        pos_x.press("Tab")
        self.page.wait_for_function("document.getElementById('inspector-pos-x').value === '5'")

        # The global undo shortcut deliberately no-ops while an input/textarea/select
        # is focused (so it doesn't steal keystrokes from someone typing a number).
        # Click a non-interactive part of the toolbar to blur before undoing.
        self.page.click("#game-toolbar")
        self.page.keyboard.press("Control+z")

        # Re-select through the outline (independent of 3D camera framing) and
        # confirm the inspector reflects the reverted position.
        self.page.click("#game-scene-outline .scene-outline-row")
        self.page.wait_for_function(
            "document.getElementById('inspector-pos-x').value === " + repr(original_x)
        )


if __name__ == "__main__":
    unittest.main()
