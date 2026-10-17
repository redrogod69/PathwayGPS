import { useEffect, useRef, useState } from 'react';
import { BookOpen, Bookmark, Database, Dna, Download, GitBranch, Sparkles } from 'lucide-react';
import { api } from '../api';
import type { Analysis, PathResult, Synthesis, Workbench } from '../types';
import type { GraphHandle } from './GraphCanvas';
import MechanismTracer from './MechanismTracer';
import NetworkView from './NetworkView';
import Overview from './Overview';
import { ConflictsPanel, ImpactPanel, LiteraturePanel, SourcesPanel, SummaryPanel, WorkbenchPanel } from './Panels';
import ResolutionBanner from './Resolution';
import { PageHeader, ViewId } from './Shell';
import { Empty, Pill, Spinner } from './ui';
import { SnapshotsView } from './Views';

function storageKey(a: Analysis) {
  return `pathwaygps:workbench:${(a.resolution.clinvar_variation_id ?? a.root_id ?? a.query).toLowerCase()}`;
}
function loadWorkbench(a: Analysis): Workbench {
  if (a.snapshot?.workbench?.notes) return a.snapshot.workbench as Workbench;
  try {
    const raw = localStorage.getItem(storageKey(a));
    if (raw) return JSON.parse(raw);
  } catch { /* storage unavailable */ }
  return { notes: [], marked: [] };
}

interface Props {
  initial: Analysis;
  view: ViewId;
  onNavigate: (v: ViewId) => void;
  onQuery: (q: string) => void;
  onOpen: (a: Analysis) => void;
  onAnalysisChange: (a: Analysis) => void;
  onAssistant: () => void;
  evidenceFocus: { id: string; n: number } | null;
  notify: (msg: string, tone?: 'ok' | 'warn' | 'err') => void;
}

export default function Workspace({ initial, view, onNavigate, onQuery, onOpen, onAnalysisChange, onAssistant, evidenceFocus, notify }: Props) {
  const [analysis, setAnalysisState] = useState<Analysis>(initial);
  const setAnalysis = (a: Analysis) => { setAnalysisState(a); onAnalysisChange(a); };
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [path, setPath] = useState<PathResult | null>(null);
  const [expanding, setExpanding] = useState<string | null>(null);
  const [flashIds, setFlashIds] = useState<string[]>([]);
  const [workbench, setWorkbench] = useState<Workbench>(() => loadWorkbench(initial));
  const [evTab, setEvTab] = useState<'literature' | 'conflicts' | 'summary'>('literature');
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const graphRef = useRef<GraphHandle>(null);

  useEffect(() => {
    setAnalysisState(initial); setSelectedId(null); setPath(null); setWorkbench(loadWorkbench(initial));
  }, [initial]);
  useEffect(() => {
    if (analysis.snapshot) return;
    try { localStorage.setItem(storageKey(analysis), JSON.stringify(workbench)); } catch { /* ignore */ }
  }, [workbench, analysis]);
  useEffect(() => {
    if (!evidenceFocus) return;
    const edge = analysis.graph.edges.find((e) => e.evidence.includes(evidenceFocus.id));
    if (edge) { onNavigate('atlas'); setSelectedId(edge.id); setPath(null); }
  }, [evidenceFocus]); // eslint-disable-line react-hooks/exhaustive-deps

  const resolved = Boolean(analysis.root_id);
  const root = analysis.graph.nodes.find((n) => n.id === analysis.root_id);
  const expand = async (nodeId: string, action: string) => {
    setExpanding(`${nodeId}:${action}`);
    try {
      const res = await api.expand(analysis.analysis_id, nodeId, action);
      setAnalysis(res.analysis);
      setFlashIds(res.added_nodes);
      setTimeout(() => setFlashIds([]), 4000);
      notify(res.message, res.added_nodes.length || res.added_edges.length ? 'ok' : 'warn');
    } catch (e) { notify((e as Error).message, 'err'); } finally { setExpanding(null); }
  };
  const explain = async (nodeId: string) => {
    try { setPath(await api.path(analysis.analysis_id, nodeId)); onNavigate('atlas'); } catch (e) { notify((e as Error).message, 'err'); }
  };
  const focus = (id: string) => { onNavigate('atlas'); setSelectedId(id); setTimeout(() => graphRef.current?.center(id), 120); };
  const focusEdge = (id: string) => { onNavigate('atlas'); setSelectedId(id); };
  const toggleMark = (id: string) => setWorkbench((w) => ({ ...w, marked: w.marked.includes(id) ? w.marked.filter((x) => x !== id) : [...w.marked, id] }));
  const addNote = (targetId: string, label: string, evidenceIds: string[]) => {
    setWorkbench((w) => ({ ...w, notes: [{ id: crypto.randomUUID?.() ?? String(Date.now()), target_id: targetId, target_label: label, kind: evidenceIds.length ? 'observation' : 'question', text: '', evidence_ids: evidenceIds, created: new Date().toISOString() }, ...w.notes] }));
    onNavigate('saved');
    notify('Note added to the hypothesis workbench.', 'ok');
  };
  const exportAs = async (kind: string) => {
    setMenu(false); setBusy(kind);
    try {
      if (kind === 'md' || kind === 'html' || kind === 'json') await api.report(analysis.analysis_id, kind, workbench);
      else if (kind === 'graph' || kind === 'cytoscape') await api.exportGraph(analysis.analysis_id, kind === 'graph' ? 'json' : 'cytoscape');
      else if (kind === 'png') {
        const uri = graphRef.current?.png();
        if (uri) { const a = document.createElement('a'); a.href = uri; a.download = `PathwayGPS_${analysis.query.replace(/\W+/g, '_')}.png`; a.click(); }
        else notify('Open the Biological Atlas to export an image.', 'warn');
      } else if (kind === 'snapshot') {
        const snap = await api.snapshot(analysis.analysis_id, workbench);
        notify(`Snapshot ${snap.id} saved with retrieval timestamps — see Saved Analyses.`, 'ok');
      }
    } catch (e) { notify((e as Error).message, 'err'); } finally { setBusy(null); }
  };

  const ExportMenu = (
    <div className="relative">
      <button onClick={() => setMenu(!menu)} className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-900/80 px-3 py-1.5 text-xs font-semibold text-slate-200 hover:border-cyan-500/50">
        {busy ? <Spinner /> : <Download className="h-3.5 w-3.5" />} Export & save
      </button>
      {menu && (
        <div className="absolute right-0 z-40 mt-1 w-64 rounded-xl border border-slate-800 bg-panel p-1 shadow-2xl">
          {[['md', 'Research report (Markdown)'], ['html', 'Research report (HTML, printable)'], ['json', 'Full analysis (JSON)'], ['graph', 'Graph + evidence (JSON)'],
            ['cytoscape', 'Graph (Cytoscape.js JSON)'], ['png', 'Network image (PNG)'], ['snapshot', analysis.snapshot ? 'Save snapshot (n/a for snapshots)' : 'Save reproducible snapshot']].map(([k, label]) => (
            <button key={k} disabled={k === 'snapshot' && !!analysis.snapshot} onClick={() => exportAs(k)} className="block w-full rounded-lg px-3 py-1.5 text-left text-xs text-slate-200 hover:bg-white/5 disabled:opacity-40">{label}</button>
          ))}
        </div>
      )}
    </div>
  );
  const AiButton = (
    <button onClick={onAssistant} className="flex items-center gap-1.5 rounded-xl border border-cyan-500/40 bg-cyan-500/10 px-3 py-1.5 text-xs font-bold text-cyan-300 hover:bg-cyan-500/20">
      <Sparkles className="h-3.5 w-3.5" /> Ask the assistant
    </button>
  );
  const failed = analysis.sources.filter((s) => s.status !== 'ok');
  const sourcePill = failed.length > 0 && <button onClick={() => onNavigate('sources')}><Pill tone="amber">{failed.length} source{failed.length > 1 ? 's' : ''} partial/failed</Pill></button>;

  if (!resolved && !['sources', 'saved'].includes(view)) {
    return (
      <div className="space-y-4">
        <ResolutionBanner analysis={analysis} onQuery={onQuery} />
        <Empty>No graph was built because the input was not resolved — see the explanation above, or choose a suggested interpretation.</Empty>
      </div>
    );
  }

  return (
    <div>
      {view === 'explorer' && (
        <>
          <PageHeader icon={<Dna className="h-4 w-4" />} title="Variant Explorer" chip={root?.label}
            subtitle="Resolution, clinical classifications, predicted consequence, protein context and the downstream impact summary for the active variant."
            actions={<>{sourcePill}{AiButton}{ExportMenu}</>} />
          <div className="space-y-5">
            <ResolutionBanner analysis={analysis} onQuery={onQuery} />
            <Overview analysis={analysis} />
            <div>
              <h2 className="mb-3 text-sm font-bold uppercase tracking-wider text-slate-400">Pathway impact summary</h2>
              <ImpactPanel analysis={analysis} onFocus={focus} />
            </div>
          </div>
        </>
      )}
      {view === 'atlas' && (
        <>
          <PageHeader icon={<GitBranch className="h-4 w-4" />} title="Biological Atlas" chip={root?.label}
            subtitle="Interactive knowledge graph. Click a node for its biology, a relationship for its evidence ledger; double-click to expand from Reactome."
            actions={<>{sourcePill}{AiButton}{ExportMenu}</>} />
          {analysis.snapshot && <div className="mb-3 rounded-lg border border-violet-400/40 bg-violet-400/10 px-3 py-2 text-xs text-violet-100">{analysis.snapshot.statement} <button className="ml-2 text-cyan-300 underline" onClick={() => onQuery(analysis.query)}>Re-run with live data</button></div>}
          <NetworkView analysis={analysis} selectedId={selectedId} setSelectedId={setSelectedId} path={path} setPath={setPath} expanding={expanding} flashIds={flashIds}
            marked={workbench.marked} onExpand={expand} onExplainPath={explain} onToggleMark={toggleMark} onAddNote={addNote} graphRef={graphRef} />
        </>
      )}
      {view === 'tracer' && <MechanismTracer analysis={analysis} onIlluminate={(r) => { setPath(r); setSelectedId(null); onNavigate('atlas'); }} />}
      {view === 'evidence' && (
        <>
          <PageHeader icon={<BookOpen className="h-4 w-4" />} title="Evidence Library" chip={`${Object.keys(analysis.publications).length} publications`}
            subtitle="Literature linked to specific relationships, evidence disagreements and gaps, and the evidence-cited summary."
            actions={<>{AiButton}{ExportMenu}</>} />
          <div className="mb-4 flex gap-1 rounded-xl border border-slate-800 bg-panel p-1 text-sm" role="tablist">
            {([['literature', 'Literature'], ['conflicts', `Conflicts & gaps (${analysis.conflicts.length + analysis.gaps.length})`], ['summary', 'Summary']] as const).map(([k, l]) => (
              <button key={k} role="tab" aria-selected={evTab === k} onClick={() => setEvTab(k)} className={`rounded-lg px-3 py-1.5 ${evTab === k ? 'bg-cyan-500/15 font-semibold text-cyan-200' : 'text-slate-400 hover:text-slate-200'}`}>{l}</button>
            ))}
          </div>
          {evTab === 'literature' && <LiteraturePanel analysis={analysis} onSelectEdge={focusEdge} />}
          {evTab === 'conflicts' && <ConflictsPanel analysis={analysis} />}
          {evTab === 'summary' && <SummaryPanel analysis={analysis} onEvidence={(id) => { const e = analysis.graph.edges.find((x) => x.evidence.includes(id)); if (e) focusEdge(e.id); }} onAiResult={(s: Synthesis) => setAnalysis({ ...analysis, ai_synthesis: s })} />}
        </>
      )}
      {view === 'saved' && (
        <>
          <PageHeader icon={<Bookmark className="h-4 w-4" />} title="Saved Analyses & Workbench" subtitle="Reproducible snapshots and your private hypothesis notes for the active variant." actions={resolved ? ExportMenu : undefined} />
          {resolved && <div className="mb-6"><WorkbenchPanel analysis={analysis} workbench={workbench} onChange={setWorkbench} onFocus={focus} /></div>}
          <SnapshotsView onOpen={onOpen} notify={notify} />
        </>
      )}
      {view === 'sources' && (
        <>
          <PageHeader icon={<Database className="h-4 w-4" />} title="Data Sources" subtitle="Per-source status for the active analysis — partial results are shown as partial, never as complete." />
          <SourcesPanel analysis={analysis} />
        </>
      )}
    </div>
  );
}
