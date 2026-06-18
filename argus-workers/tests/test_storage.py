"""Unit tests for ArtifactStorage."""

import tempfile
from pathlib import Path

import pytest

from tool_core.storage import ArtifactMissingError, ArtifactRef, ArtifactStorage


@pytest.fixture
def storage():
    tmp = tempfile.mkdtemp()
    return ArtifactStorage(base_dir=tmp)


class TestStore:
    def test_stores_artifact(self, storage):
        ref = storage.store("finding-1", b"test data", "scan.txt", "text/plain")
        assert ref.finding_id == "finding-1"
        assert ref.mime == "text/plain"
        assert ref.size == 9
        assert ref.hash
        assert ref.stored_externally is True

    def test_file_exists_on_disk(self, storage):
        ref = storage.store("finding-1", b"hello", "test.txt", "text/plain")
        path = Path(storage.base_dir) / ref.path
        assert path.exists()
        assert path.read_bytes() == b"hello"

    def test_deduplication_same_content(self, storage):
        ref1 = storage.store("finding-1", b"same data", "a.txt", "text/plain")
        ref2 = storage.store("finding-2", b"same data", "b.txt", "text/plain")
        assert ref1.hash == ref2.hash

    def test_path_traversal_finding_id(self, storage):
        with pytest.raises(ValueError, match="Path traversal"):
            storage.store("../etc/passwd", b"x", "f.txt", "text/plain")

    def test_path_traversal_filename(self, storage):
        with pytest.raises(ValueError, match="Path traversal"):
            storage.store("finding-1", b"x", "../../etc/passwd", "text/plain")

    def test_multiple_findings(self, storage):
        ref1 = storage.store("f1", b"data1", "a.txt", "text/plain")
        ref2 = storage.store("f2", b"data2", "b.txt", "text/plain")
        assert ref1.finding_id == "f1"
        assert ref2.finding_id == "f2"


class TestRead:
    def test_reads_artifact(self, storage):
        ref = storage.store("finding-1", b"hello world", "test.txt", "text/plain")
        data = storage.read(ref)
        assert data == b"hello world"

    def test_missing_artifact_raises(self, storage):
        ref = ArtifactRef(
            artifact_id="x",
            finding_id="y",
            path="nonexistent/file.txt",
            hash="",
            size=0,
            mime="text/plain",
        )
        with pytest.raises(ArtifactMissingError):
            storage.read(ref)


class TestReadByPath:
    def test_reads_by_path(self, storage):
        ref = storage.store("finding-1", b"content", "f.txt", "text/plain")
        data = storage.read_by_path(ref.path)
        assert data == b"content"

    def test_path_traversal_protection(self, storage):
        with pytest.raises(ArtifactMissingError, match="Path traversal"):
            storage.read_by_path("../../etc/passwd")

    def test_missing_path(self, storage):
        with pytest.raises(ArtifactMissingError, match="not found"):
            storage.read_by_path("nonexistent/file.txt")


class TestPurge:
    def test_purges_finding_directory(self, storage):
        storage.store("finding-1", b"data", "f.txt", "text/plain")
        storage.purge("finding-1")
        assert not (Path(storage.base_dir) / "finding-1").exists()

    def test_purge_nonexistent(self, storage):
        storage.purge("does-not-exist")


class TestDeleteArtifact:
    def test_deletes_single_artifact(self, storage):
        ref = storage.store("finding-1", b"data", "f.txt", "text/plain")
        storage.delete_artifact(ref)
        assert not (Path(storage.base_dir) / ref.path).exists()

    def test_removes_empty_parent(self, storage):
        ref = storage.store("finding-1", b"data", "f.txt", "text/plain")
        storage.delete_artifact(ref)
        assert not (Path(storage.base_dir) / "finding-1").exists()

    def test_missing_artifact_does_not_raise(self, storage):
        ref = ArtifactRef(
            artifact_id="x",
            finding_id="y",
            path="nonexistent/file.txt",
            hash="",
            size=0,
            mime="text/plain",
        )
        storage.delete_artifact(ref)


class TestCheckReadability:
    def test_all_files_readable(self, storage):
        storage.store("f1", b"data1", "a.txt", "text/plain")
        storage.store("f2", b"data2", "b.txt", "text/plain")
        issues = storage.check_readability()
        assert issues == []

    def test_empty_storage(self, storage):
        issues = storage.check_readability()
        assert issues == []
