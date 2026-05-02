"""
Run once at worker startup (before Celery starts accepting jobs).
Downloads all tool assets that cannot be fetched inside the sandbox.
"""
import os
import subprocess
import sys
from pathlib import Path


def get_assets_dir():
    """Canonical host-side asset directory — outside sandbox, readable by all workers."""
    # Go up from argus-workers/scripts/ to argus-workers/ root, then to tool_assets
    workers_root = Path(__file__).parent.parent
    return workers_root / "tool_assets"


def bootstrap_nuclei_templates():
    """Download nuclei-templates if not already present."""
    assets_dir = get_assets_dir()
    nuclei_templates = assets_dir / "nuclei-templates"

    assets_dir.mkdir(exist_ok=True)

    # Check if already present
    if nuclei_templates.exists() and any(nuclei_templates.rglob("*.yaml")):
        count = len(list(nuclei_templates.rglob("*.yaml")))
        print(f"[bootstrap] nuclei-templates already present ({count} templates). Skipping.")
        return True

    print("[bootstrap] Downloading nuclei-templates from GitHub...")

    # Try git clone with shallow depth
    try:
        result = subprocess.run(
            [
                "git", "clone",
                "--depth", "1",
                "--filter=blob:none",
                "https://github.com/projectdiscovery/nuclei-templates.git",
                str(nuclei_templates),
            ],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        if result.returncode == 0:
            count = len(list(nuclei_templates.rglob("*.yaml")))
            print(f"[bootstrap] Downloaded {count} templates to {nuclei_templates}")
            return True
        else:
            print(f"[bootstrap] Git clone failed: {result.stderr[:300]}")

    except subprocess.TimeoutExpired:
        print("[bootstrap] Git clone timed out after 5 minutes")
    except Exception as e:
        print(f"[bootstrap] Git clone error: {e}")

    # Fallback: try nuclei's own updater
    print("[bootstrap] Trying fallback: nuclei -update-templates...")
    try:
        # Run with HOME pointing to assets dir so templates land there
        env = os.environ.copy()
        env["HOME"] = str(assets_dir)

        result = subprocess.run(
            ["nuclei", "-update-templates"],
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )

        # Check if it worked - templates should be in ~/.nuclei-templates
        default_path = Path(assets_dir) / ".nuclei-templates"
        if default_path.exists():
            # Move to expected location
            import shutil
            if nuclei_templates.exists():
                shutil.rmtree(nuclei_templates)
            shutil.move(str(default_path), str(nuclei_templates))
            count = len(list(nuclei_templates.rglob("*.yaml")))
            print(f"[bootstrap] nuclei -update-templates succeeded: {count} templates")
            return True

    except subprocess.TimeoutExpired:
        print("[bootstrap] nuclei -update-templates timed out")
    except Exception as e:
        print(f"[bootstrap] Fallback error: {e}")

    print("[bootstrap] WARNING: Nuclei templates not available. Web scans will be limited.")
    return False


def main():
    print("[bootstrap] Starting tool bootstrap...")
    print(f"[bootstrap] Assets directory: {get_assets_dir()}")

    # Bootstrap nuclei templates
    ok = bootstrap_nuclei_templates()

    if ok:
        print("[bootstrap] Bootstrap complete.")
        return 0
    else:
        print("[bootstrap] Bootstrap incomplete - some tools may not work.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
