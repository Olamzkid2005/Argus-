"""Evidence collector for verification results."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


class VerificationEvidenceCollector:
    """Collects and packages evidence from verification attempts."""

    def __init__(self, output_dir: str | None = None):
        self._output_dir = (
            Path(output_dir) if output_dir else Path("/tmp/argus_evidence")
        )
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def collect(self, finding: dict, reproduction_result: dict) -> dict:
        """Collect evidence from a verification attempt.

        Returns evidence package with hash, artifacts, and metadata.
        """
        artifacts = []

        evidence_data = reproduction_result.get("evidence", {})
        if evidence_data:
            artifact_path = self._write_artifact(
                finding.get("id", "unknown"),
                "evidence.json",
                json.dumps(evidence_data, indent=2),
            )
            artifacts.append(
                {
                    "path": str(artifact_path),
                    "type": "evidence_data",
                    "hash": self._hash_file(artifact_path),
                }
            )

        if reproduction_result.get("error"):
            artifact_path = self._write_artifact(
                finding.get("id", "unknown"),
                "error.txt",
                reproduction_result["error"],
            )
            artifacts.append(
                {
                    "path": str(artifact_path),
                    "type": "error_log",
                    "hash": self._hash_file(artifact_path),
                }
            )

        evidence_hash = self._compute_evidence_hash(artifacts)

        return {
            "finding_id": finding.get("id", "unknown"),
            "reproduced": reproduction_result.get("reproduced", False),
            "hash": evidence_hash,
            "artifacts": artifacts,
            "collected_at": time.time(),
            "collector": "verification_agent",
        }

    def _write_artifact(self, finding_id: str, filename: str, content: str) -> Path:
        safe_id = finding_id.replace("/", "_").replace(":", "_")[:64]
        artifact_dir = self._output_dir / safe_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = artifact_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    def _hash_file(self, path: Path) -> str:
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()[:16]

    def _compute_evidence_hash(self, artifacts: list[dict]) -> str:
        h = hashlib.sha256()
        for art in sorted(artifacts, key=lambda a: a.get("path", "")):
            h.update(art.get("hash", "").encode())
        return h.hexdigest()[:16]
