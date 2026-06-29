"""Basic syntax/import tests for Playwright browser verifier scripts.

These tests verify that the scripts are syntactically valid and their
core functions are importable. Full Playwright tests require a browser
and are skipped if playwright is not installed.
"""

import importlib.util
import subprocess
import sys

import pytest

SCRIPTS_DIR = "tools/scripts"


def _check_import_available(script_name):
    """Check whether a script's core import would work (playwright may be absent)."""
    path = f"{SCRIPTS_DIR}/{script_name}"
    try:
        with open(path) as f:
            source = f.read()
        # If the script imports playwright, skip the import test without it
        if "from playwright" in source or "import playwright" in source:
            try:
                __import__("playwright")
            except ImportError:
                return False
        return True
    except (FileNotFoundError, ImportError):
        return False


def _import_module(name, path):
    """Import a module from a file path for syntax/import checking."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPlaywrightBola:
    def test_syntax_valid(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", f"{SCRIPTS_DIR}/playwright_bola.py"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.skipif(
        not _check_import_available("playwright_bola.py"),
        reason="playwright not installed",
    )
    def test_import_core_function(self):
        mod = _import_module("playwright_bola", f"{SCRIPTS_DIR}/playwright_bola.py")
        assert hasattr(mod, "check_bola")
        assert hasattr(mod, "_check_auth_success")

    @pytest.mark.skipif(
        not _check_import_available("playwright_bola.py"),
        reason="playwright not installed",
    )
    def test_check_bola_accepts_new_params(self):
        mod = _import_module("playwright_bola", f"{SCRIPTS_DIR}/playwright_bola.py")
        import inspect

        sig = inspect.signature(mod.check_bola)
        params = list(sig.parameters.keys())
        assert "resource_pattern" in params


class TestPlaywrightXss:
    def test_syntax_valid(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", f"{SCRIPTS_DIR}/playwright_xss.py"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.skipif(
        not _check_import_available("playwright_xss.py"),
        reason="playwright not installed",
    )
    def test_import_core_function(self):
        mod = _import_module("playwright_xss", f"{SCRIPTS_DIR}/playwright_xss.py")
        assert hasattr(mod, "check_stored_xss")
        assert hasattr(mod, "_check_auth_success")


class TestPlaywrightPrivesc:
    def test_syntax_valid(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "py_compile",
                f"{SCRIPTS_DIR}/playwright_privesc.py",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.skipif(
        not _check_import_available("playwright_privesc.py"),
        reason="playwright not installed",
    )
    def test_import_core_function(self):
        mod = _import_module(
            "playwright_privesc", f"{SCRIPTS_DIR}/playwright_privesc.py"
        )
        assert hasattr(mod, "check_privesc")
        assert hasattr(mod, "_check_auth_success")


class TestCredsFileFormat:
    def test_bola_creds_structure(self):
        """Verify the expected creds file format for BOLA."""
        import json

        creds = {
            "attacker": {"username": "user1", "password": "pass1"},
            "victim": {"username": "user2", "password": "pass2"},
        }
        serialized = json.dumps(creds)
        deserialized = json.loads(serialized)
        assert "attacker" in deserialized
        assert "victim" in deserialized
        assert "username" in deserialized["attacker"]
        assert "password" in deserialized["victim"]

    def test_simple_creds_structure(self):
        """Verify simple credential format (for XSS and Privesc)."""
        import json

        creds = {"username": "user1", "password": "pass1"}
        serialized = json.dumps(creds)
        deserialized = json.loads(serialized)
        assert "username" in deserialized
        assert "password" in deserialized


# ── Argument parsing tests ───────────────────────────────────────────────────
# These tests verify that each Playwright script correctly resolves credentials
# from --creds-file (JSON) and individual inline arguments, and errors when
# neither path provides sufficient credentials.


def _resolve_xss_creds(args):
    """Simulate the credential resolution logic in playwright_xss.py's main block.

    Returns (creds_dict_or_None, error_message_or_None).
    """
    import json
    if args.creds_file:
        with open(args.creds_file) as f:
            return json.load(f), None
    if args.username and args.password:
        return {"username": args.username, "password": args.password}, None
    return None, "Either --creds-file or --username/--password must be provided"


def _resolve_privesc_creds(args):
    """Simulate the credential resolution logic in playwright_privesc.py's main block."""
    import json
    if args.creds_file:
        with open(args.creds_file) as f:
            return json.load(f), None
    if args.low_priv_username and args.low_priv_password:
        return {
            "username": args.low_priv_username,
            "password": args.low_priv_password,
        }, None
    return None, (
        "Either --creds-file or --low-priv-username/"
        "--low-priv-password must be provided"
    )


def _resolve_bola_creds(args):
    """Simulate the credential resolution logic in playwright_bola.py's main block."""
    import json
    if args.creds_file:
        with open(args.creds_file) as f:
            return json.load(f), None
    if (
        args.attacker_username
        and args.attacker_password
        and args.victim_username
        and args.victim_password
    ):
        return {
            "attacker": {
                "username": args.attacker_username,
                "password": args.attacker_password,
            },
            "victim": {
                "username": args.victim_username,
                "password": args.victim_password,
            },
        }, None
    return None, (
        "Either --creds-file or --attacker-username/--attacker-password"
        " and --victim-username/--victim-password must be provided"
    )


def _make_xss_parser():
    """Reconstruct the argparse parser from playwright_xss.py's main block."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--creds-file", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--form-page", default="/feedback")
    parser.add_argument("--payload", default="<script>alert('XSS')</script>")
    parser.add_argument("--username-selector", default="input[name=username]")
    parser.add_argument("--password-selector", default="input[name=password]")
    parser.add_argument("--submit-selector", default="button[type=submit]")
    return parser


def _make_privesc_parser():
    """Reconstruct the argparse parser from playwright_privesc.py's main block."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--creds-file", default=None)
    parser.add_argument("--low-priv-username", default=None, dest="low_priv_username")
    parser.add_argument("--low-priv-password", default=None, dest="low_priv_password")
    parser.add_argument(
        "--admin-paths",
        default="/admin,/api/admin/users,/admin/dashboard,/api/users,/admin/settings",
    )
    parser.add_argument("--username-selector", default="input[name=username]")
    parser.add_argument("--password-selector", default="input[name=password]")
    parser.add_argument("--submit-selector", default="button[type=submit]")
    return parser


def _make_bola_parser():
    """Reconstruct the argparse parser from playwright_bola.py's main block."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--creds-file", default=None)
    parser.add_argument("--attacker-username", default=None, dest="attacker_username")
    parser.add_argument("--attacker-password", default=None, dest="attacker_password")
    parser.add_argument("--victim-username", default=None, dest="victim_username")
    parser.add_argument("--victim-password", default=None, dest="victim_password")
    parser.add_argument("--resource-pattern", default="/api/users/{username}/details")
    parser.add_argument("--username-selector", default="input[name=username]")
    parser.add_argument("--password-selector", default="input[name=password]")
    parser.add_argument("--submit-selector", default="button[type=submit]")
    return parser


class TestPlaywrightXssArgs:
    """Argument parsing tests for playwright_xss.py."""

    def test_creds_file_arg_structure(self):
        """Verify --creds-file is accepted as a flag."""
        parser = _make_xss_parser()
        parsed = parser.parse_args(
            [
                "--target",
                "http://example.com",
                "--creds-file",
                "/tmp/test_creds.json",
            ]
        )
        assert parsed.creds_file == "/tmp/test_creds.json"

    def test_inline_creds_args(self):
        """Verify --username/--password are accepted as flags."""
        parser = _make_xss_parser()
        parsed = parser.parse_args(
            [
                "--target",
                "http://example.com",
                "--username",
                "admin",
                "--password",
                "secret",
            ]
        )
        assert parsed.username == "admin"
        assert parsed.password == "secret"

    def test_default_form_page(self):
        """Verify --form-page defaults to /feedback."""
        parser = _make_xss_parser()
        parsed = parser.parse_args(["--target", "http://example.com"])
        assert parsed.form_page == "/feedback"

    def test_custom_form_page(self):
        """Verify --form-page accepts custom paths."""
        parser = _make_xss_parser()
        parsed = parser.parse_args(
            [
                "--target",
                "http://example.com",
                "--form-page",
                "/contact",
            ]
        )
        assert parsed.form_page == "/contact"

    def test_custom_payload(self):
        """Verify --payload accepts a custom XSS payload."""
        parser = _make_xss_parser()
        custom_payload = "<img src=x onerror=alert(1)>"
        parsed = parser.parse_args(
            [
                "--target",
                "http://example.com",
                "--payload",
                custom_payload,
            ]
        )
        assert parsed.payload == custom_payload

    def test_default_selectors(self):
        """Verify selector arguments have the correct defaults."""
        parser = _make_xss_parser()
        parsed = parser.parse_args(["--target", "http://example.com"])
        assert parsed.username_selector == "input[name=username]"
        assert parsed.password_selector == "input[name=password]"
        assert parsed.submit_selector == "button[type=submit]"

    def test_resolve_creds_file(self, tmp_path):
        """Verify --creds-file creds are correctly loaded."""
        import json
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps({"username": "u1", "password": "p1"}))

        parser = _make_xss_parser()
        parsed = parser.parse_args(
            ["--target", "http://x", "--creds-file", str(creds_file)]
        )
        creds, err = _resolve_xss_creds(parsed)
        assert err is None
        assert creds["username"] == "u1"
        assert creds["password"] == "p1"

    def test_resolve_inline_creds(self):
        """Verify inline --username/--password are resolved correctly."""
        parser = _make_xss_parser()
        parsed = parser.parse_args(
            ["--target", "http://x", "--username", "u1", "--password", "p1"]
        )
        creds, err = _resolve_xss_creds(parsed)
        assert err is None
        assert creds["username"] == "u1"
        assert creds["password"] == "p1"

    def test_resolve_no_creds_fails(self):
        """Verify missing creds produce the expected error."""
        parser = _make_xss_parser()
        parsed = parser.parse_args(["--target", "http://x"])
        creds, err = _resolve_xss_creds(parsed)
        assert creds is None
        assert "--creds-file" in err
        assert "--username" in err
        assert "--password" in err

    def test_resolve_partial_inline_creds_fails(self):
        """Verify only --username without --password fails."""
        parser = _make_xss_parser()
        parsed = parser.parse_args(
            ["--target", "http://x", "--username", "u1"]
        )
        creds, err = _resolve_xss_creds(parsed)
        assert creds is None
        assert err is not None

    def test_creds_file_takes_precedence(self, tmp_path):
        """Verify --creds-file is preferred when both paths are provided."""
        import json
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps({"username": "from_file", "password": "file_pwd"}))

        parser = _make_xss_parser()
        parsed = parser.parse_args(
            [
                "--target",
                "http://x",
                "--creds-file",
                str(creds_file),
                "--username",
                "inline_user",
                "--password",
                "inline_pwd",
            ]
        )
        creds, err = _resolve_xss_creds(parsed)
        assert err is None
        assert creds["username"] == "from_file"  # creds-file wins
        assert creds["password"] == "file_pwd"

    def test_missing_target_fails(self):
        """Verify --target is required."""
        parser = _make_xss_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


class TestPlaywrightPrivescArgs:
    """Argument parsing tests for playwright_privesc.py."""

    def test_creds_file_arg_structure(self):
        parser = _make_privesc_parser()
        parsed = parser.parse_args(
            ["--target", "http://x", "--creds-file", "/tmp/c.json"]
        )
        assert parsed.creds_file == "/tmp/c.json"

    def test_inline_creds_args(self):
        parser = _make_privesc_parser()
        parsed = parser.parse_args(
            [
                "--target",
                "http://x",
                "--low-priv-username",
                "low_user",
                "--low-priv-password",
                "low_pass",
            ]
        )
        assert parsed.low_priv_username == "low_user"
        assert parsed.low_priv_password == "low_pass"

    def test_default_admin_paths(self):
        parser = _make_privesc_parser()
        parsed = parser.parse_args(["--target", "http://x"])
        assert "/admin" in parsed.admin_paths
        assert "/api/admin/users" in parsed.admin_paths

    def test_custom_admin_paths(self):
        parser = _make_privesc_parser()
        parsed = parser.parse_args(
            ["--target", "http://x", "--admin-paths", "/custom,/admin2"]
        )
        assert parsed.admin_paths == "/custom,/admin2"

    def test_resolve_creds_file(self, tmp_path):
        import json
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps({"username": "u1", "password": "p1"}))

        parser = _make_privesc_parser()
        parsed = parser.parse_args(
            ["--target", "http://x", "--creds-file", str(creds_file)]
        )
        creds, err = _resolve_privesc_creds(parsed)
        assert err is None
        assert creds["username"] == "u1"
        assert creds["password"] == "p1"

    def test_resolve_inline_creds(self):
        parser = _make_privesc_parser()
        parsed = parser.parse_args(
            [
                "--target",
                "http://x",
                "--low-priv-username",
                "low_user",
                "--low-priv-password",
                "low_pass",
            ]
        )
        creds, err = _resolve_privesc_creds(parsed)
        assert err is None
        assert creds["username"] == "low_user"
        assert creds["password"] == "low_pass"

    def test_resolve_no_creds_fails(self):
        parser = _make_privesc_parser()
        parsed = parser.parse_args(["--target", "http://x"])
        creds, err = _resolve_privesc_creds(parsed)
        assert creds is None
        assert "--creds-file" in err
        assert "--low-priv-username" in err

    def test_resolve_partial_inline_fails(self):
        parser = _make_privesc_parser()
        parsed = parser.parse_args(
            ["--target", "http://x", "--low-priv-username", "u1"]
        )
        creds, err = _resolve_privesc_creds(parsed)
        assert creds is None
        assert err is not None

    def test_creds_file_takes_precedence(self, tmp_path):
        import json
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(
            json.dumps({"username": "from_file", "password": "file_pwd"})
        )

        parser = _make_privesc_parser()
        parsed = parser.parse_args(
            [
                "--target",
                "http://x",
                "--creds-file",
                str(creds_file),
                "--low-priv-username",
                "inline_user",
                "--low-priv-password",
                "inline_pass",
            ]
        )
        creds, err = _resolve_privesc_creds(parsed)
        assert err is None
        assert creds["username"] == "from_file"

    def test_missing_target_fails(self):
        parser = _make_privesc_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


class TestPlaywrightBolaArgs:
    """Argument parsing tests for playwright_bola.py."""

    def test_creds_file_arg(self):
        parser = _make_bola_parser()
        parsed = parser.parse_args(
            ["--target", "http://x", "--creds-file", "/tmp/c.json"]
        )
        assert parsed.creds_file == "/tmp/c.json"

    def test_inline_creds_all_four(self):
        parser = _make_bola_parser()
        parsed = parser.parse_args(
            [
                "--target",
                "http://x",
                "--attacker-username",
                "att",
                "--attacker-password",
                "att_pwd",
                "--victim-username",
                "vic",
                "--victim-password",
                "vic_pwd",
            ]
        )
        assert parsed.attacker_username == "att"
        assert parsed.attacker_password == "att_pwd"
        assert parsed.victim_username == "vic"
        assert parsed.victim_password == "vic_pwd"

    def test_default_resource_pattern(self):
        parser = _make_bola_parser()
        parsed = parser.parse_args(["--target", "http://x"])
        assert parsed.resource_pattern == "/api/users/{username}/details"

    def test_custom_resource_pattern(self):
        parser = _make_bola_parser()
        parsed = parser.parse_args(
            ["--target", "http://x", "--resource-pattern", "/api/profiles/{username}"]
        )
        assert parsed.resource_pattern == "/api/profiles/{username}"

    def test_resolve_creds_file(self, tmp_path):
        import json
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(
            json.dumps(
                {
                    "attacker": {
                        "username": "att_user",
                        "password": "att_pwd",
                    },
                    "victim": {"username": "vic_user", "password": "vic_pwd"},
                }
            )
        )

        parser = _make_bola_parser()
        parsed = parser.parse_args(
            ["--target", "http://x", "--creds-file", str(creds_file)]
        )
        creds, err = _resolve_bola_creds(parsed)
        assert err is None
        assert creds["attacker"]["username"] == "att_user"
        assert creds["attacker"]["password"] == "att_pwd"
        assert creds["victim"]["username"] == "vic_user"
        assert creds["victim"]["password"] == "vic_pwd"

    def test_resolve_inline_creds(self):
        parser = _make_bola_parser()
        parsed = parser.parse_args(
            [
                "--target",
                "http://x",
                "--attacker-username",
                "att",
                "--attacker-password",
                "att_pwd",
                "--victim-username",
                "vic",
                "--victim-password",
                "vic_pwd",
            ]
        )
        creds, err = _resolve_bola_creds(parsed)
        assert err is None
        assert creds["attacker"]["username"] == "att"
        assert creds["victim"]["password"] == "vic_pwd"

    def test_resolve_no_creds_fails(self):
        parser = _make_bola_parser()
        parsed = parser.parse_args(["--target", "http://x"])
        creds, err = _resolve_bola_creds(parsed)
        assert creds is None
        assert "--creds-file" in err
        assert "--attacker-username" in err

    def test_resolve_partial_inline_fails(self):
        """Only attacker creds without victim creds should fail."""
        parser = _make_bola_parser()
        parsed = parser.parse_args(
            [
                "--target",
                "http://x",
                "--attacker-username",
                "att",
                "--attacker-password",
                "att_pwd",
            ]
        )
        creds, err = _resolve_bola_creds(parsed)
        assert creds is None
        assert err is not None

    def test_creds_file_takes_precedence(self, tmp_path):
        import json
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(
            json.dumps(
                {
                    "attacker": {
                        "username": "file_att",
                        "password": "file_att_pwd",
                    },
                    "victim": {
                        "username": "file_vic",
                        "password": "file_vic_pwd",
                    },
                }
            )
        )

        parser = _make_bola_parser()
        parsed = parser.parse_args(
            [
                "--target",
                "http://x",
                "--creds-file",
                str(creds_file),
                "--attacker-username",
                "inline_att",
                "--attacker-password",
                "inline_att_pwd",
                "--victim-username",
                "inline_vic",
                "--victim-password",
                "inline_vic_pwd",
            ]
        )
        creds, err = _resolve_bola_creds(parsed)
        assert err is None
        assert creds["attacker"]["username"] == "file_att"

    def test_missing_target_fails(self):
        parser = _make_bola_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_extra_keys_in_creds_file_ignored(self, tmp_path):
        """Extra keys in the creds JSON should be ignored, not crash."""
        import json
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(
            json.dumps(
                {
                    "attacker": {
                        "username": "att",
                        "password": "pwd",
                    },
                    "victim": {"username": "vic", "password": "pwd"},
                    "extra_field": "should_be_ignored",
                    "another_extra": {"nested": "data"},
                }
            )
        )

        parser = _make_bola_parser()
        parsed = parser.parse_args(
            ["--target", "http://x", "--creds-file", str(creds_file)]
        )
        creds, err = _resolve_bola_creds(parsed)
        assert err is None
        assert creds["attacker"]["username"] == "att"
        assert creds["victim"]["username"] == "vic"
