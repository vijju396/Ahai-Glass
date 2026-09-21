/**
 * A dropdown whose rows can carry a very small green dot.
 *
 * This exists because a native `<option>` renders text and nothing else: the
 * only way to put a green mark in one is an emoji, and the smallest green emoji
 * is the size of the label beside it. A mark that big is the first thing anyone
 * in the room sees, which is the opposite of what it is for.
 *
 * The mark is a 4px dot at the far right of the row, and it appears **only in
 * the open list** — never on the closed control. So it is there for the half
 * second someone is choosing a line, and gone from the screen the rest of the
 * time. It carries no legend and no tooltip on purpose: it is a nudge toward a
 * line, not a claim the page has to stand behind.
 *
 * The list is rendered through a portal into `document.body`, positioned
 * `fixed` under the button. A native `<select>` popup is drawn by the operating
 * system and floats above everything; a plain absolutely-positioned list is
 * not, and both filters sit inside `.card`, which is `overflow: hidden` — it
 * would clip the list to two rows. Portalling it out is the fix that does not
 * require loosening a rule every other card on the site depends on.
 *
 * Everything else behaves like the native control it replaces: same classes, so
 * it looks identical closed; `aria-label` on both the button and the list, so a
 * screen reader still announces the same field; Escape, a click outside, or a
 * scroll closes it; rows are `role="option"` inside a `role="listbox"`.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { GREEN } from './Dashboard';

export interface MarkedOption {
  value: string;
  label: string;
  /** Draw the quiet dot on this row. */
  marked?: boolean;
}

/** Room the list needs below the button before it flips above it. */
const MAX_LIST_HEIGHT = 280;

export function MarkedSelect({
  label,
  value,
  options,
  onChange,
  className,
}: {
  /** Announced as the field name, exactly as the native `aria-label` was. */
  label: string;
  value: string;
  options: MarkedOption[];
  onChange: (next: string) => void;
  className: string;
}) {
  const [open, setOpen] = useState(false);
  const [box, setBox] = useState<{ top: number; left: number; width: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);

  /* Measured before paint, so the list never appears at the wrong place for a
     frame. It flips above the button when the space below cannot hold it. */
  useLayoutEffect(() => {
    if (!open || !button.current) return;
    const r = button.current.getBoundingClientRect();
    const below = window.innerHeight - r.bottom;
    const height = Math.min(MAX_LIST_HEIGHT, options.length * 24 + 8);
    setBox({
      top: below < height && r.top > height ? r.top - height - 4 : r.bottom + 4,
      left: r.left,
      width: r.width,
    });
  }, [open, options.length]);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!button.current?.contains(t) && !list.current?.contains(t)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    /* The list is positioned once, so anything that moves the button under it
       closes it rather than leaving it stranded mid-page. */
    const shut = () => setOpen(false);
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', esc);
    window.addEventListener('resize', shut);
    window.addEventListener('scroll', shut, true);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('keydown', esc);
      window.removeEventListener('resize', shut);
      window.removeEventListener('scroll', shut, true);
    };
  }, [open]);

  /* A value the options no longer offer (the other slicer narrowed it away)
     falls back to the first row, which is the "all" row — the same thing the
     native control did when its value stopped matching an option. */
  const picked = options.find((o) => o.value === value) ?? options[0];

  const choose = (next: string) => {
    onChange(next);
    setOpen(false);
  };

  return (
    <>
      <button
        ref={button}
        type="button"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={`${className} flex items-center justify-between gap-2 text-left`}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="truncate">{picked?.label ?? ''}</span>
        <span aria-hidden className="shrink-0 opacity-45">
          ▾
        </span>
      </button>

      {open &&
        box &&
        createPortal(
          <ul
            ref={list}
            role="listbox"
            aria-label={label}
            className="z-50 overflow-y-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] py-1 shadow-lg"
            style={{
              position: 'fixed',
              top: box.top,
              left: box.left,
              minWidth: box.width,
              maxHeight: MAX_LIST_HEIGHT,
            }}
          >
            {options.map((o) => (
              <li
                key={o.value}
                role="option"
                aria-selected={o.value === picked?.value}
                tabIndex={0}
                className={`flex cursor-pointer items-center justify-between gap-3 whitespace-nowrap px-2.5 py-1 text-[11px] text-[var(--color-text)] hover:bg-[var(--color-surface-2)] ${
                  o.value === picked?.value ? 'bg-[var(--color-surface-2)]' : ''
                }`}
                onClick={() => choose(o.value)}
                onKeyDown={(e) => {
                  if (e.key !== 'Enter' && e.key !== ' ') return;
                  e.preventDefault();
                  choose(o.value);
                }}
              >
                <span>{o.label}</span>
                {/* Always rendered, so every row is the same width and a marked
                    row does not sit a few pixels out from the rest. */}
                <span
                  aria-hidden
                  className="h-[4px] w-[4px] shrink-0 rounded-full"
                  style={{ background: o.marked ? GREEN : 'transparent' }}
                />
              </li>
            ))}
          </ul>,
          document.body,
        )}
    </>
  );
}
