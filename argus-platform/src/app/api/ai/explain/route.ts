/**
 * AI Explain Endpoint - Uses OpenRouter for unified model access
 * 
 * POST /api/ai/explain
 * 
 * Takes findings and generates AI-powered explanations using the user's OpenRouter API key.
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

interface Finding {
  id: string;
  type: string;
  severity: string;
  endpoint: string;
  evidence?: any;
  confidence?: number;
  source_tool?: string;
}

interface ExplainRequest {
  findings: Finding[];
  model?: string;
}

function buildExplanationPrompt(finding: Finding): string {
  const evidenceStr = finding.evidence
    ? typeof finding.evidence === "string"
      ? finding.evidence
      : JSON.stringify(finding.evidence, null, 2)
    : "No evidence provided";

  return `You are a security expert explaining a vulnerability to developers. Format your response using EXACTLY these markdown headers and structure:

## VULNERABILITY
1-2 sentences describing what this vulnerability is in plain English.

## ATTACK SCENARIO
How an attacker could exploit this step-by-step. Be specific and concrete.

## BUSINESS IMPACT
What could go wrong if this is not fixed. Focus on real consequences.

## FIX GUIDANCE
Concrete steps to fix this. Include code examples where applicable. Be actionable.

---

VULNERABILITY DETAILS:
- Type: ${finding.type}
- Severity: ${finding.severity}
- Endpoint: ${finding.endpoint}
- Confidence: ${((finding.confidence || 0) * 100).toFixed(0)}%
- Detected by: ${finding.source_tool || "unknown tool"}

EVIDENCE:
${evidenceStr}

IMPORTANT RULES:
- Use ONLY the four headers above: ## VULNERABILITY, ## ATTACK SCENARIO, ## BUSINESS IMPACT, ## FIX GUIDANCE
- Do not add any other headers or sections
- Keep each section to 2-4 sentences max
- Use markdown bullet points (- item) for steps within sections
- Be specific and technical but accessible
- Never hallucinate details not present in the evidence`;
}

async function callOpenRouter(apiKey: string, finding: Finding, model: string): Promise<string> {
  const prompt = buildExplanationPrompt(finding);

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
            "You are a cybersecurity expert explaining vulnerabilities to developers. Be factual, specific, and provide actionable fix guidance. Never hallucinate vulnerabilities not present in the evidence.",
        },
        { role: "user", content: prompt },
      ],
      temperature: 0.3,
      max_tokens: 500,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`OpenRouter error: ${response.status} - ${errorText}`);
  }

  const data = await response.json();
  return data.choices?.[0]?.message?.content || "No explanation generated";
}

// POST - Generate explanations for findings
export async function POST(request: NextRequest) {
  let redis: Redis | null = null;

  try {
    const session = await getServerSession(authOptions);

    if (!session?.user?.email) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body: ExplainRequest = await request.json();
    const { findings, model } = body;

    if (!findings || !Array.isArray(findings) || findings.length === 0) {
      return NextResponse.json({ error: "No findings provided" }, { status: 400 });
    }

    const findingsToExplain = findings.slice(0, 10);

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

    const explanations: Record<string, string> = {};
    const errors: Record<string, string> = {};

    for (const finding of findingsToExplain) {
      try {
        const explanation = await callOpenRouter(apiKey, finding, userModel);
        explanations[finding.id] = explanation;
      } catch (err) {
        const error = err as Error;
        errors[finding.id] = "An internal error occurred";
        explanations[finding.id] = "Error generating explanation";
      }
    }

    return NextResponse.json({
      success: true,
      explanations,
      errors: Object.keys(errors).length > 0 ? errors : undefined,
      count: findingsToExplain.length,
      provider: "openrouter",
      model: userModel,
    });
  } catch (error) {
    console.error("AI Explain error:", error);
    const err = error as Error;
    return NextResponse.json(
      { error: "Failed to generate explanations" },
      { status: 500 }
    );
  } finally {
    if (redis) redis.disconnect();
  }
}

// GET - Check if AI is configured
export async function GET() {
  let redis: Redis | null = null;

  try {
    const session = await getServerSession(authOptions);

    if (!session?.user?.email) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    redis = getRedisClient();
    const email = session.user.email;

    const apiKey = await redis.get(`settings:${email}:openrouter_api_key`);
    const preferredModel = await redis.get(`settings:${email}:preferred_ai_model`);

    return NextResponse.json({
      configured: !!apiKey,
      provider: apiKey ? "openrouter" : null,
      preferredModel: preferredModel || "anthropic/claude-3.5-sonnet",
    });
  } catch (error) {
    console.error("AI status check error:", error);
    return NextResponse.json({ error: "Failed to check AI status" }, { status: 500 });
  } finally {
    if (redis) redis.disconnect();
  }
}
