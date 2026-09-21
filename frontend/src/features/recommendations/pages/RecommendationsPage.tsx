/**
 * AI Recommendations — its own destination.
 *
 * Separate from the AI Assistant on purpose. The assistant answers what you
 * ask; this answers the question you have before you know what to ask. They
 * read the same bounded, read-only tools and neither can reach anything else,
 * but they are different jobs: one is a conversation you drive, the other is a
 * standing list that is the same every time you open it.
 *
 * Sharing a page made the standing list read as part of a conversation it had
 * nothing to do with, and cost the conversation its height.
 */
import { Link } from 'react-router-dom';
import { RecommendationList } from '@/features/recommendations/components/RecommendationList';
import { Card } from '@/components/ui/Dashboard';
import { Explain } from '@/components/ui/Explain';

export function RecommendationsPage() {
  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-primary)]">
            AI Recommendations
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[var(--color-text)]">
            What is worth your attention.
          </h1>
          <Explain label="About this page" variant="note">
            A standing pass over this application&apos;s own exceptions, replenishment,
            model error and data quality. Every item carries the figures it rests on and
            names the page you can check them against.
          </Explain>
        </div>
        <Link
          to="/assistant"
          className="rounded-lg border border-[var(--color-primary)] px-3 py-1.5 text-xs font-medium text-[var(--color-primary)] hover:bg-[var(--color-primary)]/10"
        >
          Ask a question instead
        </Link>
      </header>

      <RecommendationList />

      <Card>
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text)]">
          How this list is built
        </h2>
        <ul className="mt-2 flex flex-col gap-1.5">
          {[
            'The same five read-only tools run every time, in the same order. Nothing here can query the database directly, and the list cannot be steered by a parameter.',
            'An item that could not be attached to a measured figure is dropped, not softened into a vague suggestion. Fewer items is the correct outcome.',
            'These are things to look at, not instructions to act. This project has no inventory-policy backtest, so nothing here can claim that acting would have helped.',
            'Without an API key the list is still produced, from templates, and the badge says so — a model-written list and a template one read identically otherwise.',
          ].map((note) => (
            <li key={note} className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
              {note}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
