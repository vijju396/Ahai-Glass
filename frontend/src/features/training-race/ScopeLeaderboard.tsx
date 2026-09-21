/**
 * One branch x SKU at a time: which model won *this* line, and by how much.
 *
 * The summary leaderboard beside it answers "which model is best on average
 * across every scope". That is a different question from "which model do I get
 * for the SKU I am about to schedule", and the two genuinely disagree - a model
 * can lead the average and lose forty out of forty individual lines. This table
 * answers the second question, from `GET /api/models/leaderboard` at the scope
 * asked for, which is the same ranking the champion selector read.
 *
 * Models that did not run are rows here too, with the requirement they missed,
 * for the same reason they are rows on the summary: a model that vanishes when
 * it fails makes the field look stronger than it is.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchLeaderboard, leaderboardKeys } from '@/api/leaderboard';
import { AMBER, GREEN, RED } from '@/components/ui/Dashboard';
import { ErrorState, LoadingBlock } from '@/components/ui/States';
import { Explain } from '@/components/ui/Explain';

const pct = (v: number | null, digits = 1) => (v == null ? '—' : `${v.toFixed(digits)}%`);

/** 100 - MAPE, floored at zero. Restating one number, not a second measure. */
const accuracy = (mape: number | null) => (mape == null ? null : Math.max(0, 100 - mape));

export function ScopeLeaderboard({
  trainingRunId,
  scopeKey,
}: {
  trainingRunId?: string;
  scopeKey: string;
}) {
  const query = useMemo(
    () => ({
      ...(trainingRunId ? { training_run_id: trainingRunId } : {}),
      scope_level: 'series',
      scope_key: scopeKey,
    }),
    [trainingRunId, scopeKey],
  );
  const board = useQuery({
    queryKey: leaderboardKeys.board(query),
    queryFn: () => fetchLeaderboard(query),
    retry: false,
  });

  if (board.isPending) return <LoadingBlock rows={6} label={`Reading ${scopeKey}`} />;
  if (board.isError) return <ErrorState error={board.error} onRetry={() => board.refetch()} />;

  const rows = (board.data?.rows ?? []).filter((r) => !r.is_baseline);
  const ranked = rows
    .slice()
    .sort((a, b) => (a.rank ?? 9e9) - (b.rank ?? 9e9) || a.display_name.localeCompare(b.display_name));
  const winner = ranked.find((r) => r.is_champion);
  /* Models that scored on the test months and still could not be fitted on
     this line's full history. They are not a footnote: one of them may have
     had the best score on the board, and the reader is owed the reason the
     crown went past it. */
  const refused = ranked.filter((r) => r.exclusion === 'not_deployable');

  return (
    <div>
      <p className="mb-2 text-[11px] text-[var(--color-text-muted)]">
        {winner ? (
          <>
            For this line the forecast comes from <strong>{winner.display_name}</strong>, which was
            wrong by <strong>{pct(winner.mape)}</strong> on the months it was tested against —{' '}
            <strong>{pct(accuracy(winner.mape))} accurate</strong> over{' '}
            {winner.distinct_test_points || winner.validation_points} test month(s).
          </>
        ) : (
          <>No model produced a rankable result for this line.</>
        )}
      </p>

      {refused.length > 0 && (
        <p
          className="mb-2 rounded-lg border px-2 py-1.5 text-[10px] leading-relaxed"
          style={{ borderColor: `${AMBER}55`, background: `${AMBER}0f`, color: 'var(--color-text)' }}
        >
          <strong>
            {refused.length} model{refused.length > 1 ? 's' : ''} scored on the test months but
            cannot run on this line.
          </strong>{' '}
          A model is tested on a window that stops short of today and then refitted on everything,
          and these could not make the second fit — so they were passed over rather than crowned
          and left producing nothing. They are in the table below with the requirement each one
          missed: {refused.map((r) => r.display_name).join(', ')}.
        </p>
      )}

      {board.data?.ranking_source === 'recomputed' && (
        <p className="mb-2 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
          No champion has been selected for this line from this run, so this is the test-month
          ranking alone. A model can lead it and still be unable to fit on the full history.
        </p>
      )}

      <div className="table-scroll">
        <table className="data">
          <thead>
            <tr>
              <th className="num">#</th>
              <th>Model</th>
              <th className="num">Accuracy</th>
              <th className="num">MAPE</th>
              <th className="num">WAPE</th>
              <th className="num">Bias</th>
              <th className="num">Months</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((r) => (
              <tr key={r.model_id} title={r.exclusion_reason ?? r.failure_reason ?? undefined}>
                <td className="num" style={{ color: r.is_champion ? GREEN : undefined }}>
                  {r.rank ?? '—'}
                </td>
                <td style={{ fontWeight: r.is_champion ? 600 : 400 }}>{r.display_name}</td>
                <td className="num" style={{ fontWeight: 600 }}>
                  {pct(accuracy(r.mape))}
                </td>
                <td className="num">{pct(r.mape)}</td>
                <td className="num">{pct(r.wape)}</td>
                <td className="num" style={{ color: (r.bias ?? 0) < 0 ? AMBER : undefined }}>
                  {pct(r.bias)}
                </td>
                <td className="num">{r.distinct_test_points || r.validation_points || '—'}</td>
                <td
                  className="text-[10px]"
                  style={{
                    color: r.ranked
                      ? undefined
                      : r.status === 'failed'
                        ? RED
                        : 'var(--color-text-muted)',
                  }}
                >
                  {r.is_champion ? 'In use' : r.ranked ? 'Ranked' : (r.exclusion ?? r.status)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-2">
        <Explain variant="note">
          Every registered model is listed, including the ones that did not run — a model that
          disappears when it fails makes the field look stronger than it is. Hover a row that is
          not ranked to read the requirement it missed. Accuracy is 100 minus MAPE, floored at
          zero, which is the same number restated rather than a second measurement. WAPE is the
          total units missed over the total units ordered, so it answers the same question in
          units instead of in percent-per-month. A negative bias means the model forecasts below
          real demand, which is the direction that causes a stockout.
        </Explain>
      </div>
    </div>
  );
}
