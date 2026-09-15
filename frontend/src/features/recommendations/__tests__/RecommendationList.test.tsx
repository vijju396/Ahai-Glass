/**
 * The AI recommendations list.
 *
 * What is asserted here is mostly what the panel refuses to hide: the figures
 * behind a claim, the page those figures can be checked on, which of the two
 * writers produced the list, and the caveats that qualify all of it. A
 * recommendation someone acts on because it sounded confident is the failure
 * this panel is shaped to avoid.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import * as api from '@/api/analytics';
import { renderWithProviders } from '@/test/renderWithProviders';
import { RecommendationList } from '../components/RecommendationList';

function payload(overrides: Partial<api.RecommendationsPayload> = {}): api.RecommendationsPayload {
  return {
    items: [
      {
        title: 'Critical supply exceptions are open',
        severity: 'critical',
        observation: '3,638 branch x SKU lines are flagged critical.',
        explanation:
          'A critical exception is a line where despatch fell short of the order. ' +
          'Short despatch means the recorded order is only a lower bound on true demand.',
        next_step: 'Open Operational Exceptions and sort by units affected.',
        evidence: ['critical_lines = 3,638', 'short_despatch_lines = 2,587'],
        source: 'stock_exceptions',
        verify_on: 'Operational Exceptions',
      },
      {
        title: 'Recent demand has shifted',
        severity: 'medium',
        observation: 'National demand has shifted +23.3% over 6 months.',
        explanation: 'Drift compares recent demand against the history before it.',
        next_step: null,
        evidence: ['national_shift_pct = 23.29'],
        source: 'data_quality',
        verify_on: 'Demand Analytics',
      },
    ],
    answered_by: 'deterministic_no_key',
    sources: ['stock_exceptions', 'data_quality'],
    facts: {},
    caveats: [
      'These are things to look at, not instructions to act.',
      'Stock figures come from one snapshot dated 2026-08-01.',
    ],
    temperature: 2.0,
    model: null,
    provider_error: null,
    ...overrides,
  };
}

function stub(overrides: Partial<api.RecommendationsPayload> = {}) {
  return vi.spyOn(api, 'fetchRecommendations').mockResolvedValue(payload(overrides));
}

describe('RecommendationList', () => {
  it('shows each item with its observation and plain-language explanation', async () => {
    stub();
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText('Critical supply exceptions are open')).toBeInTheDocument();
    expect(screen.getByText(/3,638 branch x SKU lines are flagged critical/)).toBeInTheDocument();
    expect(screen.getByText(/only a lower bound on true demand/)).toBeInTheDocument();
  });

  it('prints the figures a claim rests on', async () => {
    // The reader must be able to check the number, not just the sentence.
    stub();
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText('critical_lines = 3,638')).toBeInTheDocument();
    expect(screen.getByText('short_despatch_lines = 2,587')).toBeInTheDocument();
  });

  it('names the page each item can be verified on', async () => {
    stub();
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/check on Operational Exceptions/)).toBeInTheDocument();
    expect(screen.getByText(/check on Demand Analytics/)).toBeInTheDocument();
  });

  it('says a template wrote the list when no key is configured', async () => {
    // A template list and a model list read identically on a screen.
    stub();
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/no API key configured/i)).toBeInTheDocument();
  });

  it('says the model wrote the list, and at what temperature', async () => {
    stub({ answered_by: 'openai', model: 'gpt-4.1-mini' });
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/Written by the model from measured facts/i)).toBeInTheDocument();
    // Worth stating: at 2.0 the same facts give a different list each run.
    expect(screen.getByText(/temperature 2/)).toBeInTheDocument();
  });

  it('does not advertise a temperature the list was not written at', async () => {
    stub({ answered_by: 'deterministic_no_key' });
    renderWithProviders(<RecommendationList />);

    await screen.findByText('Critical supply exceptions are open');
    expect(screen.queryByText(/temperature/i)).toBeNull();
  });

  it('says the provider failed rather than presenting the fallback as a model answer', async () => {
    stub({ answered_by: 'deterministic_after_provider_error', provider_error: 'APITimeoutError' });
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/the provider failed/i)).toBeInTheDocument();
  });

  it('carries the caveats that qualify the whole list', async () => {
    stub();
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/not instructions to act/)).toBeInTheDocument();
    expect(screen.getByText(/snapshot dated 2026-08-01/)).toBeInTheDocument();
  });

  it('explains an empty list instead of rendering nothing', async () => {
    // Nothing to report and nothing loaded look identical otherwise.
    stub({ items: [] });
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/Nothing met the bar for a recommendation/)).toBeInTheDocument();
    expect(screen.getByText(/dropped rather than softened/)).toBeInTheDocument();
  });

  it('re-reads the data on request', async () => {
    // It owns a page now, so it does not collapse - a page that hides its
    // only content is a worse control than no control. Refresh replaces it,
    // and matters more at temperature 2.0, where a re-read genuinely differs.
    const spy = stub();
    renderWithProviders(<RecommendationList />);
    await screen.findByText('Critical supply exceptions are open');
    expect(spy).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: /refresh/i }));

    expect(spy).toHaveBeenCalledTimes(2);
    expect(screen.getByText('Critical supply exceptions are open')).toBeInTheDocument();
  });
});
