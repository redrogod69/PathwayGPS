import { FormEvent, ReactNode, useState } from 'react';
import { Activity, BookOpen, Bookmark, Database, Dna, FlaskConical, GitBranch, GitCompare, Home, Route, Search, Sparkles, X } from 'lucide-react';
import type { Analysis } from '../types';

export type ViewId = 'overview' | 'explorer' | 'atlas' | 'tracer' | 'compare' | 'evidence' | 'saved' | 'enrichment' | 'sources';

export const NAV: { id: ViewId; label: string; icon: ReactNode; needsAnalysis?: boolean; group?: string }[] = [
  { id: 'overview', label: 'Overview', icon: <Home className="h-4 w-4" /> },
  { id: 'explorer', label: 'Variant Explorer', icon: <Dna className="h-4 w-4" />, needsAnalysis: true },
  { id: 'atlas', label: 'Biological Atlas', icon: <GitBranch className="h-4 w-4" />, needsAnalysis: true },
  { id: 'tracer', label: 'Mechanism Tracer', icon: <Route className="h-4 w-4" />, needsAnalysis: true },
  { id: 'compare', label: 'Compare Variants', icon: <GitCompare className="h-4 w-4" /> },
  { id: 'evidence', label: 'Evidence Library', icon: <BookOpen className="h-4 w-4" />, needsAnalysis: true },
  { id: 'saved', label: 'Saved Analyses', icon: <Bookmark className="h-4 w-4" /> },
  { id: 'enrichment', label: 'Gene-list Analysis', icon: <FlaskConical className="h-4 w-4" />, group: 'Tools' },
  { id: 'sources', label: 'Data Sources', icon: <Database className="h-4 w-4" />, group: 'Tools' },
];

export function Logo() {
  return (
    <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-tr from-cyan-500 to-teal-400 text-slate-950 shadow-md shadow-cyan-500/20">
      <Dna className="h-4 w-4 stroke-[2.5]" />
    </div>
  );
}

export function Navbar({ analysis, onQuery, onHome, onAssistant, onSources, health, busy }: {
  analysis: Analysis | null; onQuery: (q: string) => void; onHome: () => void; onAssistant: () => void; onSources: () => void; health: any; busy: boolean;
}) {
  const [q, setQ] = useState('');
  const submit = (e: FormEvent) => { e.preventDefault(); if (q.trim()) { onQuery(q); setQ(''); } };
  const root = analysis?.graph.nodes.find((n) => n.id === analysis.root_id);
  const ok = analysis ? analysis.sources.filter((s) => s.status === 'ok').length : null;
  return (
    <header className="z-30 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-slate-800/80 bg-panel/95 px-4 backdrop-blur-md">
      <div className="flex min-w-0 items-center gap-3">
        <button onClick={onHome} className="flex items-center gap-2.5" aria-label="PathwayGPS home">
          <Logo />
          <div className="text-left leading-none">
            <div className="flex items-center gap-1.5">
              <span className="text-base font-extrabold tracking-tight text-slate-100">Pathway<span className="text-cyan-400">GPS</span></span>
              <span className="hidden rounded border border-cyan-800/60 bg-cyan-950/60 px-1.5 py-0.5 font-mono text-[10px] font-bold text-cyan-400 sm:inline">v2.1</span>
            </div>
            <div className="mt-1 hidden text-[10px] text-slate-400 md:block">From mutation to mechanism</div>
          </div>
        </button>
        {analysis && root && (
          <div className="ml-2 hidden items-center gap-2 border-l border-slate-800 pl-4 lg:flex">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Active:</span>
            <span className="rounded-full border border-slate-700/80 bg-slate-900 px-2.5 py-0.5 font-mono text-xs font-bold text-cyan-300">{root.label}</span>
            <span className="max-w-[180px] truncate text-[11px] text-slate-400">{analysis.resolution.protein?.protein_name ?? analysis.resolution.gene?.description}</span>
            {analysis.snapshot && <span className="rounded-full border border-violet-500/40 px-2 text-[10px] text-violet-300">snapshot</span>}
          </div>
        )}
      </div>
      <form onSubmit={submit} className="mx-2 max-w-md flex-1">
        <div className="relative flex items-center">
          <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <input value={q} onChange={(e) => setQ(e.target.value)} disabled={busy} aria-label="Quick search variant, gene or rsID"
            placeholder={busy ? 'Navigating…' : 'Quick search variant, gene, or rsID…'}
            className="w-full rounded-xl border border-slate-800 bg-slate-900/90 py-1.5 pl-8 pr-3 font-mono text-xs text-slate-200 placeholder:font-sans placeholder:text-slate-500 focus:border-cyan-500/80 focus:outline-none" />
        </div>
      </form>
      <div className="flex items-center gap-2.5">
        <button onClick={onSources} className="flex items-center gap-1.5 rounded-xl border border-slate-800 bg-slate-900/80 px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-700"
          title={analysis ? `${ok}/${analysis.sources.length} sources responded fully` : health?.status === 'down' ? 'API unreachable' : 'API online'}>
          <span className={`h-2 w-2 rounded-full ${health?.status === 'down' ? 'bg-rose-400' : analysis && ok! < analysis.sources.length ? 'bg-amber-400' : 'bg-emerald-400'} animate-pulse`} />
          <span className="hidden text-[11px] sm:inline">Sources{analysis ? ` ${ok}/${analysis.sources.length}` : ''}</span>
        </button>
        <button onClick={onAssistant} className="flex items-center gap-1.5 rounded-xl border border-cyan-500/40 bg-cyan-500/10 px-3 py-1.5 text-xs font-bold text-cyan-300 shadow-md shadow-cyan-950/40 hover:bg-cyan-500/20">
          <Sparkles className="h-3.5 w-3.5" /><span className="hidden sm:inline">AI Assistant</span>
        </button>
      </div>
    </header>
  );
}

export function Sidebar({ view, onSelect, analysis, badges }: { view: ViewId; onSelect: (v: ViewId) => void; analysis: Analysis | null; badges: Partial<Record<ViewId, number>> }) {
  const groups = [undefined, 'Tools'];
  return (
    <nav className="z-20 flex w-16 shrink-0 select-none flex-col justify-between border-r border-slate-800/80 bg-panel/95 py-4 md:w-56" aria-label="Main navigation">
      <div className="space-y-1 px-2">
        {groups.map((grp) => (
          <div key={grp ?? 'main'} className="space-y-1">
            <div className="hidden px-3 pb-1.5 pt-2 text-[10px] font-bold uppercase tracking-wider text-slate-500 md:block">{grp ?? 'Navigation'}</div>
            {NAV.filter((n) => n.group === grp).map((item) => {
              const active = view === item.id;
              const disabled = item.needsAnalysis && !analysis?.root_id;
              return (
                <button key={item.id} onClick={() => onSelect(item.id)} disabled={disabled} title={disabled ? `${item.label} — analyse a variant first` : item.label}
                  className={`group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-xs font-semibold transition-all disabled:cursor-not-allowed disabled:opacity-35 ${active ? 'border border-cyan-500/30 bg-cyan-500/10 text-cyan-300 shadow-md shadow-cyan-950/40' : 'border border-transparent text-slate-400 hover:bg-slate-900/60 hover:text-slate-200'}`}>
                  <span className={active ? 'text-cyan-400' : 'group-hover:text-cyan-400'}>{item.icon}</span>
                  <span className="hidden truncate md:inline">{item.label}</span>
                  {badges[item.id] ? <span className="ml-auto hidden rounded-full bg-amber-500/15 px-1.5 text-[10px] text-amber-300 md:inline">{badges[item.id]}</span>
                    : active && <span className="ml-auto hidden h-1.5 w-1.5 rounded-full bg-cyan-400 md:block" />}
                </button>
              );
            })}
          </div>
        ))}
      </div>
      <div className="hidden border-t border-slate-800/80 px-3 pt-3 text-[11px] text-slate-500 md:block">
        <div className="space-y-1 rounded-xl border border-slate-800 bg-slate-950/60 p-2.5">
          <div className="flex items-center gap-1 font-semibold text-slate-300"><Activity className="h-3 w-3 text-teal-400" />Harmonized Graph</div>
          <p className="text-[10px] leading-tight text-slate-500">
            {analysis?.root_id ? `${analysis.graph.nodes.length} nodes · ${analysis.graph.edges.length} relationships · ${Object.keys(analysis.graph.evidence).length} evidence records` : 'ClinVar • VEP • UniProt • Reactome • IntAct • Open Targets • CIViC • PubMed'}
          </p>
        </div>
      </div>
    </nav>
  );
}

export function PageHeader({ icon, title, chip, subtitle, actions }: { icon: ReactNode; title: string; chip?: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-4 border-b border-slate-800/80 pb-5">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-cyan-500/30 bg-cyan-500/10 text-cyan-300">{icon}</span>
          <h1 className="text-xl font-bold tracking-tight text-white">{title}</h1>
          {chip && <span className="rounded-md border border-cyan-800/60 bg-cyan-950/50 px-2 py-0.5 font-mono text-xs text-cyan-300">{chip}</span>}
        </div>
        {subtitle && <p className="mt-2 max-w-3xl text-sm text-slate-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CloseButton({ onClick }: { onClick: () => void }) {
  return <button onClick={onClick} aria-label="Close" className="rounded-lg p-1.5 text-slate-400 hover:bg-white/5 hover:text-white"><X className="h-4 w-4" /></button>;
}
