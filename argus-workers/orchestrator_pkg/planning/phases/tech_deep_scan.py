"""Phase: tech_deep_scan — _activate_tech_deep_scan and _tech_deep_scan_tools."""

from __future__ import annotations

import logging

from ._types import ToolTask, _get_tech_stack

logger = logging.getLogger(__name__)




# ── Phase: Tech Deep Scan ──────────────────────────────────────────────


def _activate_tech_deep_scan(rc) -> tuple[bool, str]:
    """Activate when a specific tech stack is detected.

    Triggers deeper scanning for known CMS, frameworks, and servers.
    """
    tech = _get_tech_stack(rc)
    if not tech:
        return False, "no tech_stack detected"
    # Only activate for tech stacks with dedicated scanning tools
    recognized = {"wordpress", "drupal", "joomla", "apache", "nginx", "iis",
                  "php", "python", "node.js", "react", "vue", "angular",
                  "django", "flask", "express", "spring", "rails"}
    matched = [t for t in tech if t.lower() in recognized]
    if not matched:
        return False, f"no recognized technologies in stack: {tech[:5]}"
    return True, f"detected: {', '.join(matched[:5])}"


def _tech_deep_scan_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks based on the specific tech stack detected."""
    tools: list[ToolTask] = []
    tech = _get_tech_stack(recon_context)
    tech_lower = [t.lower() for t in tech]

    # WordPress
    if any("wordpress" in t for t in tech_lower):
        tools.append(ToolTask(
            tool_name="nuclei",
            description="WordPress-specific vulnerability scanning",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "wordpress"],
        ))

    # Apache
    if any("apache" in t for t in tech_lower):
        tools.append(ToolTask(
            tool_name="nuclei",
            description="Apache-specific vulnerability scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "apache"],
        ))
        if any("tomcat" in t for t in tech_lower):
            tools.append(ToolTask(
                tool_name="nuclei",
                description="Apache Tomcat vulnerability scanning",
                priority=25,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "tomcat"],
            ))

    # Nginx
    if any("nginx" in t for t in tech_lower):
        tools.append(ToolTask(
            tool_name="nuclei",
            description="Nginx-specific vulnerability scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "nginx"],
        ))

    # JS frameworks (React, Vue, Angular) → browser scanner hint
    js_frameworks = {"react", "vue", "angular", "node.js"}
    if any(fw in tech_lower for fw in js_frameworks):
        tools.append(ToolTask(
            tool_name="nuclei",
            description="JavaScript framework vulnerability scanning",
            priority=30,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "js,tech"],
        ))

    # PHP
    if any("php" in t for t in tech_lower):
        tools.append(ToolTask(
            tool_name="nuclei",
            description="PHP-specific vulnerability scanning",
            priority=40,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "php,php-fpm,lfi,disclosure"],
        ))

    # Generic tech template scan
    tools.append(ToolTask(
        tool_name="nuclei",
        description="Generic technology fingerprinting and CVE scanning",
        priority=100,
        timeout=300,
        args_template=["-u", "{target}", "-jsonl", "-silent",
                       "-severity", "medium,high,critical",
                       "-tags", "tech,cve,exposure"],
    ))

    return tools
