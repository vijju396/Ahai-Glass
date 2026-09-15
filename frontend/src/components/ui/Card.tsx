import type { ReactNode } from 'react';
import './ui.css';

interface CardProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  tight?: boolean;
  className?: string;
  /** Anchor target, for pages long enough to need in-page navigation. */
  id?: string;
}

export function Card({ title, subtitle, actions, children, tight, className, id }: CardProps) {
  return (
    <section id={id} className={`card ${className ?? ''}`}>
      {(title || actions) && (
        <header className="card-header">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <div className="sub">{subtitle}</div>}
          </div>
          {actions && <div>{actions}</div>}
        </header>
      )}
      <div className={`card-body${tight ? ' tight' : ''}`}>{children}</div>
    </section>
  );
}
