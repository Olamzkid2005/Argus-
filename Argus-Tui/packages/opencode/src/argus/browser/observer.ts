import type { Page } from "playwright"
import type { Observation, DiffResult } from "./types"

export async function observeUrl(page: Page, url: string): Promise<Observation> {
  const response = await page.goto(url, { waitUntil: "networkidle", timeout: 30000 })
  const domSnapshot = await page.content()

  return {
    url,
    domSnapshot,
    responseHeaders: {},
    statusCode: response?.status() ?? 0,
    timestamp: new Date().toISOString(),
  }
}

export function compareObservations(a: Observation, b: Observation): DiffResult {
  const additions: string[] = []
  const removals: string[] = []

  if (a.domSnapshot !== b.domSnapshot) {
    const aLines = a.domSnapshot.split("\n")
    const bLines = b.domSnapshot.split("\n")
    const aSet = new Set(aLines)
    const bSet = new Set(bLines)

    for (const line of bLines) {
      if (!aSet.has(line)) additions.push(line)
    }
    for (const line of aLines) {
      if (!bSet.has(line)) removals.push(line)
    }
  }

  return {
    changed: additions.length > 0 || removals.length > 0,
    additions,
    removals,
  }
}
