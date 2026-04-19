/**
 * Request timeout utilities
 */

export const DEFAULT_REQUEST_TIMEOUT = 30000; // 30 seconds
export const MAX_REQUEST_TIMEOUT = 120000; // 2 minutes

/**
 * Abort controller wrapper for request timeouts
 */
export function createTimeoutSignal(timeout: number = DEFAULT_REQUEST_TIMEOUT): {
  signal: AbortSignal;
  timeoutId: NodeJS.Timeout;
} {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => {
    controller.abort();
  }, timeout);

  return {
    signal: controller.signal,
    timeoutId,
  };
}

/**
 * Clear timeout
 */
export function clearTimeoutSignal(timeoutId: NodeJS.Timeout): void {
  clearTimeout(timeoutId);
}

/**
 * Check if error is abort error
 */
export function isAbortError(error: unknown): boolean {
  return (
    error instanceof DOMException && error.name === "AbortError"
  );
}

/**
 * Check if error is timeout error
 */
export function isTimeoutError(error: unknown): boolean {
  return isAbortError(error);
}