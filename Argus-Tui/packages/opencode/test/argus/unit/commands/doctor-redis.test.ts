import { afterEach, describe, expect, test } from "bun:test"
import { createServer, type Server } from "net"
import { redisCheck } from "../../../../src/argus/commands/doctor"

// A minimal RESP server: enough to prove the doctor authenticates before
// PINGing, and that a rejection is reported as such rather than as "no PONG".
let server: Server | undefined
const originalRedisUrl = process.env.REDIS_URL
const originalBrokerUrl = process.env.CELERY_BROKER_URL

async function startRedis(password?: string): Promise<number> {
  server = createServer((socket) => {
    socket.on("data", (buffer) => {
      const text = buffer.toString()
      if (password && !text.includes(password)) {
        socket.write("-NOAUTH Authentication required.\r\n")
        return
      }
      const authReply = text.includes("AUTH") ? "+OK\r\n" : ""
      socket.write(authReply + (text.includes("PING") ? "+PONG\r\n" : ""))
    })
  })
  await new Promise<void>((resolve) => server!.listen(0, "127.0.0.1", resolve))
  const address = server!.address()
  if (!address || typeof address === "string") throw new Error("no listening port")
  return address.port
}

function restore(name: string, value: string | undefined) {
  if (value === undefined) delete process.env[name]
  else process.env[name] = value
}

afterEach(() => {
  server?.close()
  server = undefined
  restore("REDIS_URL", originalRedisUrl)
  restore("CELERY_BROKER_URL", originalBrokerUrl)
})

describe("doctor Redis check", () => {
  test("authenticates with the password in REDIS_URL", async () => {
    const port = await startRedis("s3cret-value")
    process.env.REDIS_URL = `redis://:s3cret-value@127.0.0.1:${port}`
    delete process.env.CELERY_BROKER_URL

    const result = await redisCheck()

    expect(result.status).toBe("PASS")
    expect(result.message).toContain("authenticated")
    expect(result.message).toContain("responded to PING")
  })

  test("reports a rejected password as an authentication failure", async () => {
    const port = await startRedis("s3cret-value")
    process.env.REDIS_URL = `redis://:wrong-value@127.0.0.1:${port}`
    delete process.env.CELERY_BROKER_URL

    const result = await redisCheck()

    expect(result.status).toBe("FAIL")
    expect(result.message).toContain("rejected authentication")
  })

  test("still passes against a server without a password", async () => {
    const port = await startRedis()
    process.env.REDIS_URL = `redis://127.0.0.1:${port}`
    delete process.env.CELERY_BROKER_URL

    const result = await redisCheck()

    expect(result.status).toBe("PASS")
    expect(result.message).not.toContain("authenticated")
    expect(result.message).toContain("responded to PING")
  })

  test("warns when REDIS_URL cannot be parsed", async () => {
    process.env.REDIS_URL = "redis://"
    delete process.env.CELERY_BROKER_URL

    const result = await redisCheck()

    expect(result.status).toBe("WARN")
  })

  test("warns when no Redis URL is configured", async () => {
    delete process.env.REDIS_URL
    delete process.env.CELERY_BROKER_URL

    const result = await redisCheck()

    expect(result.status).toBe("WARN")
    expect(result.message).toContain("REDIS_URL not set")
  })
})
