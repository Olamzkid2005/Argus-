/**
 * Navigator — Global TUI route navigation helper.
 *
 * Provides a simple callback-based mechanism for the Argus
 * command handlers to navigate the TUI to different routes.
 * The app.tsx subscribes to this callback.
 *
 * When no handler is registered (e.g., CLI mode, non-TTY stdout),
 * navigateTo logs a warning so the caller knows the navigation
 * was silently dropped, rather than silently no-oping.
 */

export type ArgusRoute =
  | { type: "dashboard" }
  | { type: "scan"; target: string; engagementId: string }
  | { type: "findings"; engagementId?: string }
  | { type: "finding"; findingId: string }
  | { type: "engagements" }
  | { type: "engagement"; engagementId: string; tab?: string }
  | { type: "report"; engagementId: string }
  | { type: "workspace" }

/**
 * Returns true when the process is running in an interactive TTY
 * where TUI route rendering is meaningful.
 */
export function isTuiAvailable(): boolean {
  return !!(
    process.stdout.isTTY &&
    process.stderr.isTTY
  )
}

let navigateHandler: ((route: ArgusRoute) => void) | null = null

export function setNavigateHandler(handler: (route: ArgusRoute) => void) {
  navigateHandler = handler
}

export function clearNavigateHandler() {
  navigateHandler = null
}

export function navigateTo(route: ArgusRoute) {
  if (navigateHandler) {
    navigateHandler(route)
  } else if (!isTuiAvailable()) {
    console.warn(
      `[navigator] navigateTo(${route.type}) called but no TUI renderer is available — ` +
      `stdout is not a TTY. Run without piping to enable the interactive TUI.`
    )
  }
}
