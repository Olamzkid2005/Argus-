"""Verify repo-only tool phase assignments at runtime."""
import sys
sys.path.insert(0, ".")

from tool_definitions import TOOLS

REPO_TOOLS = [
    "semgrep", "bandit", "gitleaks", "trufflehog", "trivy",
    "npm-audit", "pip-audit", "pip_audit", "gosec", "brakeman",
    "eslint", "phpcs", "spotbugs", "govulncheck", "dependency_check",
]

print("=== Repo-Only Tool Phase Assignments (Runtime) ===")
all_ok = True
for name in REPO_TOOLS:
    t = TOOLS.get(name)
    if t:
        ok = set(t.phases) == {"repo_scan"}
        if not ok:
            all_ok = False
        status = "OK" if ok else "FAIL"
        print(f"  {status} {name}: {t.phases}")
    else:
        print(f"  FAIL {name}: NOT FOUND")
        all_ok = False

print(f"\nAll 15 correct: {all_ok}")

print("\n=== Verifying no repo tools in web phases ===")
for phase in ["scan", "deep_scan"]:
    bad = [n for n, t in TOOLS.items() if phase in t.phases and n in REPO_TOOLS]
    print(f"  {phase}: {bad if bad else '(none)'}")
