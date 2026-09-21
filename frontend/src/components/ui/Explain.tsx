/**
 * An explanation, collapsed to one clickable line.
 *
 * The pages carry a lot of standing explanation — how a metric is defined,
 * why a number is not what it looks like, what a chart excludes. All of it
 * earns its place the first time somebody reads a page, and none of it earns
 * the vertical space on the twentieth visit. Several panels each carrying
 * three lines of caveat also read as faults to anyone seeing the page fresh,
 * which is the opposite of what the text is for.
 *
 * So the text is not removed and not shortened — it is one click away, with
 * the trigger naming what is underneath rather than saying "more". Nothing
 * here decides what a planner does; it explains what they are looking at.
 *
 * Deliberately NOT applied to `.callout.crit` and `.callout.warn`. Those carry
 * failed controls, blocking states and data defects. This repository's rule is
 * that a failure is never hidden, and a warning behind a click is hidden.
 */
import { useId, useState, type ReactNode } from 'react';

const LABELS = {
  hint: 'What this means',
  note: 'How to read this',
  callout: 'Why this matters',
} as const;

export type ExplainVariant = keyof typeof LABELS;

export function Explain({
  children,
  variant = 'hint',
  label,
  className,
  style,
}: {
  children: ReactNode;
  variant?: ExplainVariant;
  /** Overrides the default trigger text when the panel has a better name. */
  label?: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  // Collapsed in the application. The test suite asserts that a page *states*
  // something, which is still true when the statement is one click away, so
  // `src/test/setup.ts` opens these by default rather than every test having
  // to drive the disclosure. `Explain.test.tsx` turns it back off and covers
  // the real collapse-and-expand behaviour.
  const [open, setOpen] = useState(
    () => Boolean((globalThis as { __EXPLAIN_DEFAULT_OPEN__?: boolean }).__EXPLAIN_DEFAULT_OPEN__),
  );
  const id = useId();

  return (
    <div className={`explain${className ? ` ${className}` : ''}`} style={style}>
      <button
        type="button"
        className="explain-trigger"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="explain-caret" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
        {label ?? LABELS[variant]}
      </button>
      {open && (
        <div id={id} className={`explain-body ${variant}`}>
          {children}
        </div>
      )}
    </div>
  );
}
