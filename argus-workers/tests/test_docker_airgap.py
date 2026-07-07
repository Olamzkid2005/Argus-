"""Tests for Dockerfile AIRGAP support."""

import os

import pytest


class TestDockerfileAirgap:
    """Dockerfile defines ARG AIRGAP=0 and wraps Go download in a conditional."""

    DOCKERFILE_PATH = os.path.join(
        os.path.dirname(__file__), "..", "Dockerfile"
    )

    @classmethod
    def setup_class(cls):
        with open(cls.DOCKERFILE_PATH) as f:
            cls.content = f.read()
        cls.lines = cls.content.splitlines()

    def test_has_airgap_arg(self):
        """Dockerfile should define ARG AIRGAP=0."""
        assert "ARG AIRGAP=0" in self.content, (
            "Dockerfile must define ARG AIRGAP=0 for air-gapped builds"
        )

    def test_airgap_arg_is_early(self):
        """ARG AIRGAP=0 should appear near the top, before any RUN instructions."""
        for i, line in enumerate(self.lines):
            if line.startswith("ARG AIRGAP="):
                arg_line = i
                break
        else:
            pytest.fail("ARG AIRGAP=0 not found")

        for i, line in enumerate(self.lines):
            if line.startswith("RUN "):
                first_run = i
                break
        else:
            first_run = len(self.lines)

        assert arg_line < first_run, (
            "ARG AIRGAP must be declared before any RUN instruction"
        )

    def test_go_download_is_conditional(self):
        """Go curl download should be guarded by if [ \"$AIRGAP\" = \"0\" ]."""
        assert 'if [ "$AIRGAP" = "0" ]; then' in self.content, (
            "Go download must be conditional on AIRGAP env var"
        )

    def test_tar_extraction_happens_always(self):
        """tar extraction of Go should happen outside the AIRGAP conditional."""
        assert "tar -C /usr/local -xzf /tmp/go.tar.gz" in self.content

    def test_go_tools_install_after_airgap_block(self):
        """Go tool installations should occur after the AIRGAP conditional block."""
        tools_line = None
        airgap_block_end = None

        for i, line in enumerate(self.lines):
            if 'if [ "$AIRGAP" = "0" ]; then' in line:
                airgap_block_end = airgap_block_end or i
            if "fi;" in line and airgap_block_end is not None:
                airgap_block_end = i
                break

        for i, line in enumerate(self.lines):
            if "go install" in line and "projectdiscovery" in line:
                tools_line = i
                break

        if airgap_block_end is not None and tools_line is not None:
            assert tools_line > airgap_block_end, (
                "Go tool installations should come after the AIRGAP conditional"
            )

    def test_no_old_key_format(self):
        """Ensure old Go download pattern (unconditional curl) is not present."""
        # Check for non-commented curl commands
        non_comment_curl_lines = [
            line for line in self.lines
            if 'curl -fsSL "https://go.dev/dl/go' in line
            and not line.strip().startswith("#")
        ]
        assert len(non_comment_curl_lines) == 0, (
            f"Found {len(non_comment_curl_lines)} non-commented curl command(s): {non_comment_curl_lines}"
        )
