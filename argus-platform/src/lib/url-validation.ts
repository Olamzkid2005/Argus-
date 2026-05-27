/**
 * URL validation utilities for SSRF prevention and input sanitization.
 *
 * H-v3-03: Centralized validation to prevent duplicated code across
 * engagement API routes.
 */

/**
 * Validate that a URL does not target internal/private networks (SSRF prevention).
 *
 * Blocks requests to:
 * - Localhost / loopback (localhost, 127.0.0.1, ::1, 0.0.0.0)
 * - Private IPv4 ranges (10.x.x.x, 172.16-31.x.x, 192.168.x.x)
 * - Link-local (169.254.x.x)
 * - Multicast (224.x.x.x, 239.x.x.x)
 *
 * @param url - The URL to validate
 * @throws {Error} If the URL is invalid, uses a blocked protocol, or targets a blocked address
 */
export function validateTargetUrl(url: string): void {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error("Invalid URL format");
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("Only http:// and https:// URLs are allowed");
  }

  const hostname = parsed.hostname.toLowerCase();

  // Block localhost / loopback
  if (
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "::1" ||
    hostname === "0.0.0.0"
  ) {
    throw new Error("Requests to localhost/loopback are not allowed");
  }

  // Block private IPv4 ranges: 10.x.x.x, 172.16-31.x.x, 192.168.x.x
  if (
    /^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(hostname) ||
    /^172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3}$/.test(hostname) ||
    /^192\.168\.\d{1,3}\.\d{1,3}$/.test(hostname)
  ) {
    throw new Error("Requests to private IP addresses are not allowed");
  }

  // Block link-local and multicast
  if (
    /^169\.254\.\d{1,3}\.\d{1,3}$/.test(hostname) ||
    /^224\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(hostname) ||
    /^239\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(hostname)
  ) {
    throw new Error(
      "Requests to link-local/multicast addresses are not allowed",
    );
  }
}
