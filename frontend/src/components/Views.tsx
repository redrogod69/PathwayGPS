import React, { useEffect, useState } from 'react';
import { ArrowRight, BookOpen, Database, Dna, GitBranch, GitCompare, History, Layers, Route, Search, ShieldAlert, Sparkles } from 'lucide-react';
import { PageHeader } from './Shell';
import { api } from '../api';
import type { Analysis } from '../types';
import { shortDate, stars } from '../lib/vocab';
import { Button, Card, Empty, ExtLink, Pill, Spinner } from './ui';

export const FALLBACK_EXAMPLES = [
  { query: 'EGFR L858R', label: 'EGFR L858R', note: 'Somatic driver in NSCLC' },
  { query: 'BRAF V600E', label: 'BRAF V600E', note: 'Conflicting germline vs Tier I somatic evidence' },
  { query: 'rs121434568', label: 'rs121434568', note: 'Multi-allelic dbSNP ID' },
  { query: 'NM_000546.6:c.524G>A', label: 'TP53 c.524G>A', note: 'Transcript HGVS' },
  { query: 'KRAS G12C', label: 'KRAS G12C', note: 'Targetable KRAS allele' },
  { query: 'TP53', label: 'TP53 (gene only)', note: 'Gene-level exploration' },
];

/* ------------------------------------------------------------------ landing */
export function Landing({ onQuery, examples, recent }: { onQuery: (q: string) => void; examples: typeof FALLBACK_EXAMPLES; recent: string[] }) {
  const [q, setQ] = useState('');
  const features: [React.ReactNode, string, string, string][] = [
    [<Dna key="d" className="h-5 w-5" />, 'Canonical Variant Resolution', 'Resolves variants across ClinVar, Ensembl VEP and UniProtKB, validates the reference residue and reports ambiguity instead of guessing.', 'text-cyan-300 border-cyan-500/30 bg-cyan-500/10'],
    [<GitBranch key="g" className="h-5 w-5" />, 'Interactive Biological Atlas', 'Explore Reactome pathways, the curated mutant entity, downstream reactions, interactors, diseases and drugs with route, force and ring layouts.', 'text-teal-300 border-teal-500/30 bg-teal-500/10'],
    [<BookOpen key="b" className="h-5 w-5" />, 'Edge-by-Edge Evidence Grounding', 'Every relationship links to its source records, PubMed citations and evidence category — curated, experimental, association, computational or inferred.', 'text-indigo-300 border-indigo-500/30 bg-indigo-500/10'],
    [<Route key="r" className="h-5 w-5" />, 'Mechanism Tracer', 'Rank alternative source-backed routes from the variant to any downstream entity, with per-step evidence and inferred steps flagged.', 'text-pink-300 border-pink-500/30 bg-pink-500/10'],
    [<ShieldAlert key="s" className="h-5 w-5" />, 'Conflicts & Gaps', 'Submitter disagreements, germline vs somatic contexts, opposing clinical evidence and missing literature are surfaced, not hidden.', 'text-amber-300 border-amber-500/30 bg-amber-500/10'],
    [<Sparkles key="a" className="h-5 w-5" />, 'Grounded AI Research Assistant', 'Ask questions about the active variant; every answer cites the evidence records it is built from.', 'text-violet-300 border-violet-500/30 bg-violet-500/10'],
  ];
  return (
    <div className="relative pb-10">
      <div className="pointer-events-none absolute left-1/2 top-0 h-80 w-[720px] -translate-x-1/2 rounded-full bg-cyan-500/10 blur-3xl" />
      <section className="relative mx-auto max-w-4xl pt-10 text-center">
        <span className="inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/5 px-3 py-1 text-xs font-semibold text-cyan-300">
          <Sparkles className="h-3.5 w-3.5" />Interactive Biological Navigation Platform<span className="h-1 w-1 rounded-full bg-cyan-400" /><span className="text-slate-400">MedVision ’26 · BioNav</span>
        </span>
        <h1 className="mt-6 text-5xl font-extrabold leading-[1.08] tracking-tight text-white md:text-6xl">From mutation<br /><span className="bg-gradient-to-r from-cyan-300 to-teal-300 bg-clip-text text-transparent">to mechanism.</span></h1>
        <p className="mx-auto mt-5 max-w-2xl text-lg leading-relaxed text-slate-400">Navigate the biological consequences of genetic variation through interconnected pathways, protein cascades, and verifiable scientific evidence.</p>
        <form onSubmit={(e) => { e.preventDefault(); onQuery(q); }} className="mx-auto mt-8 flex max-w-2xl items-center gap-2 rounded-2xl border border-slate-700 bg-panel/90 p-1.5 shadow-xl shadow-cyan-950/30 focus-within:border-cyan-500/60">
          <Search className="ml-3 h-5 w-5 shrink-0 text-slate-500" />
          <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Variant, gene, protein or identifier"
            placeholder="Enter a variant, gene, protein, or identifier (e.g., EGFR L858R, BRAF V600E)…" className="min-w-0 flex-1 bg-transparent px-2 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none" />
          <button type="submit" disabled={!q.trim()} className="flex items-center gap-1.5 rounded-xl bg-cyan-600 px-5 py-2.5 text-sm font-bold text-white hover:bg-cyan-500 disabled:opacity-50">Analyze<ArrowRight className="h-4 w-4" /></button>
        </form>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Demonstration benchmarks:</span>
          {examples.map((e) => (
            <button key={e.query} onClick={() => onQuery(e.query)} title={e.note} className="flex items-center gap-1.5 rounded-full border border-slate-800 bg-panel px-3 py-1 text-xs hover:border-cyan-500/50">
              <span className="h-1.5 w-1.5 rounded-full bg-cyan-400" /><span className="font-mono text-slate-100">{e.label}</span><span className="hidden text-[10px] text-slate-500 md:inline">({e.note})</span>
            </button>
          ))}
        </div>
        {recent.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center justify-center gap-2 text-[11px] text-slate-500">
            <History className="h-3.5 w-3.5" />Recent:
            {recent.map((r) => <button key={r} onClick={() => onQuery(r)} className="rounded-md border border-slate-800 px-2 py-0.5 font-mono text-slate-300 hover:border-cyan-500/50">{r}</button>)}
          </div>
        )}
      </section>
      <section className="relative mx-auto mt-14 grid max-w-6xl gap-4 md:grid-cols-2 xl:grid-cols-3">
        {features.map(([icon, t, d, tone]) => (
          <div key={t} className="rounded-2xl border border-slate-800 bg-panel/80 p-5 transition hover:border-slate-700">
            <span className={`flex h-10 w-10 items-center justify-center rounded-xl border ${tone}`}>{icon}</span>
            <h3 className="mt-4 text-base font-bold text-white">{t}</h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-400">{d}</p>
          </div>
        ))}
      </section>
      <section className="relative mx-auto mt-6 flex max-w-6xl flex-wrap items-center gap-x-5 gap-y-2 rounded-2xl border border-slate-800 bg-panel/80 px-5 py-3.5 text-xs">
        <span className="flex items-center gap-2 font-semibold text-slate-200"><Database className="h-4 w-4 text-cyan-400" />Connected biomedical repositories:</span>
        {['NCBI ClinVar', 'Ensembl VEP', 'UniProtKB', 'Reactome', 'IntAct', 'PubMed / NCBI', 'Open Targets', 'CIViC', 'Claude AI (optional)'].map((s) => (
          <span key={s} className="flex items-center gap-1.5 text-slate-300"><span className="h-2 w-2 rounded-full bg-emerald-400" />{s}</span>
        ))}
        <span className="w-full text-[11px] text-slate-500">KEGG linked, not integrated (licensing) · Research use only — not a clinical decision tool.</span>
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ compare */
function clsTone(desc?: string) {
  if (!desc) return 'border-slate-700 text-slate-400';
  if (/conflict|uncertain/i.test(desc)) return 'border-amber-500/40 bg-amber-500/10 text-amber-200';
  if (/benign/i.test(desc)) return 'border-teal-500/40 bg-teal-500/10 text-teal-200';
  if (/pathogenic|oncogenic|tier i\b/i.test(desc)) return 'border-rose-500/40 bg-rose-500/10 text-rose-200';
  return 'border-violet-500/40 bg-violet-500/10 text-violet-200';
}

function ClsCell({ cls }: { cls: any }) {
  if (!cls) return <span className="text-slate-500">—</span>;
  return <div className="space-y-1"><span className={`inline-block rounded-full border px-2 py-0.5 text-[11px] font-semibold ${clsTone(cls.description)}`}>{cls.description}</span><div className="text-[11px] text-slate-500">{stars(cls.stars)} {cls.review_status}</div></div>;
}

export function CompareView({ onOpen, onAssistantFor }: { onOpen: (a: Analysis) => void; onAssistantFor?: (a: Analysis) => void }) {
  const [a, setA] = useState('EGFR L858R');
  const [b, setB] = useState('BRAF V600E');
  const [state, setState] = useState<{ loading: boolean; error?: string; data?: Awaited<ReturnType<typeof api.compare>> }>({ loading: false });
  const run = async () => {
    setState({ loading: true });
    try { setState({ loading: false, data: await api.compare(a, b) }); } catch (e) { setState({ loading: false, error: (e as Error).message }); }
  };
  useEffect(() => { run(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const d = state.data;
  const pa = d?.a, pb = d?.b;
  const row = (label: string, f: (p: Analysis) => React.ReactNode) => (
    <tr className="border-t border-slate-800 align-top">
      <td className="px-4 py-3 text-xs font-semibold text-slate-400">{label}</td>
      <td className="px-4 py-3 text-sm text-slate-200">{pa ? f(pa) : null}</td>
      <td className="px-4 py-3 text-sm text-slate-200">{pb ? f(pb) : null}</td>
    </tr>
  );
  const feature = (p: Analysis) => (p.overview?.protein?.features_at_variant?.covering ?? []).map((f: any) => `${f.description || f.type} (${f.start}–${f.end})`).join('; ') || '—';
  const Diff = ({ title, dd }: { title: string; dd: any }) => (
    <div className="grid gap-3 md:grid-cols-3">
      {[[`Convergent (${dd.shared.length})`, dd.shared, 'text-violet-300', 'bg-violet-400'], [`Unique to ${pa?.query} (${dd.only_a.length})`, dd.only_a, 'text-cyan-300', 'bg-cyan-400'], [`Unique to ${pb?.query} (${dd.only_b.length})`, dd.only_b, 'text-teal-300', 'bg-teal-400']].map(([label, list, tone, dot]: any) => (
        <div key={label} className="rounded-xl border border-slate-800 bg-slate-950/40 p-3">
          <div className={`mb-2 text-[11px] font-bold uppercase tracking-wider ${tone}`}>{label}</div>
          <ul className="max-h-48 space-y-1 overflow-auto text-xs text-slate-300">{list.map((x: any) => <li key={x.id} className="flex items-start gap-1.5"><span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />{x.label}</li>)}</ul>
          {list.length === 0 && <div className="text-xs text-slate-600">None</div>}
        </div>
      ))}
      <div className="hidden">{title}</div>
    </div>
  );
  return (
    <div>
      <PageHeader icon={<GitCompare className="h-4 w-4" />} title="Comparative Variant Workbench"
        subtitle="Side-by-side comparison of resolution, protein context, ClinVar assertions, retrieved pathways, disease context and therapies — each column from its own live analysis." />
      <form onSubmit={(e) => { e.preventDefault(); run(); }} className="grid gap-4 md:grid-cols-[1fr_1fr_auto]">
        {([['Primary variant (A)', a, setA, pa], ['Comparative variant (B)', b, setB, pb]] as const).map(([label, val, set, p]) => (
          <div key={label} className="rounded-2xl border border-slate-800 bg-panel p-4">
            <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-cyan-300">
              <span className="flex items-center gap-1.5"><Dna className="h-3.5 w-3.5" />{label}</span>
              {p?.root_id && <button type="button" onClick={() => onOpen(p)} className="flex items-center gap-1 font-medium normal-case tracking-normal text-cyan-300 hover:underline">Load in Atlas<ArrowRight className="h-3 w-3" /></button>}
            </div>
            <input value={val} onChange={(e) => (set as (v: string) => void)(e.target.value)} aria-label={label}
              className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm text-slate-100 focus:border-cyan-500/70 focus:outline-none" />
          </div>
        ))}
        <button type="submit" disabled={state.loading} className="flex items-center justify-center gap-2 self-stretch rounded-2xl bg-cyan-600 px-6 text-sm font-bold text-white hover:bg-cyan-500 disabled:opacity-50">{state.loading ? <Spinner /> : <><GitCompare className="h-4 w-4" />Compare</>}</button>
      </form>
      {state.loading && <p className="mt-3 text-xs text-slate-400">Querying 8 sources for both variants — first runs can take 20–40 s; cached runs are fast.</p>}
      {state.error && <p className="mt-3 text-sm text-rose-300">{state.error}</p>}
      {pa && pb && d && (
        <>
          <div className="mt-5 overflow-x-auto rounded-2xl border border-slate-800 bg-panel">
            <table className="w-full min-w-[720px] text-left">
              <thead><tr className="bg-slate-950/50 text-xs">
                <th className="w-48 px-4 py-3 font-bold uppercase tracking-wider text-slate-500">Attribute</th>
                <th className="px-4 py-3 font-mono font-bold text-cyan-300">{pa.query}</th>
                <th className="px-4 py-3 font-mono font-bold text-teal-300">{pb.query}</th>
              </tr></thead>
              <tbody>
                {row('Resolution', (p) => <span className="text-xs">{p.resolution.message}</span>)}
                {row('Gene & cytoband', (p) => p.overview?.gene ? `${p.overview.gene.description} (chr${p.overview.gene.chromosome}${p.overview.clinvar?.grch38?.band ?? ''})` : '—')}
                {row('UniProt & feature', (p) => <span><b className="font-mono text-cyan-300">{p.resolution.protein?.accession}</b> · {feature(p)}</span>)}
                {row('GRCh38 & cDNA', (p) => <span className="font-mono text-xs">{p.overview?.clinvar?.canonical_spdi ?? '—'}<br /><span className="text-slate-500">{p.overview?.vep?.primary?.hgvsc} ({p.overview?.vep?.primary?.hgvsp?.split(':').pop()})</span></span>)}
                {row('VEP consequence', (p) => p.overview?.vep?.primary ? `${p.overview.vep.primary.consequence_terms?.join(', ')} · SIFT ${p.overview.vep.primary.sift_prediction ?? '—'} · PolyPhen ${p.overview.vep.primary.polyphen_prediction ?? '—'}` : '—')}
                {row('ClinVar germline', (p) => <ClsCell cls={p.overview?.clinvar?.germline} />)}
                {row('ClinVar somatic impact', (p) => <ClsCell cls={p.overview?.clinvar?.somatic_clinical_impact} />)}
                {row('Curated mutant entity', (p) => p.graph.nodes.filter((n) => n.type === 'reactome_entity').map((n) => `${n.label} — ${n.attributes.pathway}`).join('; ') || 'none found (wild-type context)')}
                {row('Focus pathway', (p) => p.impact?.focus_pathway?.name ?? '—')}
                {row('CIViC evidence', (p) => `${p.overview?.civic?.total ?? 0} accepted items`)}
                {row('Conflicts detected', (p) => p.conflicts.map((c) => c.title).join('; ') || 'none')}
                {row('Graph', (p) => `${p.graph.nodes.length} nodes · ${p.graph.edges.length} relationships · ${Object.keys(p.graph.evidence).length} evidence records`)}
              </tbody>
            </table>
          </div>
          <div className="mt-5 space-y-5 rounded-2xl border border-slate-800 bg-panel p-5">
            <h3 className="flex items-center gap-2 text-sm font-bold text-white"><Layers className="h-4 w-4 text-cyan-400" />Pathway convergence & divergence (all Reactome pathways retrieved)</h3>
            <Diff title="pathways" dd={d.diff.pathways_all} />
            <h3 className="flex items-center gap-2 pt-2 text-sm font-bold text-white"><Pill_ />Drugs / therapies in graph</h3>
            <Diff title="drugs" dd={d.diff.drugs} />
            <h3 className="pt-2 text-sm font-bold text-white">Diseases / phenotypes in graph</h3>
            <Diff title="diseases" dd={d.diff.diseases} />
            <p className="text-xs text-slate-500">{d.note}</p>
          </div>
        </>
      )}
    </div>
  );
}

function Pill_() { return <Sparkles className="h-4 w-4 text-yellow-300" />; }

/* ------------------------------------------------------------------ snapshots */
export function SnapshotsView({ onOpen, notify }: { onOpen: (a: Analysis) => void; notify: (m: string, t?: 'ok' | 'warn' | 'err') => void }) {
  const [rows, setRows] = useState<any[] | null>(null);
  useEffect(() => { api.snapshots().then((r) => setRows(r.snapshots)).catch((e) => { setRows([]); notify(e.message, 'err'); }); }, [notify]);
  const importFile = async (file: File) => {
    try {
      const payload = JSON.parse(await file.text());
      onOpen(await api.importSnapshot(payload));
    } catch (e) { notify(`Import failed: ${(e as Error).message}`, 'err'); }
  };
  return (
    <div className="space-y-4">
      <Card title="Reproducible snapshots" subtitle="A snapshot freezes the retrieved records, retrieval timestamps, source releases and your workbench notes. Opening one does not contact external databases."
        actions={<label className="cursor-pointer rounded-lg border border-line px-3 py-1.5 text-xs text-slate-200 hover:border-cyan-400/50">Import analysis JSON<input type="file" accept="application/json" className="hidden" onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} /></label>}>
        {rows === null ? <Spinner label="Loading…" /> : rows.length === 0 ? <Empty>No snapshots yet. Use “Export & save → Save reproducible snapshot” in a workspace.</Empty> : (
          <table className="w-full text-left text-xs">
            <thead className="text-slate-400"><tr className="border-b border-line"><th className="py-1.5">Query</th><th>Data retrieved</th><th>Saved</th><th>Status</th><th /></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.id} className="border-b border-line/40">
                <td className="py-1.5 font-mono text-slate-100">{r.query}</td><td className="text-slate-400">{shortDate(r.original_created_at)}</td>
                <td className="text-slate-400">{shortDate(r.saved_at)}</td><td><Pill>{r.status}</Pill></td>
                <td className="text-right"><Button variant="outline" onClick={async () => { try { onOpen(await api.loadSnapshot(r.id)); } catch (e) { notify((e as Error).message, 'err'); } }}>Open</Button></td>
              </tr>))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------------ enrichment */
export function EnrichmentView() {
  const [text, setText] = useState('EGFR\nERBB2\nKRAS\nBRAF\nMAP2K1\nMAPK1\nPIK3CA\nPTEN\nAKT1');
  const [state, setState] = useState<{ loading: boolean; error?: string; data?: any }>({ loading: false });
  const run = async () => {
    setState({ loading: true });
    try { setState({ loading: false, data: await api.enrichment(text.split(/[\s,;]+/).filter(Boolean)) }); } catch (e) { setState({ loading: false, error: (e as Error).message }); }
  };
  return (
    <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
      <Card title="Gene-list pathway analysis" subtitle="Reactome Analysis Service over-representation test. For lists of genes (e.g. a panel or a set of altered genes) — never for a single variant.">
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={12} aria-label="Gene symbols or UniProt accessions, one per line"
          className="w-full rounded-lg border border-line bg-ink px-3 py-2 font-mono text-xs outline-none focus:border-cyan-400" />
        <Button variant="primary" className="mt-2 w-full" onClick={run} disabled={state.loading}>{state.loading ? <Spinner /> : 'Run Reactome analysis'}</Button>
        {state.error && <p className="mt-2 text-xs text-rose-300">{state.error}</p>}
      </Card>
      <Card title="Results" subtitle={state.data?.note}>
        {!state.data ? <Empty>Submit at least 3 identifiers.</Empty> : (
          <>
            <p className="mb-2 text-xs text-slate-400">{state.data.submitted} submitted · {state.data.pathways_found} pathways hit{state.data.identifiers_not_found ? ` · ${state.data.identifiers_not_found} identifiers not found` : ''} · retrieved {shortDate(state.data.retrieved_at)}</p>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-slate-400"><tr className="border-b border-line"><th className="py-1.5 pr-3">Pathway</th><th className="pr-3">Found / total</th><th className="pr-3">p-value</th><th className="pr-3">FDR</th><th /></tr></thead>
                <tbody>{state.data.pathways.map((p: any) => (
                  <tr key={p.stId} className="border-b border-line/40">
                    <td className="py-1.5 pr-3 text-slate-100">{p.name}{p.inDisease && <span className="ml-1 text-pink-300">(disease)</span>}</td>
                    <td className="pr-3 font-mono text-slate-300">{p.found}/{p.total}</td>
                    <td className="pr-3 font-mono text-slate-300">{p.pValue?.toExponential(2)}</td>
                    <td className="pr-3 font-mono text-slate-300">{p.fdr?.toExponential(2)}</td>
                    <td><ExtLink href={p.url}>Reactome ↗</ExtLink></td>
                  </tr>))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
