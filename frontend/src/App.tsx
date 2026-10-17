import { useCallback, useEffect, useRef, useState } from 'react';
import { Database, FlaskConical } from 'lucide-react';
import { api, HOSTED_API, STATIC_DEMO } from './api';
import type { Analysis } from './types';
import AssistantModal from './components/AssistantModal';
import { Navbar, PageHeader, Sidebar, ViewId } from './components/Shell';
import { CompareView, EnrichmentView, FALLBACK_EXAMPLES, Landing, SnapshotsView } from './components/Views';
import Workspace from './components/Workspace';

type Toast = { id: number; msg: string; tone: 'ok' | 'warn' | 'err' };

const LOADING_STEPS = [
  'Detecting input type',
  'Resolving gene (Ensembl) and protein (UniProt)',
  'Looking up ClinVar records and submissions',
  'Annotating consequence with Ensembl VEP',
  'Mapping Reactome pathways, reactions and mutant entities',
  'Collecting IntAct, Open Targets and CIViC evidence',
  'Fetching PubMed metadata for cited records',
];
const ANALYSIS_VIEWS: ViewId[] = ['explorer', 'atlas', 'tracer', 'evidence'];

function loadRecent(): string[] {
  try { return JSON.parse(localStorage.getItem('pathwaygps:recent') || '[]'); } catch { return []; }
}

export default function App() {
  const [view, setView] = useState<ViewId>('overview');
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [workspaceSeed, setWorkspaceSeed] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [examples, setExamples] = useState(FALLBACK_EXAMPLES);
  const [health, setHealth] = useState<any>(null);
  const [assistant, setAssistant] = useState(false);
  const [evidenceFocus, setEvidenceFocus] = useState<{ id: string; n: number } | null>(null);
  const [recent, setRecent] = useState<string[]>(loadRecent);
  const reqId = useRef(0);
  const [staticMode, setStaticMode] = useState(STATIC_DEMO);
  useEffect(() => { const f = () => setStaticMode(true); window.addEventListener('pathwaygps:static-fallback', f); return () => window.removeEventListener('pathwaygps:static-fallback', f); }, []);

  const notify = useCallback((msg: string, tone: Toast['tone'] = 'ok') => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);

  useEffect(() => {
    api.examples().then((r) => setExamples(r.examples)).catch(() => undefined);
    api.health().then(setHealth).catch(() => setHealth({ status: 'down' }));
    const q = new URLSearchParams(window.location.search).get('q');
    if (q) run(q);
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'j') { e.preventDefault(); setAssistant((v) => !v); } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!loading) return;
    setStep(0);
    const t = setInterval(() => setStep((s) => Math.min(s + 1, LOADING_STEPS.length - 1)), 2200);
    return () => clearInterval(t);
  }, [loading]);

  const open = (a: Analysis, target?: ViewId) => {
    setAnalysis(a); setWorkspaceSeed(a); setError(null);
    setView(target ?? (a.root_id ? (ANALYSIS_VIEWS.includes(view) ? view : 'explorer') : 'explorer'));
  };

  const run = async (q: string) => {
    const query = q.trim();
    if (!query) return;
    const id = ++reqId.current;
    setLoading(query); setError(null);
    if (!ANALYSIS_VIEWS.includes(view)) setView('explorer');
    try {
      const result = await api.analyze(query);
      if (id !== reqId.current) return;
      open(result, ANALYSIS_VIEWS.includes(view) ? view : 'explorer');
      const next = [query, ...loadRecent().filter((r) => r.toLowerCase() !== query.toLowerCase())].slice(0, 6);
      setRecent(next);
      try { localStorage.setItem('pathwaygps:recent', JSON.stringify(next)); } catch { /* ignore */ }
      const url = new URL(window.location.href);
      url.searchParams.set('q', query);
      window.history.replaceState(null, '', url.toString());
    } catch (e) {
      if (id === reqId.current) setError((e as Error).message);
    } finally {
      if (id === reqId.current) setLoading(null);
    }
  };

  const goHome = () => { setView('overview'); setError(null); };
  const badges = analysis?.root_id ? { evidence: analysis.conflicts.length || undefined } : {};
  const workspaceViews: ViewId[] = analysis ? [...ANALYSIS_VIEWS, 'saved', 'sources'] : [];

  let content: React.ReactNode;
  if (loading) {
    content = (
      <div className="mx-auto mt-16 max-w-xl rounded-2xl border border-slate-800 bg-panel p-6" role="status" aria-live="polite">
        <div className="flex items-center gap-3">
          <span className="h-5 w-5 animate-spin rounded-full border-2 border-cyan-400/30 border-t-cyan-300" />
          <div><div className="text-sm text-slate-400">Navigating</div><div className="font-mono text-lg text-white">{loading}</div></div>
        </div>
        <ol className="mt-5 space-y-1.5">
          {LOADING_STEPS.map((s, i) => (
            <li key={s} className={`flex items-center gap-2 text-sm ${i < step ? 'text-slate-500' : i === step ? 'text-cyan-200' : 'text-slate-600'}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${i < step ? 'bg-teal-400' : i === step ? 'animate-pulse bg-cyan-300' : 'bg-slate-700'}`} />{s}
            </li>
          ))}
        </ol>
        <p className="mt-4 text-xs text-slate-500">Live queries to public databases; a variant's first run can take 10–40 s, then it is cached. (Step list is indicative.)</p>
      </div>
    );
  } else if (error && ANALYSIS_VIEWS.includes(view)) {
    content = (
      <div className="mx-auto mt-16 max-w-xl rounded-xl border border-rose-400/40 bg-rose-400/10 p-5 text-sm text-rose-100">
        <b>Request failed.</b> {error}
        <div className="mt-3"><button className="rounded-md border border-rose-300/40 px-3 py-1 text-xs" onClick={() => setError(null)}>Dismiss</button></div>
      </div>
    );
  } else if (view === 'overview') {
    content = <Landing onQuery={run} examples={examples} recent={recent} />;
  } else if (view === 'compare') {
    content = <CompareView onOpen={(a) => open(a, 'atlas')} />;
  } else if (view === 'enrichment') {
    content = <><PageHeader icon={<FlaskConical className="h-4 w-4" />} title="Gene-list Pathway Analysis" chip="Reactome Analysis Service" subtitle="Over-representation analysis for lists of genes — never for a single variant." /><EnrichmentView /></>;
  } else if (workspaceViews.includes(view) && workspaceSeed) {
    content = <Workspace initial={workspaceSeed} view={view} onNavigate={setView} onQuery={run} onOpen={(a) => open(a)} onAnalysisChange={setAnalysis}
      onAssistant={() => setAssistant(true)} evidenceFocus={evidenceFocus} notify={notify} />;
  } else if (view === 'saved') {
    content = <SnapshotsView onOpen={(a) => open(a)} notify={notify} />;
  } else {
    content = (
      <div className="mx-auto mt-16 max-w-lg rounded-2xl border border-slate-800 bg-panel p-6 text-center text-sm text-slate-400">
        <Database className="mx-auto mb-3 h-6 w-6 text-cyan-400" />Analyse a variant first — this view shows results for the active analysis.
        <div className="mt-4"><button onClick={goHome} className="rounded-lg bg-cyan-600 px-4 py-1.5 text-xs font-bold text-white">Go to Overview</button></div>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-ink text-slate-100">
      <Navbar analysis={analysis} onQuery={run} onHome={goHome} onAssistant={() => setAssistant(true)} onSources={() => setView('sources')} health={health} busy={!!loading} />
      <div className="flex min-h-0 flex-1">
        <Sidebar view={view} onSelect={setView} analysis={analysis} badges={badges} />
        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1600px] px-4 py-6 md:px-6">
            {staticMode && (
              <div className="mb-4 rounded-xl border border-violet-500/30 bg-violet-500/10 px-4 py-2.5 text-xs text-violet-100">
                <b>{HOSTED_API ? 'Live backend unreachable — showing the static demo.' : 'Static demo (GitHub Pages).'}</b> Showing real analyses recorded from ClinVar, Ensembl VEP, UniProt, Reactome, IntAct, Open Targets, CIViC and PubMed for the demo variants
                ({examples.map((e) => e.label).join(', ')}). Paths, routes and the evidence assistant run in your browser. Live querying of any variant, node expansion, reports and snapshots need the local backend — see the{' '}
                <a className="text-cyan-300 underline" href="https://github.com/redrogod69/PathwayGPS#run-locally" target="_blank" rel="noreferrer">README</a>.
              </div>
            )}
            {health?.status === 'down' && (
              <div className="mb-4 rounded-lg border border-rose-400/40 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">
                The PathwayGPS API is not reachable. Start it with <code className="rounded bg-ink px-1">python -m uvicorn app.main:app --port 8000</code> in <code>backend/</code>.
              </div>
            )}
            {content}
            <footer className="mt-10 border-t border-slate-800/80 pt-4 text-[11px] text-slate-600">
              PathwayGPS is a research and exploration tool — not a clinically validated diagnostic or prescribing system. Data: ClinVar & PubMed (NCBI), Ensembl, UniProt (CC BY 4.0), Reactome (CC0), IntAct (CC BY 4.0), Open Targets (CC0), CIViC (CC0).
              {health?.mode === 'offline_replay' && <span className="ml-1 text-violet-300">Offline replay mode: only cached responses are used.</span>}
              <span className="ml-1">Press ⌘/Ctrl + J for the AI assistant.</span>
            </footer>
          </div>
        </main>
      </div>
      {assistant && <AssistantModal analysis={analysis} onClose={() => setAssistant(false)} onEvidence={(id) => { setAssistant(false); setEvidenceFocus({ id, n: Date.now() }); }} />}
      <div className="fixed bottom-4 right-4 z-50 space-y-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`max-w-sm rounded-lg border px-3 py-2 text-sm shadow-xl ${t.tone === 'ok' ? 'border-teal-400/40 bg-teal-950 text-teal-100' : t.tone === 'warn' ? 'border-amber-400/40 bg-amber-950 text-amber-100' : 'border-rose-400/40 bg-rose-950 text-rose-100'}`}>{t.msg}</div>
        ))}
      </div>
    </div>
  );
}
