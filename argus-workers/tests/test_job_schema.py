"""Tests for job_schema — Category: dataclass"""


from job_schema import JobMessage


class TestJobMessage:
    """Tests for the JobMessage class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = JobMessage()
            assert instance is not None
            assert isinstance(instance, JobMessage)
        except TypeError:
            instance = JobMessage()
            assert instance is not None

    def test_field_access(self):
        """Instance fields are accessible."""
        try:
            instance = JobMessage()
            fields = vars(instance) if hasattr(instance, '__dict__') else {}
            assert isinstance(fields, dict)
        except TypeError:
            instance = JobMessage()
            assert instance is not None

    def test_from_dict_preserves_scope(self):
        """from_dict() keeps the scope field when present."""
        scope_payload = {
            "mode": "allowlist",
            "allowed_targets": ["127.0.0.1:3001"],
            "blocked_targets": ["*"],
        }
        job = JobMessage.from_dict({
            "type": "recon",
            "engagement_id": "eng-1",
            "target": "http://127.0.0.1:3001",
            "budget": {},
            "trace_id": "trace-1",
            "scope": scope_payload,
        })
        assert job.scope == scope_payload
        assert job.scope["mode"] == "allowlist"
        assert job.scope["allowed_targets"] == ["127.0.0.1:3001"]

    def test_from_dict_missing_scope_defaults_none(self):
        """from_dict() sets scope to None when omitted."""
        job = JobMessage.from_dict({
            "type": "recon",
            "engagement_id": "eng-1",
            "target": "http://127.0.0.1:3001",
            "budget": {},
            "trace_id": "trace-1",
        })
        assert job.scope is None

    def test_scope_is_known_dataclass_field(self):
        """Scope is a declared field on JobMessage, not dropped as unknown."""
        job = JobMessage.from_dict({
            "type": "recon",
            "engagement_id": "eng-1",
            "target": "http://127.0.0.1:3001",
            "budget": {},
            "trace_id": "trace-1",
            "scope": {"mode": "allowlist", "allowed_targets": [], "blocked_targets": []},
        })
        # The unknown-fields warning in from_dict() only fires for fields NOT in
        # __dataclass_fields__. scope IS declared, so it should be preserved.
        assert "scope" in type(job).__dataclass_fields__
        assert job.scope is not None

    def test_to_celery_args_recon_includes_scope(self):
        """to_celery_args() passes scope through build_task_args for recon type."""
        scope_payload = {"mode": "allowlist", "allowed_targets": ["127.0.0.1"], "blocked_targets": []}
        job = JobMessage(
            type="recon",
            engagement_id="eng-1",
            target="http://127.0.0.1",
            budget={},
            trace_id="trace-1",
            scope=scope_payload,
        )
        args = job.to_celery_args()
        # The scope is the 12th positional arg (index 11) in build_task_args for "recon"
        # Format: [engagement_id, target, budget, trace_id, agent_mode, scan_mode,
        #          aggressiveness, bug_bounty_mode, prev_engagement_id, auth_config,
        #          dual_auth_config, scope]
        assert len(args) >= 12
        assert args[11] == scope_payload

    def test_to_celery_args_scan_includes_scope(self):
        """to_celery_args() passes scope through build_task_args for scan type."""
        scope_payload = {"mode": "warn", "allowed_targets": [], "blocked_targets": ["*"]}
        job = JobMessage(
            type="scan",
            engagement_id="eng-1",
            target="http://127.0.0.1",
            budget={},
            trace_id="trace-1",
            scope=scope_payload,
        )
        args = job.to_celery_args()
        # For scan, the target is wrapped in [target], but scope is still index 10
        assert len(args) >= 11
        assert args[10] == scope_payload
