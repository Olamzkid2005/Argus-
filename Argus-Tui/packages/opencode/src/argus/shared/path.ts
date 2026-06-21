/**
 * Central project-root resolution helper.
 *
 * Computes the repo root once from import.meta.url so all modules use a
 * single consistent path.  Without this, every caller hand-counts
 * "../../../../../argus-workers/" relative paths that break on relocation.
 *
 * File location:  Argus-Tui/packages/opencode/src/argus/shared/path.ts
 * Project root:   Grandparent of Argus-Tui/ (i.e. the directory that contains
 *                 both Argus-Tui/ and argus-workers/).
 *
 * From src/argus/shared/ to project root: 6 levels up.
 */
import { resolve } from "path"

const _dirname = new URL(".", import.meta.url).pathname

/**
 * Absolute path to the repository root (parent of Argus-Tui/ and argus-workers/).
 * Uses decodeURIComponent to handle spaces in the path.
 */
export const PROJECT_ROOT: string = resolve(
  decodeURIComponent(_dirname),
  "../../../../../..",
)

/**
 * Convenience: absolute path to the MCP worker script.
 */
export const MCP_WORKER_PATH: string = resolve(
  PROJECT_ROOT,
  "argus-workers/mcp_server.py",
)
