/**
 * Strips CLI flags (tokens starting with `--`) from a target argument string.
 *
 * Used by the TUI prompt to remove flags like `--no-cache` and `--refresh-cache`
 * from `/assess`, `/scan`, and `/recon` commands so they don't become part of
 * the engagement's target URL in SQLite.
 *
 * @example
 * stripFlags("https://example.com --no-cache")        // → "https://example.com"
 * stripFlags("--no-cache https://example.com")        // → "https://example.com"
 * stripFlags("https://example.com")                   // → "https://example.com"
 * stripFlags("--no-cache")                            // → ""
 * stripFlags("")                                      // → ""
 */
export function stripFlags(raw: string): string {
  return raw
    .trim()
    .split(" ")
    .filter((t) => !t.startsWith("--"))
    .join(" ")
    .trim()
}

/**
 * Check whether a specific flag token is present in the raw argument string.
 * Uses exact token matching to avoid partial matches (e.g. `--refresh` will
 * NOT match `--refresh-cache`).
 *
 * @example
 * hasFlag("https://example.com --no-cache", "--no-cache")        // → true
 * hasFlag("https://example.com --verbose", "--verbose")          // → true
 * hasFlag("https://example.com", "--no-cache")                   // → false
 * hasFlag("https://example.com --refresh", "--refresh-cache")    // → false
 */
export function hasFlag(raw: string, flag: string): boolean {
  return raw
    .trim()
    .split(" ")
    .includes(flag)
}

/**
 * Detects cache mode flags (`--no-cache`, `--refresh-cache`) in a raw argument
 * string and returns the corresponding `CacheMode` value.
 *
 * - `--no-cache`        → `"no_cache"`  (skip cache reads AND writes)
 * - `--refresh-cache`   → `"refresh"`   (skip cache reads, still write results)
 * - Neither flag present → `undefined`  (normal caching)
 *
 * When both flags are present, `--no-cache` takes precedence (more restrictive).
 *
 * @example
 * detectCacheMode("https://example.com --no-cache")       // → "no_cache"
 * detectCacheMode("https://example.com --refresh-cache")  // → "refresh"
 * detectCacheMode("https://example.com")                  // → undefined
 * detectCacheMode("--no-cache --refresh-cache")           // → "no_cache"
 */
export function detectCacheMode(raw: string): "no_cache" | "refresh" | undefined {
  const hasNoCache = hasFlag(raw, "--no-cache")
  const hasRefresh = hasFlag(raw, "--refresh-cache")

  // --no-cache is more restrictive, so it wins if both are present
  if (hasNoCache) return "no_cache"
  if (hasRefresh) return "refresh"
  return undefined
}

/**
 * Detects the `--verbose` flag in a raw argument string.
 *
 * @example
 * hasVerboseFlag("https://example.com --verbose")     // → true
 * hasVerboseFlag("https://example.com --no-cache")    // → false
 * hasVerboseFlag("https://example.com")               // → false
 */
export function hasVerboseFlag(raw: string): boolean {
  return hasFlag(raw, "--verbose")
}
