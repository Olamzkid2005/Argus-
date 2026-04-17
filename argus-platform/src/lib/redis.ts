import Redis from "ioredis";
import { v4 as uuidv4 } from "uuid";
import crypto from "crypto";

// Redis client for job queue
const redis = new Redis(process.env.REDIS_URL || "redis://localhost:6379");

export interface JobMessage {
  type: "recon" | "scan" | "analyze" | "report";
  engagement_id: string;
  target: string;
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
  target: string
): string {
  const data = `${engagementId}:${jobType}:${target}`;
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
 * Push a job to the Redis queue
 */
export async function pushJob(job: JobMessage): Promise<string> {
  const jobId = uuidv4();
  
  // Generate idempotency key
  const idempotencyKey = generateIdempotencyKey(
    job.engagement_id,
    job.type,
    job.target
  );

  // Check if job already processed
  if (await isJobProcessed(idempotencyKey)) {
    console.log(`Job already processed: ${idempotencyKey}`);
    return jobId;
  }

  // Mark as processing
  await markJobProcessing(idempotencyKey);

  const jobData = {
    ...job,
    job_id: jobId,
    idempotency_key: idempotencyKey,
  };

  // Push to Celery queue format
  // Celery expects: [args, kwargs, embed]
  const celeryMessage = JSON.stringify([
    [], // args
    jobData, // kwargs
    {
      callbacks: null,
      errbacks: null,
      chain: null,
      chord: null,
    },
  ]);

  // Push to the appropriate queue based on job type
  const queueName = `celery:${job.type}`;
  
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
