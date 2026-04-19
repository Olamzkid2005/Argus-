import Redis from "ioredis";
import { v4 as uuidv4 } from "uuid";
import crypto from "crypto";

// Redis client for job queue
const redis = new Redis(process.env.REDIS_URL || "redis://localhost:6379");

// Map job types to Celery task names
const TASK_NAME_MAP: Record<string, string> = {
  recon: "tasks.recon.run_recon",
  scan: "tasks.scan.run_scan",
  analyze: "tasks.analyze.run_analysis",
  report: "tasks.report.generate_report",
  repo_scan: "tasks.repo_scan.run_repo_scan",
};

// Map job types to positional arg order (matching Celery task signatures)
// recon: (engagement_id, target, budget, trace_id)
// scan: (engagement_id, targets, budget, trace_id)
// analyze: (engagement_id, budget, trace_id)
// report: (engagement_id, trace_id)
// repo_scan: (engagement_id, repo_url, budget, trace_id)

export interface JobMessage {
  type: "recon" | "scan" | "analyze" | "report" | "repo_scan";
  engagement_id: string;
  target: string;
  repo_url?: string;
  budget: {
    max_cycles: number;
    max_depth: number;
    max_cost: number;
  };
  trace_id: string;
  created_at: string;
}

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

/**
 * Build positional args for a Celery task based on job type
 */
function buildTaskArgs(job: JobMessage): unknown[] {
  switch (job.type) {
    case "recon":
      return [job.engagement_id, job.target, job.budget, job.trace_id];
    case "scan":
      return [job.engagement_id, [job.target], job.budget, job.trace_id];
    case "analyze":
      return [job.engagement_id, job.budget, job.trace_id];
    case "report":
      return [job.engagement_id, job.trace_id];
    case "repo_scan":
      return [
        job.engagement_id,
        job.repo_url || job.target,
        job.budget,
        job.trace_id,
      ];
    default:
      return [job.engagement_id, job.target, job.budget, job.trace_id];
  }
}

/**
 * Push a job to the Celery task queue using the proper Kombu message format
 */
export async function pushJob(job: JobMessage): Promise<string> {
  const jobId = uuidv4();

  // Generate idempotency key
  const idempotencyKey = generateIdempotencyKey(
    job.engagement_id,
    job.type,
    job.target,
  );

  // Use atomic SET NX (SET if Not eXists) for idempotency check-and-set
  // This prevents race conditions where two requests could both pass the check
  const key = `idempotency:${idempotencyKey}`;
  const wasSet = await redis.set(key, "processing", "EX", 3600, "NX");

  // If wasSet is null, another process already set this key - job is duplicate
  if (!wasSet) {
    return jobId; // Return jobId but don't push duplicate to queue
  }

  // Get the Celery task name
  const taskName =
    TASK_NAME_MAP[job.type] || `tasks.${job.type}.run_${job.type}`;

  // Build positional args matching the Celery task signature
  const args = buildTaskArgs(job);

  // Build the Celery/Kombu message in the format Celery expects
  // Format: [args, kwargs, embed, content_type, content_encoding]
  // But the JSON-encoded body format Celery uses is:
  // {"body": "<base64-encoded-json>", "content-encoding": "utf-8", "content-type": "application/json", "headers": {...}, "properties": {...}}
  const taskBody = {
    args: args,
    kwargs: {},
  };

  const taskBodyStr = JSON.stringify(taskBody);
  const taskBodyB64 = Buffer.from(taskBodyStr).toString("base64");

  const celeryMessage = JSON.stringify({
    body: taskBodyB64,
    "content-encoding": "utf-8",
    "content-type": "application/json",
    headers: {
      id: jobId,
      task: taskName,
      lang: "py",
      root_id: jobId,
      parent_id: null,
      group: null,
    },
    properties: {
      correlation_id: jobId,
      reply_to: jobId,
      delivery_mode: 2,
      delivery_info: {
        exchange: job.type,
        routing_key: job.type,
      },
      priority: 0,
      body_encoding: "base64",
      delivery_tag: jobId,
    },
  });

  const queueName = job.type;

  await redis.lpush(queueName, celeryMessage);

  return jobId;
}

/**
 * Get job status from Redis
 */
export async function getJobStatus(jobId: string): Promise<string | null> {
  return await redis.get(`celery-task-meta-${jobId}`);
}

export default redis;
