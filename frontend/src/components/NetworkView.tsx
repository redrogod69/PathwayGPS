import { useMemo, useRef, useState } from 'react';
import type { Analysis, Category, NodeType, PathResult } from '../types';
import { CATEGORY_STYLE, NODE_STYLE, SOURCE_LABEL } from '../lib/vocab';
import DetailPanel from './DetailPanel';
import GraphCanvas, { GraphFilters, GraphHandle, LayoutMode } from './GraphCanvas';
import { PathPanel } from './Panels';
import { Button } from './ui';

interface Props {
  analysis: Analysis;
  selectedId: string | null;
  setSelectedId: (id: string | null) => void;
  path: PathResult | null;
  setPath: (p: PathResult | null) => void;
  expanding: string | null;
  flashIds: string[];
  marked: string[];
  onExpand: (nodeId: string, action: string) => void;
  onExplainPath: (nodeId: string) => void;
  onToggleMark: (nodeId: string) => void;
  onAddNote: (targetId: string, label: string, evidenceIds: string[]) => void;
  graphRef: React.RefObject<GraphHandle>;
}

const ALL_CATS: Category[] = ['curated', 'experimental', 'association', 'computational', 'inferred', 'hypothesis'];

function Toggle({ on, onClick, color, children, title }: { on: boolean; onClick: () => void; color?: string; children: React.ReactNode; title?: string }) {
  return (
    <button onClick={onClick} title={title} aria-pressed={on}
      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] transition ${on ? 'border-line bg-white/5 text-slate-100' : 'border-transparent text-slate-500 line-through'}`}>
      {color && <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: on ? color : 'transparent', border: `1.5px solid ${color}` }} />}
      {children}
    </button>
  );
}

export default function NetworkView(p: Props) {
  const { analysis } = p;
  const presentTypes = useMemo(() => [...new Set(analysis.graph.nodes.map((n) => n.type))] as NodeType[], [analysis]);
  const presentSources = useMemo(() => [...new Set(Object.values(analysis.graph.evidence).map((e) => e.source))], [analysis]);
  const presentCats = useMemo(() => ALL_CATS.filter((c) => analysis.graph.edges.some((e) => e.categories.includes(c))), [analysis]);
  const [filters, setFilters] = useState<GraphFilters>(() => ({
    nodeTypes: new Set(Object.keys(NODE_STYLE)), sources: new Set([...Object.keys(SOURCE_LABEL)]), categories: new Set(ALL_CATS), showSecondary: false,
  }));
  const [layout, setLayout] = useState<LayoutMode>('route');
  const [search, setSearch] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const canvasWrap = useRef<HTMLDivElement>(null);

  const toggleIn = (key: 'nodeTypes' | 'sources' | 'categories', value: string) => {
    setFilters((f) => {
      const next = new Set(f[key]);
      if (next.has(value)) next.delete(value); else next.add(value);
      return { ...f, [key]: next };
    });
  };
  const matches = useMemo(() => {
    const t = search.trim().toLowerCase();
    if (t.length < 2) return [];
    return analysis.graph.nodes.filter((n) => `${n.label} ${n.subtitle ?? ''} ${n.id}`.toLowerCase().includes(t)).slice(0, 8);
  }, [search, analysis]);
  const secondaryCount = analysis.graph.nodes.filter((n) => n.secondary).length;

  return (
    <div className="grid gap-3 lg:h-[calc(100vh-215px)] lg:min-h-[620px] lg:grid-cols-[minmax(0,1fr)_400px]">
      <section className="relative flex h-[78vh] min-h-[520px] flex-col overflow-hidden rounded-xl border border-line bg-[#060b17] lg:h-auto lg:min-h-0">
        {/* toolbar */}
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel/80 px-3 py-2">
          <div className="relative">
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Find in graph…" aria-label="Find an entity in the graph"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && matches[0]) { p.setSelectedId(matches[0].id); p.graphRef.current?.center(matches[0].id); setSearch(''); }
                if (e.key === 'Escape') setSearch('');
              }}
              className="w-48 rounded-md border border-line bg-ink px-2.5 py-1 text-xs outline-none focus:border-cyan-400" />
            {matches.length > 0 && (
              <ul className="absolute left-0 top-full z-30 mt-1 w-72 rounded-lg border border-line bg-panel p-1 shadow-xl">
                {matches.map((n) => (
                  <li key={n.id}><button className="w-full truncate rounded px-2 py-1 text-left text-xs text-slate-200 hover:bg-white/5"
                    onClick={() => { p.setSelectedId(n.id); p.graphRef.current?.center(n.id); setSearch(''); }}>
                    <span style={{ color: NODE_STYLE[n.type].color }}>●</span> {n.label} <span className="text-slate-500">· {NODE_STYLE[n.type].label}</span></button></li>
                ))}
              </ul>
            )}
          </div>
          <div className="flex rounded-md border border-line p-0.5" role="group" aria-label="Layout">
            {(['route', 'network', 'concentric'] as LayoutMode[]).map((l) => (
              <button key={l} onClick={() => setLayout(l)} className={`rounded px-2 py-0.5 text-[11px] ${layout === l ? 'bg-cyan-400 font-semibold text-ink' : 'text-slate-300'}`}>{l === 'route' ? 'Route' : l === 'network' ? 'Force' : 'Rings'}</button>
            ))}
          </div>
          <div className="flex items-center gap-0.5">
            <Button title="Zoom in" onClick={() => p.graphRef.current?.zoom(1.25)}>＋</Button>
            <Button title="Zoom out" onClick={() => p.graphRef.current?.zoom(0.8)}>－</Button>
            <Button title="Fit visible graph to screen" onClick={() => p.graphRef.current?.fit()}>Fit</Button>
            <Button title="Re-run layout and reset view" onClick={() => { p.graphRef.current?.reset(); p.setPath(null); p.setSelectedId(null); }}>Reset</Button>
          </div>
          <label className="inline-flex cursor-pointer items-center gap-1.5 text-[11px] text-slate-300" title="IntAct interactors and lower-ranked diseases are hidden by default to limit clutter">
            <input type="checkbox" checked={filters.showSecondary} onChange={() => setFilters((f) => ({ ...f, showSecondary: !f.showSecondary }))} className="accent-cyan-400" />
            Show secondary ({secondaryCount})
          </label>
          <button className="ml-auto text-[11px] text-cyan-300" onClick={() => setShowFilters(!showFilters)}>{showFilters ? 'Hide filters & legend' : 'Filters & legend'}</button>
        </div>
        {showFilters && (
          <div className="grid gap-2 border-b border-line bg-panel/50 px-3 py-2 text-[11px] md:grid-cols-[auto_1fr]">
            <span className="pt-1 font-semibold uppercase tracking-wider text-slate-500">Entities</span>
            <div className="flex flex-wrap gap-1">{presentTypes.map((t) => (
              <Toggle key={t} on={filters.nodeTypes.has(t)} onClick={() => toggleIn('nodeTypes', t)} color={NODE_STYLE[t].color}>{NODE_STYLE[t].label}</Toggle>))}
            </div>
            <span className="pt-1 font-semibold uppercase tracking-wider text-slate-500">Evidence</span>
            <div className="flex flex-wrap gap-1">{presentCats.map((c) => (
              <Toggle key={c} on={filters.categories.has(c)} onClick={() => toggleIn('categories', c)} color={CATEGORY_STYLE[c].color} title={CATEGORY_STYLE[c].help}>
                <svg width="18" height="6" aria-hidden><line x1="0" y1="3" x2="18" y2="3" stroke={CATEGORY_STYLE[c].color} strokeWidth="2" strokeDasharray={CATEGORY_STYLE[c].line === 'dashed' ? '5 3' : CATEGORY_STYLE[c].line === 'dotted' ? '1.5 2.5' : undefined} /></svg>
                {CATEGORY_STYLE[c].label}
              </Toggle>))}
            </div>
            <span className="pt-1 font-semibold uppercase tracking-wider text-slate-500">Sources</span>
            <div className="flex flex-wrap gap-1">{presentSources.map((s) => (
              <Toggle key={s} on={filters.sources.has(s)} onClick={() => toggleIn('sources', s)}>{SOURCE_LABEL[s] ?? s}</Toggle>))}
            </div>
          </div>
        )}
        <div ref={canvasWrap} className="relative min-h-0 flex-1">
          <GraphCanvas ref={p.graphRef} analysis={analysis} filters={filters} layout={layout} selectedId={p.selectedId}
            pathNodes={p.path?.found ? p.path.nodes ?? [] : []} pathEdges={p.path?.found ? (p.path.hops ?? []).map((h) => h.edge_id) : []}
            searchTerm={search} marked={p.marked} flashIds={p.flashIds}
            onSelectNode={(id) => p.setSelectedId(id)} onSelectEdge={(id) => p.setSelectedId(id)} onBackground={() => p.setSelectedId(null)}
            onExpand={(id) => {
              const node = analysis.graph.nodes.find((n) => n.id === id);
              const action = node ? ({ protein: 'all_pathways', pathway: 'reactions', reaction: 'downstream', physical_entity: 'consumers', reactome_entity: 'consumers' } as Record<string, string>)[node.type] : undefined;
              if (action && !analysis.snapshot) p.onExpand(id, action);
            }} />
          {!showFilters && (
            <div className="pointer-events-none absolute bottom-2 left-3 flex flex-wrap gap-x-3 gap-y-1 rounded-md bg-ink/80 px-2 py-1 text-[10px] text-slate-400">
              {presentCats.map((c) => (
                <span key={c} className="inline-flex items-center gap-1">
                  <svg width="16" height="6" aria-hidden><line x1="0" y1="3" x2="16" y2="3" stroke={CATEGORY_STYLE[c].color} strokeWidth="2" strokeDasharray={CATEGORY_STYLE[c].line === 'dashed' ? '5 3' : CATEGORY_STYLE[c].line === 'dotted' ? '1.5 2.5' : undefined} /></svg>{CATEGORY_STYLE[c].label}
                </span>))}
              {presentTypes.map((t) => <span key={t} className="inline-flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full" style={{ background: NODE_STYLE[t].color }} />{NODE_STYLE[t].label}</span>)}
            </div>
          )}
          {layout === 'route' && (
            <div className="pointer-events-none absolute left-3 top-2 flex gap-1 text-[10px] uppercase tracking-[.2em] text-slate-600">
              variant → gene → protein → feature / mutant entity → pathway → reactions → products
            </div>
          )}
          {p.expanding && <div className="absolute right-3 top-3 rounded-lg border border-cyan-400/40 bg-ink/90 px-3 py-1.5 text-xs text-cyan-200">Querying Reactome…</div>}
          {p.path && <div className="absolute inset-x-3 bottom-3"><PathPanel path={p.path} analysis={analysis} onClose={() => p.setPath(null)} onSelectEdge={(id) => p.setSelectedId(id)} /></div>}
        </div>
      </section>
      <aside className="min-h-0 overflow-y-auto rounded-xl border border-line bg-panel/90 lg:max-h-none" aria-label="Details">
        <DetailPanel analysis={analysis} selectedId={p.selectedId} expanding={p.expanding} marked={p.marked}
          onSelectNode={(id) => { p.setSelectedId(id); p.graphRef.current?.center(id); }} onSelectEdge={(id) => p.setSelectedId(id)}
          onExpand={p.onExpand} onExplainPath={p.onExplainPath} onToggleMark={p.onToggleMark} onAddNote={p.onAddNote} />
      </aside>
    </div>
  );
}
