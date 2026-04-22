"""
Tests for Container Security Scanner
"""
import pytest
import json
import tempfile
import os
from pathlib import Path
from tools.container_scanner import ContainerSecurityScanner


class TestContainerSecurityScanner:
    """Test ContainerSecurityScanner"""

    @pytest.fixture
    def scanner(self):
        return ContainerSecurityScanner()

    def _create_dockerfile(self, content):
        fd, path = tempfile.mkstemp(suffix=".dockerfile")
        os.write(fd, content.encode())
        os.close(fd)
        return path

    def test_scan_dockerfile_latest_tag(self, scanner):
        path = self._create_dockerfile("FROM ubuntu:latest\nRUN apt-get update")
        try:
            findings = scanner.scan_dockerfile(path)
            latest_findings = [f for f in findings if f["type"] == "DOCKERFILE_LATEST_TAG"]
            assert len(latest_findings) == 1
            assert latest_findings[0]["severity"] == "MEDIUM"
        finally:
            os.unlink(path)

    def test_scan_dockerfile_root_user(self, scanner):
        path = self._create_dockerfile("FROM ubuntu:22.04\nUSER root")
        try:
            findings = scanner.scan_dockerfile(path)
            root_findings = [f for f in findings if f["type"] == "DOCKERFILE_ROOT_USER"]
            assert len(root_findings) == 1
            assert root_findings[0]["severity"] == "HIGH"
        finally:
            os.unlink(path)

    def test_scan_dockerfile_no_healthcheck(self, scanner):
        path = self._create_dockerfile("FROM ubuntu:22.04\nCMD ['echo', 'hi']")
        try:
            findings = scanner.scan_dockerfile(path)
            health_findings = [f for f in findings if f["type"] == "DOCKERFILE_NO_HEALTHCHECK"]
            assert len(health_findings) == 1
        finally:
            os.unlink(path)

    def test_scan_dockerfile_secrets_in_env(self, scanner):
        path = self._create_dockerfile("FROM ubuntu:22.04\nENV API_KEY=sk-1234567890abcdef")
        try:
            findings = scanner.scan_dockerfile(path)
            secret_findings = [f for f in findings if f["type"] == "DOCKERFILE_SECRETS_IN_ENV"]
            assert len(secret_findings) == 1
            assert secret_findings[0]["severity"] == "CRITICAL"
        finally:
            os.unlink(path)

    def test_scan_kubernetes_privileged(self, scanner):
        manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "spec": {
                "containers": [{"name": "app", "image": "nginx", "securityContext": {"privileged": True}}]
            }
        }
        fd, path = tempfile.mkstemp(suffix=".yaml")
        os.write(fd, json.dumps(manifest).encode())
        os.close(fd)
        try:
            findings = scanner.scan_kubernetes_manifest(path)
            priv_findings = [f for f in findings if f["type"] == "K8S_PRIVILEGED_CONTAINER"]
            assert len(priv_findings) == 1
            assert priv_findings[0]["severity"] == "CRITICAL"
        finally:
            os.unlink(path)

    def test_scan_kubernetes_host_network(self, scanner):
        manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "spec": {"hostNetwork": True, "containers": [{"name": "app", "image": "nginx"}]}
        }
        fd, path = tempfile.mkstemp(suffix=".yaml")
        os.write(fd, json.dumps(manifest).encode())
        os.close(fd)
        try:
            findings = scanner.scan_kubernetes_manifest(path)
            host_findings = [f for f in findings if f["type"] == "K8S_HOST_NETWORK"]
            assert len(host_findings) == 1
        finally:
            os.unlink(path)

    def test_generate_sbom_package_json(self, scanner):
        with tempfile.TemporaryDirectory() as tmpdir:
            package_json = Path(tmpdir) / "package.json"
            package_json.write_text(json.dumps({
                "name": "test-app",
                "dependencies": {"express": "^4.18.0", "lodash": "^4.17.21"}
            }))
            sbom = scanner.generate_sbom(tmpdir)
            assert sbom["specVersion"] == "1.4"
            assert len(sbom["components"]) == 2
            assert sbom["components"][0]["name"] == "express"

    def test_generate_sbom_requirements_txt(self, scanner):
        with tempfile.TemporaryDirectory() as tmpdir:
            req = Path(tmpdir) / "requirements.txt"
            req.write_text("requests==2.28.1\nflask>=2.0.0\n")
            sbom = scanner.generate_sbom(tmpdir)
            assert len(sbom["components"]) == 1  # Only == parsed
            assert sbom["components"][0]["name"] == "requests"

    def test_generate_sbom_unsupported(self, scanner):
        with tempfile.TemporaryDirectory() as tmpdir:
            sbom = scanner.generate_sbom(tmpdir)
            assert sbom["components"] == []

    def test_run_trivy_scan(self, scanner):
        from unittest.mock import Mock
        mock_tool_runner = Mock()
        mock_tool_runner.run.return_value = {
            "stdout": json.dumps({"Results": []}),
            "stderr": "",
            "returncode": 0,
            "success": True
        }
        findings = scanner.run_trivy_scan("/tmp/test", mock_tool_runner)
        assert isinstance(findings, list)
