"""
Container Security Scanning Module

Integrates Trivy for container vulnerability scanning, Dockerfile analysis,
Kubernetes configuration security checks, and SBOM generation.

Requirements: 16.1, 16.2, 16.3, 16.4
"""
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class ContainerSecurityScanner:
    """
    Container security scanner for Docker images, Dockerfiles,
    Kubernetes manifests, and SBOM generation.
    """

    # Dockerfile security checks
    DOCKERFILE_CHECKS = [
        {
            "id": "DOCKERFILE_LATEST_TAG",
            "pattern": r'^\s*FROM\s+[^:]*\s*(?:#.*)?$|^\s*FROM\s+[^:]*:latest',
            "message": "Using 'latest' tag or untagged base image",
            "severity": "MEDIUM",
        },
        {
            "id": "DOCKERFILE_ROOT_USER",
            "pattern": r'^\s*USER\s+root\s*(?:#.*)?$',
            "message": "Container running as root user",
            "severity": "HIGH",
        },
        {
            "id": "DOCKERFILE_NO_HEALTHCHECK",
            "pattern": None,  # Checked via absence
            "message": "No HEALTHCHECK instruction defined",
            "severity": "LOW",
        },
        {
            "id": "DOCKERFILE_SECRETS_IN_ENV",
            "pattern": r'^\s*ENV\s+.*(?:PASSWORD|SECRET|KEY|TOKEN|API_KEY)\s*=\s*[^\s]+',
            "message": "Potential secret hardcoded in ENV instruction",
            "severity": "CRITICAL",
        },
        {
            "id": "DOCKERFILE_SUDO_USAGE",
            "pattern": r'^\s*RUN\s+.*\bsudo\b',
            "message": "Using sudo inside container",
            "severity": "MEDIUM",
        },
        {
            "id": "DOCKERFILE_ADD_INSTEAD_OF_COPY",
            "pattern": r'^\s*ADD\s+',
            "message": "Using ADD instead of COPY for local files",
            "severity": "LOW",
        },
    ]

    # Kubernetes security checks
    K8S_CHECKS = [
        {
            "id": "K8S_PRIVILEGED_CONTAINER",
            "path": ["spec", "containers", "*", "securityContext", "privileged"],
            "value": True,
            "message": "Privileged container detected",
            "severity": "CRITICAL",
        },
        {
            "id": "K8S_RUN_AS_ROOT",
            "path": ["spec", "containers", "*", "securityContext", "runAsUser"],
            "value": 0,
            "message": "Container configured to run as root (UID 0)",
            "severity": "HIGH",
        },
        {
            "id": "K8S_MISSING_SECURITY_CONTEXT",
            "path": ["spec", "containers", "*", "securityContext"],
            "exists": False,
            "message": "Container missing security context",
            "severity": "MEDIUM",
        },
        {
            "id": "K8S_HOST_NETWORK",
            "path": ["spec", "hostNetwork"],
            "value": True,
            "message": "Pod using host network namespace",
            "severity": "HIGH",
        },
        {
            "id": "K8S_HOST_PID",
            "path": ["spec", "hostPID"],
            "value": True,
            "message": "Pod sharing host PID namespace",
            "severity": "HIGH",
        },
        {
            "id": "K8S_WRITABLE_FS",
            "path": ["spec", "containers", "*", "securityContext", "readOnlyRootFilesystem"],
            "value": False,
            "message": "Container has writable root filesystem",
            "severity": "MEDIUM",
        },
        {
            "id": "K8S_ALLOW_PRIVILEGE_ESCALATION",
            "path": ["spec", "containers", "*", "securityContext", "allowPrivilegeEscalation"],
            "value": True,
            "message": "Privilege escalation allowed",
            "severity": "HIGH",
        },
    ]

    def __init__(self):
        """Initialize container security scanner."""
        self.findings = []

    def scan_dockerfile(self, dockerfile_path: str) -> list[dict]:
        """
        Analyze Dockerfile for security misconfigurations.

        Args:
            dockerfile_path: Path to Dockerfile

        Returns:
            List of findings
        """
        self.findings = []
        path = Path(dockerfile_path)

        if not path.exists():
            return self.findings

        content = path.read_text()
        lines = content.split("\n")

        has_healthcheck = False

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()

            if stripped.upper().startswith("HEALTHCHECK"):
                has_healthcheck = True

            for check in self.DOCKERFILE_CHECKS:
                if check["pattern"] is None:
                    continue
                if re.search(check["pattern"], stripped, re.IGNORECASE):
                    self.findings.append({
                        "type": check["id"],
                        "severity": check["severity"],
                        "endpoint": str(path),
                        "evidence": {
                            "line": line_num,
                            "content": stripped,
                            "message": check["message"],
                        },
                        "confidence": 0.90,
                        "tool": "container_scanner",
                    })

        # Check for missing HEALTHCHECK
        if not has_healthcheck:
            check = next((c for c in self.DOCKERFILE_CHECKS if c["id"] == "DOCKERFILE_NO_HEALTHCHECK"), None)
            if check:
                self.findings.append({
                    "type": check["id"],
                    "severity": check["severity"],
                    "endpoint": str(path),
                    "evidence": {
                        "message": check["message"],
                    },
                    "confidence": 0.80,
                    "tool": "container_scanner",
                })

        return self.findings

    def scan_kubernetes_manifest(self, manifest_path: str) -> list[dict]:
        """
        Analyze Kubernetes manifest for security misconfigurations.

        Args:
            manifest_path: Path to K8s YAML manifest

        Returns:
            List of findings
        """
        self.findings = []
        path = Path(manifest_path)

        if not path.exists():
            return self.findings

        try:
            import yaml
            docs = list(yaml.safe_load_all(path.read_text()))
        except Exception:
            return self.findings

        for doc in docs:
            if not doc or not isinstance(doc, dict):
                continue

            kind = doc.get("kind", "")
            if kind not in ["Pod", "Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "CronJob"]:
                continue

            for check in self.K8S_CHECKS:
                result = self._check_k8s_path(doc, check["path"], check.get("value"), check.get("exists", True))
                if result["matched"]:
                    self.findings.append({
                        "type": check["id"],
                        "severity": check["severity"],
                        "endpoint": f"{kind}/{doc.get('metadata', {}).get('name', 'unknown')}",
                        "evidence": {
                            "manifest": str(path),
                            "message": check["message"],
                            "matched_value": result.get("value"),
                        },
                        "confidence": 0.90,
                        "tool": "container_scanner",
                    })

        return self.findings

    def _check_k8s_path(self, doc: dict, path: list[str], expected_value=None, should_exist=True) -> dict:
        """Check if a path exists in K8s document and matches expected value."""
        current = doc

        for i, key in enumerate(path):
            if key == "*":
                # Handle wildcard for lists
                if isinstance(current, list):
                    for item in current:
                        sub_path = path[i + 1:]
                        result = self._check_k8s_path(item, sub_path, expected_value, should_exist)
                        if result["matched"]:
                            return result
                    return {"matched": False}
                return {"matched": False}

            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return {"matched": not should_exist}

        if expected_value is not None:
            return {"matched": current == expected_value, "value": current}

        return {"matched": should_exist, "value": current}

    def generate_sbom(self, image_or_path: str, output_path: str | None = None) -> dict:
        """
        Generate Software Bill of Materials (SBOM) for a container image or filesystem.

        Args:
            image_or_path: Container image name or filesystem path
            output_path: Optional path to write SBOM JSON

        Returns:
            SBOM dictionary
        """
        sbom = {
            "specVersion": "1.4",
            "tool": "argus-container-scanner",
            "components": [],
            "dependencies": [],
        }

        # Try to detect package files and extract dependencies
        path = Path(image_or_path)
        if path.is_dir():
            # Scan for package files
            package_files = {
                "package.json": self._parse_npm_packages,
                "requirements.txt": self._parse_pip_packages,
                "Pipfile": self._parse_pipfile_packages,
                "go.mod": self._parse_go_packages,
                "Cargo.toml": self._parse_rust_packages,
            }

            for filename, parser in package_files.items():
                file_path = path / filename
                if file_path.exists():
                    components = parser(file_path)
                    sbom["components"].extend(components)

        if output_path:
            Path(output_path).write_text(json.dumps(sbom, indent=2))

        return sbom

    def _parse_npm_packages(self, package_json_path: Path) -> list[dict]:
        """Parse npm package.json for dependencies."""
        components = []
        try:
            data = json.loads(package_json_path.read_text())
            deps = {}
            deps.update(data.get("dependencies", {}))
            deps.update(data.get("devDependencies", {}))

            for name, version in deps.items():
                components.append({
                    "type": "library",
                    "name": name,
                    "version": version,
                    "purl": f"pkg:npm/{name}@{version}",
                })
        except Exception as e:
            logger.warning("Failed to parse npm packages from %s: %s", package_json_path, e)
        return components

    def _parse_pip_packages(self, requirements_path: Path) -> list[dict]:
        """Parse requirements.txt for Python packages."""
        components = []
        try:
            for line in requirements_path.read_text().split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Simple parsing: package==version
                if "==" in line:
                    name, version = line.split("==", 1)
                    components.append({
                        "type": "library",
                        "name": name.strip(),
                        "version": version.strip(),
                        "purl": f"pkg:pypi/{name.strip()}@{version.strip()}",
                    })
        except Exception as e:
            logger.warning("Failed to parse pip packages from %s: %s", requirements_path, e)
        return components

    def _parse_pipfile_packages(self, pipfile_path: Path) -> list[dict]:
        """Parse Pipfile for Python packages."""
        components = []
        try:
            import toml
            data = toml.loads(pipfile_path.read_text())
            for section in ["packages", "dev-packages"]:
                for name, spec in data.get(section, {}).items():
                    version = spec if isinstance(spec, str) else spec.get("version", "*")
                    components.append({
                        "type": "library",
                        "name": name,
                        "version": version,
                        "purl": f"pkg:pypi/{name}@{version}",
                    })
        except Exception as e:
            logger.warning("Failed to parse Pipfile packages from %s: %s", pipfile_path, e)
        return components

    def _parse_go_packages(self, go_mod_path: Path) -> list[dict]:
        """Parse go.mod for Go packages."""
        components = []
        try:
            content = go_mod_path.read_text()
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("require "):
                    parts = line.replace("require ", "").strip().split()
                    if len(parts) >= 2:
                        components.append({
                            "type": "library",
                            "name": parts[0],
                            "version": parts[1],
                            "purl": f"pkg:golang/{parts[0]}@{parts[1]}",
                        })
        except Exception as e:
            logger.warning("Failed to parse Go modules from %s: %s", go_mod_path, e)
        return components

    def _parse_rust_packages(self, cargo_toml_path: Path) -> list[dict]:
        """Parse Cargo.toml for Rust packages."""
        components = []
        try:
            import toml
            data = toml.loads(cargo_toml_path.read_text())
            for name, spec in data.get("dependencies", {}).items():
                version = spec if isinstance(spec, str) else spec.get("version", "*")
                components.append({
                    "type": "library",
                    "name": name,
                    "version": version,
                    "purl": f"pkg:cargo/{name}@{version}",
                })
        except Exception as e:
            logger.warning("Failed to parse Cargo packages from %s: %s", cargo_toml_path, e)
        return components

    def run_trivy_scan(self, image_or_path: str, tool_runner) -> list[dict]:
        """
        Run Trivy container/filesystem scan using the provided tool runner.

        Args:
            image_or_path: Container image or path to scan
            tool_runner: ToolRunner instance

        Returns:
            List of parsed findings
        """
        findings = []

        result = tool_runner.run(
            "trivy",
            [
                "fs", "--scanners", "vuln,misconfig,secret",
                "--skip-dirs", "node_modules,vendor,dist,build,.git,coverage",
                "--format", "json", image_or_path,
            ],
            timeout=600,
        )

        if result.get("success"):
            try:
                from parsers.parser import TrivyParser
                parser = TrivyParser()
                findings = parser.parse(result.get("stdout", ""))
            except Exception as e:
                logger.warning("Failed to parse Trivy scan results: %s", e)

        return findings
