/**
 * Navigator — Global TUI route navigation helper.
 *
 * Provides a simple callback-based mechanism for the Argus
 * command handlers to navigate the TUI to different routes.
 * The app.tsx subscribes to this callback.
 */

type Route =
  | { type: "scan"; target: string; engagementId: string }
  | { type: "findings"; engagementId?: string }

let navigateHandler: ((route: Route) => void) | null = null

export function setNavigateHandler(handler: (route: Route) => void) {
  navigateHandler = handler
}

export function clearNavigateHandler() {
  navigateHandler = null
}

export function navigateTo(route: Route) {
  navigateHandler?.(route)
}
