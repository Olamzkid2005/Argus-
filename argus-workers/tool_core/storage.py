"""Artifact Storage — filesystem-backed storage for binary artifacts.

Large scan outputs (screenshots, HAR files, raw HTTP responses, etc.)
are stored on the filesystem rather than in SQLite. The database stores
only metadata references (path, hash, size, mime type).

Storage layout:
  ~/.argus/artifacts/
    <finding_id>/
      <filename>
      ...
"""

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from exceptions import ArtifactMissingError


@dataclass
class ArtifactData:
    data: bytes
    filename: str
    mime: str


@dataclass
class ArtifactRef:
    artifact_id: str
    finding_id: str
    path: str
    hash: str
    size: int
    mime: str
    stored_externally: bool = True


class ArtifactStorage:
    def __init__(self, base_dir: str = "~/.argus/artifacts"):
        self.base_dir = Path(base_dir).expanduser()

    def store(
        self, finding_id: str, data: bytes, filename: str, mime: str
    ) -> ArtifactRef:
        self._validate_path(finding_id, filename)

        artifact_dir = self.base_dir / finding_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        path = artifact_dir / filename

        content_hash = hashlib.sha256(data).hexdigest()

        path.write_bytes(data)

        artifact_id = content_hash[:16]

        return ArtifactRef(
            artifact_id=artifact_id,
            finding_id=finding_id,
            path=str(path.relative_to(self.base_dir)),
            hash=content_hash,
            size=len(data),
            mime=mime,
            stored_externally=True,
        )

    def read(self, ref: ArtifactRef) -> bytes:
        path = self.base_dir / ref.path
        if not path.exists():
            raise ArtifactMissingError(f"Artifact not found at {path}")
        return path.read_bytes()

    def read_by_path(self, relative_path: str) -> bytes:
        full_path = self.base_dir / relative_path
        full_path = full_path.resolve()
        if not str(full_path).startswith(str(self.base_dir.resolve())):
            raise ArtifactMissingError("Path traversal detected")
        if not full_path.exists():
            raise ArtifactMissingError(f"Artifact not found at {full_path}")
        return full_path.read_bytes()

    def purge(self, finding_id: str):
        shutil.rmtree(self.base_dir / finding_id, ignore_errors=True)

    def delete_artifact(self, ref: ArtifactRef):
        path = self.base_dir / ref.path
        if path.exists():
            path.unlink()
        parent = path.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()

    def check_readability(self) -> list[dict]:
        """Check that all stored artifacts are readable.

        Returns a list of issues (file paths that cannot be read).
        Unlike verify_integrity, this does not compare hashes against
        a stored reference (the storage layer does not persist expected
        hashes independently).
        """
        issues = []
        for finding_dir in self.base_dir.iterdir():
            if not finding_dir.is_dir():
                continue
            for file_path in finding_dir.iterdir():
                if not file_path.is_file():
                    continue
                try:
                    content = file_path.read_bytes()
                    hashlib.sha256(content).hexdigest()
                    len(content)
                except Exception as e:
                    issues.append(
                        {
                            "path": str(file_path),
                            "error": f"Failed to read: {e}",
                        }
                    )
                    continue
        return issues

    def _validate_path(self, finding_id: str, filename: str):
        resolved = (self.base_dir / finding_id / filename).resolve()
        if not str(resolved).startswith(str(self.base_dir.resolve())):
            raise ValueError(
                f"Path traversal detected in finding_id={finding_id!r} filename={filename!r}"
            )
