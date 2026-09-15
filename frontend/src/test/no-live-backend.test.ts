import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fetchHealth } from '@/api/health';
import { ApiError } from '@/api/client';

// The mirror of the backend's `test_tests_never_touch_the_real_database`: proof
// that the transport guard in setup.ts is actually installed. Without this the
// guard could silently stop working - the symptom would be tests quietly
// passing against a live dev backend rather than their fixtures, which is the
// hardest kind of green to distrust.
describe('the test transport never reaches a real backend', () => {
  it('rejects an unstubbed API call instead of opening a socket', async () => {
    await expect(fetchHealth()).rejects.toBeInstanceOf(ApiError);
  });

  it('keeps the guard diagnostic as the cause, naming the unstubbed endpoint', async () => {
    // The interceptor's own message is deliberately generic for users, so the
    // endpoint name has to survive somewhere - otherwise a developer who adds
    // a page without stubbing its query gets a message that blames the backend
    // for being down.
    const error = await fetchHealth().then(
      () => null,
      (caught: unknown) => caught as ApiError,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(String((error?.cause as Error | undefined)?.message)).toMatch(
      /Unstubbed request to .*\/health/,
    );
  });
});

// Phase 11 replaced the last placeholder page with a real one, so the
// `PhaseNotice` component was deleted. This guards the direction of travel: a
// page that regains a "arrives in Phase N" placeholder after its endpoint
// exists would be showing a stale promise instead of the data it now has.
describe('no page carries a phase placeholder any more', () => {
  it('has no PhaseNotice component and no page importing one', () => {
    const src = join(process.cwd(), 'src');
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir)) {
        const path = join(dir, entry);
        if (statSync(path).isDirectory()) {
          walk(path);
          continue;
        }
        if (!/\.tsx?$/.test(entry)) continue;
        const text = readFileSync(path, 'utf8');
        if (/PhaseNotice|arrives in Phase/.test(text) && !path.includes('no-live-backend')) {
          offenders.push(relative(src, path));
        }
      }
    };
    walk(src);
    expect(offenders).toEqual([]);
  });
});
