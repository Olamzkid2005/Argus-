/**
 * Settings API - In-memory settings (stored in Redis for now)
 * 
 * GET /api/settings - Get all settings
 * PUT /api/settings - Update settings including API keys
 */
import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { redis, checkIdempotency, setAPIIdempotencyResult, generateAPIIdempotencyKey } from "@/lib/redis";
import { log as logger } from "@/lib/logger";

// GET - retrieve settings from Redis
export async function GET() {
  try {
    const session = await getServerSession(authOptions);
    
    if (!session?.user?.email) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    
    const email = session.user.email;
    
    const openrouterKey = await redis.get(`settings:${email}:openrouter_api_key`);
    const preferredModel = await redis.get(`settings:${email}:preferred_ai_model`);
    const scanAggressiveness = await redis.get(`settings:${email}:scan_aggressiveness`);
    const llmReviewEnabled = await redis.get(`settings:${email}:llm_review_enabled`);
    const llmPayloadGenEnabled = await redis.get(`settings:${email}:llm_payload_generation_enabled`);
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

    return NextResponse.json({ settings });
    
  } catch (error) {
    console.error("Settings GET error:", error instanceof Error ? error.message : String(error));
    return NextResponse.json({ error: "Failed to get settings" }, { status: 500 });
  }
}

// PUT - update settings in Redis
export async function PUT(request: NextRequest) {
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
    
    // Store OpenRouter key (if not masked with •)
    if (openrouter_api_key && openrouter_api_key.length > 5 && !openrouter_api_key.includes("•")) {
      await redis.setex(`settings:${email}:openrouter_api_key`, 2592000, openrouter_api_key);
    }
    
    // Store preferred model
    if (preferred_ai_model && typeof preferred_ai_model === "string" && preferred_ai_model.length > 0) {
      await redis.setex(`settings:${email}:preferred_ai_model`, 2592000, preferred_ai_model);
    }
    
    // Store other settings — only allow known setting keys (H-15)
    const ALLOWED_SETTING_KEYS = new Set([
      'scan_aggressiveness',
      'llm_review_enabled',
      'llm_payload_generation_enabled',
      'preferred_ai_model',
      'scan_timeout',
      'max_concurrent_scans',
      'notification_email',
      'webhook_url',
    ]);
    for (const [key, value] of Object.entries(otherSettings)) {
      if (!ALLOWED_SETTING_KEYS.has(key)) {
        logger.warn(`Blocked attempt to set unknown setting key: ${key}`);
        continue;
      }
      if (value && typeof value === "string" && value.length > 0) {
        await redis.setex(`settings:${email}:${key}`, 2592000, value);
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
    console.error("Settings PUT error:", error instanceof Error ? error.message : String(error));
    return NextResponse.json({ error: "Failed to update settings" }, { status: 500 });
  }
}
