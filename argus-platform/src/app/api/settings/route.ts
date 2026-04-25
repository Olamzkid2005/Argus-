/**
 * Settings API - In-memory settings (stored in Redis for now)
 * 
 * GET /api/settings - Get all settings
 * PUT /api/settings - Update settings including API keys
 */
import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import Redis from "ioredis";
import { checkIdempotency, setAPIIdempotencyResult, generateAPIIdempotencyKey } from "@/lib/redis";

// Redis client for settings storage
function getRedisClient() {
  const redisUrl = process.env.REDIS_URL || "redis://localhost:6379";
  return new Redis(redisUrl, { 
    maxRetriesPerRequest: 1,
    lazyConnect: true 
  });
}

// GET - retrieve settings from Redis
export async function GET() {
  let redis: Redis | null = null;
  
  try {
    const session = await getServerSession(authOptions);
    
    if (!session?.user?.email) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    
    const email = session.user.email;
    redis = getRedisClient();
    
    const openrouterKey = await redis.get(`settings:${email}:openrouter_api_key`);
    const preferredModel = await redis.get(`settings:${email}:preferred_ai_model`);
    const scanAggressiveness = await redis.get(`settings:${email}:scan_aggressiveness`);
    const llmReviewEnabled = await redis.get(`settings:${email}:llm_review_enabled`);
    const llmPayloadGenEnabled = await redis.get(`settings:${email}:llm_payload_generation_enabled`);
    const llmMaxCost = await redis.get(`settings:${email}:llm_max_cost`);

    const settings: Record<string, string> = {};

    // Mask the key
    if (openrouterKey) {
      settings.openrouter_api_key = "sk-or-" + "•".repeat(20);
    }
    if (preferredModel) {
      settings.preferred_ai_model = preferredModel;
    }
    if (scanAggressiveness) {
      settings.scan_aggressiveness = scanAggressiveness;
    }
    if (llmReviewEnabled) {
      settings.llm_review_enabled = llmReviewEnabled;
    }
    if (llmPayloadGenEnabled) {
      settings.llm_payload_generation_enabled = llmPayloadGenEnabled;
    }
    if (llmMaxCost) {
      settings.llm_max_cost = llmMaxCost;
    }

    return NextResponse.json({ settings });
    
  } catch (error) {
    console.error("Settings GET error:", error);
    return NextResponse.json({ error: "Failed to get settings" }, { status: 500 });
  } finally {
    if (redis) {
      redis.disconnect();
    }
  }
}

// PUT - update settings in Redis
export async function PUT(request: NextRequest) {
  let redis: Redis | null = null;
  
  try {
    const session = await getServerSession(authOptions);
    
    if (!session?.user?.email) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    
    const body = await request.json();
    const { openrouter_api_key, preferred_ai_model, ...otherSettings } = body;
    const email = session.user.email;
    const userId = (session.user as { id?: string }).id || email;

    // Check idempotency
    const idempotencyKey = request.headers.get("x-idempotency-key");
    const cachedResult = await checkIdempotency(
      userId,
      "/api/settings",
      body,
      idempotencyKey || undefined
    );

    if (cachedResult) {
      return NextResponse.json(JSON.parse(cachedResult), { status: 200 });
    }
    
    redis = getRedisClient();
    
    // Store OpenRouter key (if not masked with •)
    if (openrouter_api_key && openrouter_api_key.length > 5 && !openrouter_api_key.includes("•")) {
      await redis.setex(`settings:${email}:openrouter_api_key`, 86400, openrouter_api_key);
    }
    
    // Store preferred model
    if (preferred_ai_model && typeof preferred_ai_model === "string" && preferred_ai_model.length > 0) {
      await redis.setex(`settings:${email}:preferred_ai_model`, 86400, preferred_ai_model);
    }
    
    // Store other settings
    for (const [key, value] of Object.entries(otherSettings)) {
      if (value && typeof value === "string" && value.length > 0) {
        await redis.setex(`settings:${email}:${key}`, 86400, value);
      }
    }
    
    const response = { success: true };

    // Store result for idempotency (24h TTL)
    const cacheKey = idempotencyKey || generateAPIIdempotencyKey(
      userId,
      "/api/settings",
      body
    );
    await setAPIIdempotencyResult(
      cacheKey,
      JSON.stringify(response)
    );

    return NextResponse.json(response);

  } catch (error) {
    console.error("Settings PUT error:", error);
    return NextResponse.json({ error: "Failed to update settings" }, { status: 500 });
  } finally {
    if (redis) {
      redis.disconnect();
    }
  }
}
