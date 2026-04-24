/**
 * Consolidated Zod-based validation module.
 *
 * Replaces validation.ts and requestValidation.ts with type-safe schemas.
 *
 * Usage:
 *   import { engagementSchema, loginSchema } from "@/lib/validation/consolidated";
 *   const result = engagementSchema.safeParse(data);
 */

import { z } from "zod";

// ─────────────────────────────────────────────────────────────
// Engagement schemas
// ─────────────────────────────────────────────────────────────

export const engagementSchema = z.object({
  targetUrl: z
    .string()
    .min(1, "Target URL is required")
    .refine(
      (url) => url.startsWith("http://") || url.startsWith("https://"),
      "Target URL must start with http:// or https://"
    ),
  scanType: z.enum(["url", "repo"], {
    message: "Scan type must be 'url' or 'repo'",
  }),
  authorization: z.string().min(1, "Authorization is required"),
  scope: z.string().optional(),
  aggressiveness: z.enum(["low", "medium", "high"]).optional(),
});

export type EngagementInput = z.infer<typeof engagementSchema>;

// ─────────────────────────────────────────────────────────────
// Auth schemas
// ─────────────────────────────────────────────────────────────

export const loginSchema = z.object({
  email: z
    .string()
    .min(1, "Email is required")
    .email("Invalid email format"),
  password: z.string().min(1, "Password is required"),
});

export type LoginInput = z.infer<typeof loginSchema>;

export const signupSchema = z
  .object({
    email: z
      .string()
      .min(1, "Email is required")
      .email("Invalid email format"),
    password: z
      .string()
      .min(12, "Password must be at least 12 characters")
      .max(128, "Password must be less than 128 characters")
      .refine(
        (pwd) => /[A-Z]/.test(pwd),
        "Password must contain at least one uppercase letter"
      )
      .refine(
        (pwd) => /[a-z]/.test(pwd),
        "Password must contain at least one lowercase letter"
      )
      .refine(
        (pwd) => /\d/.test(pwd),
        "Password must contain at least one number"
      )
      .refine(
        (pwd) => /[@$!%*?&]/.test(pwd),
        "Password must contain at least one special character (@$!%*?&)"
      ),
    passwordConfirm: z.string().min(1, "Password confirmation is required"),
    orgName: z
      .string()
      .min(2, "Organization name must be at least 2 characters"),
  })
  .refine((data) => data.password === data.passwordConfirm, {
    message: "Passwords don't match",
    path: ["passwordConfirm"],
  });

export type SignupInput = z.infer<typeof signupSchema>;

// ─────────────────────────────────────────────────────────────
// Rate limit schema
// ─────────────────────────────────────────────────────────────

export const rateLimitConfigSchema = z.object({
  requestsPerSecond: z
    .number()
    .min(1, "requestsPerSecond must be at least 1")
    .max(20, "requestsPerSecond must be at most 20")
    .optional(),
  concurrentRequests: z
    .number()
    .min(1, "concurrentRequests must be at least 1")
    .max(5, "concurrentRequests must be at most 5")
    .optional(),
});

export type RateLimitConfigInput = z.infer<typeof rateLimitConfigSchema>;

// ─────────────────────────────────────────────────────────────
// Finding filters schema
// ─────────────────────────────────────────────────────────────

export const findingFiltersSchema = z.object({
  severity: z
    .array(z.enum(["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]))
    .optional(),
  type: z.string().optional(),
  status: z.enum(["open", "verified", "false_positive", "fixed"]).optional(),
  tool: z.string().optional(),
  dateFrom: z.string().datetime().optional(),
  dateTo: z.string().datetime().optional(),
});

export type FindingFiltersInput = z.infer<typeof findingFiltersSchema>;

// ─────────────────────────────────────────────────────────────
// Utility schemas
// ─────────────────────────────────────────────────────────────

export const urlSchema = z
  .string()
  .url("Invalid URL format")
  .refine(
    (url) => url.startsWith("http://") || url.startsWith("https://"),
    "URL must use http:// or https://"
  );

export const emailSchema = z.string().email("Invalid email format");

// ─────────────────────────────────────────────────────────────
// Validation helper
// ─────────────────────────────────────────────────────────────

export function validate<T>(
  schema: z.ZodSchema<T>,
  data: unknown
): { valid: boolean; errors: string[]; data?: T } {
  const result = schema.safeParse(data);

  if (result.success) {
    return { valid: true, errors: [], data: result.data };
  }

  const errors = result.error.errors.map(
    (e) => `${e.path.join(".")}: ${e.message}`
  );
  return { valid: false, errors };
}

// ─────────────────────────────────────────────────────────────
// Backwards-compatible wrappers
// ─────────────────────────────────────────────────────────────

/** @deprecated Use engagementSchema.safeParse() instead */
export function validateEngagement(data: unknown): {
  valid: boolean;
  errors: string[];
} {
  return validate(engagementSchema, data);
}

/** @deprecated Use loginSchema.safeParse() instead */
export function validateLogin(data: unknown): {
  valid: boolean;
  errors: string[];
} {
  return validate(loginSchema, data);
}

/** @deprecated Use signupSchema.safeParse() instead */
export function validateSignup(data: unknown): {
  valid: boolean;
  errors: string[];
} {
  return validate(signupSchema, data);
}

/** @deprecated Use rateLimitConfigSchema.safeParse() instead */
export function validateRateLimitConfig(data: unknown): {
  valid: boolean;
  errors: string[];
} {
  return validate(rateLimitConfigSchema, data);
}

/** @deprecated Use urlSchema.safeParse() instead */
export function isValidUrl(url: string): boolean {
  return urlSchema.safeParse(url).success;
}

/** @deprecated Use emailSchema.safeParse() instead */
export function isValidEmail(email: string): boolean {
  return emailSchema.safeParse(email).success;
}
