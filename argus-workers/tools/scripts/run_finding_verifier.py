#!/usr/bin/env python3
"""
CLI wrapper for the async finding_verifier module.

Called by the MCP server when the `finding_verifier` tool is invoked.
Routes the request to the appropriate async verifier function and
outputs structured JSON results for downstream consumption.

Usage:
    python3 tools/scripts/run_finding_verifier.py \\
        --target https://example.com \\
        --finding-type xss \\
        --payload '<script>alert(1)</script>' \\
        --endpoint https://example.com/search \\
        --engagement-id eng-001
"""

import argparse
import asyncio
import json
import os
import sys
import time

# Ensure the parent directory is on the path so tools/ can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


async def _run_verification(
    finding_type: str,
    target: str,
    endpoint: str,
    payload: str,
    engagement_id: str,
) -> dict:
    """Run the appropriate finding verifier and return structured results."""
    from tools.finding_verifier import verify_open_redirect, verify_sqli, verify_xss

    start = time.time()

    if finding_type in ("sqli", "sql-injection", "sql_injection"):
        result = await verify_sqli(endpoint, payload, engagement_id=engagement_id)
    elif finding_type in ("xss", "cross-site-scripting"):
        result = await verify_xss(endpoint, payload, engagement_id=engagement_id)
    elif finding_type in ("open_redirect", "open-redirect"):
        result = await verify_open_redirect(endpoint, engagement_id=engagement_id)
    else:
        result = {
            "verified": None,
            "confidence": "unknown",
            "reason": f"No verifier for finding type: {finding_type}",
        }

    duration_ms = int((time.time() - start) * 1000)
    result["duration_ms"] = duration_ms
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run finding verification")
    parser.add_argument("--target", required=True, help="Target URL")
    parser.add_argument("--finding-type", required=True, help="Finding type (sqli, xss, open_redirect)")
    parser.add_argument("--payload", default="", help="Payload from original finding")
    parser.add_argument("--endpoint", default="", help="Specific endpoint URL")
    parser.add_argument("--engagement-id", default="", help="Engagement ID")
    args = parser.parse_args()

    # Normalize endpoint: if not provided, use target
    endpoint = args.endpoint or args.target

    result = asyncio.run(
        _run_verification(
            finding_type=args.finding_type,
            target=args.target,
            endpoint=endpoint,
            payload=args.payload,
            engagement_id=args.engagement_id,
        )
    )

    output = {
        "success": bool(result.get("verified")),
        "data": result,
        "verified": result.get("verified", False),
        "confidence": result.get("confidence", "low"),
        "reason": result.get("reason", ""),
        "duration_ms": result.get("duration_ms", 0),
    }
    print(json.dumps(output))
    sys.exit(0 if output["success"] else 1)


if __name__ == "__main__":
    main()
