/**
 * Terminal Size Utility — Responsive width helpers for TUI components.
 *
 * Provides minimum/maximum-clamped terminal-column reading so that
 * boxes, progress bars, and fixed-width layouts adapt to the user's
 * terminal instead of rendering at arbitrary hardcoded widths.
 */

/**
 * Return a responsive bar width (for progress bars) that fills roughly
 * half the terminal width, clamped to a sensible range.
 */
export function responsiveBarWidth(): number {
  const cols = process.stdout.columns ?? 80
  const bar = Math.round((cols - 16) / 2)
  return Math.max(10, Math.min(bar, 60))
}

/**
 * Return a responsive box width (for dashboards, info panels) that fills
 * roughly 80 % of the terminal width, clamped to a sensible range.
 */
export function responsiveBoxWidth(): number {
  const cols = process.stdout.columns ?? 80
  const box = Math.round((cols - 4) * 0.92)
  return Math.max(50, Math.min(box, 120))
}
