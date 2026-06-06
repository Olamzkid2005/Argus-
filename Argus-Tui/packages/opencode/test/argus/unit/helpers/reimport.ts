/**
 * Re-import a module as a bundled ESM file, bypassing mock.module intercepts.
 * Uses Bun.build to create a self-contained bundle with all dependencies inlined.
 */
import { mkdtempSync, writeFileSync } from "fs"
import { join, dirname, resolve } from "path"
import { fileURLToPath } from "url"
import { tmpdir } from "os"
import { rmSync } from "fs"

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const _tempDirs: string[] = []

export async function reimport<T = any>(relativePath: string): Promise<T> {
  const sourcePath = resolve(__dirname, relativePath)
  const tempDir = mkdtempSync(join(tmpdir(), "argus-reimport-"))
  _tempDirs.push(tempDir)
  
  const result = await Bun.build({
    entrypoints: [sourcePath],
    outdir: tempDir,
    target: "bun",
    format: "esm",
    naming: "bundle.mjs",
    external: [],
    sourcemap: "none",
    minify: false,
  })
  
  if (!result.success) {
    throw new Error(`Bundle failed: ${result.logs.join(", ")}`)
  }
  
  const bundlePath = join(tempDir, "bundle.mjs")
  writeFileSync(bundlePath, "") // ensure file exists
  
  // Use file URL import for the bundle
  return import(bundlePath) as Promise<T>
}

export function cleanupReimports(): void {
  for (const dir of _tempDirs) {
    try { rmSync(dir, { recursive: true, force: true }) } catch {}
  }
  _tempDirs.length = 0
}
