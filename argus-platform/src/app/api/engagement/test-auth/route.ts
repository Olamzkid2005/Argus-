import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { log } from "@/lib/logger";

interface AuthTestRequest {
  targetUrl: string;
  authType: "form" | "bearer" | "cookie" | "api_key";
  username?: string;
  password?: string;
  token?: string;
  cookie?: string;
  loginUrl?: string;
  api_key?: string;
  api_key_header?: string;
}

export async function POST(req: NextRequest) {
  log.api("POST", "/api/engagement/test-auth");
  try {
    const session = await requireAuth();
    const body: AuthTestRequest = await req.json();
    const { targetUrl, authType, username, password, token, cookie, loginUrl, api_key, api_key_header } = body;

    if (!targetUrl) {
      return NextResponse.json({ error: "targetUrl is required" }, { status: 400 });
    }

    // Normalize base URL
    let baseUrl = targetUrl.trim();
    if (!baseUrl.startsWith("http://") && !baseUrl.startsWith("https://")) {
      baseUrl = `https://${baseUrl}`;
    }
    baseUrl = baseUrl.replace(/\/+$/, "");

    const results: {
      authType: string;
      success: boolean;
      details: Record<string, unknown>;
      errors: string[];
    } = {
      authType,
      success: false,
      details: {},
      errors: [],
    };

    try {
      switch (authType) {
        case "form": {
          if (!username || !password) {
            return NextResponse.json(
              { error: "Username and password are required for form-based auth" },
              { status: 400 }
            );
          }

          // Try the specified login URL, then fall back to common paths
          const loginCandidates = loginUrl
            ? [`${baseUrl}${loginUrl.startsWith("/") ? "" : "/"}${loginUrl}`]
            : [
                `${baseUrl}/login`,
                `${baseUrl}/signin`,
                `${baseUrl}/auth/login`,
                `${baseUrl}/api/auth/login`,
                `${baseUrl}/api/login`,
              ];

          let authSuccess = false;
          let sessionCookieCount = 0;
          let usedUrl = "";

          for (const loginUrl of loginCandidates) {
            try {
              const controller = new AbortController();
              const timeout = setTimeout(() => controller.abort(), 10000);

              // First, GET the login page to capture any CSRF token
              const loginPageResponse = await fetch(loginUrl, {
                method: "GET",
                signal: controller.signal,
                headers: {
                  "User-Agent": "Mozilla/5.0 (compatible; ArgusSecurity/1.0)",
                  Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
              });

              const pageText = await loginPageResponse.text();
              
              // Try to extract CSRF token
              let csrfToken = "";
              const csrfPatterns = [
                /name=["']csrf_token["'][^>]*value=["']([^"']*)["']/i,
                /name=["']_csrf["'][^>]*value=["']([^"']*)["']/i,
                /name=["']csrf["'][^>]*value=["']([^"']*)["']/i,
                /name=["']authenticity_token["'][^>]*value=["']([^"']*)["']/i,
                /"csrfToken":"([^"]+)"/,
                /"csrf":"([^"]+)"/,
              ];
              for (const pattern of csrfPatterns) {
                const match = pageText.match(pattern);
                if (match) {
                  csrfToken = match[1];
                  break;
                }
              }

              // Build login payload
              const formData = new URLSearchParams();
              formData.append("username", username);
              formData.append("password", password);
              formData.append("email", username);
              formData.append("login", username);
              formData.append("user_login", username);
              if (csrfToken) {
                formData.append("csrf_token", csrfToken);
                formData.append("_csrf", csrfToken);
                formData.append("authenticity_token", csrfToken);
              }

              const preCookies = loginPageResponse.headers.getSetCookie?.() || [];
              const preCookieCount = preCookies.length;

              const loginResponse = await fetch(loginUrl, {
                method: "POST",
                signal: controller.signal,
                headers: {
                  "User-Agent": "Mozilla/5.0 (compatible; ArgusSecurity/1.0)",
                  "Content-Type": "application/x-www-form-urlencoded",
                  Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                  Referer: loginUrl,
                },
                body: formData.toString(),
                redirect: "manual",
              });
              clearTimeout(timeout);

              const postCookies = loginResponse.headers.getSetCookie?.() || [];
              sessionCookieCount = postCookies.length - preCookieCount;

              // Check if login succeeded
              const gotNewCookies = sessionCookieCount > 0;
              const statusOk = loginResponse.status === 302 || loginResponse.status === 200;
              const notUnauthorized = loginResponse.status !== 401 && loginResponse.status !== 403;

              if (gotNewCookies || (statusOk && notUnauthorized)) {
                authSuccess = true;
                usedUrl = loginUrl;
                results.details = {
                  statusCode: loginResponse.status,
                  sessionCookies: sessionCookieCount,
                  csrfDetected: !!csrfToken,
                  redirectLocation: loginResponse.headers.get("location") || null,
                };
                break;
              }
            } catch (err) {
              results.errors.push(
                `Login attempt at ${loginUrl}: ${err instanceof Error ? err.message.slice(0, 80) : String(err)}`
              );
              continue;
            }
          }

          results.success = authSuccess;
          results.details = {
            ...results.details as Record<string, unknown>,
            usedLoginUrl: usedUrl,
            credentialType: "username/password",
          };
          break;
        }

        case "bearer": {
          if (!token) {
            return NextResponse.json(
              { error: "Token is required for bearer auth" },
              { status: 400 }
            );
          }

          // Test the token against the base URL
          const testUrls = [
            `${baseUrl}/`,
            `${baseUrl}/api/`,
            `${baseUrl}/api/v1/`,
          ];

          let tokenValid = false;
          let usedTestUrl = "";

          for (const testUrl of testUrls) {
            try {
              const controller = new AbortController();
              const timeout = setTimeout(() => controller.abort(), 8000);

              const testResponse = await fetch(testUrl, {
                method: "GET",
                signal: controller.signal,
                headers: {
                  "User-Agent": "Mozilla/5.0 (compatible; ArgusSecurity/1.0)",
                  Authorization: `Bearer ${token}`,
                  Accept: "application/json, text/html",
                },
              });
              clearTimeout(timeout);

              // 401 means token rejected, anything else is promising
              if (testResponse.status !== 401 && testResponse.status !== 403) {
                tokenValid = true;
                usedTestUrl = testUrl;
                results.details = {
                  statusCode: testResponse.status,
                  contentType: testResponse.headers.get("content-type") || "unknown",
                  bodyPreview: (await testResponse.text()).slice(0, 200),
                };
                break;
              }
            } catch (err) {
              results.errors.push(
                `Token test at ${testUrl}: ${err instanceof Error ? err.message.slice(0, 80) : String(err)}`
              );
              continue;
            }
          }

          results.success = tokenValid;
          results.details = {
            ...results.details as Record<string, unknown>,
            usedTestUrl,
          };
          break;
        }

        case "cookie": {
          if (!cookie) {
            return NextResponse.json(
              { error: "Cookie string is required for cookie auth" },
              { status: 400 }
            );
          }

          // Test the cookie against the base URL
          const testUrl = `${baseUrl}/`;
          try {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 8000);

            const testResponse = await fetch(testUrl, {
              method: "GET",
              signal: controller.signal,
              headers: {
                "User-Agent": "Mozilla/5.0 (compatible; ArgusSecurity/1.0)",
                Cookie: cookie,
                Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
              },
            });
            clearTimeout(timeout);

            const cookieValid = testResponse.status !== 401 && testResponse.status !== 403;
            results.success = cookieValid;
            results.details = {
              statusCode: testResponse.status,
              contentType: testResponse.headers.get("content-type") || "unknown",
              bodyPreview: cookieValid ? (await testResponse.text()).slice(0, 200) : "Access denied",
            };
          } catch (err) {
            results.errors.push(
              `Cookie test: ${err instanceof Error ? err.message.slice(0, 80) : String(err)}`
            );
          }
          break;
        }

        case "api_key": {
          if (!api_key) {
            return NextResponse.json(
              { error: "API key is required for API key auth" },
              { status: 400 }
            );
          }

          const headerName = api_key_header || "X-API-Key";
          const testUrl = `${baseUrl}/`;
          try {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 8000);

            const testResponse = await fetch(testUrl, {
              method: "GET",
              signal: controller.signal,
              headers: {
                "User-Agent": "Mozilla/5.0 (compatible; ArgusSecurity/1.0)",
                [headerName]: api_key,
                Accept: "application/json, text/html",
              },
            });
            clearTimeout(timeout);

            const apiKeyValid = testResponse.status !== 401 && testResponse.status !== 403;
            results.success = apiKeyValid;
            results.details = {
              statusCode: testResponse.status,
              contentType: testResponse.headers.get("content-type") || "unknown",
              headerName,
              bodyPreview: apiKeyValid ? (await testResponse.text()).slice(0, 200) : "Access denied",
            };
          } catch (err) {
            results.errors.push(
              `API key test: ${err instanceof Error ? err.message.slice(0, 80) : String(err)}`
            );
          }
          break;
        }

        default:
          return NextResponse.json(
            { error: `Unsupported auth type: ${authType}` },
            { status: 400 }
          );
      }
    } catch (err) {
      results.errors.push(
        `Auth test failed: ${err instanceof Error ? err.message : String(err)}`
      );
    }

    const summary = results.success
      ? "Authentication configuration is valid"
      : "Authentication test failed — check credentials and try again";

    log.apiEnd("POST", "/api/engagement/test-auth", 200, {
      target: baseUrl,
      authType,
      success: results.success,
    });

    return NextResponse.json({
      success: results.success,
      summary,
      details: results.details,
      errors: results.errors.length > 0
        ? results.errors.slice(0, 3)
        : undefined,
    });
  } catch (error) {
    log.error("Test auth error:", error);
    return NextResponse.json(
      { error: "Failed to test authentication" },
      { status: 500 }
    );
  }
}
