#!/usr/bin/env python3
"""
Standalone Playwright-based SPA scanner worker.

Called as a subprocess by browser_scanner.py to avoid event-loop conflicts
with Celery's thread pool. Prints JSON findings to stdout, exits cleanly.

Usage:
    python _browser_scan_worker.py <target_url> '<json_tech_stack>'
"""
import json
import logging
import re
import sys
from urllib.parse import urljoin

SPA_FRAMEWORKS = {"react", "vue", "angular", "next.js", "nuxt", "svelte", "ember", "backbone"}
CLIENT_ROUTE_PATTERNS = [
    r'["\']/([a-zA-Z0-9_\-/]+)["\']',
    r'path:\s*["\']([a-zA-Z0-9_\-/]+)["\']',
    r'route:\s*["\']([a-zA-Z0-9_\-/]+)["\']',
]


def _detect_spa_framework(page):
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
            if page.evaluate(js):
                found.append(name)
        except Exception:
            pass
    return found


def _extract_client_routes(page):
    routes = set()
    try:
        html = page.content()
        for pat in CLIENT_ROUTE_PATTERNS:
            for m in re.finditer(pat, html):
                route = m.group(1)
                if route and len(route) > 1 and route not in (" ", ""):
                    routes.add(route)
        scripts = page.evaluate("""() => {
            const scripts = document.querySelectorAll('script:not([src])');
            return Array.from(scripts).map(s => s.textContent).join('\\n');
        }""")
        for pat in CLIENT_ROUTE_PATTERNS:
            for m in re.finditer(pat, scripts):
                route = m.group(1)
                if route and len(route) > 1:
                    routes.add(route)
    except Exception:
        pass
    return sorted(routes)[:50]


def _collect_visible_links(page, base_url):
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
        return urls[:20]
    except Exception:
        return []


def _test_dom_xss(page, url, findings):
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
    except Exception:
        forms = []

    for form in forms:
        for inp in form["inputs"]:
            if inp["type"] in ("text", "search", "url", "email", "hidden", ""):
                for payload in payloads:
                    try:
                        page.evaluate("""({index, name, payload}) => {
                            const form = document.forms[index];
                            if (!form) return;
                            const input = form.querySelector(`[name="${name}"], #${name}`);
                            if (!input) return;
                            input.value = payload;
                        }""", {"index": form["index"], "name": inp["name"], "payload": payload})
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
                    except Exception:
                        continue


def _scan_js_for_secrets(page, findings):
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


def main():
    if len(sys.argv) < 2:
        print(json.dumps([]))
        return

    target_url = sys.argv[1]
    findings = []

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                ignore_https_errors=True,
            )
            page = context.new_page()

            try:
                page.goto(target_url, wait_until="networkidle", timeout=30000)
            except Exception:
                page.goto(target_url, wait_until="load", timeout=30000)

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

            links = _collect_visible_links(page, target_url)
            visited = {target_url}
            for link in links[:10]:
                if link in visited:
                    continue
                visited.add(link)
                try:
                    page.goto(link, wait_until="networkidle", timeout=15000)
                    title = page.title()
                    if title and ("not found" in title.lower() or "404" in title):
                        continue
                    _test_dom_xss(page, link, findings)
                except Exception:
                    pass

            _scan_js_for_secrets(page, findings)
            browser.close()

    except ImportError:
        pass
    except Exception:
        pass

    print(json.dumps(findings))


if __name__ == "__main__":
    main()
