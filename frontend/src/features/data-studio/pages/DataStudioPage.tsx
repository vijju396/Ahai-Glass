import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ComparisonBars } from '@/components/charts/ComparisonBars';
import {
  cancelIngestion,
  createDataset,
  datasetKeys,
  fetchProfile,
  fetchValidation,
} from '@/api/datasets';
import { useActiveDataset } from '@/hooks/useActiveDataset';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import {
  formatBytes,
  formatDays,
  formatInt,
  formatPct,
  formatSeconds,
  shortHash,
  titleiseRole,
} from '@/components/ui/format';
import type { ControlOutcome, DefectRecord, ValidationControl } from '@/types/api';

const OUTCOME_TONE: Record<ControlOutcome, string> = {
  pass: 'pill-ok',
  fail: 'pill-crit',
  warn: 'pill-warn',
  not_evaluated: 'pill-neutral',
};

const OUTCOME_LABEL: Record<ControlOutcome, string> = {
  pass: 'Pass',
  fail: 'Fail',
  warn: 'Warn',
  not_evaluated: 'Not evaluated',
};

const SEVERITY_TONE: Record<DefectRecord['severity'], string> = {
  blocking: 'pill-crit',
  corrected: 'pill-info',
  recorded: 'pill-warn',
};

function ControlRow({ control }: { control: ValidationControl }) {
  return (
    <tr data-control={control.control_code} data-outcome={control.outcome}>
      <td className="mono">{control.control_code}</td>
      <td>{control.description}</td>
      <td className="num mono">{control.expected ?? '—'}</td>
      <td className="num mono">{control.measured ?? '—'}</td>
      <td>
        <span className={`pill ${OUTCOME_TONE[control.outcome]}`}>
          {OUTCOME_LABEL[control.outcome]}
        </span>
      </td>
      <td className="mono dim">{control.difference ?? '—'}</td>
      <td className="dim">{control.remediation ?? '—'}</td>
    </tr>
  );
}

export function DataStudioPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { dataset, version, isRunning, hasCompleted, isPending, isError, error, refetch } =
    useActiveDataset();

  const profile = useQuery({
    queryKey: datasetKeys.profile(dataset?.id ?? ''),
    queryFn: () => fetchProfile(dataset!.id),
    enabled: Boolean(dataset?.id) && hasCompleted,
  });

  const validation = useQuery({
    queryKey: datasetKeys.validation(dataset?.id ?? ''),
    queryFn: () => fetchValidation(dataset!.id),
    enabled: Boolean(dataset?.id) && hasCompleted,
  });

  const start = useMutation({
    mutationFn: () =>
      createDataset({
        name: `AIS source set ${new Date().toISOString().slice(0, 10)}`,
        description: 'Five client source files, ingested read-only.',
      }),
    onSuccess: (response) => {
      toast.notify(response.message, 'info');
      void queryClient.invalidateQueries({ queryKey: datasetKeys.list });
    },
    onError: (mutationError) =>
      toast.notify(
        mutationError instanceof Error ? mutationError.message : 'Could not start ingestion.',
        'error',
      ),
  });

  const cancel = useMutation({
    mutationFn: () => cancelIngestion(dataset!.id),
    onSuccess: (response) =>
      toast.notify(
        response.cancellation_requested
          ? 'Cancellation requested; the job stops at its next checkpoint.'
          : 'No running ingestion to cancel.',
        'info',
      ),
  });

  const failedControls = validation.data?.controls.filter((c) => c.outcome === 'fail') ?? [];

  return (
    <div className="stack">
      <div className="page-head">
        <div className="eyebrow">02 &middot; Data Studio</div>
        <h1>Data Studio</h1>
        <p className="lede">
          The five client files, streamed read-only. Every structural control is
          shown with its expected and measured value, and every catalogued
          defect with the rule that handled it.
        </p>
      </div>

      {isPending && (
        <Card>
          <LoadingBlock rows={4} label="Loading datasets" />
        </Card>
      )}

      {isError && (
        <Card>
          <ErrorState error={error} onRetry={() => refetch()} />
        </Card>
      )}

      {!isPending && !isError && !dataset && (
        <Card title="No ingestion yet">
          <EmptyState
            title="The source files have not been read"
            action={
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => start.mutate()}
                disabled={start.isPending}
              >
                {start.isPending ? 'Starting…' : 'Start ingestion'}
              </button>
            }
          >
            Ingestion streams roughly 2.6 million rows across five files and
            takes about eight minutes. The originals are opened read-only and
            never modified.
          </EmptyState>
        </Card>
      )}

      {version && (
        <Card
          title={dataset?.name}
          subtitle={`Version ${version.version_number} · ${version.status.replace(/_/g, ' ')}`}
          actions={
            isRunning ? (
              <button
                type="button"
                className="btn"
                onClick={() => cancel.mutate()}
                disabled={cancel.isPending}
              >
                Cancel
              </button>
            ) : (
              <button
                type="button"
                className="btn"
                onClick={() => start.mutate()}
                disabled={start.isPending}
              >
                Re-ingest as a new version
              </button>
            )
          }
        >
          {isRunning && (
            <div role="status" aria-live="polite">
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <span>{version.stage_detail ?? 'Working'}</span>
                <span className="mono">{version.progress_pct.toFixed(0)}%</span>
              </div>
              <div
                style={{
                  height: 6,
                  background: 'var(--surface-3)',
                  borderRadius: 3,
                  overflow: 'hidden',
                }}
                role="progressbar"
                aria-valuenow={Math.round(version.progress_pct)}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <div
                  style={{
                    width: `${version.progress_pct}%`,
                    height: '100%',
                    background: 'var(--accent)',
                    transition: 'width .4s ease',
                  }}
                />
              </div>
            </div>
          )}

          {!isRunning && (
            <div className="tiles">
              <div className="tile">
                <div className="k">Controls</div>
                <div className="v">
                  {version.controls_total - version.controls_failed}/{version.controls_total}
                </div>
                <div className="s">passed</div>
              </div>
              <div className={`tile ${version.controls_failed ? 'is-crit' : 'is-ok'}`}>
                <div className="k">Controls failed</div>
                <div className="v">{version.controls_failed}</div>
                <div className="s">
                  {version.controls_failed
                    ? 'downstream phases must not treat this as clean'
                    : 'every structural control held'}
                </div>
              </div>
              <div className="tile">
                <div className="k">Defects catalogued</div>
                <div className="v">{version.defects_total}</div>
                <div className="s">each with its applied rule</div>
              </div>
              <div className="tile">
                <div className="k">Read time</div>
                <div className="v" style={{ fontSize: 20 }}>
                  {formatSeconds(version.duration_seconds)}
                </div>
                <div className="s">streaming, all five files</div>
              </div>
            </div>
          )}

          {version.failure_reason && (
            <div
              className={`callout ${version.controls_failed ? 'crit' : 'warn'}`}
              style={{ marginTop: 'var(--sp-4)' }}
            >
              <div className="h">Recorded outcome</div>
              <p>{version.failure_reason}</p>
            </div>
          )}
        </Card>
      )}

      {profile.data && <Card title="Source data footprint" subtitle="Rows read from the original files · client sources remain unchanged"><ComparisonBars unit="Rows" labels={profile.data.source_files.map(f => titleiseRole(f.role))} series={[{ name: 'Source rows', values: profile.data.source_files.map(f => f.row_count) }]} /></Card>}
      {validation.data?.service_measures && <Card title="Order fulfilment at a glance" subtitle="Ordered and despatched units are different measurements"><ComparisonBars labels={['Ordered', 'Despatched', 'Net shortfall', 'Gross positive shortfall']} series={[{ name: 'Quantity', values: [validation.data.service_measures.total_ordered, validation.data.service_measures.total_despatched, validation.data.service_measures.net_shortfall, validation.data.service_measures.gross_positive_shortfall] }]} /></Card>}
      {hasCompleted && validation.isPending && (
        <Card title="Structural controls">
          <LoadingBlock rows={6} label="Loading controls" />
        </Card>
      )}

      {validation.data && (
        <>
          {validation.data.blocking_message && (
            <div className="callout crit">
              <div className="h">Controls did not hold</div>
              <p>{validation.data.blocking_message}</p>
            </div>
          )}

          <Card
            title="Structural controls"
            subtitle={
              validation.data.passed
                ? 'Every control held. Each is shown regardless of outcome.'
                : `${failedControls.length} control(s) failed. Nothing is hidden.`
            }
          >
            <div className="table-scroll">
              <table className="data" data-testid="controls-table">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Control</th>
                    <th className="num">Expected</th>
                    <th className="num">Measured</th>
                    <th>Outcome</th>
                    <th>Difference</th>
                    <th>Remediation</th>
                  </tr>
                </thead>
                <tbody>
                  {validation.data.controls.map((control) => (
                    <ControlRow key={control.control_code} control={control} />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {validation.data.service_measures && (
            <Card
              title="Demand and service measures"
              subtitle="Net and gross shortfall are separate figures, deliberately"
            >
              <div className="tiles">
                <div className="tile">
                  <div className="k">Ordered</div>
                  <div className="v">{formatInt(validation.data.service_measures.total_ordered)}</div>
                  <div className="s">the forecast target</div>
                </div>
                <div className="tile">
                  <div className="k">Despatched</div>
                  <div className="v">
                    {formatInt(validation.data.service_measures.total_despatched)}
                  </div>
                  <div className="s">not used as demand</div>
                </div>
                <div className="tile is-warn">
                  <div className="k">Net shortfall</div>
                  <div className="v">{formatInt(validation.data.service_measures.net_shortfall)}</div>
                  <div className="s">ordered − despatched</div>
                </div>
                <div className="tile is-crit">
                  <div className="k">Gross positive shortfall</div>
                  <div className="v">
                    {formatInt(validation.data.service_measures.gross_positive_shortfall)}
                  </div>
                  <div className="s">
                    {formatPct(validation.data.service_measures.gross_shortfall_pct, 2)} of ordered
                  </div>
                </div>
                <div className="tile">
                  <div className="k">Over-delivered</div>
                  <div className="v">
                    {formatInt(validation.data.service_measures.over_delivered_qty)}
                  </div>
                  <div className="s">
                    {formatInt(validation.data.service_measures.lines_over_delivered)} lines
                  </div>
                </div>
                <div className="tile">
                  <div className="k">Net fill rate</div>
                  <div className="v">
                    {formatPct(validation.data.service_measures.net_fill_rate, 2, 'ratio')}
                  </div>
                  <div className="s">
                    {formatInt(validation.data.service_measures.lines_fully_unserved)} lines served
                    nothing
                  </div>
                </div>
              </div>
              <div className="callout" style={{ marginTop: 'var(--sp-4)' }}>
                <p>
                  The two shortfall figures differ because{' '}
                  {formatInt(validation.data.service_measures.lines_over_delivered)} lines
                  despatched more than was ordered. Reporting one number would hide
                  that.
                </p>
              </div>
            </Card>
          )}

          {validation.data.lead_time && (
            <Card
              title="Order-to-despatch lead time"
              subtitle="Computed only on parseable, non-negative dates"
            >
              <div className="tiles">
                <div className="tile">
                  <div className="k">Median</div>
                  <div className="v">{formatDays(validation.data.lead_time.median_days)}</div>
                </div>
                <div className="tile">
                  <div className="k">95th percentile</div>
                  <div className="v">{formatDays(validation.data.lead_time.p95_days)}</div>
                </div>
                <div className="tile">
                  <div className="k">Maximum</div>
                  <div className="v">{formatDays(validation.data.lead_time.max_days)}</div>
                </div>
                <div className="tile">
                  <div className="k">Lines used</div>
                  <div className="v">{formatInt(validation.data.lead_time.count)}</div>
                </div>
                <div className="tile is-warn">
                  <div className="k">Excluded</div>
                  <div className="v">
                    {formatInt(
                      validation.data.lead_time.unparseable_dates +
                        validation.data.lead_time.negative_excluded,
                    )}
                  </div>
                  <div className="s">
                    {formatInt(validation.data.lead_time.unparseable_dates)} unparseable,{' '}
                    {formatInt(validation.data.lead_time.negative_excluded)} negative
                  </div>
                </div>
              </div>
            </Card>
          )}

          <Card
            title="Defect register"
            subtitle={`${validation.data.defects.length} defects, each with the rule that handled it`}
          >
            <div className="table-scroll">
              <table className="data" data-testid="defects-table">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Defect</th>
                    <th>Handling</th>
                    <th>Rule</th>
                    <th>Source</th>
                    <th>Extent</th>
                    <th>Fix applied</th>
                  </tr>
                </thead>
                <tbody>
                  {validation.data.defects.map((defect) => (
                    <tr key={defect.defect_code} data-defect={defect.defect_code}>
                      <td className="mono">{defect.defect_code}</td>
                      <td>{defect.title}</td>
                      <td>
                        <span className={`pill ${SEVERITY_TONE[defect.severity]}`}>
                          {defect.severity}
                        </span>
                      </td>
                      <td className="mono dim">{defect.rule_applied ?? '—'}</td>
                      <td className="dim">
                        {defect.source_role ? titleiseRole(defect.source_role) : '—'}
                      </td>
                      <td className="dim">{defect.extent ?? '—'}</td>
                      <td className="dim">{defect.fix_description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      {profile.data && (
        <Card
          title="Source files as read"
          subtitle={`${formatInt(profile.data.total_rows_read)} rows across ${profile.data.source_files.length} files`}
        >
          <div className="table-scroll">
            <table className="data" data-testid="files-table">
              <thead>
                <tr>
                  <th>Role</th>
                  <th>File</th>
                  <th>Sheet</th>
                  <th className="num">Rows</th>
                  <th className="num">Cols</th>
                  <th className="num">Size</th>
                  <th className="num">Read</th>
                  <th>SHA-256</th>
                </tr>
              </thead>
              <tbody>
                {profile.data.source_files.map((file) => (
                  <tr key={file.role}>
                    <td>{titleiseRole(file.role)}</td>
                    <td className="mono" style={{ fontSize: 11.5 }}>
                      {file.filename}
                    </td>
                    <td className="dim">{file.sheet_name ?? '—'}</td>
                    <td className="num">{formatInt(file.row_count)}</td>
                    <td className="num">{file.column_count}</td>
                    <td className="num dim">{formatBytes(file.size_bytes)}</td>
                    <td className="num dim">{formatSeconds(file.read_seconds)}</td>
                    <td className="mono dim" style={{ fontSize: 11 }}>
                      {shortHash(file.content_hash_sha256)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="callout" style={{ marginTop: 'var(--sp-4)' }}>
            <div className="h">
              {profile.data.pii_columns_excluded.length} PII columns excluded from modelling
            </div>
            <p className="mono" style={{ fontSize: 11.5 }}>
              {profile.data.pii_columns_excluded.join(' · ')}
            </p>
          </div>
        </Card>
      )}
    </div>
  );
}
