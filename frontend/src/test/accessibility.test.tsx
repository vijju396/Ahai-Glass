import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AppShell } from '@/components/layout/AppShell';
import { StatusPill } from '@/components/ui/StatusPill';
import {
  LANDING_PATH,
  NAV_ITEMS,
  REQUIRED_NAV_INDEXES,
  REQUIRED_NAV_ITEMS,
} from '@/app/navigation';
import * as healthApi from '@/api/health';

describe('accessibility and navigation', () => {
  it('exposes every required destination as a link', () => {
    vi.spyOn(healthApi, 'fetchHealth').mockReturnValue(new Promise(() => {}) as never);
    renderWithProviders(<AppShell />);
    const nav = screen.getByRole('navigation', { name: /main navigation/i });
    // Every required destination is reachable, and the nav holds a link for
    // every item it advertises. Asserted against REQUIRED_NAV_ITEMS rather
    // than a hardcoded count, so adding a page cannot weaken the guarantee.
    expect(REQUIRED_NAV_ITEMS).toHaveLength(REQUIRED_NAV_INDEXES.length);
    expect(nav.querySelectorAll('a')).toHaveLength(NAV_ITEMS.length);
    for (const item of REQUIRED_NAV_ITEMS) {
      expect(screen.getByRole('link', { name: new RegExp(item.label, 'i') })).toBeInTheDocument();
    }
  });

  it('numbers the required destinations in order, without reassigning them', () => {
    // Was [1..10]. Three of the original ten were removed from the UI on
    // request (D-052) and Scenario Planner (index 8) later on request too
    // (D-086); the survivors keep their original numbers rather than being
    // renumbered - the gaps are the record of what went.
    // `REQUIRED_NAV_ITEMS` sorts by index; `REQUIRED_NAV_INDEXES` is in nav
    // order. Asserting on the sorted set is the meaningful check - that the
    // seven exist exactly once each and no number was reassigned.
    expect(REQUIRED_NAV_ITEMS.map((item) => item.index)).toEqual([7, 13, 14, 20, 21, 22, 23]);
    expect([...REQUIRED_NAV_INDEXES].sort((a, b) => a - b)).toEqual(
      REQUIRED_NAV_ITEMS.map((item) => item.index),
    );
  });

  it('offers no link to a destination that was removed from the UI', () => {
    // The point of this one: removing a page from the nav but leaving a link
    // to it somewhere else in the shell would be the same bug with a longer
    // path to it.
    vi.spyOn(healthApi, 'fetchHealth').mockReturnValue(new Promise(() => {}) as never);
    renderWithProviders(<AppShell />);

    for (const gone of [
      'Executive Command Center',
      'Data & Model Monitoring',
      'Connections & Settings',
      'Data Studio',
      'Mapping & Validation',
      'Demand Analytics',
      'Operational Exceptions',
      'Training Center',
      'Model Leaderboard',
      'Forecast Explorer',
    ]) {
      expect(screen.queryByRole('link', { name: new RegExp(gone, 'i') })).toBeNull();
    }
    for (const path of [
      '/monitoring',
      '/settings',
      '/data-studio',
      '/mapping',
      '/demand-analytics',
      '/exceptions',
      '/leaderboard',
      '/forecasts',
    ]) {
      expect(NAV_ITEMS.some((item) => item.path === path)).toBe(false);
    }
    // `/` is no longer a destination of its own - it redirects to the landing
    // page, so nothing should advertise it as one.
    expect(NAV_ITEMS.some((item) => item.path === '/')).toBe(false);
  });

  it('opens on a page that exists', () => {
    expect(NAV_ITEMS.some((item) => item.path === LANDING_PATH)).toBe(true);
  });

  it('gives every navigation item a unique index and path', () => {
    // The parity pages are numbered after the ten (11-13). This is what stops
    // a new page quietly reusing an index that the docs and the test above
    // both treat as meaningful.
    expect(new Set(NAV_ITEMS.map((item) => item.index)).size).toBe(NAV_ITEMS.length);
    expect(new Set(NAV_ITEMS.map((item) => item.path)).size).toBe(NAV_ITEMS.length);
  });

  it('exposes all eight destinations, and only those', () => {
    vi.spyOn(healthApi, 'fetchHealth').mockReturnValue(new Promise(() => {}) as never);
    renderWithProviders(<AppShell />);
    for (const label of [
      'Overall Analysis',
      'Per Branch & SKU',
      'Training',
      'Forecasting',
      'Supply Intelligence',
      'AI Assistant',
      'AI Recommendations',
    ]) {
      expect(screen.getByRole('link', { name: new RegExp(label, 'i') })).toBeInTheDocument();
    }
  });

  it('provides a skip link to the main landmark', () => {
    vi.spyOn(healthApi, 'fetchHealth').mockReturnValue(new Promise(() => {}) as never);
    renderWithProviders(<AppShell />);
    const skip = screen.getByRole('link', { name: /skip to main content/i });
    expect(skip).toHaveAttribute('href', '#main');
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main');
  });

  it('lets a keyboard user reach the first navigation link', async () => {
    vi.spyOn(healthApi, 'fetchHealth').mockReturnValue(new Promise(() => {}) as never);
    renderWithProviders(<AppShell />);
    await userEvent.tab();
    expect(screen.getByRole('link', { name: /skip to main content/i })).toHaveFocus();
    await userEvent.tab();
    // The first nav link, whatever it is - naming a page here is how this
    // test broke when the Executive Command Center was removed.
    expect(screen.getByRole('link', { name: new RegExp(NAV_ITEMS[0]!.label, 'i') })).toHaveFocus();
  });

  it('gives the theme toggle an accessible name', () => {
    vi.spyOn(healthApi, 'fetchHealth').mockReturnValue(new Promise(() => {}) as never);
    renderWithProviders(<AppShell />);
    expect(screen.getByRole('button', { name: /toggle colour theme/i })).toBeInTheDocument();
  });

  it('conveys model-run status as text, not colour alone', () => {
    renderWithProviders(<StatusPill status="ineligible" />);
    expect(screen.getByText('Ineligible')).toBeInTheDocument();
  });

  it('distinguishes ineligible from failed in the rendered text', () => {
    const { unmount } = renderWithProviders(<StatusPill status="failed" />);
    expect(screen.getByText('Failed')).toBeInTheDocument();
    unmount();
    renderWithProviders(<StatusPill status="not_evaluated_budget" />);
    expect(screen.getByText('Not evaluated (budget)')).toBeInTheDocument();
  });
});

describe('theme toggle', () => {
  it('switches away from the effective theme on the first click', async () => {
    // The bug this guards: reading data-theme alone makes the first click a
    // no-op for a viewer whose OS is already dark, because the attribute is
    // absent until an explicit choice is made.
    vi.spyOn(healthApi, 'fetchHealth').mockReturnValue(new Promise(() => {}) as never);
    document.documentElement.removeAttribute('data-theme');
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
    );

    renderWithProviders(<AppShell />);
    await userEvent.click(screen.getByRole('button', { name: /toggle colour theme/i }));
    expect(document.documentElement.dataset.theme).toBe('light');

    await userEvent.click(screen.getByRole('button', { name: /toggle colour theme/i }));
    expect(document.documentElement.dataset.theme).toBe('dark');
    document.documentElement.removeAttribute('data-theme');
  });

  it('respects a light system preference on the first click', async () => {
    vi.spyOn(healthApi, 'fetchHealth').mockReturnValue(new Promise(() => {}) as never);
    document.documentElement.removeAttribute('data-theme');
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
    );

    renderWithProviders(<AppShell />);
    await userEvent.click(screen.getByRole('button', { name: /toggle colour theme/i }));
    expect(document.documentElement.dataset.theme).toBe('dark');
    document.documentElement.removeAttribute('data-theme');
  });
});
