"""Tests for agent.tool_arguments — category: function.

The builder is the agent's half of the contract the MCP server already honors:
a validated named parameter must reach the binary as its declared flag, and a
target declared with a flag must not be passed as a bare positional.
"""

from agent.tool_arguments import build_tool_argv


class TestBuildToolArgv:
    def test_target_with_flag_uses_the_flag(self):
        """arjun declares target as -u; a bare URL is not accepted."""
        argv = build_tool_argv("arjun", target="http://lab.local/login")
        assert argv == ["-m", "GET", "-u", "http://lab.local/login"]

    def test_named_parameter_keeps_its_flag_and_order(self):
        """A parameter the registry validated must not be silently dropped."""
        argv = build_tool_argv(
            "arjun", target="http://lab.local/login", parameters={"threads": 20}
        )
        assert argv == ["-m", "GET", "-u", "http://lab.local/login", "-t", "20"]

    def test_positional_target_is_not_invented_a_flag(self):
        """nmap's target has no flag and stays positional, after default args."""
        argv = build_tool_argv("nmap", target="127.0.0.1", parameters={"ports": "80"})
        assert argv == ["-oX", "-", "127.0.0.1", "-p", "80"]

    def test_boolean_parameter_is_a_switch(self):
        """A truthy boolean emits its flag alone; a falsey one emits nothing."""
        on = build_tool_argv("dalfox", target="http://lab.local", parameters={"deep_dom": True})
        assert "--deep-domxss" in on
        assert "--deep-domxss" not in build_tool_argv(
            "dalfox", target="http://lab.local", parameters={"deep_dom": False}
        )

    def test_unknown_parameter_is_not_forwarded(self):
        """Dispatch never receives an undeclared flag, even if called directly."""
        argv = build_tool_argv(
            "arjun", target="http://lab.local", parameters={"not_a_parameter": "x"}
        )
        assert argv == ["-m", "GET", "-u", "http://lab.local"]

    def test_none_values_are_skipped(self):
        """An explicit null means \"not supplied\", not the string \"None\"."""
        argv = build_tool_argv("arjun", target="http://lab.local", parameters={"threads": None})
        assert argv == ["-m", "GET", "-u", "http://lab.local"]

    def test_undefined_tool_falls_back_to_a_bare_target(self):
        """Tools outside the registry keep the previous behavior."""
        assert build_tool_argv("not_a_tool", target="http://lab.local") == ["http://lab.local"]
        assert build_tool_argv("not_a_tool") == []
