"""
Tests for Container Security Scanner
"""
import pytest
import json
from unittest.mock import Mock, patch
from tools.container_scanner import ContainerSecurityScanner


class TestContainerSecurityScanner:
    """Test ContainerSecurityScanner"""

    @pytest.fixture
    def scanner(self):
        return ContainerSecurityScanner()

    def test_scan_dockerfile_latest_tag(self, scanner):
        dockerfile = "FROM ubuntu:latest\nRUN apt-get update"
        findings = scanner.scan_dockerfile(dockerfile)
        latest_findings = [f for f in findings if f["type"] == "CONTAINER_LATEST_TAG"]
        assert len(latest_findings) == 1
        assert latest_findings[0]["severity"] == "MEDIUM"

    def test_scan_dockerfile_root_user(self, scanner):
        dockerfile = "FROM ubuntu:22.04\nUSER root"
        findings = scanner.scan_dockerfile(dockerfile)
        root_findings = [f for f in findings if f["type"] == "CONTAINER_ROOT_USER"]
        assert len(root_findings) == 1
        assert root_findings[0]["severity"] == "MEDIUM"

    def test_scan_dockerfile_no_healthcheck(self, scanner):
        dockerfile = "FROM ubuntu:22.04\nCMD ['echo', 'hi']"
        findings = scanner.scan_dockerfile(dockerfile)
        health_findings = [f for f in findings if f["type"] == "CONTAINER_MISSING_HEALTHCHECK"]
        assert len(health_findings) == 1

    def test_scan_dockerfile_secrets_in_env(self, scanner):
        dockerfile = "FROM ubuntu:22.04\nENV API_KEY=sk-1234567890abcdef"
        findings = scanner.scan_dockerfile(dockerfile)
        secret_findings = [f for f in findings if f["type"] == "CONTAINER_SECRET_IN_ENV"]
        assert len(secret_findings) == 1
        assert secret_findings[0]["severity"] == "HIGH"

    def test_scan_kubernetes_privileged(self, scanner):
        manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "spec": {
                "containers": [{"name": "app", "image": "nginx", "securityContext": {"privileged": True}}]
            }
        }
        findings = scanner.scan_kubernetes_manifest(manifest)
        priv_findings = [f for f in findings if f["type"] == "K8S_PRIVILEGED_CONTAINER"]
        assert len(priv_findings) == 1
        assert priv_findings[0]["severity"] == "CRITICAL"

    def test_scan_kubernetes_host_network(self, scanner):
        manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "spec": {"hostNetwork": True, "containers": [{"name": "app", "image": "nginx"}]}
        }
        findings = scanner.scan_kubernetes_manifest(manifest)
        host_findings = [f for f in findings if f["type"] == "K8S_HOST_NETWORK"]
        assert len(host_findings) == 1

    def test_generate_sbom_package_json(self, scanner):
        package_json = json.dumps({
            "name": "test-app",
            "dependencies": {"express": "^4.18.0", "lodash": "^4.17.21"}
        })
        sbom = scanner.generate_sbom("package.json", package_json)
        assert sbom["format"] == "CycloneDX"
        assert sbom["spec_version"] == "1.4"
        assert len(sbom["components"]) == 2
        assert sbom["components"][0]["name"] == "express"

    def test_generate_sbom_requirements_txt(self, scanner):
        requirements = "requests==2.28.1\nflask>=2.0.0\n"
        sbom = scanner.generate_sbom("requirements.txt", requirements)
        assert len(sbom["components"]) == 2
        assert sbom["components"][0]["name"] == "requests"

    def test_generate_sbom_unsupported(self, scanner):
        sbom = scanner.generate_sbom("random.txt", "content")
        assert sbom["components"] == []

    def test_run_trivy_scan(self, scanner):
        mock_result = {
            "stdout": json.dumps({"Results": []}),
            "stderr": "",
            "returncode": 0,
            "success": True
        }
        with patch("tools.tool_runner.ToolRunner.run", return_value=mock_result):
            findings = scanner.run_trivy_scan("nginx:latest")
            assert isinstance(findings, list)
