import { createStore, reconcile } from "solid-js/store"
import { createSimpleContext } from "./helper"
import type { PromptInfo } from "../component/prompt/history"

export type HomeRoute = {
  type: "home"
  prompt?: PromptInfo
}

export type SessionRoute = {
  type: "session"
  sessionID: string
  prompt?: PromptInfo
}

export type PluginRoute = {
  type: "plugin"
  id: string
  data?: Record<string, unknown>
}

export type ScanRoute = {
  type: "scan"
  target: string
  engagementId: string
}

export type FindingsRoute = {
  type: "findings"
  engagementId?: string
}

export type DashboardRoute = {
  type: "dashboard"
}

export type EngagementsRoute = {
  type: "engagements"
}

export type WorkspaceRoute = {
  type: "workspace"
}

export type EngagementDetailRoute = {
  type: "engagement-detail"
  engagementId: string
  tab?: string
}

export type FindingDetailRoute = {
  type: "finding-detail"
  findingId: string
}

export type ReportRoute = {
  type: "report"
  engagementId: string
}

export type Route = HomeRoute | SessionRoute | PluginRoute | ScanRoute | FindingsRoute | DashboardRoute | EngagementsRoute | WorkspaceRoute | EngagementDetailRoute | FindingDetailRoute | ReportRoute

export const { use: useRoute, provider: RouteProvider } = createSimpleContext({
  name: "Route",
  init: (props: { initialRoute?: Route }) => {
    let initial: Route
    if (props.initialRoute) {
      initial = props.initialRoute
    } else if (process.env["OPENCODE_ROUTE"]) {
      try {
        initial = JSON.parse(process.env["OPENCODE_ROUTE"]) as Route
      } catch {
        console.warn(
          "Invalid OPENCODE_ROUTE env var, ignoring: %s",
          process.env["OPENCODE_ROUTE"],
        )
        initial = process.env["ARGUS_MODE"] === "1"
          ? { type: "dashboard" }
          : { type: "home" }
      }
    } else {
      initial = process.env["ARGUS_MODE"] === "1"
        ? { type: "dashboard" }
        : { type: "home" }
    }
    const [store, setStore] = createStore<Route>(initial)

    return {
      get data() {
        return store
      },
      navigate(route: Route) {
        setStore(reconcile(route))
      },
    }
  },
})

export type RouteContext = ReturnType<typeof useRoute>

export function useRouteData<T extends Route["type"]>(type: T) {
  const route = useRoute()
  return route.data as Extract<Route, { type: typeof type }>
}
