/**
 * ScanStoreWriter — Bridges ProgressEvent emissions into ScanStore mutations.
 *
 * This is the UI-layer adapter that translates framework-agnostic progress
 * events into SolidJS reactive store updates. The workflow runner emits
 * ProgressEvent objects; this writer calls the appropriate ScanStore methods.
 *
 * Architectural rule: workflow-runner.ts must NOT import SolidJS.
 * ScanStoreWriter is the adapter in the UI layer that bridges the two.
 */
import type { ProgressEvent } from "../shared/progress"
import { handleProgressEvent } from "./scan-store"

export function createScanStoreWriter() {
  return (event: ProgressEvent) => {
    handleProgressEvent(event)
  }
}
