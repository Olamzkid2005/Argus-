from dataclasses import dataclass
from typing import Any

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
    args_map = {
        "recon": [engagement_id, target, budget],
        "scan": [engagement_id, [target], budget],
        "analyze": [engagement_id],
        "report": [engagement_id],
        "repo_scan": [engagement_id, target, budget],
        "compliance_report": [engagement_id, kwargs.get("standard")],
        "full_report": [engagement_id],
        "asset_discovery": [engagement_id, target],
        "asset_risk_scoring": [engagement_id],
    }
    return args_map.get(job_type, [engagement_id, target, budget])


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
    auth_config: dict | None = None
    trace_id: str = ""
    created_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "JobMessage":
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
        )
