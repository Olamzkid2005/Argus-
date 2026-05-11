'use client';

import React from 'react';
import { log } from '@/lib/logger';

interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
  componentName?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    const componentName = this.props.componentName ?? 'UnknownComponent';
    log.browser.error(
      componentName,
      error,
      {
        componentStack: errorInfo.componentStack ?? '(none)',
        digest: (error as { digest?: string }).digest,
      }
    );
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div
          style={{
            padding: '2rem',
            margin: '1rem',
            border: '1px solid #fca5a5',
            borderRadius: '8px',
            background: '#fef2f2',
            color: '#991b1b',
            fontFamily: 'monospace',
            fontSize: '0.875rem',
          }}
        >
          <h3 style={{ margin: '0 0 0.5rem', fontSize: '1rem' }}>
            Something went wrong
          </h3>
          <p style={{ margin: '0 0 0.5rem', opacity: 0.8 }}>
            {this.props.componentName ? `[${this.props.componentName}] ` : ''}
            {this.state.error?.message ?? 'Unknown error'}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            style={{
              padding: '0.25rem 0.75rem',
              border: '1px solid #fca5a5',
              borderRadius: '4px',
              background: '#fff',
              cursor: 'pointer',
              fontSize: '0.75rem',
            }}
          >
            Try again
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
