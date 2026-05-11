type LogLevel = 'info' | 'warn' | 'error' | 'debug';

const PREFIX = '[Argus]';

function serializeArg(a: unknown): string {
  if (typeof a === 'string') return a;
  if (a instanceof Error) return `${a.name}: ${a.message}\n  stack: ${a.stack?.replace(/\n/g, '\n  ') ?? '(no stack)'}`;
  if (typeof a === 'object') {
    try { return JSON.stringify(a); } catch { return String(a); }
  }
  return String(a);
}

function logMsg(level: LogLevel, category: string, ...args: unknown[]): void {
  const timestamp = new Date().toISOString();
  const message = `${PREFIX} [${category}] ${args.map(serializeArg).join(' ')}`;

  // Always capture stack for errors
  if (level === 'error') {
    const stack = new Error().stack?.split('\n').slice(2).join('\n') ?? '';
    switch (level) {
      case 'error':
        console.error(timestamp, message, `\n  trace:\n  ${stack.replace(/\n/g, '\n  ')}`);
        break;
    }
    return;
  }

  switch (level) {
    case 'warn':
      console.warn(timestamp, message);
      break;
    case 'debug':
      console.debug(timestamp, message);
      break;
    default:
      console.log(timestamp, message);
  }
}

// ============================================================
// Page lifecycle
// ============================================================
const pageLog = {
  mount: (name: string) => logMsg('info', 'Page', `Mount: ${name}`),
  pageMount: (name: string) => logMsg('info', 'Page', `Mount: ${name}`),
  unmount: (name: string) => logMsg('info', 'Page', `Unmount: ${name}`),
  pageUnmount: (name: string) => logMsg('info', 'Page', `Unmount: ${name}`),
  error: (name: string, error: unknown) => logMsg('error', 'Page', `${name} error:`, error),
};

// ============================================================
// API routes
// ============================================================
type ApiLogFn = {
  (method: string, path: string, params?: Record<string, unknown>): void;
  start: (method: string, path: string, params?: Record<string, unknown>) => void;
  end: (method: string, path: string, status: number, durationMs?: number, details?: Record<string, unknown>) => void;
  error: (method: string, path: string, error: unknown, durationMs?: number) => void;
};

const apiLog: ApiLogFn = Object.assign(
  // Direct call: log.api(method, path, params) — shorthand for start
  (method: string, path: string, params?: Record<string, unknown>) =>
    logMsg('info', 'API', `${method} ${path}`, params ? `params=${JSON.stringify(params)}` : ''),
  {
    start: (method: string, path: string, params?: Record<string, unknown>) =>
      logMsg('info', 'API', `${method} ${path}`, params ? `params=${JSON.stringify(params)}` : ''),
    end: (method: string, path: string, status: number, durationMs?: number, details?: Record<string, unknown>) => {
      const dur = durationMs !== undefined ? ` (${durationMs}ms)` : '';
      logMsg(status >= 400 ? 'error' : 'info', 'API', `${method} ${path} -> ${status}${dur}`, details ?? '');
    },
    error: (method: string, path: string, error: unknown, durationMs?: number) => {
      const dur = durationMs !== undefined ? ` (${durationMs}ms)` : '';
      logMsg('error', 'API', `${method} ${path} -> ERROR${dur}:`, error);
    },
  },
);

// ============================================================
// Auth
// ============================================================
type AuthLogFn = {
  (message: string, details?: Record<string, unknown>): void;
  login: (provider: string, success: boolean, details?: Record<string, unknown>) => void;
  signup: (success: boolean, details?: Record<string, unknown>) => void;
  logout: () => void;
  tokenRefresh: (success: boolean) => void;
  session: (event: string, details?: Record<string, unknown>) => void;
  error: (context: string, error: unknown) => void;
};

const authLog: AuthLogFn = Object.assign(
  // Direct call: log.auth("message") — shorthand for session
  (message: string, details?: Record<string, unknown>) =>
    logMsg('info', 'Auth', message, details ?? ''),
  {
    login: (provider: string, success: boolean, details?: Record<string, unknown>) =>
      logMsg(success ? 'info' : 'error', 'Auth', `Login ${success ? 'OK' : 'FAILED'} via ${provider}`, details ?? ''),
    signup: (success: boolean, details?: Record<string, unknown>) =>
      logMsg(success ? 'info' : 'error', 'Auth', `Signup ${success ? 'OK' : 'FAILED'}`, details ?? ''),
    logout: () => logMsg('info', 'Auth', 'Logout'),
    tokenRefresh: (success: boolean) =>
      logMsg(success ? 'debug' : 'warn', 'Auth', `Token refresh ${success ? 'OK' : 'FAILED'}`),
    session: (event: string, details?: Record<string, unknown>) =>
      logMsg('info', 'Auth', event, details ?? ''),
    error: (context: string, error: unknown) =>
      logMsg('error', 'Auth', `${context}:`, error),
  },
);

// ============================================================
// Database
// ============================================================
const dbLog = {
  query: (sql: string, params?: unknown) =>
    logMsg('debug', 'DB', `Query: ${sql.substring(0, 200)}`, params ? JSON.stringify(params).substring(0, 200) : ''),
  slowQuery: (sql: string, durationMs: number) =>
    logMsg('warn', 'DB', `SLOW (${durationMs}ms): ${sql.substring(0, 200)}`),
  queryError: (sql: string, error: unknown) =>
    logMsg('error', 'DB', `Query failed: ${sql.substring(0, 200)}`, error),
  poolError: (error: unknown) =>
    logMsg('error', 'DB', 'Pool error:', error),
  connectionError: (error: unknown) =>
    logMsg('error', 'DB', 'Connection error:', error),
  migrate: (version: string) =>
    logMsg('info', 'DB', `Migration: ${version}`),
  migrateError: (version: string, error: unknown) =>
    logMsg('error', 'DB', `Migration failed: ${version}`, error),
};

// ============================================================
// Redis
// ============================================================
const redisLog = {
  connect: () => logMsg('debug', 'Redis', 'Connected'),
  disconnect: () => logMsg('debug', 'Redis', 'Disconnected'),
  error: (context: string, error: unknown) =>
    logMsg('error', 'Redis', `${context}:`, error),
  pubsub: (channel: string, action: 'sub' | 'unsub' | 'msg') =>
    logMsg('debug', 'Redis', `PubSub ${action}: ${channel}`),
  cacheHit: (key: string) =>
    logMsg('debug', 'Redis', `Cache HIT: ${key}`),
  cacheMiss: (key: string) =>
    logMsg('debug', 'Redis', `Cache MISS: ${key}`),
  cacheSet: (key: string, ttlSec?: number) =>
    logMsg('debug', 'Redis', `Cache SET: ${key}${ttlSec ? ` (TTL:${ttlSec}s)` : ''}`),
  cacheDel: (key: string) =>
    logMsg('debug', 'Redis', `Cache DEL: ${key}`),
  rateLimit: (key: string, remaining: number) =>
    logMsg(remaining === 0 ? 'warn' : 'debug', 'Redis', `Rate limit: ${key} remaining=${remaining}`),
};

// ============================================================
// WebSocket
// ============================================================
const wsLog = {
  connect: (id?: string) => logMsg('info', 'WS', `Connect${id ? `: ${id}` : ''}`),
  disconnect: (id?: string) => logMsg('info', 'WS', `Disconnect${id ? `: ${id}` : ''}`),
  event: (type: string, data?: Record<string, unknown>) =>
    logMsg('debug', 'WS', `Event: ${type}`, data ?? ''),
  error: (context: string, error: unknown) =>
    logMsg('error', 'WS', `${context}:`, error),
  reconnectAttempt: (attempt: number) =>
    logMsg('warn', 'WS', `Reconnect attempt ${attempt}`),
};

// ============================================================
// SSE (Server-Sent Events)
// ============================================================
const sseLog = {
  connect: (engagementId: string) => logMsg('info', 'SSE', `Connect: engagement=${engagementId}`),
  disconnect: (engagementId: string) => logMsg('info', 'SSE', `Disconnect: engagement=${engagementId}`),
  event: (type: string, engagementId: string) =>
    logMsg('debug', 'SSE', `${type}: engagement=${engagementId}`),
  error: (context: string, error: unknown) =>
    logMsg('error', 'SSE', `${context}:`, error),
};

// ============================================================
// Webhooks
// ============================================================
const webhookLog = {
  send: (url: string, event: string) =>
    logMsg('info', 'Webhook', `Send to ${url} event=${event}`),
  success: (url: string, event: string, durationMs: number) =>
    logMsg('info', 'Webhook', `OK (${durationMs}ms) ${url} ${event}`),
  error: (url: string, event: string, error: unknown) =>
    logMsg('error', 'Webhook', `FAILED ${url} ${event}:`, error),
};

// ============================================================
// Validation
// ============================================================
const validationLog = {
  fail: (source: string, errors: Record<string, unknown>) =>
    logMsg('warn', 'Validation', `${source} failed:`, errors),
  error: (source: string, error: unknown) =>
    logMsg('error', 'Validation', `${source}:`, error),
};

// ============================================================
// Middleware
// ============================================================
const middlewareLog = {
  block: (ip: string, path: string, reason: string) =>
    logMsg('warn', 'Middleware', `BLOCKED ${ip} ${path}: ${reason}`),
  rateLimit: (ip: string, path: string) =>
    logMsg('warn', 'Middleware', `RATE LIMITED ${ip} ${path}`),
  error: (context: string, error: unknown) =>
    logMsg('error', 'Middleware', `${context}:`, error),
};

// ============================================================
// System / Health
// ============================================================
const systemLog = {
  startup: (component: string) => logMsg('info', 'System', `${component} started`),
  shutdown: (component: string) => logMsg('info', 'System', `${component} shutdown`),
  health: (component: string, healthy: boolean, details?: string) =>
    logMsg(healthy ? 'info' : 'error', 'System', `${component} ${healthy ? 'HEALTHY' : 'UNHEALTHY'}${details ? `: ${details}` : ''}`),
  memory: () => {
    if (typeof process !== 'undefined' && process.memoryUsage) {
      const mem = process.memoryUsage();
      logMsg('debug', 'System', `Memory: heap=${Math.round(mem.heapUsed / 1024 / 1024)}MB / ${Math.round(mem.heapTotal / 1024 / 1024)}MB, rss=${Math.round(mem.rss / 1024 / 1024)}MB`);
    }
  },
};

// ============================================================
// Browser (client-safe — no server deps, no process, no fs)
// ============================================================
const browserLog = {
  error: (component: string, error: unknown, metadata?: Record<string, unknown>) => {
    const ts = new Date().toISOString();
    const msg = `${PREFIX} [Browser] ${component}: ${serializeArg(error)}`;
    console.error(ts, msg, metadata ?? '');
  },
  warn: (component: string, message: string, metadata?: Record<string, unknown>) => {
    const ts = new Date().toISOString();
    const msg = `${PREFIX} [Browser] ${component}: ${message}`;
    console.warn(ts, msg, metadata ?? '');
  },
  info: (component: string, message: string) => {
    const ts = new Date().toISOString();
    console.log(ts, `${PREFIX} [Browser] ${component}: ${message}`);
  },
  fetchError: (url: string, error: unknown) => {
    const ts = new Date().toISOString();
    console.error(ts, `${PREFIX} [Browser] Fetch FAILED: ${url}`, error);
  },
  unhandledRejection: (event: PromiseRejectionEvent) => {
    const ts = new Date().toISOString();
    console.error(ts, `${PREFIX} [Browser] Unhandled Promise Rejection:`, event.reason);
  },
  unhandledError: (event: ErrorEvent) => {
    const ts = new Date().toISOString();
    console.error(ts, `${PREFIX} [Browser] Unhandled Error: ${event.message}`, { filename: event.filename, lineno: event.lineno, colno: event.colno });
  },
};

// ============================================================
// Generic fallback
// ============================================================
const genericLog = {
  error: (source: string, error: unknown) =>
    logMsg('error', 'Error', `${source}:`, error),
  warn: (source: string, message: string) =>
    logMsg('warn', 'Warn', `${source}: ${message}`),
  info: (source: string, message: string) =>
    logMsg('info', 'Info', `${source}: ${message}`),
};

export const log = {
  page: pageLog,
  api: apiLog,
  auth: authLog,
  db: dbLog,
  redis: redisLog,
  ws: wsLog,
  sse: sseLog,
  webhook: webhookLog,
  validation: validationLog,
  middleware: middlewareLog,
  system: systemLog,
  browser: browserLog,
  error: genericLog.error,
  warn: genericLog.warn,
  info: genericLog.info,

  // Backward compatibility — wrappers for old API
  pageMount: (name: string) => pageLog.mount(name),
  pageUnmount: (name: string) => pageLog.unmount(name),
  apiEnd: (method: string, path: string, statusOrDetails?: number | Record<string, unknown>, details?: Record<string, unknown>) => {
    if (typeof statusOrDetails === 'number') {
      apiLog.end(method, path, statusOrDetails, undefined, details);
    } else {
      apiLog.end(method, path, 200, undefined, statusOrDetails);
    }
  },
  wsEvent: (type: string, data?: Record<string, unknown>) => wsLog.event(type, data),
  wsError: (error: string, details?: Record<string, unknown>) => logMsg('error', 'WS', error, details ?? ''),
  wsConnect: (id?: string) => wsLog.connect(id),
  wsDisconnect: (id?: string) => wsLog.disconnect(id),
  authError: (error: string, details?: Record<string, unknown>) => logMsg('error', 'Auth', error, details ?? ''),
} as const;

export type Logger = typeof log;
