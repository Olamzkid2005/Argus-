from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

JOB_TYPES = [
    "recon",
    "scan",
    "analyze",
    "report",
    "repo_scan",
    "compliance_report",
    "full_report",
    "asset_discovery",
    "asset_risk_scoring",
    "bugbounty_report",
]

TASK_NAME_MAP: dict[str, str] = {
    "recon": "tasks.recon.run_recon",
    "scan": "tasks.scan.run_scan",
    "analyze": "tasks.analyze.run_analysis",
    "report": "tasks.report.generate_report",
    "repo_scan": "tasks.repo_scan.run_repo_scan",
    "compliance_report": "tasks.report.generate_compliance_report",
    "full_report": "tasks.report.generate_full_report",
    "asset_discovery": "tasks.asset_discovery.run_asset_discovery",
    "asset_risk_scoring": "tasks.asset_discovery.update_asset_risk_scores",
    "bugbounty_report": "tasks.bugbounty.generate_bugbounty_report",
}


def build_task_args(
    job_type: str,
    engagement_id: str,
    target: str,
    budget: dict,
    trace_id: str,
    **kwargs,
) -> list:
    """Build positional args for a Celery task based on job type."""
    agent_mode = kwargs.get("agent_mode")
    if agent_mode is None:
        agent_mode = True
    repo_url = kwargs.get("repo_url") or target
    args_map = {
        # tasks.recon.run_recon(..., trace_id=None, agent_mode=True, scan_mode=None, aggressiveness=None, bug_bounty_mode=None, ...)
        "recon": [
            engagement_id,
            target,
            budget,
            trace_id,
            agent_mode,
            kwargs.get("scan_mode"),
            kwargs.get("aggressiveness"),
            kwargs.get("bug_bounty_mode"),
        ],
        # tasks.scan.run_scan(..., trace_id=None, agent_mode=True, scan_mode=None, aggressiveness=None, bug_bounty_mode=None)
        "scan": [engagement_id, [target], budget, trace_id, agent_mode, kwargs.get("scan_mode"), kwargs.get("aggressiveness"), kwargs.get("bug_bounty_mode")],
        # tasks.analyze.run_analysis(self, engagement_id, budget, trace_id=None)
        "analyze": [engagement_id, budget, trace_id],
        # tasks.report.generate_report(self, engagement_id, trace_id=None, budget=None)
        "report": [engagement_id, trace_id, kwargs.get("budget_for_report") or budget],
        # tasks.repo_scan.run_repo_scan(self, engagement_id, repo_url, budget, trace_id=None, ...)
        "repo_scan": [engagement_id, repo_url, budget, trace_id],
        "compliance_report": [engagement_id, kwargs.get("standard")],
        "full_report": [engagement_id, kwargs.get("report_id", "")],
        # tasks.asset_discovery.run_asset_discovery(self, engagement_id, target, trace_id=None, org_id=None)
        "asset_discovery": [engagement_id, target, trace_id, kwargs.get("org_id")],
        "asset_risk_scoring": [engagement_id],
        "bugbounty_report": [
            engagement_id,
            kwargs.get("platform", "hackerone"),
            kwargs.get("output_path", ""),
            trace_id,
        ],
    }
    return args_map.get(job_type, [engagement_id, target, budget, trace_id, agent_mode])


@dataclass
class JobMessage:
    type: str = ""
    engagement_id: str = ""
    target: str = ""
    repo_url: str | None = None
    standard: str | None = None
    report_id: str | None = None
    org_id: str | None = None
    budget: dict | None = None
    aggressiveness: str | None = None
    agent_mode: bool | None = None
    scan_mode: str | None = None
    bug_bounty_mode: bool | None = None
    auth_config: dict | None = None
    trace_id: str = ""
    created_at: str = ""
    platform: str = ""
    output_path: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "JobMessage":
        known_fields = set(cls.__dataclass_fields__.keys())
        unknown = {k for k in data if k not in known_fields}
        if unknown:
            logger.warning(
                "JobMessage received %d unknown field(s): %s — silently dropped. "
                "This may indicate a schema version mismatch between frontend and workers.",
                len(unknown), sorted(unknown),
            )
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_celery_args(self) -> list:
        """Convert this message to Celery task positional args."""
        return build_task_args(
            self.type,
            self.engagement_id,
            self.target,
            self.budget or {},
            self.trace_id,
            standard=self.standard,
            auth_config=self.auth_config,
            platform=self.platform,
            output_path=self.output_path,
            repo_url=self.repo_url,
            agent_mode=self.agent_mode,
            aggressiveness=self.aggressiveness,
            scan_mode=self.scan_mode,
            bug_bounty_mode=self.bug_bounty_mode,
            budget_for_report=self.budget,
        )
