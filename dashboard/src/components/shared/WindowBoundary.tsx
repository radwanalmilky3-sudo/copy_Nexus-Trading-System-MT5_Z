'use client';

import React from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';

interface WindowBoundaryProps {
  children: React.ReactNode;
  /** Window name used in the console log and fallback card. */
  label?: string;
  className?: string;
}

interface WindowBoundaryState {
  hasError: boolean;
}

/**
 * Isolates a single dashboard window: if one card throws, the rest of the
 * terminal keeps working. The fallback shows an honest error — never a
 * fabricated "healthy" state — and offers a local retry.
 */
export default class WindowBoundary extends React.Component<
  WindowBoundaryProps,
  WindowBoundaryState
> {
  constructor(props: WindowBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): WindowBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    const tag = this.props.label ? `:${this.props.label}` : '';
    console.error(`[WindowBoundary${tag}]`, error, info.componentStack);
  }

  private retry = () => {
    this.setState({ hasError: false });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          dir="rtl"
          className={
            this.props.className ??
            'h-full w-full min-h-[120px] flex flex-col items-center justify-center gap-2 rounded-lg border border-neon-red/30 bg-bg-card p-4 text-center'
          }
        >
          <AlertTriangle className="h-4 w-4 text-neon-red" />
          <span className="text-xs font-medium text-neon-red">
            تعطلت هذه النافذة مؤقتًا
          </span>
          <span className="text-[11px] text-text-muted">
            {this.props.label ? `(${this.props.label}) — ` : ''}بقية اللوحة تعمل بشكل طبيعي.
          </span>
          <button
            onClick={this.retry}
            className="flex items-center gap-1 rounded border border-border-primary px-2 py-1 text-[11px] text-text-secondary transition-colors hover:bg-bg-tertiary"
          >
            <RotateCcw className="h-3 w-3" />
            إعادة المحاولة
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
