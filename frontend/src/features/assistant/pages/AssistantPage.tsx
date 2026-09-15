/**
 * AI Assistant — the AIS port of the reference's AIAssistant page.
 *
 * Same composition: a scrolling conversation that owns the remaining height, a
 * suggested-question grid on the empty state, a visible scope chip with a
 * clear control, and an answer that can carry a chart.
 *
 * Three things this page is careful about, because the subject is numbers
 * someone will act on:
 *
 * - It labels **how** an answer was produced. `answered_by` distinguishes an
 *   OpenAI answer from the deterministic writer that runs when no key is
 *   configured or the provider fails, and the badge says which.
 * - It never holds the API key. The browser posts to this application's own
 *   backend, and only the backend talks to OpenAI. That is stated on the page.
 * - It shows the tools an answer came from and links to the page where the
 *   same numbers can be checked, so no figure here is a dead end.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  askAssistant,
  assistantKeys,
  fetchAssistantStatus,
  type AssistantAnswer,
  type AssistantScope,
  type AssistantTurn,
} from '@/api/analytics';
import { Badge, Card, ClearChip } from '@/components/ui/Dashboard';
import { ErrorState } from '@/components/ui/States';
import { ChatChart } from '@/features/assistant/components/ChatChart';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  answer?: AssistantAnswer;
}

/** Where each tool's numbers can be checked. A figure the reader cannot go and
 *  verify is worth less than one they can. */
const TOOL_LINKS: Record<string, { label: string; to: string }> = {
  demand_trend: { label: 'Demand Analytics', to: '/demand-analytics' },
  branch_demand: { label: 'Demand Analytics', to: '/demand-analytics' },
  model_leaderboard: { label: 'Model Leaderboard', to: '/leaderboard' },
  forecast_outlook: { label: 'Forecast Explorer', to: '/forecasts' },
  stock_exceptions: { label: 'Operational Exceptions', to: '/exceptions' },
  inventory_recommendations: { label: 'Supply Intelligence', to: '/supply' },
  // `data_quality` has no entry any more: Data & Model Monitoring was
  // removed from the UI, so there is nowhere to send the reader. An absent
  // link is honest; one that redirects to a different page is not. The tool
  // still runs and its facts still appear in the answer.
};

const ANSWERED_BY_LABEL: Record<string, { text: string; tone: string }> = {
  openai: { text: 'Written by the model from backend facts', tone: 'champion' },
  deterministic_no_key: { text: 'Deterministic answer — no API key configured', tone: 'medium' },
  deterministic_after_provider_error: { text: 'Deterministic answer — the provider failed', tone: 'high' },
  static: { text: 'Standard reply', tone: 'medium' },
  disabled: { text: 'Assistant disabled', tone: 'medium' },
  validation: { text: 'Needs a question', tone: 'medium' },
};

/** Minimal markdown: `- ` bullets and `**bold**`, which is all the backend
 *  prompt permits. Rendering it by hand rather than pulling a parser in for
 *  two constructs, and it means no untrusted HTML is ever inserted. */
function renderAnswer(text: string) {
  return text.split('\n').map((line, index) => {
    const trimmed = line.trim();
    if (!trimmed) return null;
    const bullet = trimmed.startsWith('- ');
    const body = bullet ? trimmed.slice(2) : trimmed;
    const parts = body.split(/(\*\*[^*]+\*\*)/g).filter(Boolean);
    const content = parts.map((part, partIndex) =>
      part.startsWith('**') && part.endsWith('**') ? (
        <strong key={partIndex} className="font-semibold text-[var(--color-text)]">
          {part.slice(2, -2)}
        </strong>
      ) : (
        <span key={partIndex}>{part}</span>
      ),
    );
    return bullet ? (
      <li key={index} className="ml-4 list-disc text-[13px] leading-relaxed">
        {content}
      </li>
    ) : (
      <p key={index} className="text-[13px] leading-relaxed">
        {content}
      </p>
    );
  });
}

export function AssistantPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [scope, setScope] = useState<AssistantScope | null>(null);
  const [lastQuestion, setLastQuestion] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const statusQuery = useQuery({ queryKey: assistantKeys.status, queryFn: fetchAssistantStatus });
  const status = statusQuery.data;

  const history: AssistantTurn[] = useMemo(
    () => messages.map((message) => ({ role: message.role, content: message.content })),
    [messages],
  );

  const mutation = useMutation({
    mutationFn: (question: string) => askAssistant({ question, history, current_scope: scope }),
    onSuccess: (answer) => {
      setScope(answer.scope);
      setMessages((current) => [
        ...current,
        { id: `a-${current.length}`, role: 'assistant', content: answer.answer, answer },
      ]);
    },
  });

  useEffect(() => {
    // `scrollTo` is absent in jsdom and in older embedded webviews. An
    // optional convenience must not be able to break the render.
    scrollRef.current?.scrollTo?.({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages.length, mutation.isPending]);

  const send = (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || mutation.isPending) return;
    setLastQuestion(trimmed);
    setMessages((current) => [...current, { id: `q-${current.length}`, role: 'user', content: trimmed }]);
    setInput('');
    mutation.mutate(trimmed);
  };

  const scopeParts = [scope?.branch, scope?.sku, scope?.period].filter(Boolean) as string[];

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-primary)]">
            AI Assistant
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[var(--color-text)]">
            Ask about this network.
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-[var(--color-text-muted)]">
            Every figure is read from this application&apos;s own data. The assistant explains numbers
            the backend computed — it never estimates one.
          </p>
        </div>
        {scopeParts.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wide text-[var(--color-text-muted)]">Scope</span>
            <ClearChip label={scopeParts.join(' · ')} onClear={() => setScope(null)} />
          </div>
        )}
      </header>

      {statusQuery.isError && <ErrorState error={statusQuery.error} />}

      {status && !status.configured && (
        <Card className="border-[var(--color-primary)]/40 !bg-[var(--color-primary)]/5">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-primary)]">
            {status.enabled ? 'No API key configured' : 'Assistant switched off'}
          </h2>
          <p className="mt-1 text-[13px] text-[var(--color-text)]">
            The assistant still answers from this application&apos;s data using a deterministic writer.
            Add a key to have the model write the prose instead.
          </p>
          <ol className="mt-2 flex flex-col gap-1">
            {status.steps.map((step, index) => (
              <li key={step} className="text-[12px] text-[var(--color-text-muted)]">
                {index + 1}. {step}
              </li>
            ))}
          </ol>
          <ul className="mt-2 flex flex-col gap-1 border-t border-[var(--color-border)] pt-2">
            {status.notes.map((note) => (
              <li key={note} className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
                {note}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div
        ref={scrollRef}
        className="ref-scroll flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-2)] p-4"
      >
        {messages.length === 0 && (
          <div className="flex flex-col gap-3">
            <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text-muted)]">
              Try one of these
            </p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {(status?.suggested_questions ?? []).map((question) => (
                <button
                  key={question}
                  type="button"
                  onClick={() => send(question)}
                  className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-left text-[12px] text-[var(--color-text)] transition-shadow hover:shadow-[var(--shadow-md)]"
                >
                  {question}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message) =>
          message.role === 'user' ? (
            <div key={message.id} className="flex justify-end">
              <div className="max-w-[80%] rounded-xl rounded-br-sm bg-[var(--color-primary)] px-3 py-2 text-[13px] text-white">
                {message.content}
              </div>
            </div>
          ) : (
            <div key={message.id} className="flex justify-start">
              <div className="max-w-[92%] rounded-xl rounded-bl-sm border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2.5">
                <div className="flex flex-col gap-1">{renderAnswer(message.content)}</div>
                {message.answer?.chart && <ChatChart chart={message.answer.chart} />}
                {message.answer && (
                  <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-[var(--color-border)] pt-2">
                    <Badge status={ANSWERED_BY_LABEL[message.answer.answered_by]?.tone ?? 'medium'}>
                      {ANSWERED_BY_LABEL[message.answer.answered_by]?.text ?? message.answer.answered_by}
                    </Badge>
                    {message.answer.model && (
                      <span className="text-[10px] text-[var(--color-text-muted)]">{message.answer.model}</span>
                    )}
                    {message.answer.tools_used.map((tool) => {
                      const link = TOOL_LINKS[tool];
                      return link ? (
                        <Link
                          key={tool}
                          to={link.to}
                          className="text-[10px] font-medium text-[var(--color-primary)] underline"
                        >
                          Check in {link.label}
                        </Link>
                      ) : (
                        <span key={tool} className="text-[10px] text-[var(--color-text-muted)]">
                          {tool}
                        </span>
                      );
                    })}
                    {message.answer.provider_error && (
                      <span className="text-[10px] text-[var(--color-danger)]">
                        Provider error: {message.answer.provider_error}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          ),
        )}

        {mutation.isPending && (
          <div className="flex justify-start" aria-live="polite">
            <div className="flex items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2.5">
              {[0, 1, 2].map((dot) => (
                <span
                  key={dot}
                  className="h-1.5 w-1.5 rounded-full bg-[var(--color-text-muted)]"
                  style={{ animation: `ref-typing 1.2s ${dot * 0.15}s infinite` }}
                />
              ))}
              <span className="ml-1 text-[11px] text-[var(--color-text-muted)]">Reading the data…</span>
            </div>
          </div>
        )}

        {mutation.isError && (
          <div className="flex flex-col items-start gap-2">
            <ErrorState error={mutation.error} />
            {lastQuestion && (
              <button
                type="button"
                onClick={() => send(lastQuestion)}
                className="rounded-lg border border-[var(--color-primary)] px-3 py-1.5 text-xs font-medium text-[var(--color-primary)]"
              >
                Retry
              </button>
            )}
          </div>
        )}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          send(input);
        }}
        className="flex items-center gap-2"
      >
        <label htmlFor="assistant-input" className="visually-hidden">
          Ask a question about demand, models, forecasts or stock
        </label>
        <input
          id="assistant-input"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Ask about demand, a model, a forecast or stock cover…"
          className="flex-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text)]"
          disabled={mutation.isPending}
        />
        <button
          type="submit"
          disabled={mutation.isPending || !input.trim()}
          className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          Ask
        </button>
      </form>
      <p className="text-[10px] text-[var(--color-text-muted)]">
        {status?.configured
          ? `Questions and small aggregate figures are sent to OpenAI (${status.model}) to write the answer. No source file, raw row or customer detail is ever sent, and the API key stays on the server.`
          : 'Nothing is sent to any external service: with no API key configured, answers are written locally from this application’s own data.'}
      </p>
    </div>
  );
}
