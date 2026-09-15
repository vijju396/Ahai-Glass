import { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchHealth, healthKeys } from '@/api/health';
import { HealthPill } from '@/components/ui/StatusPill';
import { NAV_ITEMS, NAV_SECTIONS } from '@/app/navigation';
import { Icon } from '@/components/ui/Icon';
import './layout.css';

/** The theme actually on screen, which is not the same as the attribute:
 *  with no explicit choice the OS preference decides. Reading the attribute
 *  alone makes the first click a no-op for anyone whose system is already
 *  dark. */
function effectiveTheme(): 'dark' | 'light' {
  const explicit = document.documentElement.dataset.theme;
  if (explicit === 'dark' || explicit === 'light') return explicit;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function ThemeToggle() {
  const toggle = () => {
    const next = effectiveTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try {
      window.localStorage.setItem('ais-theme', next);
    } catch {
      // Private windows and blocked site data must not break the toggle.
    }
  };
  return (
    <button
      type="button"
      className="icon-button"
      onClick={toggle}
      aria-label="Toggle colour theme"
    >
      <Icon name="moon" size={17} />
    </button>
  );
}

function HealthBadge() {
  const { data, isPending, isError } = useQuery({
    queryKey: healthKeys.all,
    queryFn: fetchHealth,
    refetchInterval: 30_000,
  });
  if (isPending) return <span className="pill pill-neutral">Checking</span>;
  if (isError || !data) return <HealthPill status="error" />;
  return <HealthPill status={data.status} />;
}

export function AppShell() {
  const [navOpen, setNavOpen] = useState(false);
  const location = useLocation();
  const current = NAV_ITEMS.find(item => item.path === location.pathname);
  const icons = ['overview', 'data', 'mapping', 'training', 'models', 'forecast', 'supply', 'scenario', 'monitoring', 'settings'];
  return (
    <div className={`shell${navOpen ? ' nav-open' : ''}`}>
      <a href="#main" className="skip-link">
        Skip to main content
      </a>

      <nav className="sidenav" aria-label="Main navigation">
        <div className="brand">
          <img src="/ais-logo.png" alt="Asahi India Glass Ltd." />
          <span className="brand-text">
            Intelligence
            <small>Demand &amp; Supply</small>
          </span>
        </div>

        {NAV_SECTIONS.map((section) => (
          <div className="nav-group" key={section.label}>
            <div className="nav-group-label">{section.label}</div>
            <ul>
              {section.items.map((item) => (
                <li key={item.path}>
                  <NavLink
                    to={item.path}
                    className={({ isActive }) => (isActive ? 'nav-link on' : 'nav-link')}
                    end={item.path === '/'}
                    onClick={() => setNavOpen(false)}
                  >
                    <Icon name={icons[item.index - 1] ?? 'overview'} />
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
        <div className="nav-footer"><strong>Clarity for every decision.</strong><p>AIS Consumer Glass Solutions</p><p>Forecasting proof of concept</p></div>
      </nav>

      <div className="content">
        <header className="topbar">
          <div className="topbar-meta">
            <button className="icon-button menu-button" aria-label="Toggle navigation" aria-expanded={navOpen} onClick={() => setNavOpen(!navOpen)}><Icon name="menu" /></button>
            <strong>AIS Analytics</strong><span>/</span><span>{current?.label ?? 'Workspace'}</span><span className="workspace-tag">POC WORKSPACE</span>
          </div>
          <div className="topbar-actions">
            <HealthBadge />
            <ThemeToggle />
          </div>
        </header>

        <main id="main" className="main">
          {/* The planning-workflow strip is gone with the pipeline pages it
              linked to (D-057). Leaving it would have pointed at four
              unrouted destinations. */}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
