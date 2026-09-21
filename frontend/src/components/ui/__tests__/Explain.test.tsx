/** The disclosure itself: shut until asked, and the text is never lost. */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Explain } from '../Explain';

type Flagged = { __EXPLAIN_DEFAULT_OPEN__?: boolean };

describe('Explain', () => {
  beforeEach(() => {
    // The suite-wide default opens these; this file is about the real behaviour.
    (globalThis as Flagged).__EXPLAIN_DEFAULT_OPEN__ = false;
  });
  afterEach(() => {
    (globalThis as Flagged).__EXPLAIN_DEFAULT_OPEN__ = true;
  });

  it('hides the explanation until it is clicked', async () => {
    render(<Explain variant="note">MAPE drops months where demand was zero.</Explain>);

    expect(screen.queryByText(/drops months where demand was zero/i)).not.toBeInTheDocument();

    const trigger = screen.getByRole('button', { name: /how to read this/i });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');

    await userEvent.click(trigger);

    expect(screen.getByText(/drops months where demand was zero/i)).toBeInTheDocument();
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
  });

  it('closes again, so it cannot pile back up', async () => {
    render(<Explain variant="hint">Ordered, not despatched.</Explain>);
    const trigger = screen.getByRole('button', { name: /what this means/i });

    await userEvent.click(trigger);
    expect(screen.getByText(/ordered, not despatched/i)).toBeInTheDocument();

    await userEvent.click(trigger);
    expect(screen.queryByText(/ordered, not despatched/i)).not.toBeInTheDocument();
  });

  it('lets the panel name what is underneath', () => {
    render(<Explain label="Why this model">Because it won on both folds.</Explain>);
    expect(screen.getByRole('button', { name: 'Why this model' })).toBeInTheDocument();
  });
});
