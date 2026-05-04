/**
 * AI Rule Generator Endpoint - Uses OpenRouter for unified model access
 *
 * POST /api/ai/generate-rule
 *
 * Takes a natural language description and generates a YAML detection rule.
 */
import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import Redis from "ioredis";

function getRedisClient() {
  const redisUrl = process.env.REDIS_URL || "redis://localhost:6379";
  return new Redis(redisUrl, {
    maxRetriesPerRequest: 1,
    lazyConnect: true,
  });
}

interface GenerateRuleRequest {
  description: string;
  model?: string;
}

function buildRulePrompt(userDescription: string): string {
  return `You are a cybersecurity expert specializing in vulnerability detection rules. Generate a YAML detection rule based on the user's description.

RULE FORMAT (strict YAML):
- id: A kebab-case identifier (e.g., "detect-sqli-login")
- severity: One of: INFO, LOW, MEDIUM, HIGH, CRITICAL
- message: A clear, actionable vulnerability message shown to users
- patterns: A list of pattern objects, each with:
    - pattern: A string or regex pattern to search for

EXAMPLE OUTPUT:
\`\`\`yaml
rules:
  - id: detect-hardcoded-secret
    severity: HIGH
    message: "Hardcoded API key or secret detected in source code"
    patterns:
      - pattern: "(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{8,}['\"]"
\`\`\`

USER REQUEST:
"""${userDescription}"""

IMPORTANT RULES:
- Output ONLY valid YAML inside a \`\`\`yaml code block
- Patterns should be practical regex or string matches
- Severity should match the real risk level
- Message should be concise and actionable
- Do not include explanations outside the YAML block
- Ensure the YAML is properly indented with 2 spaces`;
}

async function callOpenRouter(
  apiKey: string,
  userDescription: string,
  model: string
): Promise<string> {
  const prompt = buildRulePrompt(userDescription);

  const response = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
      "HTTP-Referer": process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000",
      "X-Title": "Argus Pentest Platform",
    },
    body: JSON.stringify({
      model: model || "anthropic/claude-3.5-sonnet",
      messages: [
        {
          role: "system",
          content:
            "You are an expert in writing YAML-based vulnerability detection rules for security scanners. You output only valid, well-formatted YAML.",
        },
        { role: "user", content: prompt },
      ],
      temperature: 0.2,
      max_tokens: 800,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`OpenRouter error: ${response.status} - ${errorText}`);
  }

  const data = await response.json();
  return data.choices?.[0]?.message?.content || "No rule generated";
}

function extractYaml(content: string): string {
  // Try to extract YAML from ```yaml blocks
  const yamlBlockMatch = content.match(/```yaml\n?([\s\S]*?)```/);
  if (yamlBlockMatch) {
    return yamlBlockMatch[1].trim();
  }
  // Fallback: if no code block, return the whole content
  return content.trim();
}

// POST - Generate a rule from natural language
export async function POST(request: NextRequest) {
  let redis: Redis | null = null;

  try {
    const session = await getServerSession(authOptions);

    if (!session?.user?.email) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body: GenerateRuleRequest = await request.json();
    const { description, model } = body;

    if (!description || typeof description !== "string" || description.trim().length === 0) {
      return NextResponse.json({ error: "Description is required" }, { status: 400 });
    }

    redis = getRedisClient();
    const email = session.user.email;

    const apiKey = await redis.get(`settings:${email}:openrouter_api_key`);
    const preferredModel = await redis.get(`settings:${email}:preferred_ai_model`);

    if (!apiKey) {
      return NextResponse.json(
        {
          error: "No OpenRouter API key configured",
          message: "Please configure your OpenRouter API key in Settings",
        },
        { status: 401 }
      );
    }

    const userModel = model || preferredModel || "anthropic/claude-3.5-sonnet";

    const rawContent = await callOpenRouter(apiKey, description.trim(), userModel);
    const yamlContent = extractYaml(rawContent);

    return NextResponse.json({
      success: true,
      rule_yaml: yamlContent,
      raw: rawContent,
      provider: "openrouter",
      model: userModel,
    });
  } catch (error) {
    console.error("AI Rule Generator error:", error);
    const err = error as Error;
    return NextResponse.json(
      { error: "Failed to generate rule" },
      { status: 500 }
    );
  } finally {
    if (redis) redis.disconnect();
  }
}
