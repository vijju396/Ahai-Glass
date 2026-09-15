/**
 * How to read Supply Intelligence.
 *
 * This page recommends order quantities, which is the most consequential
 * thing the application does — so the vocabulary behind those numbers needs
 * to be on the page, not in a document. Someone who does not know what a
 * protection period is cannot judge whether a recommended quantity is
 * sensible, and will either trust it blindly or ignore it.
 *
 * Every figure named here is defined, and every limitation is stated in the
 * same breath rather than in a footnote: there is no inventory-policy
 * backtest in this project, stock is one snapshot, and lead-time variability
 * is measured but not yet used in the cover calculation.
 */
import { useState } from 'react';
import { Card } from '@/components/ui/Card';

interface Term {
  term: string;
  plain: string;
  detail: string;
  caution?: string;
}

const TERMS: Term[] = [
  {
    term: 'Recommended order',
    plain: 'How many units to order now for this branch × SKU.',
    detail:
      'Target stock minus what is already usable on hand. Target stock is the demand expected over the protection period at the chosen service level, so the recommendation moves when you change the service level.',
    caution:
      'A current-snapshot estimate. There is no historical inventory-policy backtest in this project, so nothing here can claim that ordering this quantity would have performed better than what was actually ordered.',
  },
  {
    term: 'Protection period',
    plain: 'The stretch of time the order has to cover.',
    detail:
      'Review period plus average lead time. The review period is how long until you would next place an order; the lead time is how long the branch waits for delivery. Together they are the window during which no new stock can arrive.',
    caution:
      'Built from the average lead time only. A branch whose lead time swings between 1 and 6 days gets exactly the same cover as one reliably at 3 days — the spread is measured and shown in the lead-time panels, but it does not yet feed this number.',
  },
  {
    term: 'Service level (q80 / q90 / q95)',
    plain: 'How often you want to be able to meet demand from stock.',
    detail:
      'q95 is the demand quantity that is not expected to be exceeded 95% of the time. Sizing on q95 rather than on the point forecast is what turns a forecast into a stocking decision: half the time demand is above the point forecast, and that half is where stockouts come from.',
    caution:
      'These are service-level quantities, not a symmetric confidence interval around the forecast. q95 is not "the forecast ± error".',
  },
  {
    term: 'Usable stock',
    plain: 'What is actually available to sell at that branch today.',
    detail:
      'From the stock snapshot dated 2026-08-01, excluding quantities the source marks as unusable.',
    caution:
      'One snapshot, and demand history ends 2026-07. Anything derived from stock is a position at a moment, never a trend — there is no stock history to trend against.',
  },
  {
    term: 'Dead or slow stock',
    plain: 'Stock sitting where nothing has been ordered.',
    detail:
      'Usable stock at a branch × SKU that had no ordered demand in the last six months of history. It is a placement signal — the units may well sell somewhere else.',
    caution:
      'Not an instruction to scrap. A slow-moving safety item and genuinely dead stock look identical in this measure.',
  },
  {
    term: 'Zero stock against live demand',
    plain: 'Demand exists, stock does not.',
    detail:
      'No usable stock at that branch × SKU while demand was ordered in the last six months. The "Who holds it?" control finds other branches carrying the same SKU.',
    caution:
      'A placement problem, not necessarily a shortage: the units may exist elsewhere in the network.',
  },
  {
    term: 'Negative stock row',
    plain: 'The snapshot reports a negative quantity.',
    detail:
      'Physically impossible, so it is a defect in the source data — usually a timing mismatch between despatch and receipt.',
    caution:
      'Surfaced, never clamped to zero. Silently correcting it would hide a real problem in the feed.',
  },
  {
    term: 'Lead-time variability (CV)',
    plain: 'How unreliable a branch’s lead time is.',
    detail:
      'The standard deviation of lead time as a percentage of its mean. A high figure means the average is a weak planning number for that branch.',
    caution:
      'Measured and shown, but not used in the protection period. Feeding it into safety stock would change every recommended quantity on this page, which is a decision rather than a fix.',
  },
];

export function SupplyExplainer() {
  const [open, setOpen] = useState<string | null>(null);

  return (
    <Card>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text)]">
          How to read these recommendations
        </h2>
        <span className="text-[10px] text-[var(--color-text-muted)]">
          Click a term for the detail and its limits
        </span>
      </div>

      <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
        {TERMS.map((t) => {
          const isOpen = open === t.term;
          return (
            <div
              key={t.term}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-2.5 py-2"
            >
              <button
                type="button"
                className="flex w-full items-baseline justify-between gap-2 text-left"
                aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? null : t.term)}
              >
                <span className="text-[11.5px] font-semibold text-[var(--color-text)]">
                  {t.term}
                </span>
                <span className="shrink-0 text-[10px] text-[var(--color-primary)]">
                  {isOpen ? '−' : '+'}
                </span>
              </button>
              <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--color-text-muted)]">
                {t.plain}
              </p>
              {isOpen && (
                <div className="mt-1.5 border-t border-[var(--color-border)] pt-1.5">
                  <p className="text-[11px] leading-relaxed text-[var(--color-text)]">{t.detail}</p>
                  {t.caution && (
                    <p className="mt-1 text-[10.5px] leading-relaxed text-[var(--ais-diamond,#b3261e)]">
                      <strong>Limit: </strong>
                      {t.caution}
                    </p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <p className="mt-2.5 border-t border-[var(--color-border)] pt-2 text-[10.5px] leading-relaxed text-[var(--color-text-muted)]">
        <strong>The one caveat that applies to everything above.</strong> Every quantity on
        this page is computed from a single stock snapshot and a forecast, and this project
        has no historical inventory-policy backtest — there is no stock history to run one
        against. So these are estimates to judge, not results that were measured to work.
      </p>
    </Card>
  );
}
