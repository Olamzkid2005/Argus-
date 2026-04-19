/**
 * Request validation utilities
 */

export const DEFAULT_MAX_BODY_SIZE = 1024 * 1024; // 1MB
export const JSON_MAX_DEPTH = 10;

/**
 * Validate request body size
 */
export function validateBodySize(
  body: string | undefined,
  maxSize: number = DEFAULT_MAX_BODY_SIZE
): { valid: boolean; error?: string } {
  if (!body) {
    return { valid: true };
  }

  const size = new Blob([body]).size;

  if (size > maxSize) {
    return {
      valid: false,
      error: `Request body too large. Maximum size is ${Math.floor(maxSize / 1024)}KB`,
    };
  }

  return { valid: true };
}

/**
 * Validate JSON structure depth to prevent DoS
 */
export function validateJsonDepth(
  obj: unknown,
  maxDepth: number = JSON_MAX_DEPTH,
  currentDepth: number = 0
): boolean {
  if (currentDepth > maxDepth) {
    return false;
  }

  if (Array.isArray(obj)) {
    return obj.every((item) => validateJsonDepth(item, maxDepth, currentDepth + 1));
  }

  if (obj && typeof obj === "object") {
    return Object.values(obj as Record<string, unknown>).every((value) =>
      validateJsonDepth(value, maxDepth, currentDepth + 1)
    );
  }

  return true;
}

/**
 * Validate required fields
 */
export function validateRequiredFields(
  obj: Record<string, unknown>,
  required: string[]
): { valid: boolean; missing?: string } {
  for (const field of required) {
    if (
      !(field in obj) ||
      obj[field] === undefined ||
      obj[field] === null ||
      obj[field] === ""
    ) {
      return { valid: false, missing: field };
    }
  }

  return { valid: true };
}

/**
 * Rate limit configuration for different endpoints
 */
export const ENDPOINT_RATE_LIMITS = {
  // Auth endpoints - stricter limits
  "/api/auth/signup": { requests: 5, window: "60m" },
  "/api/auth/2fa": { requests: 10, window: "15m" },

  // Write operations - moderate limits
  "/api/engagements/write": { requests: 30, window: "60m" },
  "/api/findings/write": { requests: 100, window: "60m" },

  // Read operations - generous limits
  "/api/engagements": { requests: 200, window: "60m" },
  "/api/dashboard": { requests: 500, window: "60m" },
};