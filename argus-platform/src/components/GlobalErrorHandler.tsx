'use client';

import { useEffect } from 'react';
import { log } from '@/lib/logger';

export function GlobalErrorHandler() {
  useEffect(() => {
    const unhandledRejectionHandler = (event: PromiseRejectionEvent) => {
      log.browser.unhandledRejection(event);
    };

    const unhandledErrorHandler = (event: ErrorEvent) => {
      log.browser.unhandledError(event);
    };

    window.addEventListener('unhandledrejection', unhandledRejectionHandler);
    window.addEventListener('error', unhandledErrorHandler);

    return () => {
      window.removeEventListener('unhandledrejection', unhandledRejectionHandler);
      window.removeEventListener('error', unhandledErrorHandler);
    };
  }, []);

  return null;
}
