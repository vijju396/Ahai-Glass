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
import { LineRecommendations } from '@/features/recommendations/components/LineRecommendations';
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
  computed_only: {
    text: 'Computed — figures and ranking, explanations still being written',
    tone: 'medium',
  },
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
  /* Two passes, on purpose.
   *
   * The ranking, every figure and each line's own reason are computed without
   * a model and are ready in about six seconds; the model only writes the
   * wording, and both calls together took about thirty-five. Waiting on the
   * prose meant a skeleton on screen for half a minute with accurate content
   * already sitting behind it.
   *
   * So the fast pass renders first and the written one replaces it when it
   * arrives. The figures do not move between the two - only the sentences
   * do - because the numbers were never the model's to produce (D-104). */
  const computed = useQuery({
    queryKey: recommendationKeys.pass(false),
    queryFn: () => fetchRecommendations(false),
    retry: false,
  });
  const written = useQuery({
    queryKey: recommendationKeys.pass(true),
    queryFn: () => fetchRecommendations(true),
    retry: false,
    // Only once the fast pass has proved the endpoint answers at all, so a
    // hard failure surfaces in six seconds rather than thirty-five.
    enabled: computed.isSuccess,
  });

  const data = written.data ?? computed.data;
  const query = written.data ? written : computed;
  const writer = data ? WRITER[data.answered_by] : undefined;
  const awaitingProse = Boolean(computed.data) && written.isFetching;

  const refetch = () => {
    computed.refetch();
    written.refetch();
  };

  return (
    <div className="flex flex-col gap-4">
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-primary)]">
            What is worth attention
          </h2>
          {writer && <Badge status={writer.tone}>{writer.text}</Badge>}
          {awaitingProse && (
            // Said rather than spun on. The figures on screen are final; only
            // the wording is still being written.
            <span className="text-[10px] text-[var(--color-text-muted)]">
              figures are final — writing the explanations…
            </span>
          )}
          {data?.cached && (
            <span className="text-[10px] text-[var(--color-text-muted)]">
              from the last pass, {Math.round((data.cache_age_seconds ?? 0) / 60)} min ago
            </span>
          )}
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
          // A stable accessible name. The visible label changes to report
          // progress, but a control whose identity changes with its state is
          // one a screen reader cannot follow.
          aria-label="Refresh recommendations"
          className="link-button text-[11px]"
          onClick={refetch}
          disabled={computed.isFetching || written.isFetching}
        >
          {computed.isFetching || written.isFetching ? 'Re-reading…' : 'Refresh'}
        </button>
      </div>

      <div className="mt-2.5">
        {computed.isPending && (
          <LoadingBlock rows={4} label="Reading the application's data" />
        )}
        {query.isError && <ErrorState error={query.error} onRetry={refetch} />}

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

    {/* Below the network signals on purpose. Drift and data-quality findings
        genuinely are network-level and have nowhere else to live; the lines
        are what someone actually orders against. */}
    {data && (
      <LineRecommendations
        lines={data.lines ?? []}
        counts={data.line_counts ?? {}}
        total={data.lines_total ?? 0}
        shown={data.lines_shown ?? 0}
        answeredBy={data.lines_answered_by ?? null}
      />
    )}
    </div>
  );
}
