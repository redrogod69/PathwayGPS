import { useMemo, useState } from 'react';
import { api } from '../api';
import type { Analysis, PathResult, Synthesis, Workbench, WorkbenchNote } from '../types';
import { CATEGORY_STYLE, NODE_STYLE, RELATION_LABEL, SOURCE_LABEL, VERDICT_LABEL, shortDate } from '../lib/vocab';
import { PublicationRow } from './Evidence';
import { Button, Card, CategoryChip, Empty, ExtLink, Pill, SourceChip, Spinner } from './ui';

/* ------------------------------------------------------------------ path explanation */
export function PathPanel({ path, analysis, onClose, onSelectEdge }: { path: PathResult; analysis: Analysis; onClose: () => void; onSelectEdge: (id: string) => void }) {
  const v = path.verdict ? VERDICT_LABEL[path.verdict] : null;
  return (
    <div className="rounded-xl border border-yellow-300/30 bg-ink/95 p-3 shadow-2xl backdrop-blur">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-yellow-100">
          Explainable path
          {v && <span className={`rounded-full border px-2 py-0.5 text-[11px] ${v.tone}`}>{v.text}</span>}
        </div>
        <button onClick={onClose} className="text-xs text-slate-400 hover:text-white">✕ Clear</button>
      </div>
      {!path.found ? (
        <p className="mt-2 text-sm text-amber-200">{path.message}</p>
      ) : (
        <>
          <p className="mt-1 text-xs text-slate-400">{path.verdict_text} Ranked by fewest steps, then strongest evidence category — not a probability.</p>
          <ol className="mt-2 flex flex-wrap items-center gap-1 text-xs">
            {path.hops!.map((h, i) => (
              <li key={h.edge_id} className="flex items-center gap-1">
                {i === 0 && <span className="rounded bg-white/5 px-1.5 py-0.5 text-slate-100">{h.from_label}</span>}
                <button onClick={() => onSelectEdge(h.edge_id)} title={`${RELATION_LABEL[h.type] ?? h.type} · ${h.evidence_count} records, ${h.publication_count} publications${h.direction === 'reverse' ? ' · walked against the arrow' : ''}`}
                  className="rounded-full border px-2 py-0.5 hover:brightness-125" style={{ borderColor: `${CATEGORY_STYLE[h.category].color}88`, color: CATEGORY_STYLE[h.category].color }}>
                  {h.direction === 'reverse' ? '←' : ''}{h.label}{h.direction === 'reverse' ? '' : '→'} · {h.evidence_count}
                </button>
                <span className="rounded bg-white/5 px-1.5 py-0.5 text-slate-100">{h.to_label}</span>
              </li>
            ))}
          </ol>
          {(path.reverse_hops ?? 0) > 0 && <p className="mt-1 text-[11px] text-slate-500">← marks a step taken against the direction of the source relationship (e.g. a drug that targets the protein).</p>}
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ impact */
export function ImpactPanel({ analysis, onFocus }: { analysis: Analysis; onFocus: (id: string) => void }) {
  const imp = analysis.impact;
  if (!imp) return <Empty>No impact summary for unresolved input.</Empty>;
  const c = imp.counts;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        {[['Pathways', `${c.pathways_shown}/${c.pathways_total}`, 'drawn / retrieved'], ['Reactions', c.reactions_involving_protein, 'involving protein'], ['Interactors', c.interactors_total, 'IntAct partners'],
          ['Nodes', c.nodes, 'in graph'], ['Relationships', c.edges, 'typed edges'], ['Evidence', c.evidence_records, 'records'], ['Publications', Object.keys(analysis.publications).length, 'with metadata']].map(([k, v, s]) => (
          <div key={String(k)} className="rounded-xl border border-line bg-panel px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{k}</div>
            <div className="text-xl font-semibold text-cyan-200">{v}</div>
            <div className="text-[10px] text-slate-500">{s}</div>
          </div>
        ))}
      </div>
      {imp.focus_pathway && (
        <p className="text-xs text-slate-400">Downstream cascade drawn for <b className="text-slate-200">{imp.focus_pathway.name}</b> ({imp.focus_pathway.reactions_involving_protein} reactions involve the protein) — chosen because it {imp.focus_pathway.reason}.</p>
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Direct annotations" subtitle="Statements about the variant itself">
          {imp.direct.length ? (
            <ul className="space-y-2">
              {imp.direct.map((d, i) => (
                <li key={i} className="flex items-start justify-between gap-3 text-sm">
                  <div><div className="text-xs text-slate-400">{d.label} · <SourceChip source={d.source} /></div><div className="text-slate-100">{d.value}</div>{d.detail && <div className="text-[11px] text-slate-500">{d.detail}</div>}</div>
                  <CategoryChip category={d.category} small />
                </li>
              ))}
            </ul>
          ) : <Empty>No variant-level annotations.</Empty>}
        </Card>
        <Card title="Downstream entities with a supported route" subtitle="Reactome reactions and products reached from the variant">
          {imp.downstream.length ? (
            <ul className="max-h-80 space-y-1 overflow-auto">
              {imp.downstream.map((d) => (
                <li key={d.node_id}>
                  <button onClick={() => onFocus(d.node_id)} className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left text-xs hover:bg-white/5">
                    <span className="min-w-0 truncate text-slate-200"><span style={{ color: NODE_STYLE[d.type as keyof typeof NODE_STYLE]?.color }}>●</span> {d.label}{d.disease_event && <span className="ml-1 text-pink-300">(disease model)</span>}</span>
                    <span className="flex shrink-0 items-center gap-2"><span className="text-slate-500">{d.hops} steps</span><span className={`rounded-full border px-1.5 text-[10px] ${VERDICT_LABEL[d.verdict]?.tone}`}>{VERDICT_LABEL[d.verdict]?.text}</span></span>
                  </button>
                </li>
              ))}
            </ul>
          ) : <Empty>No downstream reactions were retrieved. Expand a pathway node to add some.</Empty>}
        </Card>
        <Card title="Disease and therapy context" subtitle="Variant-level evidence is listed before gene/protein-level associations">
          {imp.associations.length ? (
            <ul className="max-h-80 space-y-1 overflow-auto">
              {imp.associations.map((d) => (
                <li key={d.node_id}>
                  <button onClick={() => onFocus(d.node_id)} className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left text-xs hover:bg-white/5">
                    <span className="min-w-0 truncate text-slate-200"><span style={{ color: NODE_STYLE[d.type as keyof typeof NODE_STYLE]?.color }}>●</span> {d.label} <span className="text-slate-500">({(d.sources ?? []).map((s) => SOURCE_LABEL[s] ?? s).join(', ')})</span></span>
                    <Pill tone={d.level === 'variant-level' ? 'violet' : 'slate'}>{d.level}</Pill>
                  </button>
                </li>
              ))}
            </ul>
          ) : <Empty>No disease or drug records retrieved.</Empty>}
        </Card>
        <Card title="Questions to validate" subtitle="Generated from graph structure — hypotheses, not findings">
          {imp.hypotheses.length ? (
            <ul className="space-y-2">{imp.hypotheses.map((h, i) => (
              <li key={i} className="rounded-lg border border-pink-400/30 bg-pink-400/5 p-2 text-xs">
                <div className="flex items-center gap-2"><CategoryChip category="hypothesis" small /><span className="text-slate-500">basis: {h.basis}</span></div>
                <p className="mt-1 text-slate-200">{h.text}</p>
              </li>))}
            </ul>
          ) : <Empty>No structural hypotheses generated for this graph. Add your own in the Workbench.</Empty>}
        </Card>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ conflicts & gaps */
export function ConflictsPanel({ analysis }: { analysis: Analysis }) {
  return (
    <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-slate-100">Evidence disagreements ({analysis.conflicts.length})</h3>
        {analysis.conflicts.length === 0 && <Empty>No disagreements detected among the retrieved records.</Empty>}
        {analysis.conflicts.map((c, i) => (
          <Card key={i} title={c.title} subtitle={<span><SourceChip source={c.source} /> {c.summary}</span>}>
            {c.positions.length > 0 && (
              <div className="grid gap-2 md:grid-cols-2">
                {c.positions.map((pos, j) => (
                  <div key={j} className="rounded-lg border border-line bg-ink/40 p-2">
                    <div className="mb-1 flex items-center justify-between text-xs"><b className="text-slate-100">{pos.label}</b><span className="text-slate-500">{pos.count}</span></div>
                    <ul className="space-y-1">{pos.records.map((r) => (
                      <li key={r.id} className="text-[11px] text-slate-300"><ExtLink href={r.url}>{r.id}</ExtLink> {r.submitter && `· ${r.submitter}`} {r.classification && `· ${r.classification}`} {r.origin && <span className="text-slate-500">· {r.origin}</span>} {r.review_status && <span className="text-slate-500">· {r.review_status}</span>}
                        {r.conditions && r.conditions.length > 0 && <div className="text-slate-500">{r.conditions.filter(Boolean).join('; ')}</div>}
                      </li>))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
            <p className="mt-2 text-xs text-slate-400">{c.explanation}</p>
          </Card>
        ))}
      </div>
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-slate-100">Gaps and missing information ({analysis.gaps.length})</h3>
        {analysis.gaps.length === 0 && <Empty>No gaps detected.</Empty>}
        {analysis.gaps.map((g, i) => (
          <div key={i} className={`rounded-lg border p-3 text-xs ${g.kind === 'vus' ? 'border-amber-400/50 bg-amber-400/10 text-amber-100' : 'border-line bg-panel text-slate-300'}`}>
            <div className="mb-1 font-mono text-[10px] uppercase text-slate-500">{g.kind.replace(/_/g, ' ')}</div>{g.message}
          </div>
        ))}
        <Card title="Standing limitations">
          <ul className="list-disc space-y-1 pl-4 text-xs text-slate-400">{analysis.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
        </Card>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ literature */
export function LiteraturePanel({ analysis, onSelectEdge }: { analysis: Analysis; onSelectEdge: (id: string) => void }) {
  const [groupBy, setGroupBy] = useState<'relationship' | 'source' | 'year'>('relationship');
  const [q, setQ] = useState('');
  const [search, setSearch] = useState<{ loading: boolean; error?: string; data?: any }>({ loading: false });
  const gene = analysis.resolution.gene?.symbol;
  const change = analysis.resolution.protein_change?.short;
  const suggestions = [gene && change ? `${gene} ${change}` : null, gene ? `${gene} signaling mechanism` : null, gene && change ? `${gene} ${change} resistance` : null].filter(Boolean) as string[];
  const nodeById = useMemo(() => new Map(analysis.graph.nodes.map((n) => [n.id, n])), [analysis]);
  const groups = useMemo(() => {
    const out = new Map<string, { label: string; edgeId?: string; pmids: Set<string> }>();
    for (const e of analysis.graph.edges) {
      for (const evId of e.evidence) {
        const ev = analysis.graph.evidence[evId];
        if (!ev) continue;
        for (const pm of ev.publications) {
          let key: string; let label: string;
          if (groupBy === 'relationship') { key = e.id; label = `${nodeById.get(e.source)?.label} —${e.label}→ ${nodeById.get(e.target)?.label}`; }
          else if (groupBy === 'source') { key = `${ev.source}:${ev.evidence_type}`; label = `${SOURCE_LABEL[ev.source] ?? ev.source} · ${ev.evidence_type}`; }
          else { const y = analysis.publications[pm]?.year ?? 'unknown'; key = y; label = y; }
          if (!out.has(key)) out.set(key, { label, edgeId: groupBy === 'relationship' ? e.id : undefined, pmids: new Set() });
          out.get(key)!.pmids.add(pm);
        }
      }
    }
    return [...out.values()].sort((a, b) => (groupBy === 'year' ? b.label.localeCompare(a.label) : b.pmids.size - a.pmids.size));
  }, [analysis, groupBy, nodeById]);
  const runSearch = async (term: string) => {
    if (term.trim().length < 2) return;
    setQ(term);
    setSearch({ loading: true });
    try { setSearch({ loading: false, data: await api.literature(term) }); } catch (e) { setSearch({ loading: false, error: (e as Error).message }); }
  };
  const total = new Set(groups.flatMap((g) => [...g.pmids])).size;
  return (
    <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
      <Card title={`Evidence-linked literature (${total} publications)`} subtitle="Every paper here is cited by a specific source record on a specific relationship"
        actions={<div className="flex gap-1">{(['relationship', 'source', 'year'] as const).map((k) => <Button key={k} variant={groupBy === k ? 'primary' : 'ghost'} onClick={() => setGroupBy(k)}>{k}</Button>)}</div>}>
        {groups.length === 0 ? <Empty>No publications are attached to the retrieved records.</Empty> : (
          <div className="max-h-[70vh] space-y-4 overflow-auto pr-1">
            {groups.map((g) => (
              <div key={g.label}>
                <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                  <b className="text-slate-200">{g.label}</b>
                  {g.edgeId && <button className="shrink-0 text-cyan-300" onClick={() => onSelectEdge(g.edgeId!)}>open evidence →</button>}
                </div>
                <ul className="space-y-1.5">{[...g.pmids].slice(0, 12).map((pm) => <PublicationRow key={pm} pmid={pm} pub={analysis.publications[pm]} />)}</ul>
                {g.pmids.size > 12 && <div className="mt-1 text-[11px] text-slate-500">+{g.pmids.size - 12} more</div>}
              </div>
            ))}
          </div>
        )}
      </Card>
      <Card title="Literature discovery (PubMed)" subtitle="Keyword search — co-mention, not evidence of a relationship">
        <form onSubmit={(e) => { e.preventDefault(); runSearch(q); }} className="flex gap-2">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. EGFR L858R osimertinib" className="min-w-0 flex-1 rounded-lg border border-line bg-ink px-3 py-1.5 text-sm outline-none focus:border-cyan-400" />
          <Button type="submit" variant="primary">Search</Button>
        </form>
        <div className="mt-2 flex flex-wrap gap-1">{suggestions.map((s) => <button key={s} onClick={() => runSearch(s)} className="rounded-full border border-line px-2 py-0.5 text-[11px] text-slate-300 hover:border-cyan-400/50">{s}</button>)}</div>
        <div className="mt-3">
          {search.loading && <Spinner label="Searching PubMed…" />}
          {search.error && <p className="text-xs text-rose-300">{search.error}</p>}
          {search.data && (
            <>
              <p className="mb-2 text-[11px] text-slate-500">{search.data.count.toLocaleString()} results · showing {search.data.results.length} by relevance. {search.data.note}</p>
              <ul className="max-h-[55vh] space-y-1.5 overflow-auto">{search.data.results.map((r: any) => <PublicationRow key={r.pmid} pmid={r.pmid} pub={r} />)}</ul>
            </>
          )}
        </div>
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------------ synthesis */
export function SummaryPanel({ analysis, onEvidence, onAiResult }: { analysis: Analysis; onEvidence: (evidenceId: string) => void; onAiResult: (s: Synthesis) => void }) {
  const [state, setState] = useState<{ loading: boolean; message?: string }>({ loading: false });
  const det = analysis.synthesis;
  const ai = analysis.ai_synthesis;
  const run = async () => {
    setState({ loading: true });
    try {
      const res = await api.synthesis(analysis.analysis_id);
      if (res.mode === 'ai') { onAiResult(res); setState({ loading: false }); } else setState({ loading: false, message: res.message });
    } catch (e) { setState({ loading: false, message: (e as Error).message }); }
  };
  const Claims = ({ s }: { s: Synthesis }) => (
    <ul className="space-y-2">
      {s.claims.map((c, i) => (
        <li key={i} className="rounded-lg border border-line bg-ink/40 p-3 text-sm">
          <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[10px] uppercase tracking-wide text-slate-500">
            {c.kind === 'hypothesis' ? <CategoryChip category="hypothesis" small /> : <span>{c.kind}</span>}
          </div>
          <p className="text-slate-100">{c.text}</p>
          {c.evidence.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">{c.evidence.map((id) => {
              const ev = analysis.graph.evidence[id];
              return <button key={id} onClick={() => onEvidence(id)} className="rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-cyan-200 hover:border-cyan-400/60" title={ev?.statement}>{ev ? `${SOURCE_LABEL[ev.source] ?? ev.source}:${ev.record_id}`.slice(0, 38) : id}</button>;
            })}</div>
          )}
        </li>
      ))}
    </ul>
  );
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card title="Evidence-linked summary" subtitle={det?.disclaimer}>
        {det && det.claims.length ? <Claims s={det} /> : <Empty>Nothing to summarise.</Empty>}
      </Card>
      <Card title="AI-assisted interpretation (optional)" subtitle={analysis.ai.enabled ? `Server-side · ${analysis.ai.model} · grounded in the evidence ledger` : 'Disabled — no model credentials on the server'}
        actions={<Button variant="primary" disabled={!analysis.ai.enabled || state.loading || !!analysis.snapshot} onClick={run}>{state.loading ? <Spinner /> : '✦'} Generate</Button>}>
        {ai && ai.claims ? (
          <>
            <Claims s={ai} />
            {ai.follow_up_searches && ai.follow_up_searches.length > 0 && <div className="mt-3 text-xs text-slate-400">Suggested searches: {ai.follow_up_searches.join(' · ')}</div>}
            <p className="mt-2 text-[11px] text-slate-500">{ai.disclaimer}</p>
          </>
        ) : (
          <div className="space-y-2 text-xs text-slate-400">
            {state.message && <p className="text-amber-200">{state.message}</p>}
            <p>When enabled, the model receives only the retrieved evidence ledger. Every claim must cite evidence-record IDs; the server discards claims that cite unknown IDs, and speculative statements are labelled as hypotheses.</p>
            {!analysis.ai.enabled && <p>To enable: <code className="rounded bg-ink px-1">pip install anthropic</code> in the backend environment and set <code className="rounded bg-ink px-1">ANTHROPIC_API_KEY</code> in <code className="rounded bg-ink px-1">.env</code>, then restart the API.</p>}
          </div>
        )}
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------------ sources */
export function SourcesPanel({ analysis }: { analysis: Analysis }) {
  const tone = (s: string) => (s === 'ok' ? 'teal' : s === 'partial' ? 'amber' : s === 'failed' ? 'rose' : 'slate') as any;
  return (
    <Card title="Data-source status for this analysis" subtitle={`Retrieved ${shortDate(analysis.created_at)}${analysis.snapshot ? ' · frozen snapshot' : ''}. Each source is reported separately — partial results are shown as partial.`}>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-slate-400"><tr className="border-b border-line"><th className="py-2 pr-3">Source</th><th className="pr-3">Status</th><th className="pr-3">Release</th><th className="pr-3">Calls</th><th className="pr-3">From cache</th><th className="pr-3">Last retrieved</th><th className="pr-3">Licence</th><th>Notes / errors</th></tr></thead>
          <tbody>
            {analysis.sources.map((s) => (
              <tr key={s.source} className="border-b border-line/40 align-top">
                <td className="py-2 pr-3"><ExtLink href={s.homepage}>{s.name}</ExtLink></td>
                <td className="pr-3"><Pill tone={tone(s.status)}>{s.status}</Pill></td>
                <td className="pr-3 font-mono text-slate-300">{s.release ?? '—'}</td>
                <td className="pr-3 text-slate-300">{s.calls}{s.failed_calls ? <span className="text-rose-300"> ({s.failed_calls} failed)</span> : ''}</td>
                <td className="pr-3 text-slate-400">{s.from_cache}{s.stale_cache ? <span className="text-amber-300"> ({s.stale_cache} stale)</span> : ''}</td>
                <td className="pr-3 text-slate-400">{shortDate(s.last_retrieved_at)}</td>
                <td className="pr-3 text-slate-400">{s.license}</td>
                <td className="text-slate-400">{[...s.errors, ...s.notes].join(' · ') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] text-slate-500">KEGG is intentionally not integrated: its API and data require a licence for commercial use or redistribution. Gene nodes link out to KEGG instead.</p>
    </Card>
  );
}

/* ------------------------------------------------------------------ workbench */
export function WorkbenchPanel({ analysis, workbench, onChange, onFocus }: { analysis: Analysis; workbench: Workbench; onChange: (w: Workbench) => void; onFocus: (id: string) => void }) {
  const [filter, setFilter] = useState<'all' | WorkbenchNote['kind']>('all');
  const notes = workbench.notes.filter((n) => filter === 'all' || n.kind === filter);
  const nodeById = new Map(analysis.graph.nodes.map((n) => [n.id, n]));
  const update = (id: string, patch: Partial<WorkbenchNote>) => onChange({ ...workbench, notes: workbench.notes.map((n) => (n.id === id ? { ...n, ...patch } : n)) });
  return (
    <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
      <Card title="Hypothesis workbench" subtitle="Private notes stored in this browser only. Included in reports and snapshots you export."
        actions={<div className="flex gap-1">{(['all', 'observation', 'question', 'hypothesis'] as const).map((k) => <Button key={k} variant={filter === k ? 'primary' : 'ghost'} onClick={() => setFilter(k)}>{k}</Button>)}</div>}>
        {notes.length === 0 ? <Empty>No notes yet. Select a node or relationship in the Network view and choose “＋ Note”.</Empty> : (
          <ul className="space-y-2">
            {notes.map((n) => (
              <li key={n.id} className="rounded-lg border border-line bg-ink/40 p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <select value={n.kind} onChange={(e) => update(n.id, { kind: e.target.value as WorkbenchNote['kind'] })} className="rounded border border-line bg-ink px-1 py-0.5 text-xs text-slate-200">
                    <option value="observation">Observation (evidence-backed)</option>
                    <option value="question">Open question</option>
                    <option value="hypothesis">Hypothesis (needs validation)</option>
                  </select>
                  <button className="text-cyan-300 hover:underline" onClick={() => onFocus(n.target_id)}>{n.target_label}</button>
                  <span className="text-slate-500">{shortDate(n.created)}</span>
                  <button className="ml-auto text-slate-500 hover:text-rose-300" onClick={() => onChange({ ...workbench, notes: workbench.notes.filter((x) => x.id !== n.id) })}>delete</button>
                </div>
                <textarea value={n.text} onChange={(e) => update(n.id, { text: e.target.value })} rows={2} placeholder="Write your note…"
                  className="mt-2 w-full rounded-md border border-line bg-ink px-2 py-1.5 text-sm text-slate-100 outline-none focus:border-cyan-400" />
                {n.kind === 'observation' && n.evidence_ids.length === 0 && <p className="text-[11px] text-amber-200">Observations should cite evidence — attach this note to a relationship to link its records, or mark it as a question.</p>}
                {n.evidence_ids.length > 0 && <p className="text-[11px] text-slate-500">Linked evidence: {n.evidence_ids.length} record(s) on the relationship.</p>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title={`Marked entities (${workbench.marked.length})`} subtitle="Highlighted with a gold halo in the network">
        {workbench.marked.length === 0 ? <Empty>Use “☆ Mark” on a node to collect entities of interest.</Empty> : (
          <ul className="space-y-1">{workbench.marked.map((id) => {
            const n = nodeById.get(id);
            return (
              <li key={id} className="flex items-center justify-between text-xs">
                <button className="text-slate-200 hover:text-cyan-200" onClick={() => onFocus(id)}><span style={{ color: n ? NODE_STYLE[n.type].color : '#64748b' }}>●</span> {n?.label ?? id}</button>
                <button className="text-slate-500 hover:text-rose-300" onClick={() => onChange({ ...workbench, marked: workbench.marked.filter((x) => x !== id) })}>remove</button>
              </li>);
          })}</ul>
        )}
      </Card>
    </div>
  );
}
