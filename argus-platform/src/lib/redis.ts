import Redis from "ioredis";
import { v4 as uuidv4 } from "uuid";
import crypto from "crypto";

import type { JobMessage } from "./job-types";
import { TASK_NAME_MAP } from "./job-types";

// Redis client for job queue (singleton via globalThis to survive hot reloads)
const globalForRedis = globalThis as unknown as { __redis?: Redis };

function createRedisClient(): Redis {
  const url = process.env.REDIS_URL || "redis://localhost:6379";
  const enableTLS = ["true", "1", "yes"].includes((process.env.REDIS_TLS || "").toLowerCase())
    || url.startsWith("rediss://");

  const options: import("ioredis").RedisOptions = {
    maxRetriesPerRequest: 3,
    retryStrategy: (times: number) => {
      if (times > 5) return null; // Give up after 5 retries
      return Math.min(times * 200, 3000); // Exponential backoff up to 3s
    },
    enableOfflineQueue: false,
    lazyConnect: false,
  };

  // Configure TLS if enabled via REDIS_TLS env var or rediss:// protocol
  if (enableTLS) {
    options.tls = {
      rejectUnauthorized: process.env.NODE_ENV !== "development", // secure default: reject unauthorized in prod/staging; permissive only in dev
    };
  }

  const client = new Redis(url, options);

  // Prevent unhandled error events from crashing the process
  client.on("error", (err: Error) => {
    console.error("Redis connection error:", err.message);
  });

  return client;
}

const redis = globalForRedis.__redis ?? (globalForRedis.__redis = createRedisClient());

/**
 * Generate idempotency key for a job
 */
export function generateIdempotencyKey(
  engagementId: string,
  jobType: string,
  target: string,
): string {
  // For repo_scan, use repo_url as target
  const data = `${engagementId}:${jobType}:${target || ""}`;
  return crypto.createHash("sha256").update(data).digest("hex");
}

/**
 * Check if job has already been processed
 */
export async function isJobProcessed(idempotencyKey: string): Promise<boolean> {
  const status = await redis.get(`idempotency:${idempotencyKey}`);
  return status === "complete" || status === "processing";
}

/**
 * Mark job as processing
 */
export async function markJobProcessing(idempotencyKey: string): Promise<void> {
  // Set with 1 hour TTL
  await redis.setex(`idempotency:${idempotencyKey}`, 3600, "processing");
}

/**
 * Mark job as complete
 */
export async function markJobComplete(idempotencyKey: string): Promise<void> {
  // Set with 1 hour TTL
  await redis.setex(`idempotency:${idempotencyKey}`, 3600, "complete");
}

// ============================================
// API Idempotency for POST/PUT operations
// ============================================

/**
 * Generate idempotency key for API operations (POST/PUT)
 * 
 * Combines user ID, endpoint, and request body hash to create a unique key
 */
export function generateAPIIdempotencyKey(
  userId: string,
  endpoint: string,
  body: Record<string, unknown>
): string {
  const bodyHash = crypto.createHash("sha256").update(JSON.stringify(body)).digest("hex");
  const data = `${userId}:${endpoint}:${bodyHash}`;
  return crypto.createHash("sha256").update(data).digest("hex");
}

/**
 * Check if an API request has already been processed
 * Returns the previous response if found, null otherwise
 */
export async function getAPIIdempotencyResult(key: string): Promise<string | null> {
  return await redis.get(`api_idempotency:${key}`);
}

/**
 * Store API response for idempotency.
 *
 * @param key - The idempotency key
 * @param response - The response JSON to cache
 * @param ttlSeconds - TTL in seconds (default: 24 hours, pass a short TTL for
 *                     processing markers to avoid stuck keys if the request fails)
 */
export async function setAPIIdempotencyResult(
  key: string,
  response: string,
  ttlSeconds: number = 86400,
): Promise<void> {
  await redis.setex(`api_idempotency:${key}`, ttlSeconds, response);
}

/**
 * Check if request is a retry (has idempotency key) and return cached result if exists
 */
export async function checkIdempotency(
  userId: string,
  endpoint: string,
  body: Record<string, unknown>,
  idempotencyKey?: string
): Promise<string | null> {
  // Use provided key or generate one
  const key = idempotencyKey || generateAPIIdempotencyKey(userId, endpoint, body);
  return await getAPIIdempotencyResult(key);
}

/**
 * Queue name mapping — mirrors Celery task_routes in celery_app.py.
 */
function queueForJobType(jobType: string): string {
  if (jobType.startsWith("tasks.recon")) return "recon";
  if (jobType.startsWith("tasks.scan")) return "scan";
  if (jobType.startsWith("tasks.analyze") || jobType.startsWith("tasks.posture")) return "analyze";
  if (jobType.startsWith("tasks.report")) return "report";
  if (jobType.startsWith("tasks.repo_scan")) return "repo_scan";
  return "celery"; // default queue
}

/**
 * Build positional arguments matching build_task_args() in job_schema.py.
 */
function buildCeleryArgs(job: JobMessage): unknown[] {
  const { type, engagement_id, target, budget, trace_id } = job;
  const agent_mode = job.agent_mode ?? true;
  const repo_url = job.repo_url || target;

  switch (type) {
    case "recon":
      return [engagement_id, target, budget, trace_id, agent_mode, job.scan_mode ?? null, job.aggressiveness ?? null, job.bug_bounty_mode ?? null, job.auth_config ?? null, job.dual_auth_config ?? null];
    case "scan":
      return [engagement_id, [target], budget, trace_id, agent_mode, job.scan_mode ?? null, job.aggressiveness ?? null, job.bug_bounty_mode ?? null, job.auth_config ?? null, job.dual_auth_config ?? null];
    case "analyze":
      return [engagement_id, budget, trace_id];
    case "report":
      return [engagement_id, trace_id, budget ?? {}];
    case "repo_scan":
      return [engagement_id, repo_url, budget, trace_id, null, job.auth_config ?? null, job.dual_auth_config ?? null];
    case "compliance_report":
      return [engagement_id, job.standard ?? null, trace_id];
    case "full_report":
      return [engagement_id, job.report_id ?? ""];
    case "asset_discovery":
      return [engagement_id, target, trace_id, job.org_id ?? null];
    case "asset_risk_scoring":
      return [engagement_id];
    case "bugbounty_report":
      return [engagement_id, job.platform ?? "hackerone", job.output_path ?? "", trace_id];
    case "posture_recompute":
      return [engagement_id, job.org_id ?? null];
    default:
      throw new Error(`Unknown job type: ${type}`);
  }
}

/**
 * Push a job to the Celery task queue via direct Redis LPUSH.
 *
 * Replaces the previous approach of spawning a Python subprocess per job
 * (dispatch_task.py), which added ~300ms overhead per dispatch from process
 * creation + Python interpreter startup.
 *
 * Uses Celery v5.x Redis message format with JSON serialization.
 * A persistent task ID is returned for tracking.
 */
export async function pushJob(job: JobMessage): Promise<string> {
  const traceId = job.trace_id || uuidv4();

  // Generate idempotency key
  const idempotencyKey = generateIdempotencyKey(
    job.engagement_id,
    job.type,
    job.target,
  );

  // Use atomic Lua script for idempotency check-and-set.
  // Prevents race condition between redis.del() and the next redis.set()
  // where two concurrent processes could both observe a stuck key, delete it,
  // and each proceed to enqueue a job.
  const key = `idempotency:${idempotencyKey}`;
  const luaScript = `
    local current = redis.call('GET', KEYS[1])
    if current == false then
      redis.call('SET', KEYS[1], 'processing', 'EX', ARGV[1])
      return 1
    end
    if current == 'processing' then
      local ttl = redis.call('TTL', KEYS[1])
      if ttl > tonumber(ARGV[2]) then
        return 0  -- genuine duplicate
      end
      redis.call('DEL', KEYS[1])
      redis.call('SET', KEYS[1], 'processing', 'EX', ARGV[1])
      return 2  -- recovered stuck key
    end
    return 3  -- already complete
  `;
  const result = await redis.eval(
    luaScript,
    1,
    key,
    "3600",
    "500",  // M-24: Lower threshold to 500s (was 3500s) — only restart jobs whose TTL has almost expired (remaining < 500s)
  ) as number;

  if (result === 0) {
    // Genuine duplicate — job already being processed by another request
    return traceId;
  }

  if (result === 3) {
    // Already completed within idempotency window — treat as duplicate
    return traceId;
  }

  // ── Direct Redis LPUSH to Celery broker queue ──
  // This replaces the Python subprocess dispatch (M-08).
  // Celery v5.x Redis message format (JSON serializer, v2 message):

  const taskName = TASK_NAME_MAP[job.type];
  if (!taskName) {
    throw new Error(`Unknown job type: ${job.type}`);
  }

  const taskId = uuidv4();
  const queueName = queueForJobType(taskName);

  // Build positional args matching Celery task signature
  const args = buildCeleryArgs(job);

  // Celery body format: [args, kwargs, embed]
  // where embed = {callbacks, errbacks, chain, chord} or null
  const bodyJson = JSON.stringify([args, {}, null]);
  const bodyBase64 = Buffer.from(bodyJson).toString("base64");

  // v2 message format (Celery 5.x)
  const message = JSON.stringify({
    body: bodyBase64,
    "content-encoding": "utf-8",
    "content-type": "application/json",
    headers: {
      task: taskName,
      id: taskId,
      root_id: taskId,
      parent_id: null,
      group: null,
      retries: 0,
      timelimit: [null, null],
    },
    properties: {
      correlation_id: taskId,
      delivery_mode: 2,
      delivery_info: {
        priority: 0,
        routing_key: queueName,
      },
      priority: 0,
      body_encoding: "base64",
    },
  });

  // LPUSH to the queue list — Celery workers BRPOP from the right
  await redis.lpush(queueName, message);

  return taskId;
}

/**
 * Get job status from Redis
 */
export async function getJobStatus(jobId: string): Promise<string | null> {
  return await redis.get(`celery-task-meta-${jobId}`);
}

/**
 * Poll job status with progress tracking
 */
export async function pollJobStatus(
  jobId: string,
  options: {
    onProgress?: (progress: {
      status: string;
      percent: number;
      activity: string;
    }) => void;
    onComplete?: (result: unknown) => void;
    onError?: (error: string) => void;
    interval?: number;
    timeout?: number;
  } = {}
): Promise<unknown> {
  const {
    onProgress,
    onComplete,
    onError,
    interval = 2000,
    timeout = 600000, // 10 minutes
  } = options;

  const startTime = Date.now();

  return new Promise((resolve, reject) => {
    let timerId: ReturnType<typeof setTimeout> | null = null;

    const cleanup = () => {
      if (timerId !== null) {
        clearTimeout(timerId);
        timerId = null;
      }
    };

    const checkStatus = async () => {
      try {
        // Check progress first
        const progressKey = `task:progress:${jobId}`;
        const progressData = await redis.get(progressKey);

        if (progressData) {
          const progress = JSON.parse(progressData);
          onProgress?.({
            status: progress.status,
            percent: progress.percent_complete || 0,
            activity: progress.current_activity || "Processing...",
          });

          if (progress.status === "completed") {
            cleanup();
            onComplete?.(progress.result);
            redis.del(progressKey).catch(() => {});
            resolve(progress.result);
            return;
          }

          if (progress.status === "failed") {
            cleanup();
            const error = progress.error_message || "Task failed";
            onError?.(error);
            redis.del(progressKey).catch(() => {});
            reject(new Error(error));
            return;
          }

          if (progress.status === "cancelled") {
            cleanup();
            const error = "Task was cancelled";
            onError?.(error);
            reject(new Error(error));
            return;
          }
        }

        // Check Celery result
        const meta = await redis.get(`celery-task-meta-${jobId}`);
        if (meta) {
          const data = JSON.parse(meta);
          if (data.status === "SUCCESS") {
            cleanup();
            onComplete?.(data.result);
            resolve(data.result);
            return;
          }
          if (data.status === "FAILURE") {
            cleanup();
            onError?.(data.result);
            reject(new Error(data.result));
            return;
          }
        }

        // Check timeout
        if (Date.now() - startTime > timeout) {
          cleanup();
          reject(new Error("Job polling timeout"));
          return;
        }

        // Schedule next check
        timerId = setTimeout(checkStatus, interval);
      } catch (error) {
        cleanup();
        reject(error);
      }
    };

    checkStatus();
  });
}

/**
 * Cancel a running job via Redis.
 *
 * Marks the job as cancelled in the progress tracker. The Celery task
 * checks this key via its abort mechanism. Direct Celery revoke via
 * broadcast is not available without Python subprocess, but the progress
 * tracker key is what the frontend checks and what tasks monitor.
 *
 * Replaces previous Python subprocess approach (M-08).
 */
export async function cancelJob(jobId: string): Promise<boolean> {
  try {
    await redis.setex(
      `task:progress:${jobId}`,
      3600,
      JSON.stringify({
        status: "cancelled",
        updated_at: new Date().toISOString(),
      })
    );
    return true;
  } catch {
    return false;
  }
}

/**
 * Get task progress
 */
export async function getTaskProgress(
  jobId: string
): Promise<{
  status: string;
  percent: number;
  activity: string;
  metadata?: Record<string, unknown>;
} | null> {
  try {
    const data = await redis.get(`task:progress:${jobId}`);
    if (!data) return null;

    const progress = JSON.parse(data);
    return {
      status: progress.status,
      percent: progress.percent_complete || 0,
      activity: progress.current_activity || "Processing...",
      metadata: progress.metadata,
    };
  } catch {
    return null;
  }
}

export { redis };
export default redis;
