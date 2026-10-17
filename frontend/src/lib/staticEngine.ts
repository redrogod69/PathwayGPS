// Client-side implementations used by the static GitHub Pages demo (no backend).
// Ports of backend/app/pipeline/insights.py (explain_path, k_routes) and pipeline/assistant.py (retrieval mode).
import type { Analysis, Category, PathHop, PathResult } from '../types';

const ORDER: Category[] = ['curated', 'experimental', 'association', 'computational', 'inferred', 'hypothesis'];
const PENALTY: Record<Category, number> = { curated: 0, experimental: 0.1, association: 0.25, computational: 0.3, inferred: 0.5, hypothesis: 0.9 };
const VERDICT_TEXT: Record<string, string> = {
  supported_by_curated_or_experimental_evidence: 'Every step is supported by curated or experimental source records.',
  contains_association_steps: 'Includes gene-level statistical association steps (not mechanistic).',
  contains_computational_steps: 'Includes computational predictions.',
  contains_inferred_steps: 'Includes steps inferred by PathwayGPS (e.g. coordinate overlap) or by orthology.',
  hypothesis: 'Includes hypothesis steps that require validation.',
};

type R = PathResult & { rank?: number; cost: number; evidence: Record<string, string[]> };

export function explainPath(a: Analysis, source: string, target: string, removed: Set<string> = new Set()): R | null {
  const nodes = new Map(a.graph.nodes.map((n) => [n.id, n]));
  if (!nodes.has(source) || !nodes.has(target)) return null;
  const adj = new Map<string, [string, string, boolean][]>();
  const edges = new Map(a.graph.edges.filter((e) => !removed.has(e.id)).map((e) => [e.id, e]));
  edges.forEach((e) => {
    if (!adj.has(e.source)) adj.set(e.source, []);
    if (!adj.has(e.target)) adj.set(e.target, []);
    adj.get(e.source)!.push([e.target, e.id, true]);
    adj.get(e.target)!.push([e.source, e.id, false]);
  });
  const cost = (eid: string) => {
    const e = edges.get(eid)!;
    const best = Math.min(...e.categories.map((c) => ORDER.indexOf(c)), ORDER.indexOf('inferred'));
    return 1 + PENALTY[ORDER[best]] - 0.001 * Math.min(e.evidence.length, 20);
  };
  const best = new Map<string, number>([[source, 0]]);
  const heap: [number, string, [string, boolean][]][] = [[0, source, []]];
  while (heap.length) {
    heap.sort((x, y) => x[0] - y[0]);
    const [c, node, path] = heap.shift()!;
    if (node === target) {
      const hops: PathHop[] = [];
      const ids = [source];
      for (const [eid, fwd] of path) {
        const e = edges.get(eid)!;
        const [from, to] = fwd ? [e.source, e.target] : [e.target, e.source];
        ids.push(to);
        const evs = e.evidence.map((x) => a.graph.evidence[x]).filter(Boolean);
        hops.push({ edge_id: eid, from, to, from_label: nodes.get(from)!.label, to_label: nodes.get(to)!.label, type: e.type, label: e.label,
          direction: fwd ? 'forward' : 'reverse', category: e.category, categories: e.categories, evidence_count: evs.length,
          publication_count: new Set(evs.flatMap((v) => v.publications)).size, sources: [...new Set(evs.map((v) => v.source))].sort() });
      }
      const cats = hops.map((h) => h.category);
      const verdict = cats.includes('hypothesis') ? 'hypothesis' : cats.includes('inferred') ? 'contains_inferred_steps'
        : cats.includes('computational') ? 'contains_computational_steps' : cats.includes('association') ? 'contains_association_steps'
        : 'supported_by_curated_or_experimental_evidence';
      return { found: true, source, target, nodes: ids, hops, verdict, verdict_text: VERDICT_TEXT[verdict], cost: Math.round(c * 1000) / 1000,
        reverse_hops: hops.filter((h) => h.direction === 'reverse').length,
        evidence: Object.fromEntries(hops.map((h) => [h.edge_id, edges.get(h.edge_id)!.evidence])) };
    }
    if (c > (best.get(node) ?? Infinity) || path.length > 8) continue;
    for (const [nxt, eid, fwd] of adj.get(node) ?? []) {
      const nc = c + cost(eid);
      if (nc < (best.get(nxt) ?? Infinity)) { best.set(nxt, nc); heap.push([nc, nxt, [...path, [eid, fwd]]]); }
    }
  }
  return null;
}

export function kRoutes(a: Analysis, source: string, target: string, k = 3): R[] {
  const first = explainPath(a, source, target);
  if (!first) return [];
  const seen = new Set([first.hops!.map((h) => h.edge_id).join('|')]);
  const cands: R[] = [];
  for (const h of first.hops!) {
    const alt = explainPath(a, source, target, new Set([h.edge_id]));
    if (alt) {
      const key = alt.hops!.map((x) => x.edge_id).join('|');
      if (!seen.has(key)) { seen.add(key); cands.push(alt); }
    }
  }
  cands.sort((x, y) => x.cost - y.cost);
  return [first, ...cands.slice(0, k - 1)].map((r, i) => ({ ...r, rank: i + 1 }));
}

export function retrievalChat(p: Analysis, question: string) {
  const g = p.graph;
  const nodes = new Map(g.nodes.map((n) => [n.id, n]));
  const q = question.toLowerCase();
  const rows = g.edges.flatMap((e) => e.evidence.map((id) => ({ e, ev: g.evidence[id], rel: `${nodes.get(e.source)?.label} ${e.label} ${nodes.get(e.target)?.label}` }))).filter((r) => r.ev);
  const lines: string[] = [];
  const cites: string[] = [];
  const add = (r: (typeof rows)[number]) => { if (!cites.includes(r.ev.id)) { lines.push(`• ${r.ev.statement} (${r.ev.category}, ${r.ev.source})`); cites.push(r.ev.id); } };
  const pick = (pred: (r: (typeof rows)[number]) => boolean, n: number) => rows.filter(pred).filter((r, i, arr) => arr.findIndex((x) => x.ev.id === r.ev.id) === i).slice(0, n);
  if (/conflict|disagree|discord|contradict|inconsist/.test(q)) {
    if (p.conflicts.length) p.conflicts.forEach((c) => lines.push(`• ${c.title}: ${c.summary} — ${c.explanation}`));
    else lines.push('• No disagreements were detected among the retrieved records.');
  } else if (/drug|therap|treat|inhibit|sensitiv|resist/.test(q)) {
    pick((r) => ['VARIANT_PREDICTIVE_FOR_THERAPY', 'DRUG_TARGETS_PROTEIN'].includes(r.e.type), 8).forEach(add);
    lines.push('Note: disease-specific curated evidence or gene-level mechanisms — not treatment recommendations.');
  } else if (/missing|gap|uncertain|unknown|limitation|vus/.test(q)) {
    p.gaps.forEach((gp) => lines.push(`• ${gp.message}`));
  } else if (/experimental|curated|computational|inferr|predict|direct/.test(q)) {
    const counts: Record<string, number> = {};
    g.edges.forEach((e) => { counts[e.category] = (counts[e.category] ?? 0) + 1; });
    lines.push('Relationship counts by strongest evidence category: ' + Object.entries(counts).map(([k, v]) => `${k} ${v}`).join(', ') + '.');
    pick((r) => ['computational', 'inferred'].includes(r.ev.category), 4).forEach(add);
    pick((r) => r.ev.category === 'experimental' || (r.ev.category === 'curated' && r.ev.publications.length > 0), 4).forEach(add);
  } else if (/mechanism|pathway|downstream|cascade|signal|route|proliferat/.test(q)) {
    const fp = p.impact?.focus_pathway;
    if (fp) lines.push(`Downstream cascade is drawn for '${fp.name}' (${fp.reason}).`);
    ['VARIANT_ALTERS_PROTEIN', 'VARIANT_IN_PROTEIN_REGION', 'VARIANT_REPRESENTED_AS', 'MUTANT_ENTITY_IN_PATHWAY', 'PROTEIN_PARTICIPATES_IN_REACTION', 'REACTION_PRECEDES', 'REACTION_PRODUCES']
      .forEach((t) => pick((r) => r.e.type === t, 2).forEach(add));
    lines.push('Reactome event order describes curated pathway sequence, not a measured effect of the variant.');
  } else {
    const toks: string[] = q.match(/[a-z0-9-]{2,}/g) ?? [];
    rows.map((r) => ({ r, s: toks.reduce((acc: number, t: string) => acc + ((r.ev.statement + ' ' + r.rel).toLowerCase().split(t).length - 1), 0) }))
      .filter((x) => x.s > 0).sort((x, y) => y.s - x.s).slice(0, 12).forEach((x) => { if (cites.length < 6) add(x.r); });
  }
  if (!lines.length) lines.push('The retrieved evidence ledger does not contain records that answer this question. Try rephrasing around genes, pathways, drugs, conflicts or evidence types.');
  return { mode: 'retrieval', answer: lines.join('\n'), citations: cites, follow_up: (p.assistant_suggestions ?? []).slice(0, 2) };
}

export function compareDiff(pa: Analysis, pb: Analysis) {
  const labels = (p: Analysis, t: string) => new Map(p.graph.nodes.filter((n) => n.type === t).map((n) => [n.id, n.label]));
  const sec = (la: Map<string, string>, lb: Map<string, string>) => ({
    shared: [...la].filter(([k]) => lb.has(k)).map(([id, label]) => ({ id, label })),
    only_a: [...la].filter(([k]) => !lb.has(k)).map(([id, label]) => ({ id, label })),
    only_b: [...lb].filter(([k]) => !la.has(k)).map(([id, label]) => ({ id, label })),
  });
  const pw = (p: Analysis) => new Map<string, string>((p.overview?.reactome?.all_pathways ?? []).map((x: any) => [x.stId, x.name]));
  return {
    pathways_all: sec(pw(pa), pw(pb)), diseases: sec(labels(pa, 'disease'), labels(pb, 'disease')),
    drugs: sec(labels(pa, 'drug'), labels(pb, 'drug')), reactions_drawn: sec(labels(pa, 'reaction'), labels(pb, 'reaction')),
  };
}
