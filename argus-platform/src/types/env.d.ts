/**
 * L-04: Type declarations for process.env variables used throughout Argus.
 * Ensures type safety when accessing environment variables and documents
 * the expected shape of the environment.
 */
declare namespace NodeJS {
  interface ProcessEnv {
    // Database
    DATABASE_URL: string;
    DB_USER?: string;
    DB_PASSWORD?: string;
    DB_NAME?: string;
    DB_STATEMENT_TIMEOUT_MS?: string;
    DB_SSLMODE?: string;
    PGBOUNCER_MODE?: string;

    // Redis
    REDIS_URL: string;
    REDIS_HOST?: string;
    REDIS_PORT?: string;
    REDIS_TLS?: string;

    // NextAuth
    NEXTAUTH_URL: string;
    NEXTAUTH_SECRET: string;

    // OAuth
    GOOGLE_CLIENT_ID?: string;
    GOOGLE_CLIENT_SECRET?: string;
    GITHUB_CLIENT_ID?: string;
    GITHUB_CLIENT_SECRET?: string;

    // SMTP / Email
    SMTP_HOST?: string;
    SMTP_PORT?: string;
    SMTP_USER?: string;
    SMTP_PASS?: string;

    // AI / LLM
    OPENROUTER_API_KEY?: string;

    // App
    NODE_ENV: "development" | "production" | "test";
    NEXT_PUBLIC_APP_URL?: string;
    ALLOWED_ORIGINS?: string;

    // Celery
    CELERY_CONCURRENCY?: string;
    CELERY_BROKER_URL?: string;
    CELERY_RESULT_BACKEND?: string;

    // Infra
    VAULT_ADDR?: string;
    VAULT_TOKEN?: string;
  }
}
