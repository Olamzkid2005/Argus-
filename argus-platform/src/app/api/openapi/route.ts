/**
 * OpenAPI Specification for Argus Platform API
 * 
 * Auto-generated API documentation.
 * Access at /api-docs or /api/openapi.json
 */

import { NextRequest, NextResponse } from "next/server";
import { getCurrentVersion, API_VERSIONS } from "@/lib/api-version";

const openApiSpec = {
  openapi: "3.0.3",
  info: {
    title: "Argus Pentest Platform API",
    description: `
## Overview
API for the Argus security testing platform.

## Authentication
All endpoints require a valid NextAuth session token.
Pass it in the Cookie header.

## Rate Limits
- Auth endpoints: 10 req/min
- Write operations: 30 req/min  
- Read operations: 200 req/min
    `.trim(),
    version: getCurrentVersion(),
    contact: {
      name: "Argus Support",
      email: "support@argus.security",
    },
    license: {
      name: "MIT",
      url: "https://opensource.org/licenses/MIT",
    },
  },
  servers: [
    {
      url: "{baseUrl}",
      variables: {
        baseUrl: {
          default: "https://api.argus.security",
          description: "Production server",
        },
      },
    },
  ],
  tags: [
    { name: "Auth", description: "Authentication endpoints" },
    { name: "Engagements", description: "Engagement management" },
    { name: "Findings", description: "Security findings" },
    { name: "Dashboard", description: "Dashboard and stats" },
    { name: "Rules", description: "Custom detection rules" },
    { name: "AI", description: "AI-powered features" },
    { name: "Reports", description: "Report generation" },
    { name: "Health", description: "Health check endpoints" },
  ],
  paths: {
    "/api/auth/signin": {
      post: {
        tags: ["Auth"],
        summary: "Sign in user",
        description: "Authenticate with email and password",
        operationId: "signin",
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: {
                type: "object",
                required: ["email", "password"],
                properties: {
                  email: { type: "string", format: "email" },
                  password: { type: "string", format: "password" },
                },
              },
            },
          },
        },
        responses: {
          "200": { description: "Login successful" },
          "401": { description: "Invalid credentials" },
        },
      },
    },
    "/api/engagements": {
      get: {
        tags: ["Engagements"],
        summary: "List engagements",
        description: "Get all engagements for the user's organization",
        operationId: "listEngagements",
        parameters: [
          {
            name: "status",
            in: "query",
            schema: { type: "string" },
            description: "Filter by status",
          },
          {
            name: "limit",
            in: "query",
            schema: { type: "integer", default: 20 },
          },
          {
            name: "offset",
            in: "query",
            schema: { type: "integer", default: 0 },
          },
        ],
        responses: {
          "200": {
            description: "List of engagements",
            content: {
              "application/json": {
                schema: {
                  type: "object",
                  properties: {
                    engagements: { type: "array" },
                    total: { type: "integer" },
                  },
                },
              },
            },
          },
        },
      },
      post: {
        tags: ["Engagements"],
        summary: "Create engagement",
        description: "Create a new security engagement",
        operationId: "createEngagement",
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: {
                type: "object",
                required: ["targetUrl", "authorization"],
                properties: {
                  targetUrl: { type: "string" },
                  scanType: { type: "string", enum: ["url", "repo"] },
                  authorization: { type: "string" },
                  scope: { type: "string" },
                  aggressiveness: { type: "string", enum: ["low", "medium", "high"] },
                },
              },
            },
          },
        },
        responses: {
          "201": { description: "Engagement created" },
          "400": { description: "Validation error" },
        },
      },
    },
    "/api/engagement/{id}": {
      get: {
        tags: ["Engagements"],
        summary: "Get engagement",
        description: "Get a specific engagement by ID",
        operationId: "getEngagement",
        parameters: [
          {
            name: "id",
            in: "path",
            required: true,
            schema: { type: "string", format: "uuid" },
          },
        ],
        responses: {
          "200": { description: "Engagement details" },
          "404": { description: "Not found" },
        },
      },
      delete: {
        tags: ["Engagements"],
        summary: "Delete engagement",
        description: "Delete an engagement",
        operationId: "deleteEngagement",
        parameters: [
          {
            name: "id",
            in: "path",
            required: true,
            schema: { type: "string", format: "uuid" },
          },
        ],
        responses: {
          "204": { description: "Deleted" },
          "404": { description: "Not found" },
        },
      },
    },
    "/api/engagement/{id}/findings": {
      get: {
        tags: ["Findings"],
        summary: "Get engagement findings",
        description: "Get all findings for an engagement",
        operationId: "getFindings",
        parameters: [
          {
            name: "id",
            in: "path",
            required: true,
            schema: { type: "string", format: "uuid" },
          },
          {
            name: "severity",
            in: "query",
            schema: { type: "array", items: { type: "string" } },
          },
          {
            name: "status",
            in: "query",
            schema: { type: "string" },
          },
        ],
        responses: {
          "200": { description: "Findings list" },
        },
      },
    },
    "/api/findings": {
      get: {
        tags: ["Findings"],
        summary: "List all findings",
        description: "Get all findings across engagements",
        operationId: "listFindings",
        parameters: [
          {
            name: "severity",
            in: "query",
            schema: { type: "array", items: { type: "string" } },
          },
          {
            name: "type",
            in: "query",
            schema: { type: "string" },
          },
          {
            name: "status",
            in: "query",
            schema: { type: "string" },
          },
          {
            name: "limit",
            in: "query",
            schema: { type: "integer", default: 50 },
          },
        ],
        responses: {
          "200": { description: "Findings list" },
        },
      },
      put: {
        tags: ["Findings"],
        summary: "Bulk update findings",
        description: "Update multiple findings at once",
        operationId: "bulkUpdateFindings",
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: {
                type: "object",
                properties: {
                  ids: { type: "array", items: { type: "string" } },
                  status: { type: "string", enum: ["open", "verified", "fixed", "false_positive"] },
                  severity: { type: "string", enum: ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] },
                },
              },
            },
          },
        },
        responses: {
          "200": { description: "Updated" },
        },
      },
    },
    "/api/findings/{id}/verify": {
      post: {
        tags: ["Findings"],
        summary: "Verify finding",
        description: "Mark a finding as verified",
        operationId: "verifyFinding",
        parameters: [
          {
            name: "id",
            in: "path",
            required: true,
            schema: { type: "string", format: "uuid" },
          },
        ],
        responses: {
          "200": { description: "Verified" },
        },
      },
    },
    "/api/dashboard/stats": {
      get: {
        tags: ["Dashboard"],
        summary: "Get dashboard stats",
        description: "Get organization dashboard statistics",
        operationId: "getDashboardStats",
        responses: {
          "200": {
            description: "Dashboard stats",
            content: {
              "application/json": {
                schema: {
                  type: "object",
                  properties: {
                    totalEngagements: { type: "integer" },
                    activeScans: { type: "integer" },
                    criticalFindings: { type: "integer" },
                    securityScore: { type: "number" },
                  },
                },
              },
            },
          },
        },
      },
    },
    "/api/rules": {
      get: {
        tags: ["Rules"],
        summary: "List rules",
        description: "Get custom detection rules",
        operationId: "listRules",
        responses: {
          "200": { description: "Rules list" },
        },
      },
      post: {
        tags: ["Rules"],
        summary: "Create rule",
        description: "Create a custom detection rule",
        operationId: "createRule",
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: {
                type: "object",
                required: ["name", "ruleYaml"],
                properties: {
                  name: { type: "string" },
                  description: { type: "string" },
                  ruleYaml: { type: "string" },
                  severity: { type: "string", enum: ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] },
                  tags: { type: "array", items: { type: "string" } },
                },
              },
            },
          },
        },
        responses: {
          "201": { description: "Created" },
        },
      },
    },
    "/api/ai/explain": {
      post: {
        tags: ["AI"],
        summary: "Explain finding",
        description: "Get AI explanation for a finding",
        operationId: "explainFinding",
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: {
                type: "object",
                required: ["findingId"],
                properties: {
                  findingId: { type: "string", format: "uuid" },
                },
              },
            },
          },
        },
        responses: {
          "200": { description: "Explanation" },
        },
      },
    },
    "/api/ai/generate-rule": {
      post: {
        tags: ["AI"],
        summary: "Generate rule",
        description: "Generate custom detection rule using AI",
        operationId: "generateRule",
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: {
                type: "object",
                required: ["prompt"],
                properties: {
                  prompt: { type: "string" },
                },
              },
            },
          },
        },
        responses: {
          "200": { description: "Generated rule" },
        },
      },
    },
    "/api/reports/compliance": {
      get: {
        tags: ["Reports"],
        summary: "List compliance reports",
        description: "Get compliance reports",
        operationId: "listComplianceReports",
        responses: {
          "200": { description: "Reports list" },
        },
      },
      post: {
        tags: ["Reports"],
        summary: "Generate compliance report",
        description: "Generate a compliance report",
        operationId: "generateComplianceReport",
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: {
                type: "object",
                required: ["engagementId", "standard"],
                properties: {
                  engagementId: { type: "string", format: "uuid" },
                  standard: { type: "string", enum: ["owasp", "pci-dss", "hipaa"] },
                },
              },
            },
          },
        },
        responses: {
          "201": { description: "Report generated" },
        },
      },
    },
    "/api/health/db": {
      get: {
        tags: ["Health"],
        summary: "Database health check",
        description: "Check database connectivity",
        operationId: "checkDbHealth",
        responses: {
          "200": { description: "Database healthy" },
          "503": { description: "Database unhealthy" },
        },
      },
    },
    "/api/health/worker": {
      get: {
        tags: ["Health"],
        summary: "Worker health check",
        description: "Check worker/Celery status",
        operationId: "checkWorkerHealth",
        responses: {
          "200": { description: "Workers healthy" },
          "503": { description: "Workers unavailable" },
        },
      },
    },
  },
  components: {
    securitySchemes: {
      cookieAuth: {
        type: "apiKey",
        in: "header",
        name: "Cookie",
        description: "NextAuth session cookie",
      },
      bearerAuth: {
        type: "apiKey",
        in: "header",
        name: "Authorization",
        description: "Bearer token (for API access)",
      },
    },
    schemas: {
      Error: {
        type: "object",
        properties: {
          error: { type: "string" },
          code: { type: "string" },
          details: { type: "object" },
        },
      },
      Engagement: {
        type: "object",
        properties: {
          id: { type: "string", format: "uuid" },
          targetUrl: { type: "string" },
          status: { type: "string" },
          createdAt: { type: "string", format: "date-time" },
        },
      },
      Finding: {
        type: "object",
        properties: {
          id: { type: "string", format: "uuid" },
          type: { type: "string" },
          severity: { type: "string", enum: ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] },
          confidence: { type: "number" },
          endpoint: { type: "string" },
        },
      },
    },
  },
  security: [
    { cookieAuth: [] },
    { bearerAuth: [] },
  ],
};

/**
 * GET /api/openapi.json - Returns OpenAPI spec
 */
export async function GET(_req: NextRequest) {
  const baseUrl = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000";
  
  // Replace server URL variable
  const spec = JSON.parse(
    JSON.stringify(openApiSpec).replace('"{baseUrl}"', `"${baseUrl}"`)
  );

  return NextResponse.json(spec, {
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
    },
  });
}

/**
 * OPTIONS /api/openapi.json - CORS preflight
 */
export async function OPTIONS(_req: NextRequest) {
  return new NextResponse(null, {
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
    },
  });
}