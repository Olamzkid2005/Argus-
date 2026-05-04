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

interface TestRequest {
  apiKey?: string;
  model?: string;
}

export async function POST(request: NextRequest) {
  let redis: Redis | null = null;

  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.email) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body = (await request.json()) as TestRequest;
    const providedApiKey =
      body.apiKey && !body.apiKey.includes("•") ? body.apiKey.trim() : "";
    const requestedModel = body.model?.trim();

    redis = getRedisClient();
    const email = session.user.email;

    const savedApiKey = await redis.get(`settings:${email}:openrouter_api_key`);
    const savedModel = await redis.get(`settings:${email}:preferred_ai_model`);

    const apiKey = providedApiKey || savedApiKey;
    if (!apiKey) {
      return NextResponse.json(
        {
          ok: false,
          error: "No OpenRouter API key configured",
          message: "Add an API key in Settings before testing.",
        },
        { status: 400 }
      );
    }

    const model = requestedModel || savedModel || "anthropic/claude-3.5-sonnet";

    const response = await fetch("https://openrouter.ai/api/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
        "HTTP-Referer": process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000",
        "X-Title": "Argus Pentest Platform",
      },
      body: JSON.stringify({
        model,
        messages: [
          {
            role: "system",
            content:
              "You are a concise assistant used for connectivity checks. Keep responses short and plain text.",
          },
          {
            role: "user",
            content:
              "This is a connectivity test from Argus Settings. Reply with a short confirmation that includes the word 'connected'.",
          },
        ],
        temperature: 0.2,
        max_tokens: 80,
      }),
    });

    if (!response.ok) {
      return NextResponse.json(
        {
          ok: false,
          error: `OpenRouter error (${response.status})`,
          model,
        },
        { status: 502 }
      );
    }

    const data = await response.json();
    const message = data?.choices?.[0]?.message?.content?.trim() || "Connected";

    return NextResponse.json({
      ok: true,
      provider: "openrouter",
      model,
      message,
    });
  } catch (error) {
    const err = error as Error;
    return NextResponse.json(
      {
        ok: false,
        error: "Failed to test AI connection",
      },
      { status: 500 }
    );
  } finally {
    if (redis) redis.disconnect();
  }
}
