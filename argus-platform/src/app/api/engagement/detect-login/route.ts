import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { log } from "@/lib/logger";

// Common login paths — mirrors COMMON_LOGIN_PATHS from auth_manager.py
const COMMON_LOGIN_PATHS = [
  "/login",
  "/signin",
  "/auth/login",
  "/api/auth/login",
  "/api/login",
  "/auth",
  "/sign-in",
  "/log-in",
  "/account/login",
  "/user/login",
  "/admin/login",
  "/oauth/authorize",
  "/saml/login",
  "/sso",
  "/api/v1/auth/login",
  "/api/v2/auth/login",
];

interface LoginPageResult {
  path: string;
  url: string;
  status: number;
  hasForm: boolean;
  contentType: string;
  title: string;
}

export async function POST(req: NextRequest) {
  log.api("POST", "/api/engagement/detect-login");
  try {
    const session = await requireAuth();
    const body = await req.json();
    const { targetUrl } = body;

    if (!targetUrl) {
      return NextResponse.json(
        { error: "targetUrl is required" },
        { status: 400 },
      );
    }

    // Normalize target URL
    let baseUrl = targetUrl.trim();
    if (!baseUrl.startsWith("http://") && !baseUrl.startsWith("https://")) {
      baseUrl = `https://${baseUrl}`;
    }
    // Remove trailing slash for consistent joining
    baseUrl = baseUrl.replace(/\/+$/, "");

    const results: LoginPageResult[] = [];
    const errors: string[] = [];

    // Probe common login paths in parallel (batch of 5)
    const batchSize = 5;
    for (let i = 0; i < COMMON_LOGIN_PATHS.length; i += batchSize) {
      const batch = COMMON_LOGIN_PATHS.slice(i, i + batchSize);
      const probes = batch.map(async (path) => {
        const url = `${baseUrl}${path}`;
        try {
          const controller = new AbortController();
          const timeout = setTimeout(() => controller.abort(), 8000);

          const response = await fetch(url, {
            method: "GET",
            signal: controller.signal,
            headers: {
              "User-Agent":
                "Mozilla/5.0 (compatible; ArgusSecurity/1.0; +https://argus.security)",
              Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            redirect: "manual",
          });
          clearTimeout(timeout);

          const status = response.status;
          const contentType = response.headers.get("content-type") || "";
          const isHtml = contentType.includes("text/html");

          // Consider 200, 302, 301 as potential login pages
          if (status === 200 || status === 302 || status === 301 || status === 303) {
            let title = "";
            let hasForm = false;

            if (isHtml) {
              const text = await response.text();
              const titleMatch = text.match(/<title[^>]*>([^<]*)<\/title>/i);
              if (titleMatch) {
                title = titleMatch[1].trim();
              }
              // Detect login forms by common keywords/patterns
              hasForm =
                /<form[^>]*(?:login|signin|auth|password|credential)[^>]*>/i.test(text) ||
                /<input[^>]*(?:password|passwd)[^>]*>/i.test(text) ||
                /type=["']password["']/i.test(text);
            }

            results.push({
              path,
              url,
              status,
              hasForm,
              contentType: contentType.split(";")[0],
              title: title.slice(0, 120),
            });
          }
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          // Only log real errors, not timeouts for non-existent pages
          if (
            !msg.includes("abort") &&
            !msg.includes("ENOTFOUND") &&
            !msg.includes("ECONNREFUSED") &&
            !msg.includes("ECONNRESET")
          ) {
            errors.push(`${path}: ${msg.slice(0, 80)}`);
          }
        }
      });

      await Promise.all(probes);
    }

    // Sort: form-detected pages first, then by status
    results.sort((a, b) => {
      if (a.hasForm !== b.hasForm) return a.hasForm ? -1 : 1;
      return a.status - b.status;
    });

    log.apiEnd("POST", "/api/engagement/detect-login", 200, {
      target: baseUrl,
      found: results.length,
    });

    return NextResponse.json({
      target: baseUrl,
      loginPages: results,
      totalFound: results.length,
      errors: errors.length > 0 ? errors.slice(0, 5) : undefined,
    });
  } catch (error) {
    log.error("Detect login error:", error);
    return NextResponse.json(
      { error: "Failed to detect login pages" },
      { status: 500 },
    );
  }
}
