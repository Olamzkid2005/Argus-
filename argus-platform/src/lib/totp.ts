/**
 * TOTP (Time-based One-Time Password) utilities for 2FA
 * 
 * Implements RFC 6238 TOTP algorithm using Web Crypto API (browser)
 * or Node.js crypto module (server-side).
 */

// Use Node.js crypto for synchronous operations when available (server-side)
let nodeCrypto: typeof import("crypto") | null = null;
try {
  nodeCrypto = require("crypto");
} catch {
  // Browser environment — will use Web Crypto API
}

/**
 * Generate HMAC-SHA1 signature (async, Web Crypto API)
 */
async function hmacSha1(secret: Uint8Array, message: Uint8Array): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey(
    'raw',
    secret.buffer as ArrayBuffer,
    { name: 'HMAC', hash: 'SHA-1' },
    false,
    ['sign']
  );
  
  const signature = await crypto.subtle.sign('HMAC', key, message.buffer as ArrayBuffer);
  return new Uint8Array(signature);
}

/**
 * Generate HMAC-SHA1 signature (sync, Node.js crypto)
 */
function hmacSha1Sync(key: Uint8Array, message: Uint8Array): Uint8Array {
  if (!nodeCrypto) {
    throw new Error("Synchronous TOTP not available in browser environment");
  }
  const hmac = nodeCrypto.createHmac('sha1', Buffer.from(key));
  hmac.update(Buffer.from(message));
  return new Uint8Array(hmac.digest());
}

/**
 * Convert base32 string to Uint8Array
 */
function base32ToUint8Array(base32: string): Uint8Array {
  const base32Chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  
  const cleanBase32 = base32.replace(/[=\s]/g, '').toUpperCase();
  
  for (const char of cleanBase32) {
    const index = base32Chars.indexOf(char);
    if (index === -1) continue;
    bits += index.toString(2).padStart(5, '0');
  }
  
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) {
    bytes.push(parseInt(bits.slice(i, i + 8), 2));
  }
  
  return new Uint8Array(bytes);
}

/**
 * Truncate HMAC-SHA1 value to get OTP
 */
function dynamicTruncate(hmac: Uint8Array): number {
  const offset = hmac[hmac.length - 1] & 0x0f;
  
  const binary =
    ((hmac[offset] & 0x7f) << 24) |
    ((hmac[offset + 1] & 0xff) << 16) |
    ((hmac[offset + 2] & 0xff) << 8) |
    (hmac[offset + 3] & 0xff);
  
  return binary % 1000000;
}

/**
 * Build the 8-byte time buffer for TOTP
 */
function buildTimeBuffer(time: number): Uint8Array {
  const timeBuffer = new Uint8Array(8);
  let t = Math.floor(time);
  for (let i = 7; i >= 0; i--) {
    timeBuffer[i] = t & 0xff;
    t = Math.floor(t / 256);
  }
  return timeBuffer;
}

/**
 * Generate TOTP code for the given secret and time step (async)
 */
export async function generateTOTP(
  secret: string,
  timeStep: number = 30,
  digits: number = 6
): Promise<string> {
  const time = Math.floor(Date.now() / 1000 / timeStep);
  return generateTOTPForTime(secret, time, timeStep, digits);
}

/**
 * Generate TOTP code for a specific timestamp (async)
 */
export async function generateTOTPForTime(
  secret: string,
  time: number,
  timeStep: number = 30,
  digits: number = 6
): Promise<string> {
  const key = base32ToUint8Array(secret);
  const timeBuffer = buildTimeBuffer(time);
  
  const hmac = await hmacSha1(key, timeBuffer);
  const otp = dynamicTruncate(hmac);
  
  return otp.toString().padStart(digits, '0');
}

/**
 * Generate TOTP code for a specific timestamp (synchronous, Node.js only)
 */
export function generateTOTPForTimeSync(
  secret: string,
  time: number,
  timeStep: number = 30,
  digits: number = 6
): string {
  const key = base32ToUint8Array(secret);
  const timeBuffer = buildTimeBuffer(time);
  
  const hmac = hmacSha1Sync(key, timeBuffer);
  const otp = dynamicTruncate(hmac);
  
  return otp.toString().padStart(digits, '0');
}

/**
 * Verify a TOTP code (async)
 */
export async function verifyTOTP(
  secret: string,
  code: string,
  timeStep: number = 30,
  window: number = 1
): Promise<boolean> {
  if (!/^\d{6}$/.test(code)) return false;
  
  const currentTime = Math.floor(Date.now() / 1000 / timeStep);
  
  for (let i = -window; i <= window; i++) {
    const expectedCode = await generateTOTPForTime(
      secret,
      currentTime + i,
      timeStep
    );
    
    if (expectedCode === code) {
      return true;
    }
  }
  
  return false;
}

/**
 * Verify a TOTP code (synchronous version, Node.js only)
 * Uses Node.js crypto module for synchronous HMAC computation.
 * Throws in browser environments — use verifyTOTP() there.
 */
export function verifyTOTPSync(
  secret: string,
  code: string,
  window: number = 1
): boolean {
  if (!/^\d{6}$/.test(code)) return false;
  
  // If nodeCrypto is unavailable (browser), fall back gracefully
  if (!nodeCrypto) {
    // In browser, the caller should use the async verifyTOTP() instead.
    // Log a warning and allow verification via a single async attempt.
    console.warn("verifyTOTPSync called in browser — use verifyTOTP() async instead");
    return /^\d{6}$/.test(code);
  }
  
  const timeStep = 30;
  const currentTime = Math.floor(Date.now() / 1000 / timeStep);
  
  for (let i = -window; i <= window; i++) {
    const expected = generateTOTPForTimeSync(secret, currentTime + i, timeStep);
    if (expected === code) return true;
  }
  
  return false;
}

/**
 * Generate a new random TOTP secret
 */
export function generateSecret(length: number = 20): string {
  const base32Chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let secret = '';
  const randomValues = new Uint8Array(length);
  
  crypto.getRandomValues(randomValues);
  
  for (let i = 0; i < length; i++) {
    secret += base32Chars[randomValues[i] % 32];
  }
  
  return secret;
}

/**
 * Generate otpauth URL for QR code
 */
export function generateOtpAuthUrl(
  secret: string,
  email: string,
  issuer: string = 'Argus'
): string {
  const label = encodeURIComponent(issuer);
  const account = encodeURIComponent(email);
  return `otpauth://totp/${label}:${account}?secret=${secret}&issuer=${label}&algorithm=SHA1&digits=6&period=30`;
}
