import { useEffect, useState } from 'react';
import ReactECharts from 'echarts-for-react';

/** ECharts canvas cannot resolve CSS variables; re-read tokens on theme changes. */
export function useChartColors() {
  const read = () => {
    const css = getComputedStyle(document.documentElement);
    return Object.fromEntries(['ink', 'ink-2', 'ink-3', 'rule', 'surface', 's1', 's2', 's3', 's4', 's5', 's6'].map(k => [k, css.getPropertyValue(`--${k}`).trim()]));
  };
  const [colors, setColors] = useState(read);
  useEffect(() => {
    const update = () => setColors(read());
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    const media = window.matchMedia?.('(prefers-color-scheme: dark)');
    media?.addEventListener('change', update);
    return () => { observer.disconnect(); media?.removeEventListener('change', update); };
  }, []);
  return colors;
}

export function Chart({ option, height = 300, label, onEvents }: { option: Record<string, unknown>; height?: number; label: string; onEvents?: Record<string, (params: { name: string }) => void> }) {
  const c = useChartColors();
  return <div role="img" aria-label={label} className="chart-container"><ReactECharts notMerge style={{ height }} className="chart" onEvents={onEvents} option={{
    color: [c.s1, c.s2, c.s3, c.s4, c.s5, c.s6],
    textStyle: { fontFamily: 'Segoe UI, sans-serif', color: c['ink-2'], fontSize: 12 },
    animationDuration: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 0 : 300,
    ...option,
    tooltip: { trigger: 'axis', confine: true, backgroundColor: c.surface, borderColor: c.rule, textStyle: { color: c.ink }, valueFormatter: (value: unknown) => value == null ? 'Not available' : typeof value === 'number' ? Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(value) : String(value), ...((option.tooltip ?? {}) as object) },
  }} /></div>;
}

export function monthLabel(period: string) {
  const date = new Date(`${period.slice(0, 7)}-01T00:00:00`);
  return Number.isNaN(date.getTime()) ? period : date.toLocaleDateString('en-GB', { month: 'short', year: '2-digit' });
}

export function MetricCard({ label, value, note, tone = 'blue' }: { label: string; value: string; note: string; tone?: string }) {
  return <div className={`kpi-card ${tone}`}><span className="kpi-label">{label}</span><strong className="kpi-value">{value}</strong><span className="kpi-note">{note}</span></div>;
}
