import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import '@/styles/index.css';
import '@/styles/ais.css';
import '@/styles/reference.css';

// Restore the viewer's theme choice before first paint to avoid a flash.
try {
  const stored = window.localStorage.getItem('ais-theme');
  if (stored === 'dark' || stored === 'light') {
    document.documentElement.dataset.theme = stored;
  }
} catch {
  // Blocked site data must not prevent the app from mounting.
}

const container = document.getElementById('root');
if (!container) throw new Error('Root element #root is missing from index.html');

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
