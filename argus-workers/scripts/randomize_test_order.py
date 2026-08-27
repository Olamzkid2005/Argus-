#!/usr/bin/env python3
"""Run the Python test suite with randomized file collection order.

Collection-order fragility occurs when test file A leaves side effects
in sys.modules, the database, or global state that break test file B —
but only when A is collected *before* B.  This script shuffles the test
file list so that each run exercises a different collection order, making
these latent coupling bugs surface reliably.

Usage:
    python scripts/randomize_test_order.py [--iterations N] [--seed SEED] [-- ...]

Examples:
    # Default: 3 iterations, random seed each time
    python scripts/randomize_test_order.py

    # 5 iterations with a fixed seed (reproducible)
    python scripts/randomize_test_order.py --iterations 5 --seed 42

    # Pass extra pytest args (everything after the script's own flags goes to pytest)
    python scripts/randomize_test_order.py --iterations 3 -- -m "not requires_db" -q --timeout=120
"""

from __future__ import annotations

import argparse
import glob
import os
import random
import subprocess
import sys
from pathlib import Path


def collect_test_files(test_dir: str) -> list[str]:
    """Collect all test_*.py files under test_dir, respecting pytest.ini testpaths."""
    pattern = os.path.join(test_dir, "test_*.py")
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"No test files found matching {pattern}", file=sys.stderr)
        sys.exit(1)
    return files


def run_once(
    files: list[str],
    seed: int,
    iteration: int,
    total: int,
    extra_args: list[str],
    pytest_bin: list[str],
) -> int:
    """Run pytest once with a specific file order and return the exit code."""
    header = f"═══ Randomized order run {iteration + 1}/{total}  (seed={seed}) ═══"
    print(f"\n{'═' * len(header)}")
    print(header)
    print(f"{'═' * len(header)}")
    print(f"File order: {[os.path.basename(f) for f in files]}")

    cmd = [*pytest_bin, *files, *extra_args]
    result = subprocess.run(cmd, cwd=str(Path(__file__).resolve().parent.parent))
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run pytest with randomized file collection order.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Number of randomized runs (default: 3)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility (default: random)",
    )
    parser.add_argument(
        "--test-dir",
        default="tests",
        help="Directory containing test files (default: tests)",
    )
    parser.add_argument(
        "--pytest-bin",
        default=None,
        help="Path to pytest binary (default: auto-detect venv or system)",
    )
    args, extra = parser.parse_known_args()
    # Everything argparse didn't recognize goes to extra.
    # Strip a leading '--' that the shell uses to separate script args from extras.
    if extra and extra[0] == "--":
        extra = extra[1:]
    args.extra_args = extra

    # Find pytest — always a list so subprocess.run doesn't treat
    # 'python -m pytest' as a single executable path.
    if args.pytest_bin:
        pytest_bin: list[str] = args.pytest_bin.split()
    elif os.path.exists("venv/bin/pytest"):
        pytest_bin = [os.path.abspath("venv/bin/pytest")]
    else:
        pytest_bin = [sys.executable, "-m", "pytest"]

    files = collect_test_files(args.test_dir)
    print(f"Found {len(files)} test files in {args.test_dir}/")

    master_seed = args.seed if args.seed is not None else random.randint(0, 2**32 - 1)
    print(f"Master seed: {master_seed}")

    failures = 0
    results: list[tuple[int, int, int]] = []  # (iteration, seed, exit_code)

    for i in range(args.iterations):
        run_seed = master_seed + i
        rng = random.Random(run_seed)
        shuffled = list(files)
        rng.shuffle(shuffled)

        exit_code = run_once(
            files=shuffled,
            seed=run_seed,
            iteration=i,
            total=args.iterations,
            extra_args=args.extra_args,
            pytest_bin=pytest_bin,
        )
        results.append((i, run_seed, exit_code))
        if exit_code != 0:
            failures += 1

    # Summary
    print(f"\n{'═' * 60}")
    print("SUMMARY")
    print(f"{'═' * 60}")
    for iteration, seed, exit_code in results:
        status = "✅ PASS" if exit_code == 0 else "❌ FAIL"
        print(f"  Run {iteration + 1} (seed={seed}): {status} (exit {exit_code})")
    print(f"{'─' * 60}")
    print(f"  {args.iterations - failures}/{args.iterations} passed, {failures} failed")
    if failures:
        print(f"\n  FAILURE: {failures} run(s) had collection-order-dependent failures.")
        print("  This means some test files leave side effects that break other files.")
    else:
        print(f"\n  ALL CLEAR: No collection-order fragility detected across {args.iterations} runs.")
    print(f"{'═' * 60}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
