/**
 * ScanStoreWriter — Bridges ProgressEvent emissions into ScanStore mutations.
 *
 * This is the UI-layer adapter that translates framework-agnostic progress
 * events into SolidJS reactive store updates. The workflow runner emits
 * ProgressEvent objects; this writer calls the appropriate ScanStore methods.
 *
 * Architectural rule: workflow-runner.ts must NOT import SolidJS.
 * ScanStoreWriter is the adapter in the UI layer that bridges the two.
 *
 * The optional engagementId parameter ensures that analysis_progress and
 * other events are routed to the correct ScanStore engagement when the
 * writer is used from contexts (e.g., /report) where the active engagement
 * in ScanStore may differ from the one the event belongs to.
 */
import type { ProgressEvent } from "../shared/progress"
import { handleProgressEvent } from "./scan-store"

export function createScanStoreWriter(engagementId?: string) {
  return (event: ProgressEvent) => {
    handleProgressEvent(event, engagementId)
  }
}
