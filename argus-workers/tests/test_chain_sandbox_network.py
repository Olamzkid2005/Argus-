"""Tests for chain-exploit sandbox → target network wiring.

The critical fix under test: ``verify_chain_in_sandbox`` must enable the
Docker sandbox network when verifying against a real engagement target —
otherwise every curl/python step against a real URL always fails in a
network-disabled container and chain verification can never succeed in
production. The safe default (network disabled) must be preserved when
there is no target.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from chain_exploit_generator import ChainExploitGenerator
from tool_core.sandbox.client import SandboxResult


class TestVerifyChainSandboxNetworkWiring:
    def test_verify_chain_with_target_enables_sandbox_network(self):
        """SandboxClient must be constructed with network enabled when a target is set."""
        with patch("tool_core.sandbox.client.SandboxClient") as mock_cls:
            mock_sandbox = MagicMock()
            mock_sandbox.is_docker_available = True
            mock_sandbox.run_command.return_value = SandboxResult(
                returncode=0, stdout="ok"
            )
            mock_cls.return_value = mock_sandbox

            generator = ChainExploitGenerator()
            result = generator.verify_chain_in_sandbox(
                {"script": "curl {target}/admin", "chain_name": "Test chain"},
                target="https://example.com",
            )

        assert mock_cls.call_args.kwargs.get("network_disabled") is False
        assert result["verified"] is True

    def test_verify_chain_without_target_keeps_network_disabled(self):
        """No target means no reason to leave the sandbox — network must stay off."""
        with patch("tool_core.sandbox.client.SandboxClient") as mock_cls:
            mock_sandbox = MagicMock()
            mock_sandbox.is_docker_available = True
            mock_sandbox.run_command.return_value = SandboxResult(
                returncode=0, stdout="ok"
            )
            mock_cls.return_value = mock_sandbox

            generator = ChainExploitGenerator()
            generator.verify_chain_in_sandbox(
                {"script": "curl http://10.0.0.1/admin", "chain_name": "Test chain"},
                target="",
            )

        assert mock_cls.call_args.kwargs.get("network_disabled") is True

    def test_verify_chain_whitespace_target_keeps_network_disabled(self):
        """Whitespace-only targets must not open container egress."""
        with patch("tool_core.sandbox.client.SandboxClient") as mock_cls:
            mock_sandbox = MagicMock()
            mock_sandbox.is_docker_available = True
            mock_sandbox.run_command.return_value = SandboxResult(
                returncode=0, stdout="ok"
            )
            mock_cls.return_value = mock_sandbox

            generator = ChainExploitGenerator()
            generator.verify_chain_in_sandbox(
                {"script": "curl http://10.0.0.1/admin", "chain_name": "Test chain"},
                target="   ",
            )

        assert mock_cls.call_args.kwargs.get("network_disabled") is True

    def test_verify_chain_non_http_target_keeps_network_disabled(self):
        """Egress requires a scoped http(s) target — bare hostnames stay sandboxed."""
        with patch("tool_core.sandbox.client.SandboxClient") as mock_cls:
            mock_sandbox = MagicMock()
            mock_sandbox.is_docker_available = True
            mock_sandbox.run_command.return_value = SandboxResult(
                returncode=0, stdout="ok"
            )
            mock_cls.return_value = mock_sandbox

            generator = ChainExploitGenerator()
            generator.verify_chain_in_sandbox(
                {"script": "curl example.com/admin", "chain_name": "Test chain"},
                target="example.com",
            )

        assert mock_cls.call_args.kwargs.get("network_disabled") is True

    def test_curl_step_reaches_target_through_sandbox(self):
        """A curl step must run inside the sandbox against the substituted real target."""
        with patch("tool_core.sandbox.client.SandboxClient") as mock_cls:
            mock_sandbox = MagicMock()
            mock_sandbox.is_docker_available = True
            mock_sandbox.run_command.return_value = SandboxResult(returncode=0)
            mock_cls.return_value = mock_sandbox

            generator = ChainExploitGenerator()
            result = generator.verify_chain_in_sandbox(
                {"script": "curl {target}/login", "chain_name": "Test chain"},
                target="https://example.com",
                timeout=30,
            )

        args = mock_sandbox.run_command.call_args.args[0]
        assert "https://example.com/login" in args
        assert result["verified"] is True
        assert result["steps"][0]["sandboxed"] is True

    def test_curl_step_failure_marks_chain_partial(self):
        """A failing curl step in the sandbox must surface as not verified."""
        with patch("tool_core.sandbox.client.SandboxClient") as mock_cls:
            mock_sandbox = MagicMock()
            mock_sandbox.is_docker_available = True
            mock_sandbox.run_command.return_value = SandboxResult(
                returncode=7, stderr="Failed to connect"
            )
            mock_cls.return_value = mock_sandbox

            generator = ChainExploitGenerator()
            result = generator.verify_chain_in_sandbox(
                {"script": "curl {target}/login", "chain_name": "Test chain"},
                target="https://example.com",
            )

        assert result["verified"] is False
        assert result["steps"][0]["success"] is False


class TestPythonStepTargetSubstitution:
    def test_substitutes_target_in_sandboxed_python(self):
        """{target} in a python snippet must be replaced before sandbox execution."""
        sandbox = MagicMock()
        sandbox.is_docker_available = True
        sandbox.run_command.return_value = SandboxResult(returncode=0, stdout="")

        result = ChainExploitGenerator._verify_python_step_sandboxed(
            "print('{target}')", 10, sandbox, "https://example.com"
        )

        assert result["success"] is True
        cmd = sandbox.run_command.call_args.args[0]
        assert "https://example.com" in cmd[2]
        assert "{target}" not in cmd[2]

    def test_substitutes_target_before_subprocess_fallback(self):
        """Fallback (no Docker) must also receive the substituted code."""
        sandbox = MagicMock()
        sandbox.is_docker_available = False
        with patch.object(
            ChainExploitGenerator,
            "_verify_python_step",
            return_value={"success": True},
        ) as mock_fallback:
            result = ChainExploitGenerator._verify_python_step_sandboxed(
                "print('$TARGET')", 10, sandbox, "https://example.com"
            )

        assert result["success"] is True
        call_code = mock_fallback.call_args.args[0]
        assert "https://example.com" in call_code
        assert "$TARGET" not in call_code


class TestGenericStepTargetSubstitution:
    def test_substitutes_target_in_sandboxed_generic(self):
        """{target} in a generic command must be replaced before sandbox execution."""
        sandbox = MagicMock()
        sandbox.is_docker_available = True
        sandbox.run_command.return_value = SandboxResult(returncode=0, stdout="")

        result = ChainExploitGenerator._verify_generic_step_sandboxed(
            "wget {target}/backup.zip", 10, sandbox, "https://example.com"
        )

        assert result["success"] is True
        args = sandbox.run_command.call_args.args[0]
        assert "https://example.com/backup.zip" in args
        assert "{target}" not in args

    def test_substitutes_target_before_generic_fallback(self):
        """Fallback (no Docker) must also receive the substituted command."""
        sandbox = MagicMock()
        sandbox.is_docker_available = False
        with patch.object(
            ChainExploitGenerator,
            "_verify_generic_step",
            return_value={"success": True},
        ) as mock_fallback:
            result = ChainExploitGenerator._verify_generic_step_sandboxed(
                "wget $TARGET/backup.zip", 10, sandbox, "https://example.com"
            )

        assert result["success"] is True
        call_cmd = mock_fallback.call_args.args[0]
        assert "https://example.com/backup.zip" in call_cmd
        assert "$TARGET" not in call_cmd
