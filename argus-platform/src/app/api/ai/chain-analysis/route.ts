/**
 * AI Chain Analysis Endpoint - Uses OpenRouter for unified model access
 * 
 * POST /api/ai/chain-analysis
 * 
 * Analyzes ALL findings together and generates attack chain paths and takeover scenarios.
 */
import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import Redis from "ioredis";

function getRedisClient() {
  const redisUrl = process.env.REDIS_URL || "redis://localhost:6379";
  return new Redis(redisUrl, { maxRetriesPerRequest: 1, lazyConnect: true });
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

interface ChainRequest {
  findings: Finding[];
  model?: string;
}

function buildChainPrompt(findings: Finding[]): string {
  const findingsList = findings
    .map((f, i) => {
      const evidence = f.evidence
        ? typeof f.evidence === "string"
          ? f.evidence
          : JSON.stringify(f.evidence).substring(0, 200)
        : "No evidence";
      return `${i + 1}. ${f.type}
   Severity: ${f.severity}
   Endpoint: ${f.endpoint}
   Confidence: ${((f.confidence || 0) * 100).toFixed(0)}%
   Evidence: ${evidence}`;
    })
    .join("\n\n");

  return `You are an elite penetration tester analyzing a vulnerability assessment report. Your task is to identify how these vulnerabilities can be CHAINED TOGETHER to achieve a serious system takeover.

VULNERABILITIES FOUND:
${findingsList}

TASK - Provide a detailed attack chain analysis:

## 1. ATTACK CHAIN PATHS
Identify 2-4 realistic attack chains where vulnerabilities are exploited in sequence. For each chain:
- Name the chain (e.g., "Authentication Bypass → Privilege Escalation → Data Exfiltration")
- List the step-by-step exploitation path
- Explain the impact at each step
- Rate the chain: CRITICAL / HIGH / MEDIUM / LOW

## 2. SERIOUS TAKEOVER SCENARIOS
Describe the MOST DANGEROUS scenarios:
- Full system compromise: How an attacker could gain complete control
- Data breach: What sensitive data could be extracted
- Lateral movement: How they could move to other systems
- Persistence: How they could maintain access

## 3. CHAINING PREREQUISITES
For the most dangerous chains, explain:
- What conditions must be met
- What tools/knowledge the attacker needs
- Approximate time to exploitation
- Detection difficulty

## 4. DEFENSE PRIORITIES
Rank the findings by which MUST be fixed first to break the most dangerous chains.

FORMAT:
Use markdown-style formatting with clear headers. Be specific and technical. Include concrete examples. Do not hallucinate vulnerabilities not in the list.`;
}

async function callOpenRouter(apiKey: string, findings: Finding[], model: string): Promise<string> {
  const prompt = buildChainPrompt(findings);

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
            "You are an elite offensive security expert specializing in vulnerability chaining and attack path analysis. You think like an advanced persistent threat (APT) and identify how multiple seemingly minor vulnerabilities can be combined into serious system compromise. Be specific, technical, and actionable.",
        },
        { role: "user", content: prompt },
      ],
      temperature: 0.4,
      max_tokens: 2500,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`OpenRouter error: ${response.status} - ${errorText}`);
  }

  const data = await response.json();
  return data.choices?.[0]?.message?.content || "No analysis generated";
}

export async function POST(request: NextRequest) {
  let redis: Redis | null = null;

  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.email) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body: ChainRequest = await request.json();
    const { findings, model } = body;

    if (!findings || findings.length === 0) {
      return NextResponse.json({ error: "No findings provided" }, { status: 400 });
    }

    redis = getRedisClient();
    const email = session.user.email;

    const apiKey = await redis.get(`settings:${email}:openrouter_api_key`);
    const preferredModel = await redis.get(`settings:${email}:preferred_ai_model`);

    if (!apiKey) {
      return NextResponse.json(
        { error: "No OpenRouter API key configured", message: "Please configure your API key in Settings" },
        { status: 401 }
      );
    }

    const userModel = model || preferredModel || "anthropic/claude-3.5-sonnet";

    const analysis = await callOpenRouter(apiKey, findings, userModel);

    return NextResponse.json({
      success: true,
      analysis,
      findingCount: findings.length,
      provider: "openrouter",
      model: userModel,
    });
  } catch (error) {
    console.error("Chain Analysis error:", error);
    const err = error as Error;
    return NextResponse.json(
      { error: "Failed to generate chain analysis" },
      { status: 500 }
    );
  } finally {
    if (redis) redis.disconnect();
  }
}
