import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ComparisonBars } from '@/components/charts/ComparisonBars';
import { datasetKeys, fetchMapping, fetchProfile } from '@/api/datasets';
import { createMapping, fetchCurrentMapping, mappingKeys } from '@/api/mappings';
import { useActiveDataset } from '@/hooks/useActiveDataset';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import { formatInt, titleiseRole } from '@/components/ui/format';
import { ApiError } from '@/api/client';
import { RoleEditor } from '@/features/mapping/components/RoleEditor';
import { PreprocessingPanel } from '@/features/mapping/components/PreprocessingPanel';
import { PanelPanel } from '@/features/mapping/components/PanelPanel';
import { Explain } from '@/components/ui/Explain';

const FINDING_LABEL: Record<string, string> = {
  oracle_collision: 'Oracle No collision',
  canonical_disagreement: 'Canonical disagreement',
  missing_oracle_no: 'Missing Oracle No',
};

export function MappingPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { dataset, hasCompleted, isRunning } = useActiveDataset();

  const roleMapping = useQuery({
    queryKey: mappingKeys.current(dataset?.id ?? ''),
    queryFn: () => fetchCurrentMapping(dataset!.id),
    enabled: Boolean(dataset?.id) && hasCompleted,
    retry: false,
  });

  const createDraft = useMutation({
    mutationFn: () => createMapping(dataset!.id, 'Created from Mapping & Validation.'),
    onSuccess: () => {
      toast.notify('Draft mapping created from the AIS template.', 'ok');
      void queryClient.invalidateQueries({ queryKey: mappingKeys.current(dataset!.id) });
    },
    onError: (error) =>
      toast.notify(
        error instanceof ApiError ? error.message : 'Could not create a mapping.',
        'error',
      ),
  });

  const mapping = useQuery({
    queryKey: datasetKeys.mapping(dataset?.id ?? ''),
    queryFn: () => fetchMapping(dataset!.id),
    enabled: Boolean(dataset?.id) && hasCompleted,
  });

  const profile = useQuery({
    queryKey: datasetKeys.profile(dataset?.id ?? ''),
    queryFn: () => fetchProfile(dataset!.id),
    enabled: Boolean(dataset?.id) && hasCompleted,
  });

  return (
    <div className="stack">
      <div className="page-head">
        <div className="eyebrow">03 &middot; Mapping &amp; Validation</div>
        <h1>Mapping &amp; Validation</h1>
        <Explain label="About this page" variant="note">
          The canonical SKU key, reconciled against Oracle No, and the column
          roles that feed the model. Every join key is reported with the
          evidence for choosing it.
        </Explain>
      </div>

      {!dataset && (
        <Card>
          <EmptyState title="No ingested dataset yet">
            Start an ingestion in Data Studio. The key reconciliation is
            computed during that pass.
          </EmptyState>
        </Card>
      )}

      {isRunning && (
        <Card>
          <EmptyState title="Ingestion is still running">
            The canonical-key reconciliation is produced at the end of the
            streaming pass. This page fills in once it completes.
          </EmptyState>
        </Card>
      )}

      {mapping.isPending && hasCompleted && (
        <Card title="Key reconciliation">
          <LoadingBlock rows={5} label="Loading key reconciliation" />
        </Card>
      )}

      {mapping.isError && (
        <Card>
          <ErrorState error={mapping.error} onRetry={() => mapping.refetch()} />
        </Card>
      )}

      {mapping.data && (
        <>
          <Card
            title="The canonical SKU key"
            subtitle="Why Product Code, and not raw Oracle No · measured over the whole source file"
          >
            {/* Every other screen is cut to the workspace's branches, and the
                leaderboard to the series a training run reached. This one is
                not, and that is deliberate: its job is to prove the key rule
                over *all* the data. Validating it on a 20-SKU slice would
                have hidden the 109 Oracle No collisions, which is the whole
                finding. Saying so here stops the count reading as a
                contradiction of the pages that are scoped. */}
            <Explain variant="hint" style={{ marginBottom: 'var(--sp-3)' }}>
              These counts describe the <strong>source data</strong>, before any
              workspace or training restriction. They are deliberately unscoped:
              a key rule validated on a slice would hide the collisions it exists
              to find. The workspace and the trained series are narrower — see
              Demand Analytics and the Model Leaderboard for those.
            </Explain>
            <div className="tiles">
              <div className="tile is-ok">
                <div className="k">Canonical SKUs</div>
                <div className="v">{formatInt(mapping.data.canonical_sku_count)}</div>
                <div className="s">from Product Code · whole source file</div>
              </div>
              <div className="tile is-warn">
                <div className="k">Distinct Oracle No</div>
                <div className="v">{formatInt(mapping.data.oracle_no_count)}</div>
                <div className="s">fewer — the keys are not equivalent</div>
              </div>
              <div className="tile is-crit">
                <div className="k">Oracle No collisions</div>
                <div className="v">{formatInt(mapping.data.oracle_collision_count)}</div>
                <div className="s">one Oracle No, several products</div>
              </div>
              <div className="tile is-ok">
                <div className="k">Disagreements</div>
                <div className="v">{formatInt(mapping.data.canonical_disagreement_count)}</div>
                <div className="s">canonical → Oracle is many-to-one</div>
              </div>
              <div className="tile">
                <div className="k">Rows without Oracle No</div>
                <div className="v">{formatInt(mapping.data.rows_missing_oracle)}</div>
              </div>
            </div>

            <Explain variant="callout" style={{ marginTop: 'var(--sp-4)' }}>
              <div className="h">Rule applied</div>
              <p className="mono" style={{ fontSize: 12 }}>
                {mapping.data.canonical_key_rule}
              </p>
            </Explain>
            <div className="callout warn" style={{ marginTop: 'var(--sp-3)' }}>
              <div className="h">Why raw Oracle No is not the SKU key</div>
              <p>{mapping.data.why_not_oracle_no}</p>
            </div>
          </Card>

          <div className="grid-2">
            <Card title="SKU-code prefixes" subtitle="Where the extra identities come from">
              <div className="table-scroll">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Prefix</th>
                      <th className="num">Rows</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(mapping.data.sku_prefixes)
                      .sort((a, b) => b[1] - a[1])
                      .map(([prefix, count]) => (
                        <tr key={prefix}>
                          <td className="mono">{prefix}</td>
                          <td className="num">{formatInt(count)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </Card>

            <Card
              title="Four branch universes"
              subtitle="Reconciled explicitly, never conflated"
            >
              <ComparisonBars unit="Branches" labels={Object.keys(mapping.data.branch_universes).map(titleiseRole)} series={[{ name: 'Distinct branches', values: Object.values(mapping.data.branch_universes) }]} height={240} />
              <div className="table-scroll">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th className="num">Branches</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(mapping.data.branch_universes).map(([source, count]) => (
                      <tr key={source}>
                        <td>{titleiseRole(source)}</td>
                        <td className="num">{formatInt(count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>

          <Card title="SKU universes by source" subtitle="Different files, different keys">
            <div className="table-scroll">
              <table className="data">
                <thead>
                  <tr>
                    <th>Source and key</th>
                    <th className="num">Distinct SKUs</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(mapping.data.sku_universes).map(([source, count]) => (
                    <tr key={source}>
                      <td>{titleiseRole(source)}</td>
                      <td className="num">{formatInt(count)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card
            title="Reconciliation findings"
            subtitle={`${formatInt(mapping.data.findings_total)} findings recorded; showing ${mapping.data.findings.length}`}
          >
            {mapping.data.findings.length === 0 ? (
              <EmptyState title="No findings recorded">
                The canonical key maps cleanly onto Oracle No in this version.
              </EmptyState>
            ) : (
              <div className="table-scroll">
                <table className="data" data-testid="findings-table">
                  <thead>
                    <tr>
                      <th>Type</th>
                      <th>Key</th>
                      <th className="num">Count</th>
                      <th>Related values</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mapping.data.findings.map((finding) => (
                      <tr key={`${finding.finding_type}-${finding.key_value}`}>
                        <td>
                          <span className="pill pill-warn">
                            {FINDING_LABEL[finding.finding_type] ?? finding.finding_type}
                          </span>
                        </td>
                        <td className="mono" style={{ fontSize: 11.5 }}>
                          {finding.key_value}
                        </td>
                        <td className="num">{finding.occurrence_count}</td>
                        <td className="mono dim" style={{ fontSize: 11 }}>
                          {finding.related_values?.join(' · ') ?? '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}

      {profile.data && (
        <Card
          title="Column roles"
          subtitle="PII is counted but its values are never read into a profile or a payload"
        >
          {profile.data.source_files.map((file) => (
            <details key={file.role} style={{ marginBottom: 'var(--sp-3)' }}>
              <summary style={{ cursor: 'pointer', padding: '6px 0', fontWeight: 600 }}>
                {titleiseRole(file.role)}{' '}
                <span className="dim" style={{ fontWeight: 400 }}>
                  — {file.column_count} columns,{' '}
                  {file.column_profiles.filter((c) => c.is_pii).length} PII
                </span>
              </summary>
              <div className="table-scroll">
                <table className="data">
                  <thead>
                    <tr>
                      <th className="num">#</th>
                      <th>Column</th>
                      <th>Type</th>
                      <th className="num">Non-null</th>
                      <th className="num">Null</th>
                      <th className="num">Distinct</th>
                      <th>Flags</th>
                      <th>Sample</th>
                    </tr>
                  </thead>
                  <tbody>
                    {file.column_profiles.map((column) => (
                      <tr key={column.column_name}>
                        <td className="num dim">{column.ordinal}</td>
                        <td className="mono" style={{ fontSize: 11.5 }}>
                          {column.column_name}
                        </td>
                        <td className="dim">{column.detected_type}</td>
                        <td className="num">{formatInt(column.non_null_count)}</td>
                        <td className="num dim">{formatInt(column.null_count)}</td>
                        <td className="num dim">
                          {column.distinct_count === null ? '—' : formatInt(column.distinct_count)}
                        </td>
                        <td>
                          {column.is_pii && <span className="pill pill-crit">PII excluded</span>}
                          {column.is_constant && !column.is_pii && (
                            <span className="pill pill-neutral">constant</span>
                          )}
                        </td>
                        <td className="mono dim" style={{ fontSize: 11 }}>
                          {column.is_pii ? '—' : (column.sample_values?.[0] ?? '—')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          ))}
        </Card>
      )}

      {hasCompleted && roleMapping.isError && (
        <Card title="Column roles">
          <EmptyState
            title="No role mapping yet"
            action={
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => createDraft.mutate()}
                disabled={createDraft.isPending}
              >
                {createDraft.isPending ? 'Creating…' : 'Create draft mapping'}
              </button>
            }
          >
            A draft is seeded from the AIS template, with the generic suggester
            filling any column the template has no opinion on. Every assignment
            is editable, and nothing is authoritative until a person confirms
            it.
          </EmptyState>
        </Card>
      )}

      {roleMapping.isPending && hasCompleted && (
        <Card title="Column roles">
          <LoadingBlock rows={6} label="Loading role mapping" />
        </Card>
      )}

      {roleMapping.data && dataset && (
        <>
          <RoleEditor mapping={roleMapping.data} datasetId={dataset.id} />
          <div style={{ display: 'flex', gap: 'var(--sp-3)' }}>
            <button
              type="button"
              className="btn"
              onClick={() => createDraft.mutate()}
              disabled={createDraft.isPending}
            >
              {createDraft.isPending ? 'Creating…' : 'Create a new mapping version'}
            </button>
          </div>
          <PreprocessingPanel mappingId={roleMapping.data.id} />
          <PanelPanel />
        </>
      )}
    </div>
  );
}
