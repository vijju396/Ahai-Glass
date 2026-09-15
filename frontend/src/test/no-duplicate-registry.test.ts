/**
 * Guards the "one registry" rule: the frontend must consume backend-provided
 * model IDs and labels, never carry its own list.
 *
 * This scans real source files rather than trusting a convention. Test files
 * and the API-shaped fixture are exempt, because a test asserting the expected
 * 13 names is the point of having the rule.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const SRC = join(process.cwd(), 'src');

const MODEL_IDS = [
  'sarimax',
  'sarimax_exog',
  'auto_arima',
  'auto_arima_exog',
  'xgboost',
  'xgboost_exog',
  'exp_additive',
  'exp_additive_damped',
  'exp_multiplicative',
  'exp_multiplicative_damped',
  'var_exog',
  'lstm',
];

const DISPLAY_NAMES = [
  'SARIMAX',
  'Auto ARIMA',
  'XGBoost',
  'Exponential Smoothing Additive',
  'Exponential Smoothing Multiplicative',
  'VAR with exogenous variables',
];

/** Files allowed to name models: tests, and the API-response fixture. */
function isExempt(path: string): boolean {
  return (
    path.includes('__tests__') ||
    path.endsWith('.test.ts') ||
    path.endsWith('.test.tsx') ||
    path.replace(/\\/g, '/').includes('src/test/')
  );
}

function sourceFiles(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      sourceFiles(full, found);
    } else if (/\.(ts|tsx)$/.test(entry) && !isExempt(full)) {
      found.push(full);
    }
  }
  return found;
}

describe('no duplicate model registry in the frontend', () => {
  const files = sourceFiles(SRC);

  it('finds source files to scan', () => {
    expect(files.length).toBeGreaterThan(10);
  });

  it('declares no model_id literal anywhere in application source', () => {
    const offenders: string[] = [];
    for (const file of files) {
      const contents = readFileSync(file, 'utf8');
      for (const modelId of MODEL_IDS) {
        // Only a quoted literal counts: a `data-model-id={model.model_id}`
        // binding is exactly the pattern we want.
        if (contents.includes(`'${modelId}'`) || contents.includes(`"${modelId}"`)) {
          offenders.push(`${relative(SRC, file)} -> ${modelId}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it('declares no model display name anywhere in application source', () => {
    const offenders: string[] = [];
    for (const file of files) {
      const contents = readFileSync(file, 'utf8');
      for (const name of DISPLAY_NAMES) {
        if (contents.includes(`'${name}'`) || contents.includes(`"${name}"`)) {
          offenders.push(`${relative(SRC, file)} -> ${name}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it('performs no forecasting arithmetic in the frontend', () => {
    // Forecast values, quantiles and inventory quantities are computed by the
    // backend. React formats them; it must never derive them.
    const forbidden = [
      'Math.exp(',
      'quantileFrom',
      'computeForecast',
      'calculateOrderUpTo',
      'safetyStock',
      'pinballLoss',
    ];
    const offenders: string[] = [];
    for (const file of files) {
      const contents = readFileSync(file, 'utf8');
      for (const token of forbidden) {
        if (contents.includes(token)) offenders.push(`${relative(SRC, file)} -> ${token}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
