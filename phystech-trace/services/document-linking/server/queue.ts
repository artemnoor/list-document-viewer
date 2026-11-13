import { Queue } from "bullmq";
import IORedis from "ioredis";

export const ANALYSIS_QUEUE_NAME = "document-linking-analysis";
export type AnalysisQueue = { enqueue(jobId: string, resume?: boolean): Promise<void>; health(): Promise<void>; close(): Promise<void> };
export function createAnalysisQueue(redisUrl: string, queueName = ANALYSIS_QUEUE_NAME): AnalysisQueue {
  const connection = new IORedis(redisUrl, { maxRetriesPerRequest: null });
  const queue = new Queue<{ job_id: string }>(queueName, { connection });
  return {
    async enqueue(jobId, resume = false) {
      if (resume) {
        // Requeue terminal jobs atomically. Removing a finished job and adding
        // it again leaves a race where another recovery pass can observe the
        // gap and a worker can consume a replacement before the add resolves.
        for (let attempt = 0; attempt < 3; attempt++) {
          const existing = await queue.getJob(jobId);
          if (!existing) break;
          const state = await existing.getState();
          if (state === "completed" || state === "failed") {
            try {
              await existing.retry(state, { resetAttemptsMade: true, resetAttemptsStarted: true });
              return;
            } catch {
              // Another recovery worker may have moved it first. Treat any
              // nonterminal state as already recovered; retry a still-terminal
              // record on the next iteration.
              const current = await queue.getJob(jobId);
              if (!current) break;
              const currentState = await current.getState();
              if (currentState !== "completed" && currentState !== "failed") return;
            }
            continue;
          }
          // Waiting, active and delayed jobs are already represented in Redis.
          return;
        }
        const remaining = await queue.getJob(jobId);
        if (remaining) {
          const state = await remaining.getState();
          if (state === "completed" || state === "failed") throw new Error(`BullMQ could not requeue terminal job ${jobId} after three atomic attempts`);
          return;
        }
      }
      await queue.add("analyze-document-set", { job_id: jobId }, {
        jobId, attempts: 5, backoff: { type: "polza-exponential", delay: 3000 },
        removeOnComplete: { age: 86_400, count: 1000 }, removeOnFail: { age: 604_800, count: 5000 },
      });
    },
    async health() { await connection.ping(); },
    async close() { await queue.close(); await connection.quit(); },
  };
}
