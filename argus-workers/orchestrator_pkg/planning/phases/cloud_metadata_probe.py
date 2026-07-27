"""Phase: cloud_metadata_probe — _activate_cloud_metadata and _cloud_metadata_tools."""

from __future__ import annotations

import logging
from typing import Any

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)


# Cloud provider keywords for matching against tech_stack
_CLOUD_PROVIDERS: dict[str, set[str]] = {
    "AWS": {"aws", "amazon web services", "amazon", "ec2", "s3", "lambda",
             "cloudfront", "route53", "elb", "ecs", "eks", "rds"},
    "GCP": {"gcp", "google cloud", "google cloud platform", "gke",
             "cloud run", "app engine", "bigquery", "cloud storage"},
    "Azure": {"azure", "microsoft azure", "azure vm", "azure functions",
               "azure storage", "aks", "azure ad"},
}


def _activate_cloud_metadata(rc) -> tuple[bool, str]:
    """Activate when tech_stack suggests cloud infrastructure.

    Cloud-provisioned targets often expose metadata services
    (IMDS, GCP metadata, Azure IMDS) that can leak credentials
    or instance metadata via SSRF or misconfiguration.
    """
    tech = _get_tech_stack(rc)
    if not tech:
        return False, "no tech_stack detected"

    tech_lower = " ".join(t.lower() for t in tech)

    matched_providers: list[str] = []
    for provider, keywords in _CLOUD_PROVIDERS.items():
        if any(kw in tech_lower for kw in keywords):
            matched_providers.append(provider)

    if not matched_providers:
        return False, "no cloud provider keywords in tech stack"

    return True, f"cloud infrastructure detected: {', '.join(matched_providers)}"


def _cloud_metadata_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for cloud metadata probing.

    Probes for:
      - AWS IMDS (169.254.169.254/latest/meta-data/)
      - GCP metadata endpoint (metadata.google.internal)
      - Azure IMDS (169.254.169.254/metadata/instance)
      - Cloud storage bucket discovery (S3, GCS, Azure Blob)
      - Cloud credential exposure via nuclei templates
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="Cloud metadata service probing (IMDS, GCP, Azure)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "cloud,metadata,imds,ssrf"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Cloud storage bucket discovery and misconfiguration",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "s3,bucket,storage,cloud-storage"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Cloud credential and key exposure scanning",
            priority=30,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "keys,credentials,tokens,secrets"],
        ),
    ]
    return tools


# ── Phase Registry ─────────────────────────────────────────────────────
