/**
 * The one line every page owes the reader.
 *
 * This deployment reports on two branches and twenty SKUs. Every KPI on every
 * screen is computed over that slice, and a figure that looks national when it
 * is not is the failure the whole `workspace_scope` mechanism exists to
 * prevent (docs/DECISIONS.md D-049, D-056).
 *
 * So it is one component, used identically on every page, rather than a
 * sentence each page remembers to print. It renders nothing at all when the
 * workspace is unrestricted, which is the honest output in that case.
 */
import { useState } from 'react';
import type { WorkspaceScope } from '@/api/analytics';

const SOURCE_LABEL: Record<string, string> = {
  setting: 'fixed by configuration',
  training_run: 'inherited from the active training run',
  unrestricted: 'unrestricted',
};

export function ScopeBanner({ scope }: { scope?: WorkspaceScope | null }) {
  const [open, setOpen] = useState(false);
  if (!scope?.restricted) return null;

  const branches = scope.branches ?? [];
  const skus = scope.skus ?? [];

  return (
    <div className="rounded-lg border border-[var(--color-primary)]/30 bg-[var(--color-primary)]/5 px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--color-primary)]">
          Workspace
        </span>
        <span className="text-[11px] text-[var(--color-text)]">
          {/* "2 of 53" where the total is known, plain "2" where it is not.
              Some payloads do not load the panel and so cannot count it -
              printing "2 of —" there looked like missing data rather than an
              unasked question. */}
          {branches.length > 0 && (
            <>
              <strong>
                {scope.total_branches
                  ? `${scope.branch_count} of ${scope.total_branches}`
                  : scope.branch_count}
              </strong>{' '}
              branches
            </>
          )}
          {branches.length > 0 && skus.length > 0 && ' · '}
          {skus.length > 0 && (
            <>
              <strong>
                {scope.total_skus ? `${scope.sku_count} of ${scope.total_skus}` : scope.sku_count}
              </strong>{' '}
              SKUs
            </>
          )}
        </span>
        <span className="text-[10px] text-[var(--color-text-muted)]">
          {SOURCE_LABEL[scope.source] ?? scope.source}
        </span>
        <button
          type="button"
          className="link-button ml-auto text-[10px]"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          {open ? 'Hide the list' : 'What is in scope?'}
        </button>
      </div>

      <p className="mt-1 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
        Every figure on this page describes that slice only — not the national network.
      </p>

      {open && (
        <div className="mt-2 flex flex-col gap-2 border-t border-[var(--color-primary)]/20 pt-2">
          {branches.length > 0 && (
            <div>
              <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
                Branches
              </span>
              <div className="mt-0.5 flex flex-wrap gap-1">
                {branches.map((b) => (
                  <code key={b} className="scope-chip">
                    {b}
                  </code>
                ))}
              </div>
            </div>
          )}
          {skus.length > 0 && (
            <div>
              <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
                SKUs
              </span>
              <div className="mt-0.5 flex flex-wrap gap-1">
                {skus.map((sku) => (
                  <code key={sku} className="scope-chip">
                    {sku}
                  </code>
                ))}
              </div>
            </div>
          )}
          <p className="text-[10px] leading-relaxed text-[var(--color-text-muted)]">
            Source: {scope.detail}. The five client files are untouched — this narrows what
            is read, it does not delete anything.
          </p>
        </div>
      )}
    </div>
  );
}
