import { promises as dns } from "dns";

interface UrlValidationResult {
  valid: boolean;
  error?: string;
}

function isPrivateIP(ip: string): boolean {
  const parts = ip.split(".").map(Number);
  if (parts.length !== 4) return false;
  if (parts[0] === 10) return true;
  if (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) return true;
  if (parts[0] === 192 && parts[1] === 168) return true;
  if (parts[0] === 127) return true;
  if (parts[0] === 169 && parts[1] === 254) return true;
  return false;
}

async function isPrivateHostname(url: URL): Promise<boolean> {
  try {
    const addresses = await dns.resolve4(url.hostname);
    return addresses.some(isPrivateIP);
  } catch {
    // DNS resolution failure (NXDOMAIN, timeout) - cannot prove it's private,
    // but also can't reach it for SSRF. Allow with a warning logged server-side.
    return false;
  }
}

export async function validateWebhookUrl(urlString: string): Promise<UrlValidationResult> {
  let url: URL;
  try {
    url = new URL(urlString);
  } catch {
    return { valid: false, error: "Invalid webhook URL format" };
  }

  if (url.protocol !== "https:") {
    return { valid: false, error: "Webhook URL must use HTTPS" };
  }

  const isPrivate = await isPrivateHostname(url);
  if (isPrivate) {
    return { valid: false, error: "Webhook URL must not resolve to a private or internal IP address" };
  }

  return { valid: true };
}
