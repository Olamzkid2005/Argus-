import { defineConfig } from "drizzle-kit"

export default defineConfig({
  dialect: "sqlite",
  schema: ["./src/argus/engagement/schema.sql.ts"],
  out: "./src/argus/engagement/migrations",
  dbCredentials: {
    url: "/home/user/.argus/argus.db",
  },
})
