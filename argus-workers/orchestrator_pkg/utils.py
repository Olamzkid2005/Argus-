"""
Orchestrator utility functions.
"""
import os
from pathlib import Path


def get_wordlist_path(filename: str) -> Path:
    """Return the full path to a wordlist file.

    Checks the ARGUS_WORDLIST_DIR environment variable first,
    then falls back to the wordlists directory next to this module.
    Raises FileNotFoundError if the directory or file does not exist.
    """
    wordlist_dir = os.environ.get("ARGUS_WORDLIST_DIR")
    if wordlist_dir:
        base = Path(wordlist_dir)
    else:
        # Look relative to the original orchestrator.py location (parent of orchestrator_pkg)
        base = Path(__file__).resolve().parent.parent / "wordlists"

    if not base.exists():
        raise FileNotFoundError(f"Wordlists directory not found: {base}")

    word_path = base / filename
    if not word_path.exists():
        raise FileNotFoundError(f"Wordlist not found: {word_path}")

    return word_path


def get_nuclei_templates_path() -> Path:
    """Return the path to pre-downloaded nuclei templates."""
    # Check environment variable first, then default location
    custom_path = os.environ.get("ARGUS_NUCLEI_TEMPLATES")
    if custom_path:
        base = Path(custom_path)
    else:
        base = Path(__file__).resolve().parent.parent / "tool_assets" / "nuclei-templates"

    if base.exists() and any(base.rglob("*.yaml")):
        return base

    # Fall back to ~/.nuclei-templates
    home_path = Path.home() / ".nuclei-templates"
    if home_path.exists() and any(home_path.rglob("*.yaml")):
        return home_path

    return base  # May not exist - caller should check


def tool_timeout(base: int, aggressiveness: str = "default") -> int:
    """Compute tool timeout based on aggressiveness level.

    Args:
        base: Base timeout in seconds for the tool
        aggressiveness: Aggressiveness level (default, high, extreme)

    Returns:
        Timeout in seconds scaled by aggressiveness
    """
    multiplier = {"default": 1.0, "high": 1.5, "extreme": 3.0}
    return int(base * multiplier.get(aggressiveness, 1.0))
