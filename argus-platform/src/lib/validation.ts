// Simple validation utilities
// Engagement validation
export function validateEngagement(data: unknown): {
  valid: boolean;
  errors: string[];
} {
  const errors: string[] = [];
  const d = data as {
    targetUrl?: string;
    scanType?: string;
    authorization?: string;
  };

  if (!d.targetUrl) {
    errors.push("Target URL is required");
  } else if (
    !d.targetUrl.startsWith("http://") &&
    !d.targetUrl.startsWith("https://")
  ) {
    errors.push("Target URL must start with http:// or https://");
  }

  if (!d.scanType || !["url", "repo"].includes(d.scanType)) {
    errors.push("Scan type must be 'url' or 'repo'");
  }

  if (!d.authorization) {
    errors.push("Authorization is required");
  }

  return { valid: errors.length === 0, errors };
}

// Login validation
export function validateLogin(data: unknown): {
  valid: boolean;
  errors: string[];
} {
  const errors: string[] = [];
  const d = data as { email?: string; password?: string };

  if (!d.email) {
    errors.push("Email is required");
  } else if (!d.email.includes("@")) {
    errors.push("Invalid email format");
  }

  if (!d.password) {
    errors.push("Password is required");
  }

  return { valid: errors.length === 0, errors };
}

// Signup validation
export function validateSignup(data: unknown): {
  valid: boolean;
  errors: string[];
} {
  const errors: string[] = [];
  const d = data as {
    email?: string;
    password?: string;
    passwordConfirm?: string;
    orgName?: string;
  };

  if (!d.email) {
    errors.push("Email is required");
  } else if (!d.email.includes("@")) {
    errors.push("Invalid email format");
  }

  if (!d.password) {
    errors.push("Password is required");
  } else if (d.password.length < 8) {
    errors.push("Password must be at least 8 characters");
  }

  if (d.password !== d.passwordConfirm) {
    errors.push("Passwords don't match");
  }

  if (!d.orgName || d.orgName.length < 2) {
    errors.push("Organization name must be at least 2 characters");
  }

  return { valid: errors.length === 0, errors };
}

// URL validation
export function isValidUrl(url: string): boolean {
  try {
    new URL(url);
    return true;
  } catch {
    return false;
  }
}

// Email validation
export function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

// Rate limit config validation
export function validateRateLimitConfig(config: unknown): {
  valid: boolean;
  errors: string[];
} {
  const errors: string[] = [];
  const c = config as {
    requestsPerSecond?: number;
    concurrentRequests?: number;
  };

  if (
    c.requestsPerSecond &&
    (c.requestsPerSecond < 1 || c.requestsPerSecond > 20)
  ) {
    errors.push("requestsPerSecond must be between 1 and 20");
  }

  if (
    c.concurrentRequests &&
    (c.concurrentRequests < 1 || c.concurrentRequests > 5)
  ) {
    errors.push("concurrentRequests must be between 1 and 5");
  }

  return { valid: errors.length === 0, errors };
}
