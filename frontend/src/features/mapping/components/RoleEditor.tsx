import { useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  confirmMapping,
  mappingKeys,
  startPreprocessing,
  updateAssignments,
} from '@/api/mappings';
import { Card } from '@/components/ui/Card';
import { useToast } from '@/components/ui/Toast';
import { ApiError } from '@/api/client';
import { titleiseRole } from '@/components/ui/format';
import type { MappingDetail, RoleAssignment, SemanticRole } from '@/types/api';
import { Explain } from '@/components/ui/Explain';

/**
 * The editable role mapping.
 *
 * Roles come from the backend's own vocabulary; this list is the display order
 * and labelling only. It carries no model identity and no forecasting logic.
 */
const ROLE_OPTIONS: { value: SemanticRole; label: string }[] = [
  { value: 'time_column', label: 'Time column' },
  { value: 'target_column', label: 'Target column' },
  { value: 'series_identifier', label: 'Series identifier' },
  { value: 'historical_driver', label: 'Historical driver' },
  { value: 'future_known_driver', label: 'Future-known driver' },
  { value: 'static_attribute', label: 'Static attribute' },
  { value: 'inventory', label: 'Inventory' },
  { value: 'capacity', label: 'Capacity' },
  { value: 'supply', label: 'Supply' },
  { value: 'excluded_pii', label: 'Excluded (PII)' },
  { value: 'ignored', label: 'Ignored' },
];

const ROLE_TONE: Partial<Record<SemanticRole, string>> = {
  target_column: 'pill-accent',
  time_column: 'pill-info',
  series_identifier: 'pill-info',
  future_known_driver: 'pill-warn',
  excluded_pii: 'pill-crit',
  ignored: 'pill-neutral',
};

function roleLabel(role: SemanticRole): string {
  return ROLE_OPTIONS.find((option) => option.value === role)?.label ?? role;
}

export function RoleEditor({ mapping, datasetId }: { mapping: MappingDetail; datasetId: string }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [sourceFilter, setSourceFilter] = useState<string>('all');
  const [roleFilter, setRoleFilter] = useState<string>('all');
  const [onlyUnreviewed, setOnlyUnreviewed] = useState(false);
  const [confirmedBy, setConfirmedBy] = useState('');

  const locked = mapping.state !== 'draft';

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: mappingKeys.current(datasetId) });
    void queryClient.invalidateQueries({ queryKey: mappingKeys.preprocessing(mapping.id) });
  };

  const setRole = useMutation({
    mutationFn: (edit: { assignment: RoleAssignment; role: SemanticRole }) =>
      updateAssignments(mapping.id, [
        {
          source_role: edit.assignment.source_role,
          column_name: edit.assignment.column_name,
          role: edit.role,
          rationale: 'Set by a reviewer in Mapping & Validation.',
        },
      ]),
    onSuccess: invalidate,
    onError: (error) =>
      toast.notify(error instanceof ApiError ? error.message : 'Could not update the role.', 'error'),
  });

  const confirm = useMutation({
    mutationFn: () => confirmMapping(mapping.id, confirmedBy.trim()),
    onSuccess: () => {
      toast.notify('Mapping confirmed. It is now immutable.', 'ok');
      invalidate();
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        const violations = (error.details?.violations as { message: string }[]) ?? [];
        const unreviewed = (error.details?.unreviewed_columns as string[]) ?? [];
        const detail =
          violations.map((v) => v.message).join(' ') ||
          (unreviewed.length ? `Unreviewed: ${unreviewed.join(', ')}` : '');
        toast.notify(`${error.message} ${detail}`.trim(), 'error');
      } else {
        toast.notify('Could not confirm the mapping.', 'error');
      }
    },
  });

  const preprocess = useMutation({
    mutationFn: () => startPreprocessing(mapping.id),
    onSuccess: () => {
      toast.notify(
        'Preprocessing started. It re-streams all five sources and takes several minutes.',
        'info',
      );
      invalidate();
    },
    onError: (error) =>
      toast.notify(
        error instanceof ApiError ? error.message : 'Could not start preprocessing.',
        'error',
      ),
  });

  const sources = useMemo(
    () => Array.from(new Set(mapping.assignments.map((a) => a.source_role))).sort(),
    [mapping.assignments],
  );

  const visible = useMemo(
    () =>
      mapping.assignments.filter((assignment) => {
        if (sourceFilter !== 'all' && assignment.source_role !== sourceFilter) return false;
        if (roleFilter !== 'all' && assignment.role !== roleFilter) return false;
        if (onlyUnreviewed && !assignment.is_suggested) return false;
        return true;
      }),
    [mapping.assignments, sourceFilter, roleFilter, onlyUnreviewed],
  );

  return (
    <div className="stack">
      {mapping.rule_results.length > 0 && (
        <Card
          title="Validation rules"
          subtitle="Blocking rules prevent confirmation; warnings do not"
        >
          <div className="stack">
            {mapping.rule_results.map((rule) => (
              <div
                key={`${rule.rule_code}-${rule.message}`}
                className={`callout ${rule.severity === 'blocking' ? 'crit' : 'warn'}`}
                data-rule={rule.rule_code}
              >
                <div className="h">
                  {rule.rule_code} &middot; {rule.severity}
                </div>
                <p>{rule.message}</p>
                {rule.columns && rule.columns.length > 0 && (
                  <p className="mono" style={{ fontSize: 11.5 }}>
                    {rule.columns.join(' · ')}
                  </p>
                )}
                {rule.remediation && (
                  <p>
                    <strong>What to do:</strong> {rule.remediation}
                  </p>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card
        title={`Column roles — version ${mapping.version_number}`}
        subtitle={
          locked
            ? `${mapping.state} · ${mapping.assignments.length} columns · immutable`
            : `Draft · ${mapping.assignments.length} columns · ${mapping.unreviewed_count} required role(s) still unreviewed`
        }
        actions={
          <span
            className={`pill ${
              mapping.state === 'confirmed'
                ? 'pill-ok'
                : mapping.state === 'superseded'
                  ? 'pill-neutral'
                  : 'pill-warn'
            }`}
          >
            {mapping.state}
          </span>
        }
      >
        {locked && (
          <Explain variant="callout" style={{ marginBottom: 'var(--sp-4)' }}>
            <div className="h">
              {mapping.state === 'confirmed'
                ? `Confirmed by ${mapping.confirmed_by}`
                : 'Superseded by a later version'}
            </div>
            <p>
              A confirmed mapping is immutable, because a training run may already
              have used it. To change anything, create a new version.
            </p>
            <p>
              {/* Confirmation only requires the target and time columns to be
                  reviewed. The rest keep their template provenance, and saying
                  so is more honest than relabelling them "Reviewed". */}
              {mapping.assignments.filter((a) => !a.is_suggested).length} of{' '}
              {mapping.assignments.length} columns were reviewed by a person; the
              rest kept their template default. Confirmation requires the target
              and time columns to be reviewed explicitly, not every column.
            </p>
          </Explain>
        )}

        <div
          style={{
            display: 'flex',
            gap: 'var(--sp-3)',
            flexWrap: 'wrap',
            alignItems: 'end',
            marginBottom: 'var(--sp-4)',
          }}
        >
          <label style={{ fontSize: 12 }}>
            <div className="dim" style={{ marginBottom: 4 }}>
              Source
            </div>
            <select
              value={sourceFilter}
              onChange={(event) => setSourceFilter(event.target.value)}
              className="btn"
              aria-label="Filter by source file"
            >
              <option value="all">All sources</option>
              {sources.map((source) => (
                <option key={source} value={source}>
                  {titleiseRole(source)}
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: 12 }}>
            <div className="dim" style={{ marginBottom: 4 }}>
              Role
            </div>
            <select
              value={roleFilter}
              onChange={(event) => setRoleFilter(event.target.value)}
              className="btn"
              aria-label="Filter by role"
            >
              <option value="all">All roles</option>
              {ROLE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label
            style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center', paddingBottom: 8 }}
          >
            <input
              type="checkbox"
              checked={onlyUnreviewed}
              onChange={(event) => setOnlyUnreviewed(event.target.checked)}
            />
            Unreviewed only
          </label>
          <span className="dim" style={{ fontSize: 12, paddingBottom: 8 }}>
            {visible.length} of {mapping.assignments.length} columns
          </span>
        </div>

        <div className="table-scroll" style={{ maxHeight: 560 }}>
          <table className="data" data-testid="role-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Column</th>
                <th>Role</th>
                <th>Reviewed</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((assignment) => {
                const key = `${assignment.source_role}.${assignment.column_name}`;
                const isPii = assignment.role === 'excluded_pii';
                return (
                  <tr key={key} data-column={key}>
                    <td className="dim">{titleiseRole(assignment.source_role)}</td>
                    <td className="mono" style={{ fontSize: 11.5 }}>
                      {assignment.column_name}
                    </td>
                    <td>
                      {locked || isPii ? (
                        <span className={`pill ${ROLE_TONE[assignment.role] ?? 'pill-neutral'}`}>
                          {roleLabel(assignment.role)}
                        </span>
                      ) : (
                        <select
                          className="btn"
                          value={assignment.role}
                          disabled={setRole.isPending}
                          // The source must be in the accessible name: several
                          // files carry a column called "Quantity", so the
                          // column name alone is ambiguous to a screen reader.
                          aria-label={`Role for ${assignment.column_name} in ${assignment.source_role}`}
                          onChange={(event) =>
                            setRole.mutate({
                              assignment,
                              role: event.target.value as SemanticRole,
                            })
                          }
                        >
                          {ROLE_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      )}
                    </td>
                    <td>
                      {assignment.is_suggested ? (
                        <span className="pill pill-warn">Suggested</span>
                      ) : (
                        <span className="pill pill-ok">Reviewed</span>
                      )}
                    </td>
                    <td className="dim" style={{ maxWidth: '42ch' }}>
                      {assignment.rationale}
                      {assignment.notes && (
                        <div style={{ color: 'var(--warn)', marginTop: 3 }}>{assignment.notes}</div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {visible.length === 0 && (
          <p className="dim" style={{ marginTop: 'var(--sp-4)' }}>
            No columns match these filters.
          </p>
        )}
      </Card>

      {!locked && (
        <Card
          title="Confirm the mapping"
          subtitle="Confirmation locks it for training use and cannot be undone"
        >
          <div className="callout warn">
            <div className="h">The target column must be reviewed explicitly</div>
            <p>
              A suggested target is a guess, and on this dataset several columns
              look like demand &mdash; ordered quantity, despatched quantity and
              invoiced quantity all do. Only ordered quantity is the target;
              despatched is supply-censored.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 'var(--sp-3)', alignItems: 'end', marginTop: 'var(--sp-4)' }}>
            <label style={{ fontSize: 12, flex: '0 1 260px' }}>
              <div className="dim" style={{ marginBottom: 4 }}>
                Confirmed by
              </div>
              <input
                className="btn"
                style={{ width: '100%' }}
                value={confirmedBy}
                onChange={(event) => setConfirmedBy(event.target.value)}
                placeholder="Your name"
                aria-label="Confirmed by"
              />
            </label>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!mapping.can_confirm || confirmedBy.trim().length < 2 || confirm.isPending}
              onClick={() => confirm.mutate()}
            >
              {confirm.isPending ? 'Confirming…' : 'Confirm mapping'}
            </button>
          </div>
          {!mapping.can_confirm && (
            <p className="dim" style={{ marginTop: 'var(--sp-3)' }}>
              {mapping.blocking_count > 0
                ? `${mapping.blocking_count} blocking rule(s) must be resolved first.`
                : `${mapping.unreviewed_count} required role(s) still need review.`}
            </p>
          )}
        </Card>
      )}

      {mapping.state === 'confirmed' && (
        <Card
          title="Preprocessing"
          subtitle="Builds the branch and product dimensions plus the monthly facts"
          actions={
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => preprocess.mutate()}
              disabled={preprocess.isPending}
            >
              {preprocess.isPending ? 'Starting…' : 'Run preprocessing'}
            </button>
          }
        >
          <p className="dim">
            Re-streams all five sources and writes Parquet artifacts with a
            versioned manifest. The order and sales facts stay separate, because
            the hybrid target needs to know which source each period came from.
          </p>
        </Card>
      )}
    </div>
  );
}
