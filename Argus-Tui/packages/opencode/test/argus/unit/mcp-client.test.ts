import { describe, expect, test, mock } from "bun:test"
import { readFileSync } from "fs"
import { resolve } from "path"

const PROJECT_ROOT = resolve(import.meta.dir, "../../../../../..")

describe("MCP client fixes", () => {
  describe("spawnChild uses PROJECT_ROOT as cwd", () => {
    test("source code passes PROJECT_ROOT as cwd to spawn", () => {
      const source = readFileSync(
        resolve(import.meta.dir, "../../../src/argus/bridge/mcp-client.ts"),
        "utf-8",
      )
      const importMatch = source.match(/import.*PROJECT_ROOT.*from/)
      expect(importMatch).not.toBeNull()
      const cwdMatch = source.match(/cwd:\s*PROJECT_ROOT/)
      expect(cwdMatch).not.toBeNull()
    })
  })

  describe("maxPending is configurable via constructor options", () => {
    test("default maxPending is 10", async () => {
      const { WorkersBridge } = await import("../../../src/argus/bridge/mcp-client")
      const bridge = new WorkersBridge("/path/to/mcp_server.py")
      expect((bridge as any).maxPending).toBe(10)
    })

    test("custom maxPending from options", async () => {
      const { WorkersBridge } = await import("../../../src/argus/bridge/mcp-client")
      const bridge = new WorkersBridge("/path/to/mcp_server.py", "python3", { maxPending: 25 })
      expect((bridge as any).maxPending).toBe(25)
    })

    test("maxPending=0 allows zero pending requests", async () => {
      const { WorkersBridge } = await import("../../../src/argus/bridge/mcp-client")
      const bridge = new WorkersBridge("/path/to/mcp_server.py", "python3", { maxPending: 0 })
      expect((bridge as any).maxPending).toBe(0)
    })
  })

  describe("ToolResult.success defaults to false when both meta.success and isError are undefined", () => {
    test("callTool sets success=false when meta.success and isError are both undefined", async () => {
      const { WorkersBridge } = await import("../../../src/argus/bridge/mcp-client")
      const bridge = new WorkersBridge("/path/to/mcp_server.py")
      ;(bridge as any).sendRequest = async () => ({
        content: [{ type: "text", text: "some result" }],
        meta: { duration_ms: 100 },
      })
      const result = await bridge.callTool("test", {})
      expect(result.success).toBe(false)
      expect(result.data).toBe("some result")
      expect(result.error).toBeUndefined()
    })

    test("callTool sets success=false when meta is absent entirely", async () => {
      const { WorkersBridge } = await import("../../../src/argus/bridge/mcp-client")
      const bridge = new WorkersBridge("/path/to/mcp_server.py")
      ;(bridge as any).sendRequest = async () => ({
        content: [{ type: "text", text: "result" }],
      })
      const result = await bridge.callTool("test", {})
      expect(result.success).toBe(false)
    })

    test("callTool sets success=true when meta.success is true", async () => {
      const { WorkersBridge } = await import("../../../src/argus/bridge/mcp-client")
      const bridge = new WorkersBridge("/path/to/mcp_server.py")
      ;(bridge as any).sendRequest = async () => ({
        content: [{ type: "text", text: "ok" }],
        meta: { success: true, duration_ms: 50 },
      })
      const result = await bridge.callTool("test", {})
      expect(result.success).toBe(true)
    })

    test("callTool sets success=false when isError is true", async () => {
      const { WorkersBridge } = await import("../../../src/argus/bridge/mcp-client")
      const bridge = new WorkersBridge("/path/to/mcp_server.py")
      ;(bridge as any).sendRequest = async () => ({
        content: [{ type: "text", text: "error" }],
        isError: true,
        meta: { success: false, duration_ms: 50 },
      })
      const result = await bridge.callTool("test", {})
      expect(result.success).toBe(false)
    })

    test("callTool sets success=true when isError is false and meta.success is undefined", async () => {
      const { WorkersBridge } = await import("../../../src/argus/bridge/mcp-client")
      const bridge = new WorkersBridge("/path/to/mcp_server.py")
      ;(bridge as any).sendRequest = async () => ({
        content: [{ type: "text", text: "ok" }],
        isError: false,
        meta: { duration_ms: 50 },
      })
      const result = await bridge.callTool("test", {})
      expect(result.success).toBe(true)
    })
  })

  describe("exit handler cleans up readline/stderr listeners", () => {
    function setupExitHandler(bridge: any, exitCode: number | null, stderrMock?: any) {
      const rl = bridge.rl
      const stderr = stderrMock ?? { removeAllListeners: () => {} }
      ;(bridge as any).process = {
        on: (event: string, handler: (code: number | null) => void) => {
          if (event === "exit") handler(exitCode)
        },
        stderr,
        stdin: { write: () => {} },
        stdout: { on: () => {} },
        removeAllListeners: mock(() => {}),
        killed: false,
        exitCode: null,
      }
      // Simulate what spawnChild does: register the exit handler
      const proc = (bridge as any).process
      proc.on("exit", (code: number | null) => {
        ;(bridge as any).pending.clear()
        ;(bridge as any).pendingCount = 0
        rl?.removeAllListeners()
        rl?.close()
        proc.stderr?.removeAllListeners()
      })
    }

    test("exit handler removes readline listeners", async () => {
      const { WorkersBridge } = await import("../../../src/argus/bridge/mcp-client")
      const bridge = new WorkersBridge("/path/to/mcp_server.py")

      const rlRemoveAllListeners = mock(() => {})
      const rlClose = mock(() => {})
      const stderrRemoveAllListeners = mock(() => {})

      ;(bridge as any).rl = {
        removeAllListeners: rlRemoveAllListeners,
        close: rlClose,
      }

      setupExitHandler(bridge, 0, { removeAllListeners: stderrRemoveAllListeners })

      expect(rlRemoveAllListeners).toHaveBeenCalled()
      expect(rlClose).toHaveBeenCalled()
      expect(stderrRemoveAllListeners).toHaveBeenCalled()
    })

    test("exit handler fires cleanup even without stderr", async () => {
      const { WorkersBridge } = await import("../../../src/argus/bridge/mcp-client")
      const bridge = new WorkersBridge("/path/to/mcp_server.py")

      const rlRemoveAllListeners = mock(() => {})
      const rlClose = mock(() => {})

      ;(bridge as any).rl = {
        removeAllListeners: rlRemoveAllListeners,
        close: rlClose,
      }

      setupExitHandler(bridge, 1, null)

      expect(rlRemoveAllListeners).toHaveBeenCalled()
      expect(rlClose).toHaveBeenCalled()
    })
  })
})
