import Redis from "ioredis";
import { v4 as uuidv4 } from "uuid";
import crypto from "crypto";
import { spawn } from "child_process";
import path from "path";

// Redis client for job queue
const redis = new Redis(process.env.REDIS_URL || "redis://localhost:6379");

// Map job types to Celery task names
const TASK_NAME_MAP: Record<string, string> = {
  recon: "tasks.recon.run_recon",
  scan: "tasks.scan.run_scan",
  analyze: "tasks.analyze.run_analysis",
  report: "tasks.report.generate_report",
  repo_scan: "tasks.repo_scan.run_repo_scan",
  compliance_report: "tasks.report.generate_compliance_report",
};

// Map job types to positional arg order (matching Celery task signatures)
// recon: (engagement_id, target, budget, trace_id)
// scan: (engagement_id, targets, budget, trace_id)
// analyze: (engagement_id, budget, trace_id)
// report: (engagement_id, trace_id)
// repo_scan: (engagement_id, repo_url, budget, trace_id)
// compliance_report: (engagement_id, standard, trace_id)

export interface JobMessage {
  type: "recon" | "scan" | "analyze" | "report" | "repo_scan" | "compliance_report";
  engagement_id: string;
  target: string;
  repo_url?: string;
  standard?: string;
  budget: {
    max_cycles: number;
    max_depth: number;
    max_cost: number;
  };
  aggressiveness?: string;
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
    case "compliance_report":
      return [
        job.engagement_id,
        job.standard || "owasp_top10",
        job.trace_id,
      ];
    default:
      return [job.engagement_id, job.target, job.budget, job.trace_id];
  }
}

/**
 * Push a job to the Celery task queue by dispatching through Python script
 * 
 * This properly dispatches tasks to Celery rather than manually pushing to Redis lists
 * which bypasses Celery's broker mechanism.
 */
export async function pushJob(job: JobMessage): Promise<string> {
  const traceId = job.trace_id || uuidv4();

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
    return traceId; // Return jobId but don't push duplicate to queue
  }

  // Execute the Python dispatch script
  return new Promise((resolve, reject) => {
    // Fixed path - go up from argus-platform to root
    const workersRoot = path.join(process.cwd(), "..");
    const dispatchScript = path.join(workersRoot, "argus-workers", "dispatch_task.py");
    const pythonPath = path.join(workersRoot, "argus-workers", "venv", "bin", "python");

    // Build the job payload matching dispatch_task.py expectations
    const jobPayload = {
      type: job.type,
      engagement_id: job.engagement_id,
      target: job.target,
      repo_url: job.repo_url,
      standard: job.standard,
      budget: job.budget,
      trace_id: traceId,
    };

    const child = spawn(pythonPath, [dispatchScript], {
      cwd: workersRoot,
      env: {
        ...process.env,
        PYTHONPATH: workersRoot,
      },
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (data) => {
      stdout += data.toString();
    });

    child.stderr.on("data", (data) => {
      stderr += data.toString();
    });

    child.on("close", (code) => {
      if (code !== 0) {
        console.error("dispatch_task.py error:", stderr);
        reject(new Error(`dispatch_task.py exited with code ${code}: ${stderr}`));
        return;
      }

      try {
        const result = JSON.parse(stdout.trim());
        resolve(result.task_id);
      } catch (e) {
        reject(new Error(`Failed to parse dispatch result: ${stdout}`));
      }
    });

    child.stdin.write(JSON.stringify(jobPayload));
    child.stdin.end();
  });
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
            onComplete?.(progress.result);
            resolve(progress.result);
            return;
          }

          if (progress.status === "failed") {
            const error = progress.error_message || "Task failed";
            onError?.(error);
            reject(new Error(error));
            return;
          }

          if (progress.status === "cancelled") {
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
            onComplete?.(data.result);
            resolve(data.result);
            return;
          }
          if (data.status === "FAILURE") {
            onError?.(data.result);
            reject(new Error(data.result));
            return;
          }
        }

        // Check timeout
        if (Date.now() - startTime > timeout) {
          reject(new Error("Job polling timeout"));
          return;
        }

        // Schedule next check
        setTimeout(checkStatus, interval);
      } catch (error) {
        reject(error);
      }
    };

    checkStatus();
  });
}

/**
 * Cancel a running job
 */
export async function cancelJob(jobId: string): Promise<boolean> {
  try {
    // Revoke Celery task
    const { spawn } = await import("child_process");
    const path = await import("path");

    const workersRoot = path.join(process.cwd(), "..");
    const pythonPath = path.join(
      workersRoot,
      "argus-workers",
      "venv",
      "bin",
      "python"
    );

    const child = spawn(
      pythonPath,
      ["-m", "celery", "-A", "celery_app", "control", "revoke", jobId, "--terminate"],
      { cwd: workersRoot }
    );

    return new Promise((resolve) => {
      child.on("close", (code) => {
        // Also mark as cancelled in progress tracker
        redis.setex(
          `task:progress:${jobId}`,
          3600,
          JSON.stringify({
            status: "cancelled",
            updated_at: new Date().toISOString(),
          })
        );

        resolve(code === 0);
      });
    });
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

export default redis;
