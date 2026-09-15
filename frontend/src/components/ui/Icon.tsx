/** Small, dependency-free UI symbols; never used as a replacement for labels. */
export function Icon({ name, size = 19 }: { name: string; size?: number }) {
  const paths: Record<string, string> = {
    overview: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
    data: 'M4 5h16v14H4z M4 10h16 M9 5v14 M4 14h16',
    mapping: 'M4 4h6v6H4z M14 14h6v6h-6z M10 7h7v7 M7 10v7h7',
    training: 'M12 3v4 M12 17v4 M3 12h4 M17 12h4 M7 7h10v10H7z M10 10h4v4h-4z',
    models: 'M4 20V10h4v10 M10 20V4h4v16 M16 20v-7h4v7',
    forecast: 'M3 4v16h18 M6 15l4-6 4 3 6-7 M16 5h4v4',
    supply: 'M3 7l9-4 9 4v10l-9 4-9-4z M3 7l9 4 9-4 M12 11v10',
    scenario: 'M5 3v18 M12 3v18 M19 3v18 M2 8h6 M9 16h6 M16 10h6',
    monitoring: 'M2 12h5l3-8 4 16 3-8h5',
    settings: 'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6',
    arrow: 'M5 12h14 M13 6l6 6-6 6',
    menu: 'M4 6h16 M4 12h16 M4 18h16',
    moon: 'M20 15A9 9 0 019 4a9 9 0 1011 11z',
    download: 'M12 3v12 M7 10l5 5 5-5 M4 16v5h16v-5',
    calendar: 'M4 5h16v16H4z M4 10h16 M8 3v4 M16 3v4',
    check: 'M5 12l4 4L19 6',
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] ?? paths.overview} /></svg>;
}
