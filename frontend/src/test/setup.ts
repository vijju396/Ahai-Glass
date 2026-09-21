import '@testing-library/jest-dom/vitest';
import { createElement } from 'react';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import { http } from '@/api/client';

// Tests stub the API layer per test (`vi.spyOn(datasetsApi, 'fetchDatasets')`),
// never the transport. Any query a test did not stub therefore reached the real
// axios client, and axios in jsdom uses XMLHttpRequest - so jsdom opened a
// socket to 127.0.0.1:8000, had it refused, and logged an unattributed
// `AggregateError` stack.
//
// Nothing failed, but two things were wrong with that: the noise buried real
// output, and a test that happened to run while a dev backend was up would
// have silently exercised live data instead of its fixtures. So the transport
// itself is replaced with an adapter that always rejects, naming the endpoint
// no test stubbed - the message is the diagnostic.
//
// The rejection reaches the client's own response interceptor, which keeps it
// as `cause` - so an unstubbed call surfaces as the same `ApiError` a real
// network failure would, while the endpoint name still survives for whoever is
// debugging. `no-live-backend.test.ts` asserts both halves of that.
http.defaults.adapter = ((config: { url?: string; baseURL?: string }) =>
  Promise.reject(
    new Error(
      `Unstubbed request to ${config.baseURL ?? ''}${config.url ?? '?'}. Tests ` +
        `must stub the api/ module function that owns this endpoint; no test ` +
        `may reach a real backend.`,
    ),
  )) as typeof http.defaults.adapter;


// Recharts' <ResponsiveContainer> measures its parent through ResizeObserver,
// which jsdom does not implement. Without it every chart in a test throws on
// mount, and the failure surfaces as an unhandled exception rather than a
// readable assertion.
//
// The stub reports a fixed non-zero box: recharts refuses to render children
// at zero width, so a 0x0 observer would make every chart silently empty and
// turn a chart test into one that passes for the wrong reason.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

for (const [property, value] of [
  ['offsetWidth', 800],
  ['offsetHeight', 400],
  ['clientWidth', 800],
  ['clientHeight', 400],
] as const) {
  if (!Object.getOwnPropertyDescriptor(HTMLElement.prototype, property)?.get) {
    Object.defineProperty(HTMLElement.prototype, property, { configurable: true, value });
  }
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// ECharts renders onto a canvas, and jsdom has neither a canvas backend nor a
// laid-out DOM - every element measures 0x0. The library therefore warns about
// zero width/height and then throws `clearRect of null` from its render loop.
//
// The throw surfaced as a *flaky* failure: whichever test happened to be
// running when the deferred render fired failed, so the same suite failed on
// different tests between runs. That is worse than a consistent failure,
// because it reads as a problem with the assertions rather than with the
// environment.
//
// So the chart component is replaced with a marker element carrying its series
// names. A test can still assert what the page asked the chart to draw - which
// is the part this project cares about, since a chart must show a gap for a
// model that did not run - without needing a canvas.
vi.mock('echarts-for-react', () => ({
  default: ({ option }: { option?: { series?: { name?: string }[] } }) => {
    const names = (option?.series ?? [])
      .map((series) => series?.name)
      .filter(Boolean)
      .join(',');
    return createElement('div', {
      'data-testid': 'echart',
      'data-series': names,
    });
  },
}));

// Explanations render collapsed in the application (components/ui/Explain.tsx).
// The suite checks that a page states a fact, not that a disclosure is shut, so
// they start open here. Explain.test.tsx unsets this to cover the collapse.
(globalThis as { __EXPLAIN_DEFAULT_OPEN__?: boolean }).__EXPLAIN_DEFAULT_OPEN__ = true;
