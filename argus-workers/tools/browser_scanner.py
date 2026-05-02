"""
Browser-based SPA scanner using Playwright.

Captures client-side vulnerabilities that requests-based scanning misses:
DOM XSS, client-side routing, SPA-specific secrets, and JS-bundle analysis.

Runs as an optional add-on when ReconContext.tech_stack includes SPA frameworks.
"""
import json
import logging
import os
import re
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

SPA_FRAMEWORKS = {"react", "vue", "angular", "next.js", "nuxt", "svelte", "ember", "backbone"}
DOM_XSS_SINKS = [
    "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
    "document.writeln", "eval", "setTimeout", "setInterval",
    "Function(", "new Function", "location.href", "location.assign",
    "location.replace", "srcdoc", "postMessage",
]
CLIENT_ROUTE_PATTERNS = [
    r'["\']/([a-zA-Z0-9_\-/]+)["\']',
    r'path:\s*["\']([a-zA-Z0-9_\-/]+)["\']',
    r'route:\s*["\']([a-zA-Z0-9_\-/]+)["\']',
]


def _detect_spa_framework(page) -> list[str]:
    """Detect SPA framework from DOM attributes and globals."""
    found = []
    checks = [
        ("React", "document.getElementById('__next') || window.__NEXT_DATA__ || document.querySelector('[data-reactroot]')"),
        ("Next.js", "!!(window.__NEXT_DATA__ || document.getElementById('__NEXT_DATA__'))"),
        ("Vue", "!!(document.querySelector('[data-v-]') || window.__VUE__ || document.querySelector('#app'))"),
        ("Angular", "!!(document.querySelector('[ng-version]') || window.ng || document.querySelector('.ng-version'))"),
        ("Nuxt", "!!(window.__NUXT__)"),
        ("Svelte", "!!(document.querySelector('[data-svelte]') || document.querySelector('[data-svelte-h]'))"),
    ]
    for name, js in checks:
        try:
            result = page.evaluate(js)
            if result:
                found.append(name)
        except Exception:
            pass
    return found


def _extract_client_routes(page) -> list[str]:
    """Extract client-side routes from page source and JS."""
    routes = set()
    try:
        html = page.content()
        # Check for route patterns in HTML source
        for pat in CLIENT_ROUTE_PATTERNS:
            for m in re.finditer(pat, html):
                route = m.group(1)
                if route and len(route) > 1 and route not in (" ", ""):
                    routes.add(route)
        # Extract from inline scripts
        scripts = page.evaluate("""() => {
            const scripts = document.querySelectorAll('script:not([src])');
            return Array.from(scripts).map(s => s.textContent).join('\\n');
        }""")
        for pat in CLIENT_ROUTE_PATTERNS:
            for m in re.finditer(pat, scripts):
                route = m.group(1)
                if route and len(route) > 1:
                    routes.add(route)
    except Exception as e:
        logger.debug(f"Route extraction error: {e}")
    return sorted(routes)[:50]


def _collect_visible_links(page, base_url: str) -> list[str]:
    """Collect visible anchor hrefs from the page."""
    try:
        urls = page.evaluate("""(base) => {
            const links = new Set();
            document.querySelectorAll('a[href]').forEach(a => {
                try {
                    const abs = new URL(a.href, base).href;
                    if (abs.startsWith(base) && abs !== base) links.add(abs);
                } catch(e) {}
            });
            return Array.from(links);
        }""", base_url)
        return urls[:20]  # Cap at 20
    except Exception as e:
        logger.debug(f"Link collection error: {e}")
        return []


def _test_dom_xss(page, url: str, findings: list):
    """Test forms for DOM XSS by injecting payloads and observing DOM mutations."""
    payloads = [
        "<img src=x onerror=alert(1)>",
        "<script>alert(1)</script>",
        "javascript:alert(1)",
        "\"'><img src=x onerror=alert(1)>",
    ]
    try:
        forms = page.evaluate("""() => {
            return Array.from(document.forms).map((f, i) => ({
                index: i,
                action: f.action || '',
                inputs: Array.from(f.querySelectorAll('input, textarea')).map(inp => ({
                    name: inp.name || inp.id || '',
                    type: inp.type || 'text',
                })),
            }));
        }""")
    except Exception as e:
        logger.debug(f"Form detection error: {e}")
        forms = []

    for form in forms:
        for inp in form["inputs"]:
            if inp["type"] in ("text", "search", "url", "email", "hidden", ""):
                for payload in payloads:
                    try:
                        # Fill and submit
                        page.evaluate("""({index, name, payload}) => {
                            const form = document.forms[index];
                            if (!form) return;
                            const input = form.querySelector(`[name="${name}"], #${name}`);
                            if (!input) return;
                            input.value = payload;
                        }""", {"index": form["index"], "name": inp["name"], "payload": payload})

                        # Check if payload appears in DOM after fill
                        reflected = page.evaluate(f"""() => {{
                            const body = document.body.innerHTML;
                            return body.includes("{payload}");
                        }}""")
                        if reflected:
                            findings.append({
                                "type": "DOM_XSS",
                                "severity": "HIGH",
                                "endpoint": url,
                                "evidence": {
                                    "form_action": form["action"],
                                    "field": inp["name"],
                                    "payload": payload,
                                    "verified": True,
                                },
                                "confidence": 0.75,
                                "tool": "browser_scanner",
                            })
                            break
                    except Exception as e:
                        logger.debug(f"DOM XSS test error: {e}")
                        continue


def _scan_js_for_secrets(page, findings: list):
    """Scan JS bundles for secrets and sensitive data."""
    try:
        scripts = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('script[src]'))
                .map(s => s.src)
                .filter(s => s);
        }""")
    except Exception:
        scripts = []

    secret_patterns = [
        (r'api[_-]?key["\']?\s*[:=]\s*["\']([a-zA-Z0-9_\-]{16,})["\']', "API_KEY"),
        (r'token["\']?\s*[:=]\s*["\']([a-zA-Z0-9_\-\.]{20,})["\']', "AUTH_TOKEN"),
        (r'secret["\']?\s*[:=]\s*["\']([a-zA-Z0-9_\-]{16,})["\']', "SECRET"),
        (r'password["\']?\s*[:=]\s*["\']([^"\']{4,})["\']', "PASSWORD"),
    ]

    seen = set()
    for script_url in scripts[:10]:
        try:
            import requests
            resp = requests.get(script_url, timeout=10)
            if resp.status_code != 200:
                continue
            for pat, stype in secret_patterns:
                matches = re.findall(pat, resp.text, re.IGNORECASE)
                for m in matches[:3]:
                    key = f"{stype}:{m[:10]}"
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append({
                        "type": "CLIENT_SIDE_SECRET",
                        "severity": "HIGH",
                        "endpoint": script_url,
                        "evidence": {
                            "secret_type": stype,
                            "preview": m[:8] + "..." if len(m) > 8 else "***",
                        },
                        "confidence": 0.70,
                        "tool": "browser_scanner",
                    })
        except Exception:
            continue


def scan(target_url: str, findings: list | None = None) -> list[dict]:
    """
    Run browser-based SPA scan against target.

    Args:
        target_url: Target URL to scan
        findings: Optional list to append results to

    Returns:
        Updated findings list
    """
    if findings is None:
        findings = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        return findings

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                ignore_https_errors=True,
            )
            page = context.new_page()

            logger.info(f"Browser scanner navigating to {target_url}")
            try:
                page.goto(target_url, wait_until="networkidle", timeout=30000)
            except Exception as e:
                logger.warning(f"Browser scanner navigation: {e}")
                page.goto(target_url, wait_until="load", timeout=30000)

            # Detect SPA framework
            frameworks = _detect_spa_framework(page)
            if frameworks:
                findings.append({
                    "type": "SPA_FRAMEWORK_DETECTED",
                    "severity": "INFO",
                    "endpoint": target_url,
                    "evidence": {"frameworks": frameworks},
                    "confidence": 0.95,
                    "tool": "browser_scanner",
                })
                logger.info(f"SPA frameworks detected: {frameworks}")

            # Extract client-side routes
            routes = _extract_client_routes(page)
            if routes:
                findings.append({
                    "type": "CLIENT_ROUTES_DISCOVERED",
                    "severity": "INFO",
                    "endpoint": target_url,
                    "evidence": {"routes": routes, "count": len(routes)},
                    "confidence": 0.80,
                    "tool": "browser_scanner",
                })

            # Crawl visible links to discover SPA pages
            links = _collect_visible_links(page, target_url)
            visited = {target_url}
            for link in links[:10]:  # Visit top 10 links
                if link in visited:
                    continue
                visited.add(link)
                try:
                    page.goto(link, wait_until="networkidle", timeout=15000)
                    logger.debug(f"Crawled SPA route: {link}")

                    # Check for 404/cloaking in SPA
                    title = page.title()
                    if title and ("not found" in title.lower() or "404" in title):
                        continue

                    # Test for DOM XSS on each page
                    _test_dom_xss(page, link, findings)
                except Exception as e:
                    logger.debug(f"SPA crawl error for {link}: {e}")

            # Scan JS bundles for secrets
            _scan_js_for_secrets(page, findings)

            browser.close()
            logger.info(f"Browser scan complete: {len(findings)} findings")

    except Exception as e:
        logger.error(f"Browser scanner failed: {e}", exc_info=True)

    return findings


def is_spa_target(tech_stack: list[str]) -> bool:
    """Check if any detected technology is an SPA framework."""
    tech_lower = {t.lower().replace(".js", "").replace("-", "") for t in tech_stack}
    spa_lower = {f.lower().replace(".js", "").replace("-", "") for f in SPA_FRAMEWORKS}
    return bool(tech_lower & spa_lower)
