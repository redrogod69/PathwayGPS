import type { Analysis, PathResult, Synthesis, Workbench } from './types';
import { compareDiff, explainPath, kRoutes, retrievalChat } from './lib/staticEngine';

/** Static GitHub Pages build: no backend; recorded demo analyses are served from /demo. */
const API_BASE: string = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '');
const STATIC_BUILD = import.meta.env.VITE_STATIC === '1';
/** True when this build has no reachable backend and is serving recorded demo data. */
export let STATIC_DEMO = STATIC_BUILD && !API_BASE;
export const HOSTED_API = API_BASE;
const BASE = import.meta.env.BASE_URL;
export const STATIC_NOTE = 'Not available in the static GitHub Pages demo — run PathwayGPS locally (see README) for live queries.';
let demoIndex: Promise<any> | null = null;
const demoCache = new Map<string, Analysis>();
const loadIndex = () => (demoIndex ??= fetch(`${BASE}demo/index.json`).then((r) => r.json()));
async function demoAnalyze(query: string): Promise<Analysis> {
  const idx = await loadIndex();
  const file = idx.queries[query.trim().replace(/\s+/g, ' ').toUpperCase()];
  if (!file) throw new ApiError(404, `"${query}" is not one of the recorded demo analyses. Static demo variants: ${idx.examples.map((e: any) => e.label).join(', ')}. ${STATIC_NOTE}`);
  if (!demoCache.has(file)) demoCache.set(file, await fetch(`${BASE}demo/${file}`).then((r) => r.json()));
  return demoCache.get(file)!;
}
const byId = (id: string) => [...demoCache.values()].find((a) => a.analysis_id === id)!;
const unavailable = async (): Promise<never> => { throw new ApiError(0, STATIC_NOTE); };
async function eutils(path: string) {
  const r = await fetch(`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/${path}${path.includes('?') ? '&' : '?'}tool=PathwayGPS`);
  if (!r.ok) throw new ApiError(r.status, 'PubMed unavailable');
  return r;
}

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
    const res = await fetch(url.startsWith('/api') ? API_BASE + url : url, { ...init, signal: ctrl.signal });
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
  const res = await fetch(API_BASE + url, body === undefined ? undefined : json(body));
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
    const res = await fetch(`${API_BASE}/api/analysis/${id}/export/graph?format=${format}`);
    if (!res.ok) throw new ApiError(res.status, 'Export failed');
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') || '')?.[1] ?? 'PathwayGPS_graph.json';
    a.click();
  },
};

const staticApi: typeof liveApi = {
  ...liveApi,
  health: async () => ({ status: 'ok', mode: 'static_demo', ai: { enabled: false } }),
  examples: async () => ({ examples: (await loadIndex()).examples }),
  analyze: demoAnalyze,
  expand: unavailable, synthesis: unavailable, enrichment: unavailable, snapshot: unavailable, loadSnapshot: unavailable,
  snapshots: async () => ({ snapshots: [] }),
  importSnapshot: async (payload: unknown) => payload as Analysis,
  path: async (id, target, source) => {
    const a = byId(id);
    return explainPath(a, source ?? a.root_id!, target) ?? { found: false, source: a.root_id!, target, message: 'No connecting path exists in the retrieved graph. PathwayGPS does not invent one.' };
  },
  routes: async (id, target, k = 3) => {
    const a = byId(id);
    const routes = kRoutes(a, a.root_id!, target, k) as any;
    return { source: a.root_id!, target, routes, message: routes.length ? undefined : 'No connecting route exists in the retrieved graph.', ranking: 'Fewest steps first, then strongest evidence category, then most supporting records. Not a probability.' };
  },
  chat: async (id, messages) => retrievalChat(byId(id), messages[messages.length - 1].content),
  compare: async (a, b) => {
    const [pa, pb] = await Promise.all([demoAnalyze(a), demoAnalyze(b)]);
    return { a: pa, b: pb, diff: compareDiff(pa, pb), note: 'Pathway overlap compares all Reactome pathways retrieved for each protein. Shared pathways do not imply the variants have the same effect.' };
  },
  abstract: async (pmid) => {
    const xml = await (await eutils(`efetch.fcgi?db=pubmed&id=${pmid}&retmode=xml&rettype=abstract`)).text();
    const doc = new DOMParser().parseFromString(xml, 'text/xml');
    return { pmid, title: doc.querySelector('ArticleTitle')?.textContent ?? undefined, url: `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`, mesh: [], pubtypes: [],
      copyright: doc.querySelector('CopyrightInformation')?.textContent ?? undefined,
      sections: [...doc.querySelectorAll('AbstractText')].map((n) => ({ label: n.getAttribute('Label') ?? undefined, text: n.textContent ?? '' })) };
  },
  literature: async (q) => {
    const s = await (await eutils(`esearch.fcgi?db=pubmed&retmode=json&retmax=15&sort=relevance&term=${encodeURIComponent(q)}`)).json();
    const ids: string[] = s.esearchresult?.idlist ?? [];
    const sum = ids.length ? await (await eutils(`esummary.fcgi?db=pubmed&retmode=json&id=${ids.join(',')}`)).json() : { result: {} };
    return { query: q, count: Number(s.esearchresult?.count ?? 0), note: 'Keyword search results: co-mention of terms in PubMed, not evidence for any specific relationship.',
      results: ids.map((id) => sum.result[id]).filter(Boolean).map((r: any) => ({ pmid: r.uid, title: r.title, journal: r.source, year: (r.pubdate ?? '').slice(0, 4), authors: (r.authors ?? []).slice(0, 3).map((x: any) => x.name), url: `https://pubmed.ncbi.nlm.nih.gov/${r.uid}/` })) };
  },
  report: unavailable, exportGraph: async (id) => {
    const a = byId(id);
    const url = URL.createObjectURL(new Blob([JSON.stringify({ query: a.query, retrieved: a.created_at, root_id: a.root_id, ...a.graph, sources: a.sources }, null, 2)], { type: 'application/json' }));
    const el = document.createElement('a'); el.href = url; el.download = `PathwayGPS_${a.query.replace(/\W+/g, '_')}_graph.json`; el.click();
  },
};

/** Hosted static build with a backend URL: use the live API, and fall back to the recorded demo if it is unreachable. */
function withFallback(): typeof liveApi {
  const out: any = {};
  for (const key of Object.keys(liveApi) as (keyof typeof liveApi)[]) {
    out[key] = async (...args: any[]) => {
      if (!STATIC_DEMO) {
        try { return await (liveApi[key] as any)(...args); } catch (e) {
          if (!(e instanceof ApiError) || e.status !== 0 || key === 'chat' || key === 'routes' || key === 'path' || key === 'expand') throw e;
          STATIC_DEMO = true;
          window.dispatchEvent(new Event('pathwaygps:static-fallback'));
        }
      }
      return (staticApi[key] as any)(...args);
    };
  }
  return out;
}

export const api: typeof liveApi = STATIC_BUILD ? (API_BASE ? withFallback() : staticApi) : liveApi;
