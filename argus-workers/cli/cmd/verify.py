"""Verify command for the Argus CLI."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import cli._local_mode as local_mode

logger = logging.getLogger("cli.cmd")


def cmd_verify(args: argparse.Namespace) -> int:
    """Re-verify engagement findings and produce a remediation diff.

    Loads all findings for an engagement, re-runs the finding verifier
    on each verifiable finding (SQLi, XSS, open redirect), compares
    results with original findings, and produces a structured diff
    showing which findings are still present, which are fixed, and
    which are new.

    Usage:
        argus verify <engagement_id>
        argus verify <engagement_id> --output verify-report.json
        argus verify <engagement_id> --local
        argus verify <engagement_id> --db assessments.db
    """
    import copy

    from database.sqlite_backend import SQLiteEngagementRepo, SQLiteFindingRepo

    db_path = local_mode._apply_local_mode(getattr(args, "local", False), getattr(args, "db", None))
    engagement_id = args.engagement_id
    output_path = getattr(args, "output", None)

    try:
        # Load engagement and findings
        eng_repo = SQLiteEngagementRepo(db_path)
        finding_repo = SQLiteFindingRepo(db_path)

        eng = eng_repo.find_by_id(engagement_id)
        if eng is None:
            logger.error("Engagement %s not found", engagement_id[:8])
            print(f"Error: Engagement {engagement_id[:8]} not found.")
            eng_repo.close()
            finding_repo.close()
            return 1

        findings, total = finding_repo.get_findings_by_engagement(
            engagement_id, limit=1000
        )

        if not findings:
            logger.info("No findings found for engagement %s", engagement_id[:8])
            print(f"Engagement {engagement_id[:8]} has no findings to verify.")
            eng_repo.close()
            finding_repo.close()
            return 0

        # Verifiable finding types (ones with registered verifiers)
        verifiable_types = _VERIFIABLE_FINDING_TYPES

        # Snapshot original state
        original_map: dict[str, dict] = {}
        for f in findings:
            ftype = (f.get("type") or "").lower().replace("-", "_").replace(" ", "_")
            if ftype in verifiable_types:
                key = (f.get("endpoint", ""), ftype)
                original_map[key] = copy.deepcopy(f)

        if not original_map:
            logger.info(
                "No verifiable findings (SQLi/XSS/OpenRedirect) for engagement %s",
                engagement_id[:8],
            )
            print(f"No verifiable findings found for engagement {engagement_id[:8]}.")
            eng_repo.close()
            finding_repo.close()
            return 0

        logger.info(
            "Re-verifying %d finding(s) for engagement %s...",
            len(original_map),
            engagement_id[:8],
        )

        # ── Re-run verification ──
        import asyncio

        findings_list = list(original_map.values())

        async def _run_verifications() -> list[dict]:
            from tools.finding_verifier import verify_finding as _vf

            results = await asyncio.gather(
                *(_vf(dict(f), engagement_id=engagement_id) for f in findings_list),
                return_exceptions=True,
            )
            return results

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            import threading
            results_container: list = []
            done_event = threading.Event()

            def _run_in_thread():
                inner = asyncio.new_event_loop()
                try:
                    res = inner.run_until_complete(_run_verifications())
                    results_container.extend(res if isinstance(res, list) else [res])
                finally:
                    inner.close()
                    done_event.set()

            thread = threading.Thread(target=_run_in_thread, daemon=True)
            thread.start()
            thread.join(timeout=120)
            results = results_container
        else:
            results = asyncio.run(_run_verifications())

        # ── Compute diff ──
        still_present: list[dict] = []
        fixed: list[dict] = []
        verification_errors: list[dict] = []
        unchanged: list[dict] = []

        for i, result in enumerate(results):
            if i >= len(findings_list):
                break
            original = findings_list[i]

            if isinstance(result, Exception):
                verification_errors.append({
                    "finding": original,
                    "error": str(result),
                })
                unchanged.append(original)
                continue

            verification = result.get("verification", {})
            verified = verification.get("verified", False)
            reason = verification.get("reason", "")
            verifier_confidence = verification.get("confidence", "low")

            entry = {
                "endpoint": original.get("endpoint", ""),
                "type": original.get("type", ""),
                "original_severity": original.get("severity", "INFO"),
                "original_confidence": original.get("confidence", 0),
                "verifier_confidence": verifier_confidence,
                "verified": verified,
                "reason": reason,
                "original_status": original.get("status", "UNKNOWN"),
            }

            if verified:
                entry["status"] = "STILL_PRESENT"
                still_present.append(entry)
            elif verifier_confidence == "low" and not verified:
                # If verifier couldn't reproduce (likely fixed or changed)
                entry["status"] = "NOT_REPRODUCED"
                fixed.append(entry)
            else:
                entry["status"] = "VERIFICATION_INCONCLUSIVE"
                unchanged.append(entry)

        # ── Update findings in SQLite with verification evidence ──
        for entry in still_present:
            original = original_map.get((entry["endpoint"], entry["type"].lower().replace("-", "_").replace(" ", "_")), {})
            if original:
                try:
                    from tools.verification.finding_promoter import promote_finding
                    promoted = promote_finding(
                        original,
                        confidence=0.85,  # verified → high confidence
                        reproduced=True,
                    )
                    finding_repo.create_finding(
                        engagement_id=engagement_id,
                        finding_type=original.get("type", ""),
                        severity=original.get("severity", "INFO"),
                        endpoint=original.get("endpoint", ""),
                        evidence={
                            **(original.get("evidence") or {}),
                            "remediation_verification": {
                                "verified": True,
                                "status": "STILL_PRESENT",
                                "reason": entry["reason"],
                                "timestamp": __import__("time").time(),
                            },
                        },
                        confidence=0.85,
                        source_tool=original.get("source_tool", "verification"),
                    )
                except Exception as e:
                    logger.debug("Failed to update finding: %s", e)

        for entry in fixed:
            original = original_map.get((entry["endpoint"], entry["type"].lower().replace("-", "_").replace(" ", "_")), {})
            if original:
                try:
                    finding_repo.create_finding(
                        engagement_id=engagement_id,
                        finding_type=original.get("type", ""),
                        severity=original.get("severity", "INFO"),
                        endpoint=original.get("endpoint", ""),
                        evidence={
                            **(original.get("evidence") or {}),
                            "remediation_verification": {
                                "verified": False,
                                "status": "FIXED",
                                "reason": entry["reason"],
                                "timestamp": __import__("time").time(),
                            },
                        },
                        confidence=0.15,  # very low confidence → likely fixed
                        source_tool=original.get("source_tool", "verification"),
                    )
                except Exception as e:
                    logger.debug("Failed to update finding: %s", e)

        # ── Build and output diff report ──
        diff_report = {
            "engagement_id": engagement_id,
            "target": eng.get("target_url", ""),
            "timestamp": __import__("time").time(),
            "summary": {
                "total_original": len(original_map),
                "still_present": len(still_present),
                "fixed": len(fixed),
                "verification_errors": len(verification_errors),
                "unchanged": len(unchanged),
            },
            "still_present": still_present,
            "fixed": fixed,
            "verification_errors": verification_errors,
        }

        # Print summary
        print("\n  Remediation Verification Report")
        print(f"  {'=' * 54}")
        print(f"  Engagement:  {engagement_id[:8]}")
        print(f"  Target:      {eng.get('target_url', '')}")
        print(f"  Findings:    {len(original_map)} verifiable, "
              f"{diff_report['summary']['still_present']} still present, "
              f"{diff_report['summary']['fixed']} fixed")
        print()

        if still_present:
            print(f"  {'Still Present':^54}")
            print(f"  {'-' * 54}")
            for f in still_present:
                print(f"    [{f['original_severity']}] {f['type']} @ {f['endpoint'][:50]}")
            print()

        if fixed:
            print(f"  {'Fixed / Not Reproduced':^54}")
            print(f"  {'-' * 54}")
            for f in fixed:
                print(f"    [{f['original_severity']}] {f['type']} @ {f['endpoint'][:50]}")
            print()

        if verification_errors:
            print(f"  {'Verification Errors':^54}")
            print(f"  {'-' * 54}")
            for f in verification_errors:
                print(f"    {f['finding'].get('type', '?')} @ {f['finding'].get('endpoint', '?')[:40]}: {f['error'][:40]}")
            print()

        # Save to file if requested
        if output_path:
            import json as _json
            with open(output_path, "w") as f:
                _json.dump(diff_report, f, indent=2, default=str)
            logger.info("Verification report written to %s", output_path)
        else:
            import json as _json
            print(_json.dumps(diff_report, indent=2, default=str))

        eng_repo.close()
        finding_repo.close()
        logger.info(
            "Verification complete: %d still present, %d fixed",
            len(still_present),
            len(fixed),
        )
        return 0

    except Exception as e:
        logger.error("Verification failed: %s", e)
        print(f"Error: Verification failed: {e}")
        return 1


