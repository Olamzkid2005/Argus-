/**
 * API Documentation Redirect
 * 
 * Redirects /api-docs to OpenAPI spec JSON
 * Can also serve Swagger UI in future
 */
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const baseUrl = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000";
  
  // Return HTML redirect or Swagger UI
  const html = `
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Argus API Documentation</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { 
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #0f172a; color: #e2e8f0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .container {
      max-width: 600px; padding: 2rem;
      text-align: center;
    }
    h1 { font-size: 2rem; margin-bottom: 1rem; color: #38bdf8; }
    p { color: #94a3b8; margin-bottom: 2rem; }
    .links { display: flex; flex-direction: column; gap: 1rem; }
    a {
      display: block;
      padding: 1rem 2rem;
      background: #1e293b;
      color: #38bdf8;
      text-decoration: none;
      border-radius: 8px;
      transition: background 0.2s;
    }
    a:hover { background: #334155; }
    code {
      background: #1e293b;
      padding: 0.25rem 0.5rem;
      border-radius: 4px;
      font-size: 0.875em;
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>Argus API Documentation</h1>
    <p>Interactive API reference for the Argus Pentest Platform</p>
    <div class="links">
      <a href="${baseUrl}/api/openapi.json">📄 OpenAPI 3.0 JSON Spec</a>
      <a href="https://swagger.io/tools/swagger-ui/">🔧 Swagger UI</a>
      <a href="https://argus.security/docs/api">📚 Full API Docs</a>
    </div>
    <p style="margin-top: 2rem;">
      <code>GET /api/openapi.json</code> for raw spec
    </p>
  </div>
</body>
</html>
  `.trim();

  return new NextResponse(html, {
    headers: {
      "Content-Type": "text/html",
      "Access-Control-Allow-Origin": "*",
    },
  });
}