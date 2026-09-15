import type { ReactNode } from 'react';
import { ApiError } from '@/api/client';
import './ui.css';

export function Skeleton({ height = 16, width = '100%' }: { height?: number; width?: string }) {
  return <div className="skeleton" style={{ height, width }} aria-hidden="true" />;
}

export function LoadingBlock({ rows = 5, label }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true">
      <span className="visually-hidden">{label ?? 'Loading'}</span>
      <div style={{ display: 'grid', gap: 'var(--sp-3)' }}>
        {Array.from({ length: rows }, (_, index) => (
          <Skeleton
            key={index}
            height={index === 0 ? 24 : 14}
            width={index === 0 ? '40%' : '100%'}
          />
        ))}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="state">
      <div className="mark" aria-hidden="true">
        &#9702;
      </div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const apiError = error instanceof ApiError ? error : null;
  const heading =
    apiError?.code === 'network_error' ? 'Cannot reach the API' : 'Something went wrong';
  const message =
    apiError?.message ?? (error instanceof Error ? error.message : 'Unknown error.');
  return (
    <div className="state state-error" role="alert">
      <div className="mark" aria-hidden="true">
        !
      </div>
      <h3>{heading}</h3>
      <p>{message}</p>
      {apiError?.remediation && (
        <p>
          <strong>What to do:</strong> {apiError.remediation}
        </p>
      )}
      {apiError?.correlationId && (
        <p className="mono" style={{ fontSize: 11, color: 'var(--ink-3)' }}>
          correlation id {apiError.correlationId}
        </p>
      )}
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
