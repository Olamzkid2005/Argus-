import { NextRequest, NextResponse } from 'next/server';
import { log } from '@/lib/logger';

type RouteHandler = (
  req: NextRequest,
  context: { params: Promise<Record<string, string>> }
) => Promise<NextResponse>;

export function withApiLogging(method: string, path: string, handler: RouteHandler): RouteHandler {
  return async (req: NextRequest, ctx: { params: Promise<Record<string, string>> }) => {
    const start = Date.now();

    let params: Record<string, string> = {};
    try {
      params = await ctx.params;
    } catch (error) {
      log.warn("API", `Params resolution failed for ${method} ${path}: ${error}`);
    }

    log.api.start(method, path, params);

    try {
      const response = await handler(req, ctx);
      const durationMs = Date.now() - start;
      log.api.end(method, path, response.status, durationMs);
      return response;
    } catch (error) {
      const durationMs = Date.now() - start;
      log.api.error(method, path, error, durationMs);

      // Re-throw so Next.js error handling can render an error page
      // but also return a 500 JSON response if it's an API route
      return NextResponse.json(
        {
          error: 'Internal Server Error',
          message: error instanceof Error ? error.message : 'Unknown error',
          path,
          method,
          timestamp: new Date().toISOString(),
        },
        { status: 500 }
      );
    }
  };
}
