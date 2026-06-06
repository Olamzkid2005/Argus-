/**
 * Navigator — Global TUI route navigation helper.
 *
 * Provides a simple callback-based mechanism for the Argus
 * command handlers to navigate the TUI to different routes.
 * The app.tsx subscribes to this callback.
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

let navigateHandler: ((route: ArgusRoute) => void) | null = null

export function setNavigateHandler(handler: (route: ArgusRoute) => void) {
  navigateHandler = handler
}

export function clearNavigateHandler() {
  navigateHandler = null
}

export function navigateTo(route: ArgusRoute) {
  navigateHandler?.(route)
}
