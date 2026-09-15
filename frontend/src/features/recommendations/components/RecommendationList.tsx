/**
 * AI recommendations — the standing "what should I look at?" list.
 *
 * Its own destination, separate from the AI Assistant: the assistant answers
 * what you ask, this answers the question you have before you know what to
 * ask. Both read the same bounded read-only tools, and neither can reach
 * anything else.
 *
 * Three things it is careful about, all of them for the same reason: these are
 * numbers someone may act on.
 *
 * - **Every item shows its evidence.** The figures the claim rests on are
 *   printed on the card, and the page they can be checked against is named.
 *   An item the backend could not attach a measured figure to was dropped
 *   before it got here.
 * - **It says who wrote it.** A model-written list and the deterministic
 *   template list read the same on a screen, so the badge distinguishes them.
 * - **It repeats the caveats.** Nothing here is an instruction to act, and the
 *   workspace scope means the whole list describes two branches.
 */
import { useQuery } from '@tanstack/react-query';
import {
  fetchRecommendations,
  recommendationKeys,
  type Recommendation,
} from '@/api/analytics';
import { Badge, Card } from '@/components/ui/Dashboard';
import { ErrorState, LoadingBlock } from '@/components/ui/States';

const SEVERITY: Record<string, { tone: string; label: string; bar: string }> = {
  critical: { tone: 'critical', label: 'Critical', bar: 'bg-[var(--ais-diamond)]' },
  high: { tone: 'high', label: 'High', bar: 'bg-amber-500' },
  medium: { tone: 'medium', label: 'Medium', bar: 'bg-slate-400' },
};

/** How the list was produced. A template and a model read identically on a
 *  screen, so the difference has to be stated rather than implied. */
const WRITER: Record<string, { text: string; tone: string }> = {
  openai: { text: 'Written by the model from measured facts', tone: 'champion' },
  deterministic_no_key: { text: 'Written from templates — no API key configured', tone: 'medium' },
  deterministic_after_provider_error: {
    text: 'Written from templates — the provider failed',
    tone: 'high',
  },
};

function Item({ item }: { item: Recommendation }) {
  const severity = SEVERITY[item.severity] ?? SEVERITY.medium!;
  return (
    <li className="flex gap-2.5">
      <span className={`mt-1 w-[3px] shrink-0 rounded-full ${severity.bar}`} aria-hidden />
      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="flex flex-wrap items-baseline gap-2">
          <h3 className="text-[13px] font-semibold text-[var(--color-text)]">{item.title}</h3>
          <Badge status={severity.tone}>{severity.label}</Badge>
        </div>
        <p className="text-[12px] font-medium leading-relaxed text-[var(--color-text)]">
          {item.observation}
        </p>
        <p className="text-[12px] leading-relaxed text-[var(--color-text-muted)]">
          {item.explanation}
        </p>
        {item.next_step && (
          <p className="text-[12px] leading-relaxed text-[var(--color-text)]">
            <span className="font-semibold">Next step: </span>
            {item.next_step}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
          {item.evidence.map((figure) => (
            <code
              key={figure}
              className="rounded border border-[var(--color-border)] bg-[var(--color-surface-2)] px-1.5 py-0.5 text-[10px] text-[var(--color-text-muted)]"
            >
              {figure}
            </code>
          ))}
          {item.verify_on && (
            <span className="text-[10px] text-[var(--color-text-muted)]">
              · check on {item.verify_on}
            </span>
          )}
        </div>
      </div>
    </li>
  );
}

export function RecommendationList() {
  const query = useQuery({
    queryKey: recommendationKeys.all,
    queryFn: fetchRecommendations,
    retry: false,
  });
  const data = query.data;
  const writer = data ? WRITER[data.answered_by] : undefined;

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-primary)]">
            What is worth attention
          </h2>
          {writer && <Badge status={writer.tone}>{writer.text}</Badge>}
          {data?.answered_by === 'openai' && (
            // Temperature is on the card because it changes what the reader is
            // looking at: at 2.0 the same facts produce a noticeably different
            // list each time, and that is worth knowing before comparing two.
            <span className="text-[10px] text-[var(--color-text-muted)]">
              temperature {data.temperature}
            </span>
          )}
        </div>
        <button
          type="button"
          className="link-button text-[11px]"
          onClick={() => query.refetch()}
          disabled={query.isFetching}
        >
          {query.isFetching ? 'Re-reading…' : 'Refresh'}
        </button>
      </div>

      <div className="mt-2.5">
        {query.isPending && <LoadingBlock rows={4} label="Reading the application's data" />}
        {query.isError && <ErrorState error={query.error} onRetry={() => query.refetch()} />}

        {data && data.items.length === 0 && (
          <p className="text-[12px] leading-relaxed text-[var(--color-text-muted)]">
            Nothing met the bar for a recommendation. An item has to carry a measured
            figure from this application's own data, and anything that could not was
            dropped rather than softened into a vague suggestion.
          </p>
        )}

        {data && data.items.length > 0 && (
          <ul className="flex flex-col gap-3.5">
            {data.items.map((item) => (
              <Item key={item.title} item={item} />
            ))}
          </ul>
        )}

        {data && data.caveats.length > 0 && (
          <ul className="mt-3 flex flex-col gap-1 border-t border-[var(--color-border)] pt-2">
            {data.caveats.map((note) => (
              <li
                key={note}
                className="text-[10px] leading-relaxed text-[var(--color-text-muted)]"
              >
                {note}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
