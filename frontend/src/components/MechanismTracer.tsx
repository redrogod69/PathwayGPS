import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, Crosshair, Dna, MapPin, Route as RouteIcon } from 'lucide-react';
import { api } from '../api';
import type { Analysis, PathResult } from '../types';
import { CATEGORY_STYLE, NODE_STYLE, RELATION_LABEL, SOURCE_LABEL, VERDICT_LABEL } from '../lib/vocab';
import { PageHeader } from './Shell';
import { Button, Empty, ExtLink, Spinner } from './ui';

type RouteRes = PathResult & { rank: number; cost: number; evidence: Record<string, string[]> };

const TARGET_GROUPS: { label: string; types: string[] }[] = [
  { label: 'Downstream entities & reactions', types: ['physical_entity', 'reaction'] },
  { label: 'Pathways', types: ['pathway'] },
  { label: 'Diseases / phenotypes', types: ['disease'] },
  { label: 'Drugs / therapies', types: ['drug'] },
  { label: 'Protein features & interactors', types: ['protein_region', 'reactome_entity', 'interactor'] },
];

export default function MechanismTracer({ analysis, onIlluminate }: { analysis: Analysis; onIlluminate: (route: PathResult) => void }) {
  const root = analysis.graph.nodes.find((n) => n.id === analysis.root_id)!;
  const defaultTarget = useMemo(() => {
    const d = analysis.impact?.downstream ?? [];
    return (d.find((x) => x.type === 'physical_entity') ?? d[d.length - 1])?.node_id ?? analysis.graph.nodes.find((n) => n.type === 'pathway')?.id ?? '';
  }, [analysis]);
  const [target, setTarget] = useState(defaultTarget);
  const [state, setState] = useState<{ loading: boolean; error?: string; routes?: RouteRes[]; message?: string; ranking?: string }>({ loading: false });
  const [active, setActive] = useState(0);
  useEffect(() => setTarget(defaultTarget), [defaultTarget]);
  useEffect(() => {
    if (!target) return;
    let live = true;
    setState({ loading: true }); setActive(0);
    api.routes(analysis.analysis_id, target, 3)
      .then((r) => live && setState({ loading: false, routes: r.routes, message: r.message ?? undefined, ranking: r.ranking }))
      .catch((e) => live && setState({ loading: false, error: (e as Error).message }));
    return () => { live = false; };
  }, [target, analysis.analysis_id, analysis.graph.edges.length]);

  const nodeById = useMemo(() => new Map(analysis.graph.nodes.map((n) => [n.id, n])), [analysis]);
  const route = state.routes?.[active];
  const tgt = nodeById.get(target);

  return (
    <div>
      <PageHeader icon={<RouteIcon className="h-4 w-4" />} title="Mechanism Tracing Engine" chip="Variant → Pathway → Downstream"
        subtitle="Trace source-backed routes from the variant through its protein, curated Reactome steps and downstream products to any entity — each step shows its evidence category, records and literature, and inferred steps are flagged." />
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-slate-800 bg-panel p-4">
          <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400"><Dna className="h-3.5 w-3.5 text-cyan-400" />Origin (genomic variant)</div>
          <div className="mt-2 flex items-center justify-between gap-3">
            <div>
              <div className="font-mono text-lg font-bold text-cyan-300">{root.label}</div>
              <div className="text-xs text-slate-400">{analysis.resolution.gene?.description}{root.attributes.grch38?.chr ? ` (chr${root.attributes.grch38.chr}:${root.attributes.grch38.start})` : ''}</div>
            </div>
            <span className="rounded-full border border-cyan-500/40 bg-cyan-500/10 px-3 py-1 text-xs font-semibold text-cyan-300">Root origin</span>
          </div>
        </div>
        <div className="rounded-2xl border border-slate-800 bg-panel p-4">
          <label htmlFor="tracer-target" className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400"><Crosshair className="h-3.5 w-3.5 text-cyan-400" />Downstream biological target</label>
          <select id="tracer-target" value={target} onChange={(e) => setTarget(e.target.value)}
            className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-cyan-500/70 focus:outline-none">
            {TARGET_GROUPS.map((g) => {
              const opts = analysis.graph.nodes.filter((n) => g.types.includes(n.type) && n.id !== root.id);
              if (!opts.length) return null;
              return (
                <optgroup key={g.label} label={g.label}>
                  {opts.map((n) => <option key={n.id} value={n.id}>[{NODE_STYLE[n.type].label.toUpperCase()}] {n.attributes.full_name && n.type !== 'disease' ? n.attributes.full_name : n.label}</option>)}
                </optgroup>
              );
            })}
          </select>
        </div>
      </div>

      {state.loading && <div className="mt-6"><Spinner label="Ranking evidence-backed routes…" /></div>}
      {state.error && <p className="mt-6 text-sm text-rose-300">{state.error}</p>}
      {!state.loading && state.message && <div className="mt-6"><Empty>{state.message}</Empty></div>}

      {state.routes && state.routes.length > 0 && (
        <>
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <span className="mr-1 text-sm font-semibold text-slate-300">Discovered routes:</span>
            {state.routes.map((r, i) => {
              const v = VERDICT_LABEL[r.verdict!];
              return (
                <button key={i} onClick={() => setActive(i)}
                  className={`flex items-center gap-2 rounded-xl border px-3 py-1.5 text-sm ${active === i ? 'border-cyan-500/50 bg-cyan-500/10 text-cyan-200' : 'border-slate-800 bg-panel text-slate-400 hover:text-slate-200'}`}>
                  Route #{r.rank}
                  <span className="rounded border border-slate-700 bg-slate-950 px-1.5 font-mono text-[10px] text-slate-300">{r.hops!.length} steps</span>
                  <span className={`text-[10px] font-bold uppercase ${v?.tone.split(' ')[0]}`}>{v?.text}</span>
                </button>
              );
            })}
            <span className="ml-auto text-[11px] text-slate-500">{state.ranking}</span>
          </div>

          {route && (
            <div className="mt-4 rounded-2xl border border-slate-800 bg-panel/70 p-4 md:p-5">
              <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                <div className="min-w-0 flex-1">
                  <div className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Mechanistic trace summary</div>
                  <p className="mt-1 text-sm leading-relaxed text-slate-200">
                    <b className="text-cyan-300">{root.label}</b> reaches <b className="text-white">{tgt?.attributes.full_name ?? tgt?.label}</b> in {route.hops!.length} step{route.hops!.length > 1 ? 's' : ''} via{' '}
                    {route.hops!.map((h) => h.label).join(' → ')}. {route.verdict_text}
                  </p>
                </div>
                <div className="text-right">
                  <div className="text-[11px] text-slate-500">Route cost (rank #{route.rank})</div>
                  <div className="font-mono text-lg font-bold text-cyan-300">{route.cost.toFixed(2)}</div>
                  <div className="text-[10px] text-slate-500">lower = shorter / stronger — not a probability</div>
                </div>
                <Button variant="outline" onClick={() => onIlluminate(route)} className="border-cyan-500/40 text-cyan-200"><MapPin className="h-3.5 w-3.5" />Illuminate on Atlas</Button>
              </div>

              <div className="mt-5 text-xs font-bold uppercase tracking-wider text-slate-400">Sequential molecular cascade steps</div>
              <ol className="mt-3 space-y-3">
                {route.hops!.map((h, i) => {
                  const cs = CATEGORY_STYLE[h.category];
                  const evs = (route.evidence[h.edge_id] ?? []).map((id) => analysis.graph.evidence[id]).filter(Boolean);
                  const pmids = [...new Set(evs.flatMap((e) => e.publications))];
                  const from = nodeById.get(h.from)!;
                  const to = nodeById.get(h.to)!;
                  return (
                    <li key={h.edge_id} className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/80 pb-2.5">
                        <div className="flex items-center gap-2">
                          <span className="flex h-5 w-5 items-center justify-center rounded-full border border-cyan-500/40 font-mono text-[10px] text-cyan-300">{i + 1}</span>
                          <span className="text-sm font-semibold text-slate-100">{RELATION_LABEL[h.type] ?? h.label}</span>
                          {h.direction === 'reverse' && <span className="text-[10px] text-slate-500">(walked against the arrow)</span>}
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase" style={{ color: cs.color, borderColor: `${cs.color}66`, background: `${cs.color}14` }}>{cs.label}</span>
                          <span className="font-mono text-[10px] text-slate-500">{h.evidence_count} records · {h.sources.map((s) => SOURCE_LABEL[s] ?? s).join(', ')}</span>
                        </div>
                      </div>
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <span className="flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1 text-xs font-semibold text-slate-100"><span className="h-2 w-2 rounded-full" style={{ background: NODE_STYLE[from.type].color }} />{from.label}</span>
                        <ArrowRight className="h-4 w-4 text-cyan-400" />
                        <span className="flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1 text-xs font-semibold text-slate-100"><span className="h-2 w-2 rounded-full" style={{ background: NODE_STYLE[to.type].color }} />{to.attributes.full_name && to.type !== 'disease' ? to.attributes.full_name : to.label}</span>
                      </div>
                      {evs.slice(0, 2).map((e) => (
                        <p key={e.id} className="mt-2.5 rounded-lg border border-slate-800/80 bg-slate-900/60 px-3 py-2 text-xs leading-relaxed text-slate-300">
                          {e.statement}{e.inference && <span className="block pt-1 text-slate-500">PathwayGPS inference: {e.inference}</span>}
                        </p>
                      ))}
                      <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[11px]">
                        <span className="text-slate-500">Literature proof:</span>
                        {pmids.length ? pmids.slice(0, 6).map((p) => (
                          <ExtLink key={p} href={`https://pubmed.ncbi.nlm.nih.gov/${p}/`} className="rounded border border-slate-800 px-1.5 py-0.5 font-mono text-[10px] no-underline">PMID:{p}</ExtLink>
                        )) : <span className="italic text-slate-500">none attached in the source record</span>}
                        {pmids.length > 6 && <span className="text-slate-500">+{pmids.length - 6}</span>}
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>
          )}
        </>
      )}
    </div>
  );
}
