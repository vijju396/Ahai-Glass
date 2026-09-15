/**
 * The caveat a composition chart has to carry in a sampled workspace.
 *
 * The twenty SKUs were chosen by stratification — one per glass type × value
 * class, then one per vehicle category — so that every category is represented
 * at all. That is the right sample for judging how the models behave, and it
 * makes the *volume mix* unrepresentative by construction: the SKU counts are
 * spread deliberately, so the proportions cannot also be proportional.
 *
 * The workspace banner at the top of each page already says the figures cover
 * 2 of 53 branches and 20 of 2,334 SKUs. That is not the same warning. A reader
 * can accept "this is a slice" and still read the glass-type split as the shape
 * of that slice's business — which it is not. Measured on the current
 * workspace, laminated glass is 90.2% of sampled volume against 68.4% across
 * the same two branches with every SKU.
 *
 * So the numbers here are **computed per axis, not written as fixed text**. The
 * first guess was that vehicle category was the problem; it is in fact the
 * least distorted of the four, and vehicle age — which was never a
 * stratification rule — is the worst. A hard-coded sentence would have been
 * confidently wrong, and would have gone stale the moment the workspace
 * changed.
 *
 * It renders nothing when an axis is not materially distorted, and nothing at
 * all when no SKU restriction is configured. A warning on every panel is read
 * on none of them.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchSampleMix, sampleMixKeys, type MixAxis } from '@/api/analytics';

export function SampleMixCaveat({ axis }: { axis: string }) {
  const [open, setOpen] = useState(false);
  const { data } = useQuery({
    queryKey: sampleMixKeys.all,
    queryFn: fetchSampleMix,
    // One request serves every panel that mounts this, and the answer only
    // changes when the workspace or the panel build does.
    staleTime: 5 * 60_000,
    retry: false,
  });

  if (!data?.restricted) return null;
  const row: MixAxis | undefined = data.axes?.[axis];
  if (!row || !row.material || !row.caveat) return null;

  const shown = row.levels.filter((l) => l.sample_pct > 0 || l.branch_pct > 0);

  return (
    <div className="mt-1.5 rounded-lg border border-[var(--ais-diamond,#b3261e)]/30 bg-[var(--ais-diamond,#b3261e)]/[0.06] px-2 py-1.5">
      <button
        type="button"
        className="flex w-full items-start gap-1.5 text-left"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span className="mt-[1px] shrink-0 text-[10px] font-bold text-[var(--ais-diamond,#b3261e)]">
          !
        </span>
        <span className="text-[10px] leading-relaxed text-[var(--color-text)]">
          {row.caveat}
        </span>
        <span className="ml-auto shrink-0 text-[10px] text-[var(--color-primary)]">
          {open ? '−' : '+'}
        </span>
      </button>

      {open && (
        <div className="mt-1.5 border-t border-[var(--color-border)] pt-1.5">
          <table className="w-full text-[10px]">
            <thead>
              <tr className="text-[var(--color-text-muted)]">
                <th className="text-left font-medium">Level</th>
                <th className="text-right font-medium">This chart</th>
                <th className="text-right font-medium">All SKUs, same branches</th>
                <th className="text-right font-medium">Gap</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((l) => (
                <tr key={l.level}>
                  <td
                    className="truncate py-[1px] pr-1 text-[var(--color-text)]"
                    style={{ maxWidth: 150 }}
                    title={l.level}
                  >
                    {l.level}
                  </td>
                  <td className="text-right tabular-nums">{l.sample_pct.toFixed(1)}%</td>
                  <td className="text-right tabular-nums text-[var(--color-text-muted)]">
                    {l.branch_pct.toFixed(1)}%
                  </td>
                  <td
                    className="text-right tabular-nums"
                    style={{
                      color: l.material ? 'var(--ais-diamond,#b3261e)' : 'var(--color-text-muted)',
                      fontWeight: l.material ? 600 : 400,
                    }}
                  >
                    {l.gap_points > 0 ? '+' : ''}
                    {l.gap_points.toFixed(1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1.5 leading-relaxed text-[10px] text-[var(--color-text-muted)]">
            {data.why}
          </p>
          <p className="mt-1 leading-relaxed text-[10px] text-[var(--color-text-muted)]">
            <strong>What is still safe to read here.</strong> Each series is
            forecast independently, so per-SKU and per-branch accuracy mean exactly what
            they say. It is the <em>proportions between categories</em> that belong to the
            sample rather than to the business.
          </p>
        </div>
      )}
    </div>
  );
}
