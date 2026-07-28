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
export declare function responsiveBarWidth(): number;
/**
 * Return a responsive box width (for dashboards, info panels) that fills
 * roughly 80 % of the terminal width, clamped to a sensible range.
 */
export declare function responsiveBoxWidth(): number;
