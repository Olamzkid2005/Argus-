/**
 * Input sanitization utilities for security
 */

// Remove null bytes and control characters
export function sanitizeString(input: string): string {
  if (typeof input !== "string") {
    return "";
  }

  // Remove null bytes and other control characters (except newlines, tabs)
  return input.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, "").trim();
}

// Sanitize URL
export function sanitizeUrl(input: string): string {
  if (typeof input !== "string") {
    return "";
  }

  try {
    const url = new URL(input);

    // Only allow http and https
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return "";
    }

    return url.toString();
  } catch {
    return "";
  }
}

// Sanitize email
export function sanitizeEmail(input: string): string {
  if (typeof input !== "string") {
    return "";
  }

  // Basic email validation and sanitization
  const email = input.toLowerCase().trim();
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  if (!emailRegex.test(email)) {
    return "";
  }

  // Remove potential injection characters
  return email.replace(/[<>'"()]/g, "");
}

// Sanitize SQL wildcard characters (for LIKE queries)
export function sanitizeSqlWildcard(input: string): string {
  if (typeof input !== "string") {
    return "";
  }

  // Escape LIKE wildcards
  return input.replace(/[%_]/g, "\\$&").replace(/\\/g, "\\\\");
}

// Strip HTML tags
export function stripHtml(input: string): string {
  if (typeof input !== "string") {
    return "";
  }

  return input.replace(/<[^>]*>/g, "");
}

// Normalize whitespace
export function normalizeWhitespace(input: string): string {
  if (typeof input !== "string") {
    return "";
  }

  return input.replace(/\s+/g, " ").trim();
}

// Validate and sanitize UUID
export function sanitizeUuid(input: string): string | null {
  if (typeof input !== "string") {
    return null;
  }

  const uuidRegex =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const trimmed = input.trim();

  if (!uuidRegex.test(trimmed)) {
    return null;
  }

  return trimmed.toLowerCase();
}

// Validate IP address
export function sanitizeIp(input: string): string | null {
  if (typeof input !== "string") {
    return null;
  }

  const trimmed = input.trim();

  // IPv4
  const ipv4Regex = /^(\d{1,3}\.){3}\d{1,3}$/;
  // IPv6 (simplified)
  const ipv6Regex = /^([0-9a-f]{1,4}:){1,7}[0-9a-f]{1,4}$/i;

  if (ipv4Regex.test(trimmed) || ipv6Regex.test(trimmed)) {
    return trimmed;
  }

  return null;
}

// Sanitize filename (for uploads - remove path traversal)
export function sanitizeFilename(input: string): string {
  if (typeof input !== "string") {
    return "";
  }

  // Remove path traversal attempts — strip ".." but keep single dots (e.g., file extensions)
  const filename = input
    .replace(/\.\./g, "")
    .replace(/[^a-zA-Z0-9_.-]/g, "_")
    .substring(0, 255);

  return filename;
}
