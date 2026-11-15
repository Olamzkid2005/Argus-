"""Tests for action identity, bounded revisits, stop and coverage (Stage 5.1 item 3)."""

from agent.action_policy import (
    ActionPolicy,
    CoveragePolicy,
    action_signature,
    check_action,
)


class TestActionSignature:
    def test_same_tool_with_different_arguments_has_a_different_signature(self):
        first = action_signature("sqlmap", {"target": "https://a.example.com/1"})
        second = action_signature("sqlmap", {"target": "https://a.example.com/2"})
        assert first != second

    def test_argument_order_does_not_change_the_signature(self):
        assert action_signature("nuclei", {"target": "x", "severity": "high"}) == action_signature(
            "nuclei", {"severity": "high", "target": "x"}
        )

    def test_tool_name_is_part_of_the_signature(self):
        assert action_signature("nuclei", {"target": "x"}) != action_signature(
            "nmap", {"target": "x"}
        )


class TestBoundedRevisits:
    def test_a_new_action_is_allowed(self):
        decision = check_action({}, {}, "nuclei", {"target": "https://a"})
        assert decision.allowed is True
        assert decision.revisit is False

    def test_an_identical_action_is_refused(self):
        policy = ActionPolicy()
        policy.record("nuclei", {"target": "https://a"})
        decision = policy.check("nuclei", {"target": "https://a"})
        assert decision.allowed is False
        assert "duplicate action" in decision.reason

    def test_the_same_tool_with_new_arguments_is_a_bounded_revisit(self):
        policy = ActionPolicy(max_revisits_per_tool=2)
        policy.record("nuclei", {"target": "https://a"})
        decision = policy.check("nuclei", {"target": "https://a/other"})
        assert decision.allowed is True
        assert decision.revisit is True

    def test_new_identity_justifies_repeating_the_same_action_once(self):
        policy = ActionPolicy(max_revisits_per_tool=1)
        policy.record("bola", {"target": "https://a/1"})
        justified = policy.check("bola", {"target": "https://a/1"}, new_identity=True)
        assert justified.allowed is True
        assert justified.revisit is True

        policy.record("bola", {"target": "https://a/1"})
        refused = policy.check("bola", {"target": "https://a/1"}, new_evidence=True)
        assert refused.allowed is False
        assert "revisit limit reached" in refused.reason

    def test_revisits_are_bounded_per_tool(self):
        policy = ActionPolicy(max_revisits_per_tool=1)
        policy.record("nuclei", {"target": "https://a"})
        policy.record("nuclei", {"target": "https://b"})
        decision = policy.check("nuclei", {"target": "https://c"})
        assert decision.allowed is False
        assert "revisit limit reached for nuclei" in decision.reason

    def test_other_tools_are_unaffected_by_one_tool_s_limit(self):
        policy = ActionPolicy(max_revisits_per_tool=0)
        policy.record("nuclei", {"target": "https://a"})
        assert policy.check("nmap", {"target": "https://a"}).allowed is True

    def test_executed_tools_are_tracked_for_coverage(self):
        policy = ActionPolicy()
        policy.record("nuclei", {"target": "https://a"})
        policy.record("nuclei", {"target": "https://b"})
        assert policy.executed_tools == ["nuclei", "nuclei"]


class TestCoveragePolicy:
    def test_stop_is_honoured_when_coverage_is_complete(self):
        policy = CoveragePolicy(["nuclei"])
        decision = policy.can_stop(True, ["nuclei"])
        assert decision.stop is True
        assert decision.missing == ()

    def test_stop_is_deferred_when_required_coverage_is_missing(self):
        policy = CoveragePolicy(["nuclei", "sqlmap"])
        decision = policy.can_stop(True, ["nuclei"])
        assert decision.stop is False
        assert decision.missing == ("sqlmap",)
        assert "required coverage missing" in decision.reason

    def test_no_stop_request_means_continue(self):
        decision = CoveragePolicy(["nuclei"]).can_stop(False, [])
        assert decision.stop is False
        assert decision.reason == "continue"

    def test_extra_executed_tools_do_not_satisfy_missing_coverage(self):
        decision = CoveragePolicy(["nuclei"]).can_stop(True, ["nmap", "httpx"])
        assert decision.stop is False
        assert decision.missing == ("nuclei",)
