type LogLevel = 'info' | 'warn' | 'error' | 'debug';

const PREFIX = '[Argus]';

function serializeArg(a: unknown): string {
  if (typeof a === 'string') return a;
  if (a instanceof Error) return `${a.name}: ${a.message}`;
  if (typeof a === 'object') {
    try { return JSON.stringify(a); } catch { return String(a); }
  }
  return String(a);
}

function logMsg(level: LogLevel, category: string, ...args: unknown[]): void {
  const timestamp = new Date().toISOString();
  const message = `${PREFIX} [${category}] ${args.map(serializeArg).join(' ')}`;
  switch (level) {
    case 'error':
      console.error(timestamp, message);
      break;
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

export const log = {
  pageMount: (name: string) => logMsg('info', 'Page', `Mount: ${name}`),
  pageUnmount: (name: string) => logMsg('info', 'Page', `Unmount: ${name}`),
  api: (method: string, path: string, details?: Record<string, unknown>) =>
    logMsg('info', 'API', `${method} ${path}`, details ?? ''),
  apiEnd: (method: string, path: string, statusOrDetails?: number | Record<string, unknown>, details?: Record<string, unknown>) => {
    if (typeof statusOrDetails === 'number') {
      logMsg('info', 'API', `${method} ${path} -> ${statusOrDetails}`, details ?? '');
    } else {
      logMsg('info', 'API', `${method} ${path} -> done`, statusOrDetails ?? '');
    }
  },

  auth: (event: string, details?: Record<string, unknown>) =>
    logMsg('info', 'Auth', event, details ?? ''),
  authError: (error: string, details?: Record<string, unknown>) =>
    logMsg('error', 'Auth', error, details ?? ''),

  wsConnect: (id?: string) => logMsg('info', 'WS', `Connect${id ? `: ${id}` : ''}`),
  wsDisconnect: (id?: string) => logMsg('info', 'WS', `Disconnect${id ? `: ${id}` : ''}`),
  wsEvent: (type: string, data?: Record<string, unknown>) =>
    logMsg('debug', 'WS', `Event: ${type}`, data ?? ''),
  wsError: (error: string, details?: Record<string, unknown>) =>
    logMsg('error', 'WS', error, details ?? ''),

  error: (source: string, error: unknown) =>
    logMsg('error', 'Error', `${source}:`, error),
};
