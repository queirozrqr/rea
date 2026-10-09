"""Testes unitários (somente biblioteca padrão): python -m unittest discover -s tests"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from bbrea.pipelines import PipelineError, select_target
from bbrea.report import redact_url, render
from bbrea.runner import ReaRunner, validate_cdp_endpoint
from bbrea.scope import OutOfScope, Scope, ScopeError
from bbrea.workspace import Workspace, WorkspaceError

SCOPE = """
# programa exemplo
app.example.com
*.api.example.com
198.51.100.0/24
!admin.api.example.com
"""


class ScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scope = Scope.parse(SCOPE)

    def test_exact_and_wildcard(self) -> None:
        self.scope.check_url("https://app.example.com/login")
        self.scope.check_url("https://v1.api.example.com/x?y=1")
        self.scope.check_url("http://APP.example.com.:8080/")

    def test_wildcard_does_not_cover_apex_or_lookalikes(self) -> None:
        for url in (
            "https://api.example.com/",
            "https://example.com/",
            "https://evilapp.example.com/",
            "https://app.example.com.evil.net/",
            "https://x.api.example.com@evil.net/",
        ):
            with self.subTest(url=url), self.assertRaises(OutOfScope):
                self.scope.check_url(url)

    def test_exclusion_wins(self) -> None:
        with self.assertRaises(OutOfScope):
            self.scope.check_url("https://admin.api.example.com/")
        with self.assertRaises(OutOfScope):
            self.scope.check_url("https://deep.admin.api.example.com/")

    def test_cidr(self) -> None:
        self.scope.check_url("http://198.51.100.7/")
        with self.assertRaises(OutOfScope):
            self.scope.check_url("http://198.51.101.7/")

    def test_rejects_bad_schemes_and_ambiguous_urls(self) -> None:
        for url in ("ftp://app.example.com/", "javascript:alert(1)", "https://app.example.com\\@evil.net/",
                    "https://app.example.com:99999/", "https:///nohost"):
            with self.subTest(url=url), self.assertRaises((ScopeError, OutOfScope)):
                self.scope.check_url(url)

    def test_default_deny(self) -> None:
        with self.assertRaises(OutOfScope):
            Scope.parse("# vazio\n").check_url("https://app.example.com/")

    def test_invalid_rules(self) -> None:
        for rule in ("https://app.example.com", "app.example.com/path", "a*.example.com", "10.0.0.1/33"):
            with self.subTest(rule=rule), self.assertRaises(ScopeError):
                Scope.parse(rule)


class WorkspaceTests(unittest.TestCase):
    def test_program_name_validation(self) -> None:
        for name in ("../etc", "Prog", "", "a/b", "-x"):
            with self.subTest(name=name), self.assertRaises(WorkspaceError):
                Workspace(Path("/tmp"), name)

    def test_init_and_confine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp), "acme")
            ws.init()
            self.assertEqual(os.stat(ws.targets).st_mode & 0o777, 0o700)
            inside = ws.targets / "app.apk"
            inside.write_bytes(b"x")
            self.assertEqual(ws.confine(inside), inside.resolve())
            outside = Path(tmp) / "outside.apk"
            outside.write_bytes(b"x")
            with self.assertRaises(WorkspaceError):
                ws.confine(outside)
            link = ws.targets / "link.apk"
            link.symlink_to(outside)
            with self.assertRaises(WorkspaceError):
                ws.confine(link)
            with self.assertRaises(WorkspaceError):
                ws.confine(ws.targets / ".." / ".." / "outside.apk")
            first, second = ws.new_run_dir("web"), ws.new_run_dir("web")
            self.assertNotEqual(first, second)


class RunnerTests(unittest.TestCase):
    def test_cdp_endpoint_loopback_only(self) -> None:
        self.assertEqual(validate_cdp_endpoint("http://127.0.0.1:9222"), "http://127.0.0.1:9222")
        validate_cdp_endpoint("http://[::1]:9222/")
        for bad in ("http://localhost:9222", "http://10.0.0.5:9222", "https://127.0.0.1:9222",
                    "http://127.0.0.1", "http://u:p@127.0.0.1:9222", "http://127.0.0.1:9222/json"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_cdp_endpoint(bad)

    def test_command_is_argument_list(self) -> None:
        runner = ReaRunner(executable="/usr/local/bin/rea")
        self.assertEqual(runner.command(["inspect", "a; rm -rf /"]),
                         ["/usr/local/bin/rea", "inspect", "a; rm -rf /", "--json"])
        with self.assertRaises(ValueError):
            runner.command(["bad\x00arg"])


class PipelineTests(unittest.TestCase):
    LISTING = {"result": {"targets": [
        {"target_id": "A", "url": "https://app.example.com/home"},
        {"target_id": "B", "url": "https://app.example.com/settings"},
        {"target_id": "C", "url": "https://other.example.net/"},
    ]}}

    def test_select_exact_and_explicit(self) -> None:
        self.assertEqual(select_target(self.LISTING, "https://app.example.com/home")["target_id"], "A")
        self.assertEqual(select_target(self.LISTING, "https://x/", "C")["target_id"], "C")

    def test_ambiguous_and_missing(self) -> None:
        with self.assertRaises(PipelineError):
            select_target(self.LISTING, "https://app.example.com/other")
        with self.assertRaises(PipelineError):
            select_target(self.LISTING, "https://nothing.example.org/")


class ReportTests(unittest.TestCase):
    def test_redaction(self) -> None:
        self.assertEqual(
            redact_url("https://u:p@app.example.com/a?token=abc&x=1#frag"),
            "https://app.example.com/a?token=REDACTED&x=REDACTED#REDACTED",
        )

    def test_render_classifies_and_never_leaks_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "01-x.json").write_text(json.dumps({"a": [
                "https://app.example.com/static/main.js.map",
                "https://cdn.evil.net/x?key=SECRET123",
                "/api/v2/users",
            ]}))
            text = render(run, Scope.parse(SCOPE))
            self.assertIn("main.js.map", text)
            self.assertIn("/api/v2/users", text)
            self.assertIn("fora do escopo", text)
            self.assertNotIn("SECRET123", text)


if __name__ == "__main__":
    unittest.main()
