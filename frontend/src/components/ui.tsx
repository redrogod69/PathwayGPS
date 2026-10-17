import type { ReactNode } from 'react';
import type { Category } from '../types';
import { CATEGORY_STYLE, SOURCE_LABEL } from '../lib/vocab';

export function Card({ title, subtitle, children, actions, className = '' }: { title?: ReactNode; subtitle?: ReactNode; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-line bg-panel/90 ${className}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            {title && <h3 className="text-sm font-semibold text-slate-100">{title}</h3>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function CategoryChip({ category, small = false }: { category: Category; small?: boolean }) {
  const s = CATEGORY_STYLE[category] ?? CATEGORY_STYLE.inferred;
  return (
    <span title={s.help} className={`inline-flex items-center gap-1 rounded-full border px-2 ${small ? 'py-0 text-[10px]' : 'py-0.5 text-[11px]'} font-semibold uppercase tracking-wide`}
      style={{ color: s.color, borderColor: `${s.color}66`, background: `${s.color}14` }}>
      <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: s.color }} />
      {s.label}
    </span>
  );
}

export function SourceChip({ source }: { source: string }) {
  return <span className="inline-flex items-center rounded-md border border-line bg-ink px-1.5 py-0.5 font-mono text-[10px] text-cyan-200">{SOURCE_LABEL[source] ?? source}</span>;
}

export function Pill({ children, tone = 'slate' }: { children: ReactNode; tone?: 'slate' | 'teal' | 'amber' | 'rose' | 'violet' | 'sky' }) {
  const tones: Record<string, string> = {
    slate: 'border-slate-500/40 bg-slate-500/10 text-slate-300',
    teal: 'border-teal-400/40 bg-teal-400/10 text-teal-200',
    amber: 'border-amber-400/40 bg-amber-400/10 text-amber-200',
    rose: 'border-rose-400/40 bg-rose-400/10 text-rose-200',
    violet: 'border-violet-400/40 bg-violet-400/10 text-violet-200',
    sky: 'border-sky-400/40 bg-sky-400/10 text-sky-200',
  };
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${tones[tone]}`}>{children}</span>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate-300">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-400/30 border-t-cyan-300" />
      {label}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-sm text-slate-400">{children}</div>;
}

export function ExtLink({ href, children, className = '' }: { href?: string | null; children: ReactNode; className?: string }) {
  if (!href) return <span className={className}>{children}</span>;
  return <a href={href} target="_blank" rel="noreferrer noopener" className={`text-cyan-300 underline decoration-cyan-300/30 underline-offset-2 hover:decoration-cyan-300 ${className}`}>{children}</a>;
}

export function KV({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(110px,max-content)_1fr] gap-x-4 gap-y-1.5 text-sm">
      {rows.filter(([, v]) => v !== null && v !== undefined && v !== '').map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-slate-400">{k}</dt>
          <dd className="min-w-0 break-words text-slate-100">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Button({ children, onClick, variant = 'ghost', disabled, title, type = 'button', className = '' }: {
  children: ReactNode; onClick?: () => void; variant?: 'primary' | 'ghost' | 'outline'; disabled?: boolean; title?: string; type?: 'button' | 'submit'; className?: string;
}) {
  const styles = {
    primary: 'bg-cyan-400 text-ink hover:bg-cyan-300 font-semibold',
    ghost: 'text-slate-300 hover:bg-white/5 hover:text-white',
    outline: 'border border-line text-slate-200 hover:border-cyan-400/50 hover:text-white',
  }[variant];
  return (
    <button type={type} title={title} disabled={disabled} onClick={onClick}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition disabled:cursor-not-allowed disabled:opacity-40 ${styles} ${className}`}>
      {children}
    </button>
  );
}
