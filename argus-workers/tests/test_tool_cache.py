"""Tests for tools.tool_cache — Category: class"""


from tools.tool_cache import ToolCache


class TestToolCache:
    """Tests for the ToolCache class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ToolCache()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ToolCache()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)


class TestToolCacheDirLocation:
    """The cache must survive a reboot.

    It holds downloaded binaries that are symlinked into ~/go/bin; $TMPDIR is
    purged by macOS on reboot and periodically while idle, which left those
    symlinks dangling and made every tool look uninstalled.
    """

    def test_cache_dir_is_not_in_tmp(self):
        import tempfile
        from pathlib import Path

        from tools import tool_cache

        assert not tool_cache.TOOL_CACHE_DIR.is_relative_to(
            Path(tempfile.gettempdir()).resolve()
        )

    def test_cache_dir_defaults_under_argus_home(self, monkeypatch):
        from pathlib import Path

        from tools import tool_cache

        monkeypatch.delenv("ARGUS_TOOL_CACHE_DIR", raising=False)
        assert tool_cache._resolve_tool_cache_dir() == Path.home() / ".argus" / "tools"

    def test_cache_dir_env_override(self, monkeypatch, tmp_path):
        from tools import tool_cache

        monkeypatch.setenv("ARGUS_TOOL_CACHE_DIR", str(tmp_path / "custom"))
        assert tool_cache._resolve_tool_cache_dir() == tmp_path / "custom"

    def test_legacy_tmp_cache_is_migrated(self, monkeypatch, tmp_path):
        from tools import tool_cache

        legacy = tmp_path / "tmp" / "argus_tool_cache"
        (legacy / "nuclei").mkdir(parents=True)
        (legacy / "nuclei" / "nuclei").write_text("binary")
        dest = tmp_path / "persistent"
        dest.mkdir()

        def fake_gettempdir():
            return str(tmp_path / "tmp")

        monkeypatch.setattr(tool_cache.tempfile, "gettempdir", fake_gettempdir)
        monkeypatch.setattr(tool_cache, "TOOL_CACHE_DIR", dest)
        tool_cache._migrate_legacy_cache()

        assert (dest / "nuclei" / "nuclei").read_text() == "binary"
        assert not legacy.exists()

    def test_migration_keeps_existing_destination(self, monkeypatch, tmp_path):
        from tools import tool_cache

        legacy = tmp_path / "tmp" / "argus_tool_cache"
        (legacy / "nuclei").mkdir(parents=True)
        (legacy / "nuclei" / "nuclei").write_text("stale")
        dest = tmp_path / "persistent"
        (dest / "nuclei").mkdir(parents=True)
        (dest / "nuclei" / "nuclei").write_text("current")

        monkeypatch.setattr(
            tool_cache.tempfile, "gettempdir", lambda: str(tmp_path / "tmp")
        )
        monkeypatch.setattr(tool_cache, "TOOL_CACHE_DIR", dest)
        tool_cache._migrate_legacy_cache()

        assert (dest / "nuclei" / "nuclei").read_text() == "current"
        assert not legacy.exists()
