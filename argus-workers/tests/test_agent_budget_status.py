"""Worker budget-status ledger tests for driver checkpoint reconciliation."""

from mcp_server import MCPServer, ToolDefinition


def make_server() -> MCPServer:
    server = MCPServer(tools_dir="/tmp/nonexistent_tools_dir_xyz")
    server.register_tool(ToolDefinition(name="nuclei", command="nuclei"))
    server.register_tool(ToolDefinition(name="nmap", command="nmap"))
    return server


class TestAgentBudgetStatus:
    def test_missing_engagement_id_is_an_error(self):
        server = make_server()
        assert server.handle_agent_budget({}) == {"error": "engagement_id is required"}

    def test_empty_engagement_has_zero_usage(self):
        server = make_server()
        assert server.handle_agent_budget({"engagement_id": "eng-absent"}) == {
            "engagement_id": "eng-absent",
            "tool_calls": 0,
            "executed_tools": [],
            "identities": [],
            "sessions": 0,
        }

    def test_budget_aggregates_session_executions_and_safe_identities(self):
        server = make_server()
        first = server.session_store.create(
            target="https://example.com",
            phase="recon",
            engagement_id="eng-budget",
        )
        second = server.session_store.create(
            target="https://example.com",
            phase="scan",
            engagement_id="eng-budget",
        )

        server.handle_agent_observe(
            {
                "session_id": first,
                "tool": "nuclei",
                "arguments": {"target": "https://example.com", "identity": "attacker"},
                "reasoning": "engine chose nuclei for web scanning",
                "success": True,
                "summary": "nuclei finished",
            }
        )
        server.handle_agent_observe(
            {
                "session_id": second,
                "tool": "nmap",
                "arguments": {
                    "target": "https://example.com",
                    "username": "victim",
                    "password": "super-secret",
                },
                "reasoning": "engine chose nmap after open ports",
                "success": False,
                "summary": "nmap timed out",
            }
        )

        status = server.handle_agent_budget({"engagement_id": "eng-budget"})
        assert status == {
            "engagement_id": "eng-budget",
            "tool_calls": 2,
            "executed_tools": ["nmap", "nuclei"],
            "identities": ["attacker", "victim"],
            "sessions": 2,
        }

        executions = server.session_store.executions_for_engagement("eng-budget")
        assert [execution.identity for execution in executions] == ["attacker", "victim"]
        assert executions[1].arguments["password"] == "***REDACTED***"
