import { useMemo, useState } from 'react';
import type { Analysis, GEdge, GNode } from '../types';
import { EXPAND_ACTIONS, NODE_STYLE, RELATION_LABEL, stars } from '../lib/vocab';
import { EvidenceCard } from './Evidence';
import { Button, CategoryChip, ExtLink, KV, Pill, SourceChip, Spinner } from './ui';

interface Props {
  analysis: Analysis;
  selectedId: string | null;
  expanding: string | null;
  marked: string[];
  onSelectNode: (id: string) => void;
  onSelectEdge: (id: string) => void;
  onExpand: (nodeId: string, action: string) => void;
  onExplainPath: (nodeId: string) => void;
  onToggleMark: (nodeId: string) => void;
  onAddNote: (targetId: string, label: string, evidenceIds: string[]) => void;
}

function Classification({ label, cls }: { label: string; cls: any }) {
  if (!cls) return null;
  const tone = /pathogenic|oncogenic|tier i\b/i.test(cls.description) && !/conflicting|likely benign|benign/i.test(cls.description) ? 'rose'
    : /uncertain|conflicting/i.test(cls.description) ? 'amber' : /benign/i.test(cls.description) ? 'teal' : 'violet';
  return (
    <div className="rounded-lg border border-line bg-ink/50 p-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <Pill tone={tone as any}>{cls.description}</Pill>
        <span className="text-xs text-amber-300" title="ClinVar review status stars">{stars(cls.stars)}</span>
      </div>
      <div className="mt-1 text-[11px] text-slate-400">{cls.review_status}{cls.last_evaluated ? ` · evaluated ${cls.last_evaluated}` : ''}</div>
    </div>
  );
}

function Literature({ refs }: { refs?: { pmid?: string; title?: string; journal?: string; year?: number }[] }) {
  if (!refs || !refs.length) return <p className="text-xs italic text-slate-500">No literature reference recorded on this Reactome object.</p>;
  return (
    <ul className="space-y-1 text-xs">
      {refs.slice(0, 8).map((r, i) => (
        <li key={i} className="text-slate-300">
          {r.title} <span className="text-slate-500">{r.journal} {r.year}</span>{' '}
          {r.pmid && <ExtLink href={`https://pubmed.ncbi.nlm.nih.gov/${r.pmid}/`}>PMID {r.pmid}</ExtLink>}
        </li>
      ))}
    </ul>
  );
}

function NodeBody({ node }: { node: GNode }) {
  const a = node.attributes;
  const [more, setMore] = useState(false);
  switch (node.type) {
    case 'variant':
      return (
        <div className="space-y-3">
          <KV rows={[
            ['HGVS c.', <span className="font-mono text-xs">{a.hgvs_c ?? '—'}</span>],
            ['HGVS p.', <span className="font-mono text-xs">{a.hgvs_p ?? (a.protein_change ? a.protein_change.hgvs_long : '—')}</span>],
            ['GRCh38', a.grch38?.chr ? <span className="font-mono text-xs">chr{a.grch38.chr}:{a.grch38.start}</span> : 'not resolved'],
            ['Transcript', a.transcript ? <span className="font-mono text-xs">{a.transcript} {a.mane_select ? `(MANE ${a.mane_select})` : ''}</span> : null],
            ['Consequence', a.consequence ? <span>{a.consequence.join(', ')} <CategoryChip category="computational" small /></span> : null],
            ['SIFT', a.sift ? <span>{a.sift.prediction} ({a.sift.score}) <CategoryChip category="computational" small /></span> : null],
            ['PolyPhen-2', a.polyphen ? <span>{a.polyphen.prediction} ({a.polyphen.score}) <CategoryChip category="computational" small /></span> : null],
          ]} />
          <div className="grid gap-2">
            <Classification label="ClinVar germline" cls={a.germline} />
            <Classification label="ClinVar somatic clinical impact" cls={a.somatic_clinical_impact} />
            <Classification label="ClinVar oncogenicity" cls={a.oncogenicity} />
            {!a.germline && !a.somatic_clinical_impact && !a.oncogenicity && <p className="text-xs text-slate-400">No ClinVar classification is available for this variant.</p>}
          </div>
          <p className="text-[11px] text-slate-500">SIFT / PolyPhen-2 are computational predictions (ACMG/AMP supporting evidence at most) and are not classifications.</p>
        </div>
      );
    case 'protein': {
      const fn: string = (a.function ?? []).join(' ');
      return (
        <div className="space-y-2">
          <KV rows={[['Name', a.protein_name], ['Length', a.length ? `${a.length} aa` : null], ['Location', (a.subcellular_location ?? []).join(', ')],
            ['Structures', a.pdb_structures ? `${a.pdb_structures} PDB entries` : null], ['UniProt annotation score', a.annotation_score ? `${a.annotation_score}/5` : null]]} />
          {fn && <p className="text-xs leading-relaxed text-slate-300">{more ? fn : `${fn.slice(0, 420)}${fn.length > 420 ? '…' : ''}`} {fn.length > 420 && <button className="text-cyan-300" onClick={() => setMore(!more)}>{more ? 'less' : 'more'}</button>} <span className="text-slate-500">— UniProt function (curated)</span></p>}
        </div>
      );
    }
    case 'protein_region':
      return <KV rows={[['Feature', a.feature_type], ['Residues', `${a.start}–${a.end}`], ['Description', a.description], ['Evidence', (a.evidence_labels ?? []).join('; ')], ['Basis', (a.evidence_sources ?? []).join(', ')]]} />;
    case 'pathway':
      return (
        <div className="space-y-2">
          <KV rows={[['Top-level', (a.top_level ?? []).join(', ')], ['Disease pathway', a.is_in_disease ? 'yes (models disease variants)' : 'no'], ['Review', a.review_status], ['Last updated', a.last_updated], ['Orthology-inferred', a.is_inferred ? 'yes' : null]]} />
          {a.summation && <p className="text-xs leading-relaxed text-slate-300">{more ? a.summation : `${a.summation.slice(0, 380)}${a.summation.length > 380 ? '…' : ''}`} {a.summation.length > 380 && <button className="text-cyan-300" onClick={() => setMore(!more)}>{more ? 'less' : 'more'}</button>}</p>}
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Pathway references</div>
          <Literature refs={a.literature} />
        </div>
      );
    case 'reaction':
      return (
        <div className="space-y-2">
          <KV rows={[
            ['Inputs', (a.inputs ?? []).map((x: any) => x.name).join('; ')],
            ['Outputs', (a.outputs ?? []).map((x: any) => x.name).join('; ')],
            ['Catalyst', (a.catalysts ?? []).join('; ')],
            ['Regulation', (a.regulators ?? []).join('; ')],
            ['Compartment', (a.compartments ?? []).join(', ')],
            ['Disease', (a.diseases ?? []).map((d: any) => d.name).join(', ')],
            ['Review', a.review_status],
          ]} />
          {a.summation && <p className="text-xs leading-relaxed text-slate-300">{more ? a.summation : `${a.summation.slice(0, 380)}${a.summation.length > 380 ? '…' : ''}`} {a.summation.length > 380 && <button className="text-cyan-300" onClick={() => setMore(!more)}>{more ? 'less' : 'more'}</button>}</p>}
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Reaction references</div>
          <Literature refs={a.literature} />
        </div>
      );
    case 'disease':
      return <KV rows={[['Name', a.full_name], ['Reported by', (a.harmonized_sources ?? []).join(', ')], ['Therapeutic area', (a.therapeutic_areas ?? []).join(', ')]]} />;
    case 'drug':
      return <KV rows={[['Reported by', (a.harmonized_sources ?? []).join(', ')], ['Source names', (a.source_names ?? []).join(', ')], ['Max clinical stage', a.max_stage], ['Type', a.drug_type],
        ['Indications', (a.indications ?? []).slice(0, 6).join('; ')], ['Harmonisation', a.harmonization_rule]]} />;
    case 'interactor':
      return <KV rows={[['IntAct MI-score', a.mi_score], ['Evidence records', a.evidence_count]]} />;
    case 'reactome_entity':
    case 'physical_entity':
      return <KV rows={[['Reactome name', a.full_name], ['Class', a.schema_class], ['Member of', a.member_of_set?.name], ['Pathway', a.pathway]]} />;
    default:
      return <KV rows={Object.entries(a).filter(([, v]) => typeof v !== 'object').slice(0, 8) as any} />;
  }
}

export default function DetailPanel(p: Props) {
  const { analysis } = p;
  const node = analysis.graph.nodes.find((n) => n.id === p.selectedId) ?? null;
  const edge = node ? null : analysis.graph.edges.find((e) => e.id === p.selectedId) ?? null;
  const nodeById = useMemo(() => new Map(analysis.graph.nodes.map((n) => [n.id, n])), [analysis]);

  if (!node && !edge) {
    return (
      <div className="space-y-3 p-4 text-sm text-slate-300">
        <h3 className="text-sm font-semibold text-slate-100">Explore the network</h3>
        <ul className="list-disc space-y-1 pl-5 text-xs text-slate-400">
          <li>Click a <b>node</b> for its biology, identifiers and expansion options.</li>
          <li>Click a <b>relationship</b> (line) to open its evidence ledger with source records and publications.</li>
          <li>Double-click a pathway, reaction or entity to expand it from Reactome.</li>
          <li>Use <b>Explain path</b> to see how a node connects to the variant, step by step.</li>
        </ul>
        <div className="rounded-lg border border-line bg-ink/50 p-3 text-xs text-slate-400">
          Line style shows the <b>strongest evidence category</b> on a relationship. Gene-level associations (Open Targets) are dashed orange and are not variant-specific.
        </div>
      </div>
    );
  }

  if (edge) {
    const from = nodeById.get(edge.source)!;
    const to = nodeById.get(edge.target)!;
    const evs = edge.evidence.map((id) => analysis.graph.evidence[id]).filter(Boolean);
    return (
      <div className="space-y-3 p-4">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[.18em] text-cyan-300">Relationship evidence</div>
          <h3 className="mt-1 text-base font-semibold text-white">{RELATION_LABEL[edge.type] ?? edge.type}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-1 text-sm">
            <button className="text-cyan-200 hover:underline" onClick={() => p.onSelectNode(from.id)}>{from.label}</button>
            <span className="text-slate-500">—{edge.label}→</span>
            <button className="text-cyan-200 hover:underline" onClick={() => p.onSelectNode(to.id)}>{to.label}</button>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {edge.categories.map((c) => <CategoryChip key={c} category={c} />)}
            <span className="text-xs text-slate-400">{evs.length} supporting record{evs.length === 1 ? '' : 's'}</span>
          </div>
          {edge.type === 'TARGET_ASSOCIATED_WITH_DISEASE' && <p className="mt-2 text-xs text-orange-200">Gene-level association — not specific to the queried variant.</p>}
          {edge.type === 'VARIANT_PREDICTIVE_FOR_THERAPY' && <p className="mt-2 text-xs text-amber-200">Disease-specific clinical evidence. Not a treatment recommendation.</p>}
          <div className="mt-2 flex gap-2">
            <Button variant="outline" onClick={() => p.onAddNote(edge.id, `${from.label} → ${to.label}`, edge.evidence)}>＋ Note on this relationship</Button>
          </div>
        </div>
        <div className="space-y-2">{evs.map((ev) => <EvidenceCard key={ev.id} ev={ev} pubs={analysis.publications} />)}</div>
      </div>
    );
  }

  const n = node!;
  const style = NODE_STYLE[n.type];
  const edges: GEdge[] = analysis.graph.edges.filter((e) => e.source === n.id || e.target === n.id);
  const actions = EXPAND_ACTIONS[n.type] ?? [];
  const isMarked = p.marked.includes(n.id);
  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-ink" style={{ background: style.color }}>{style.label}</span>
          <SourceChip source={n.source} />
          {n.flags.includes('vus') && <Pill tone="amber">VUS</Pill>}
          {n.flags.includes('conflicting') && <Pill tone="amber">Conflicting submissions</Pill>}
          {(n.flags.includes('disease_pathway') || n.flags.includes('disease_event') || n.flags.includes('disease_entity')) && <Pill tone="rose">Disease-variant model</Pill>}
          {n.flags.includes('orthology_inferred') && <Pill>Orthology-inferred</Pill>}
          {n.secondary && <Pill>Secondary</Pill>}
        </div>
        <h3 className="mt-2 break-words text-lg font-semibold text-white">{n.attributes.full_name && n.type !== 'disease' ? n.attributes.full_name : n.label}</h3>
        {n.subtitle && <p className="text-xs text-slate-400">{n.subtitle}</p>}
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {n.xrefs.map((x, i) => <ExtLink key={i} href={x.url}>{x.db}: {x.id}</ExtLink>)}
        </div>
      </div>
      <NodeBody node={n} />
      <div className="flex flex-wrap gap-2">
        {actions.map((a) => (
          <Button key={a.action} variant="outline" title={a.help} disabled={!!p.expanding || !!analysis.snapshot} onClick={() => p.onExpand(n.id, a.action)}>
            {p.expanding === `${n.id}:${a.action}` ? <Spinner /> : '⊕'} {a.label}
          </Button>
        ))}
        {n.id !== analysis.root_id && <Button variant="outline" onClick={() => p.onExplainPath(n.id)}>⇢ Explain path from {analysis.root_id?.startsWith('variant') ? 'variant' : 'gene'}</Button>}
        <Button variant="outline" onClick={() => p.onToggleMark(n.id)}>{isMarked ? '★ Unmark' : '☆ Mark'}</Button>
        <Button variant="outline" onClick={() => p.onAddNote(n.id, n.label, [])}>＋ Note</Button>
      </div>
      {analysis.snapshot && actions.length > 0 && <p className="text-[11px] text-slate-500">Expansion is disabled for snapshots (frozen data). Re-run the query for live exploration.</p>}
      <div>
        <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Relationships ({edges.length})</div>
        <ul className="space-y-1">
          {edges.map((e) => {
            const other = nodeById.get(e.source === n.id ? e.target : e.source);
            return (
              <li key={e.id}>
                <button onClick={() => p.onSelectEdge(e.id)} className="flex w-full items-center justify-between gap-2 rounded-md border border-line/60 bg-ink/40 px-2 py-1.5 text-left text-xs hover:border-cyan-400/50">
                  <span className="min-w-0 truncate"><span className="text-slate-500">{e.source === n.id ? `${e.label} →` : `← ${e.label}`}</span> <span className="text-slate-200">{other?.label}</span></span>
                  <CategoryChip category={e.category} small />
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
