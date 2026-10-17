import type { Analysis, PathResult, Synthesis, Workbench } from './types';
import { call, onEngineStatus } from './lib/pyEngine';

/**
 * Two runtimes, same Python pipeline:
 *  - default: the FastAPI backend (local / Docker)
 *  - VITE_ENGINE=browser (GitHub Pages): backend/app runs in the browser under Pyodide and
 *    queries the public databases directly. No server and no recorded data.
 */
export const BROWSER_ENGINE = import.meta.env.VITE_ENGINE === 'browser';
export { onEngineStatus };

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(url: string, init?: RequestInit, timeoutMs = 180_000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...init, signal: ctrl.signal });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      } catch { /* not JSON */ }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if ((e as Error).name === 'AbortError') throw new ApiError(0, 'The request timed out. Public databases can be slow; please retry.');
    throw new ApiError(0, 'Cannot reach the PathwayGPS backend. Is the API server running on port 8000?');
  } finally {
    clearTimeout(timer);
  }
}

const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

async function download(url: string, body: unknown, fallbackName: string) {
  const res = await fetch(url, body === undefined ? undefined : json(body));
  if (!res.ok) throw new ApiError(res.status, `Export failed (${res.status})`);
  const blob = await res.blob();
  const dispo = res.headers.get('Content-Disposition') || '';
  const name = /filename="([^"]+)"/.exec(dispo)?.[1] ?? fallbackName;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

const liveApi = {
  health: () => request<any>('/api/health', undefined, 10_000),
  examples: () => request<{ examples: { query: string; label: string; note: string }[] }>('/api/examples', undefined, 10_000),
  analyze: (query: string) => request<Analysis>('/api/analyze', json({ query })),
  expand: (id: string, node_id: string, action: string) =>
    request<{ analysis: Analysis; added_nodes: string[]; added_edges: string[]; message: string }>(`/api/analysis/${id}/expand`, json({ node_id, action })),
  path: (id: string, target: string, source?: string) =>
    request<PathResult>(`/api/analysis/${id}/path?target=${encodeURIComponent(target)}${source ? `&source=${encodeURIComponent(source)}` : ''}`),
  routes: (id: string, target: string, k = 3) =>
    request<{ source: string; target: string; routes: (PathResult & { rank: number; cost: number; evidence: Record<string, string[]> })[]; message?: string; ranking: string }>(`/api/analysis/${id}/routes?target=${encodeURIComponent(target)}&k=${k}`),
  chat: (id: string, messages: { role: string; content: string }[]) =>
    request<{ mode: string; answer: string; citations: string[]; follow_up?: string[]; notice?: string; model?: string }>(`/api/analysis/${id}/chat`, json({ messages }), 180_000),
  synthesis: (id: string) => request<Synthesis & { mode: string }>(`/api/analysis/${id}/synthesis`, { method: 'POST' }),
  abstract: (pmid: string) => request<{ pmid: string; title?: string; sections: { label?: string; text: string }[]; mesh: string[]; pubtypes: string[]; copyright?: string; url: string }>(`/api/publications/${pmid}/abstract`),
  literature: (q: string) => request<{ query: string; count: number; results: any[]; note: string; query_translation?: string }>(`/api/literature/search?q=${encodeURIComponent(q)}`),
  compare: (a: string, b: string) => request<{ a: Analysis; b: Analysis; diff: any; note: string }>('/api/compare', json({ a, b }), 300_000),
  enrichment: (identifiers: string[]) => request<any>('/api/enrichment', json({ identifiers })),
  snapshot: (id: string, workbench: Workbench) => request<any>(`/api/analysis/${id}/snapshot`, json({ workbench })),
  snapshots: () => request<{ snapshots: any[] }>('/api/snapshots'),
  loadSnapshot: (id: string) => request<Analysis>(`/api/snapshots/${id}`),
  importSnapshot: (payload: unknown) => request<Analysis>('/api/snapshots/import', json(payload)),
  report: (id: string, format: 'md' | 'html' | 'json', workbench: Workbench) => download(`/api/analysis/${id}/report`, { format, workbench }, `PathwayGPS_report.${format}`),
  exportGraph: async (id: string, format: 'json' | 'cytoscape') => {
    const res = await fetch(`/api/analysis/${id}/export/graph?format=${format}`);
    if (!res.ok) throw new ApiError(res.status, 'Export failed');
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') || '')?.[1] ?? 'PathwayGPS_graph.json';
    a.click();
  },
};

function pyError(e: unknown): never {
  const msg = String((e as Error)?.message ?? e);
  const last = msg.trim().split('\n').filter(Boolean).pop() ?? msg;
  const status = /KeyError/.test(last) ? 404 : /ValueError/.test(last) ? 400 : 0;
  throw new ApiError(status, last.replace(/^\w+(Error|Exception): ?/, '').replace(/^'|'$/g, '') || 'Engine error');
}
const py = <T,>(expr: string, args: Record<string, unknown> = {}) => call<T>(expr, args).catch(pyError);
const saveFile = (text: string, name: string, type: string) => {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
};
const SNAP_KEY = 'pathwaygps:snapshots';
const readSnaps = (): any[] => { try { return JSON.parse(localStorage.getItem(SNAP_KEY) || '[]'); } catch { return []; } };
const fname = (q: string) => `PathwayGPS_${q.replace(/[^A-Za-z0-9._-]+/g, '_')}`;

const browserApi: typeof liveApi = {
  health: async () => ({ status: 'ok', mode: 'browser', ai: { enabled: false } }),
  examples: async () => ({ examples: [
    { query: 'EGFR L858R', label: 'EGFR L858R', note: 'NSCLC sensitizing' },
    { query: 'BRAF V600E', label: 'BRAF V600E', note: 'Conflicting germline · Tier I' },
    { query: 'KRAS G12C', label: 'KRAS G12C', note: '2 nucleotide records' },
    { query: 'NM_000546.6:c.524G>A', label: 'TP53 R175H', note: 'Transcript HGVS' },
    { query: 'rs121434568', label: 'rs121434568', note: 'Multi-allelic rsID' },
    { query: 'TP53', label: 'TP53', note: 'Gene-level only' },
  ] }),
  analyze: (query) => py<Analysis>('service.analyze(_a["q"])', { q: query }),
  expand: (id, node_id, action) => py('service.expand(_a["id"], _a["n"], _a["act"])', { id, n: node_id, act: action }),
  path: (id, target, source) => py<PathResult>('service.path(_a["id"], _a["t"], _a.get("s"))', { id, t: target, s: source ?? null }),
  routes: (id, target, k = 3) => py('service.routes(_a["id"], _a["t"], _a["k"])', { id, t: target, k }),
  chat: (id, messages) => py('service.chat(_a["id"], _a["m"])', { id, m: messages }),
  synthesis: (id) => py('service.synthesize_ai(_a["id"])', { id }),
  abstract: (pmid) => py('service.abstract(_a["p"])', { p: pmid }),
  literature: (q) => py('service.literature_search(_a["q"])', { q }),
  compare: (a, b) => py('service.compare(_a["a"], _a["b"])', { a, b }),
  enrichment: (identifiers) => py('service.enrichment(_a["ids"])', { ids: identifiers }),
  snapshot: async (id, workbench) => {
    const payload = await py<any>('service.get(_a["id"])', { id });
    const snap = { id: Math.random().toString(16).slice(2, 14), saved_at: new Date().toISOString(), original_analysis_id: id, original_created_at: payload.created_at, workbench,
      statement: 'Frozen copy of the analysis as retrieved; external data are not refreshed. Re-run the query to compare with current source data.' };
    const list = readSnaps();
    list.unshift({ ...payload, snapshot: snap });
    try { localStorage.setItem(SNAP_KEY, JSON.stringify(list.slice(0, 8))); } catch { throw new ApiError(0, 'Browser storage is full; export the analysis as JSON instead.'); }
    return snap;
  },
  snapshots: async () => ({ snapshots: readSnaps().map((p) => ({ id: p.snapshot.id, query: p.query, saved_at: p.snapshot.saved_at, original_created_at: p.snapshot.original_created_at, status: p.resolution?.status })) }),
  loadSnapshot: async (id) => {
    const p = readSnaps().find((x) => x.snapshot.id === id);
    if (!p) throw new ApiError(404, 'Snapshot not found in this browser.');
    return py<Analysis>('service.register_snapshot(_a["p"])', { p });
  },
  importSnapshot: (payload) => py<Analysis>('service.register_snapshot(_a["p"])', { p: payload }),
  report: async (id, format, workbench) => {
    const payload = await py<any>('service.get(_a["id"])', { id });
    if (format === 'json') return saveFile(JSON.stringify({ ...payload, workbench }, null, 2), `${fname(payload.query)}.json`, 'application/json');
    const text = await py<string>(format === 'html' ? 'to_html(build_blocks(service.get(_a["id"]), _a["w"]), "PathwayGPS report")' : 'to_markdown(build_blocks(service.get(_a["id"]), _a["w"]))', { id, w: workbench });
    saveFile(text, `${fname(payload.query)}.${format}`, format === 'html' ? 'text/html' : 'text/markdown');
  },
  exportGraph: async (id, format) => {
    const p = await py<any>('service.get(_a["id"])', { id });
    const body = format === 'cytoscape'
      ? { format_version: '1.0', generated_by: 'PathwayGPS', elements: { nodes: p.graph.nodes.map((n: any) => ({ data: { ...n, attributes: undefined } })), edges: p.graph.edges.map((e: any) => ({ data: e })) }, evidence: p.graph.evidence }
      : { query: p.query, retrieved: p.created_at, root_id: p.root_id, ...p.graph, sources: p.sources };
    saveFile(JSON.stringify(body, null, 2), `${fname(p.query)}_graph.json`, 'application/json');
  },
};

export const api: typeof liveApi = BROWSER_ENGINE ? browserApi : liveApi;
