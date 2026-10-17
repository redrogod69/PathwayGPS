import { useMemo, useState } from 'react';
import type { Analysis } from '../types';
import { stars } from '../lib/vocab';
import { Card, CategoryChip, Empty, ExtLink, KV, Pill } from './ui';

function ProteinMap({ protein, position }: { protein: any; position?: number }) {
  const length: number = protein.length || 1;
  const W = 640;
  const x = (p: number) => 10 + ((p - 1) / length) * (W - 20);
  const regions = (protein.track ?? []).filter((f: any) => ['Domain', 'Topological domain', 'Transmembrane', 'Region', 'Motif'].includes(f.type) && f.end - f.start >= 4);
  const sites = (protein.track ?? []).filter((f: any) => ['Active site', 'Binding site'].includes(f.type));
  const color: Record<string, string> = { Domain: '#22d3ee', 'Topological domain': '#334155', Transmembrane: '#f59e0b', Region: '#818cf8', Motif: '#34d399' };
  const rows: any[][] = [];
  regions.sort((a: any, b: any) => (a.type === 'Topological domain' ? -1 : 0) - (b.type === 'Topological domain' ? -1 : 0) || a.start - b.start).forEach((f: any) => {
    const row = rows.find((r) => r.every((g) => g.end < f.start - 2 || g.start > f.end + 2));
    if (row) row.push(f); else rows.push([f]);
  });
  const H = 46 + rows.length * 16;
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Protein feature map of ${protein.accession}, ${length} residues${position ? `, variant at ${position}` : ''}`}>
        <rect x={10} y={20} width={W - 20} height={6} rx={3} fill="#1e293b" />
        {rows.map((row, ri) => row.map((f: any, i: number) => (
          <g key={`${ri}-${i}`}>
            <rect x={x(f.start)} y={32 + ri * 16} width={Math.max(2, x(f.end) - x(f.start))} height={11} rx={3} fill={color[f.type] ?? '#64748b'} opacity={f.type === 'Topological domain' ? 0.55 : 0.85}>
              <title>{`${f.type}: ${f.description || ''} (${f.start}–${f.end}) · ${f.category}`}</title>
            </rect>
            {x(f.end) - x(f.start) > 70 && <text x={x(f.start) + 4} y={41 + ri * 16} fontSize={9} fill="#020617" fontWeight={600}>{(f.description || f.type).slice(0, 26)}</text>}
          </g>
        )))}
        {sites.map((f: any, i: number) => <rect key={i} x={x(f.start) - 0.5} y={16} width={1.5} height={14} fill="#fde68a"><title>{`${f.type} ${f.start}${f.end !== f.start ? `–${f.end}` : ''}`}</title></rect>)}
        {position && (
          <g>
            <line x1={x(position)} x2={x(position)} y1={6} y2={H - 4} stroke="#f472b6" strokeWidth={2} />
            <circle cx={x(position)} cy={8} r={5} fill="#f472b6" />
            <text x={Math.min(Math.max(x(position), 30), W - 30)} y={H - 1} textAnchor="middle" fontSize={10} fill="#f9a8d4" fontWeight={700}>{position}</text>
          </g>
        )}
        <text x={10} y={13} fontSize={9} fill="#64748b">1</text>
        <text x={W - 10} y={13} fontSize={9} fill="#64748b" textAnchor="end">{length}</text>
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-3 text-[10px] text-slate-500">
        {Object.entries(color).map(([k, c]) => <span key={k} className="inline-flex items-center gap-1"><span className="inline-block h-2 w-3 rounded-sm" style={{ background: c }} />{k}</span>)}
        <span className="inline-flex items-center gap-1"><span className="inline-block h-2 w-0.5 bg-amber-200" />Active / binding site</span>
        <span>· UniProt {protein.accession} canonical isoform</span>
      </figcaption>
    </figure>
  );
}

function ClassBlock({ title, cls }: { title: string; cls: any }) {
  if (!cls) return <div className="rounded-lg border border-line/60 p-2.5 text-xs text-slate-500"><div className="font-semibold uppercase tracking-wider">{title}</div>No classification</div>;
  return (
    <div className="rounded-lg border border-line bg-ink/40 p-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{title}</div>
      <div className="mt-1 text-sm font-semibold text-white">{cls.description}</div>
      <div className="text-[11px] text-amber-300">{stars(cls.stars)} <span className="text-slate-400">{cls.review_status}</span></div>
      {cls.traits?.length > 0 && <div className="mt-1 text-[11px] text-slate-400">{cls.traits.map((t: any) => t.name).slice(0, 3).join('; ')}</div>}
    </div>
  );
}

export default function Overview({ analysis }: { analysis: Analysis }) {
  const ov = analysis.overview;
  const [showSubs, setShowSubs] = useState(false);
  const r = analysis.resolution;
  const subGroups = useMemo(() => {
    const out: Record<string, number> = {};
    for (const s of ov?.clinvar_submissions ?? []) {
      const key = `${s.classification ?? 'no classification'}${s.classification_type && s.classification_type !== 'germline' ? ` (${s.classification_type.replace(/_/g, ' ')})` : ''}`;
      out[key] = (out[key] ?? 0) + 1;
    }
    return Object.entries(out).sort((a, b) => b[1] - a[1]);
  }, [ov]);
  if (!ov) return <Empty>No overview: the input was not resolved.</Empty>;
  const cv = ov.clinvar;
  const vep = ov.vep;
  const primary = vep?.primary;
  const protein = ov.protein;
  const fa = protein?.features_at_variant;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Variant identity" subtitle={r.status === 'gene_level' ? 'Gene-level view — no variant selected' : cv?.title ?? primary?.hgvsc ?? r.query}>
          <KV rows={[
            ['Gene', ov.gene ? <span>{ov.gene.symbol} <span className="text-slate-500">· {ov.gene.description}</span></span> : null],
            ['Ensembl / HGNC', ov.gene ? <span className="font-mono text-xs"><ExtLink href={ov.gene.url}>{ov.gene.ensembl_id}</ExtLink> · {ov.gene.hgnc_id}</span> : null],
            ['Protein change', r.protein_change ? <span className="font-mono">p.{r.protein_change.long} ({r.protein_change.short})</span> : null],
            ['ClinVar', cv ? <ExtLink href={cv.url}>{cv.accession_version ?? cv.accession}</ExtLink> : (r.status === 'gene_level' ? null : 'no record')],
            ['dbSNP', cv?.rsid ? <ExtLink href={`https://www.ncbi.nlm.nih.gov/snp/${cv.rsid}`}>{cv.rsid}</ExtLink> : null],
            ['GRCh38', cv?.grch38 ? <span className="font-mono text-xs">chr{cv.grch38.chr}:{cv.grch38.start} ({cv.grch38.band})</span> : (vep ? <span className="font-mono text-xs">chr{vep.chromosome}:{vep.start}</span> : null)],
            ['SPDI', cv?.canonical_spdi ? <span className="font-mono text-xs">{cv.canonical_spdi}</span> : null],
            ['Resolved via', r.resolved_via.join(' · ')],
          ]} />
        </Card>
        <Card title="Clinical classifications" subtitle="ClinVar aggregate classifications — germline and somatic are separate questions">
          {cv ? (
            <div className="space-y-2">
              <div className="grid gap-2 sm:grid-cols-3 xl:grid-cols-1 2xl:grid-cols-3">
                <ClassBlock title="Germline" cls={cv.germline} />
                <ClassBlock title="Somatic impact" cls={cv.somatic_clinical_impact} />
                <ClassBlock title="Oncogenicity" cls={cv.oncogenicity} />
              </div>
              {subGroups.length > 0 && (
                <div className="text-xs text-slate-400">
                  <div className="mb-1">{ov.clinvar_submissions.length} submissions:</div>
                  <div className="flex flex-wrap gap-1">{subGroups.map(([k, v]) => <Pill key={k}>{k} × {v}</Pill>)}</div>
                </div>
              )}
              {/uncertain/i.test(cv.germline?.description ?? '') && (
                <p className="rounded border border-amber-400/40 bg-amber-400/10 px-2 py-1 text-xs text-amber-100">Variant of Uncertain Significance (germline). Exploratory context only — not a basis for clinical decisions.</p>
              )}
            </div>
          ) : <Empty>{r.status === 'gene_level' ? 'Select a variant to see classifications.' : 'No ClinVar record for this exact variant — no submitted classification exists.'}</Empty>}
        </Card>
        <Card title="Predicted consequence" subtitle="Ensembl VEP — computational annotation">
          {primary ? (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-white">{primary.consequence_terms?.join(', ')}</span>
                <Pill tone={primary.impact === 'HIGH' ? 'rose' : primary.impact === 'MODERATE' ? 'amber' : 'slate'}>{primary.impact}</Pill>
                <CategoryChip category="computational" small />
              </div>
              <KV rows={[
                ['Transcript', <span className="font-mono text-xs">{primary.transcript_id}{primary.mane_select ? ` · MANE ${primary.mane_select}` : ''}</span>],
                ['HGVS c.', <span className="font-mono text-xs">{primary.hgvsc}</span>],
                ['HGVS p.', <span className="font-mono text-xs">{primary.hgvsp}</span>],
                ['Codons', primary.codons], ['Exon', primary.exon],
                ['SIFT', primary.sift_prediction ? `${primary.sift_prediction} (${primary.sift_score})` : 'not available'],
                ['PolyPhen-2', primary.polyphen_prediction ? `${primary.polyphen_prediction} (${primary.polyphen_score})` : 'not available'],
                ['Transcripts annotated', vep.transcript_count],
                ['Co-located records', `${vep.colocated?.rsids?.join(', ') || '—'}${vep.colocated?.cosmic?.length ? ` · ${vep.colocated.cosmic.join(', ')}` : ''}`],
              ]} />
              <p className="text-[11px] text-slate-500">Predictions are supporting evidence at most (ACMG/AMP PP3/BP4) and do not classify the variant.</p>
            </div>
          ) : <Empty>{r.status === 'gene_level' ? 'No variant selected.' : 'No VEP annotation (genomic coordinates unresolved or VEP unavailable).'}</Empty>}
        </Card>
      </div>

      {protein && (
        <Card title={`Protein context — ${protein.protein_name}`} subtitle={`UniProt ${protein.accession} · ${protein.length} aa · ${protein.feature_count} annotated features`}
          actions={<ExtLink href={protein.url} className="text-xs">UniProt entry ↗</ExtLink>}>
          <ProteinMap protein={protein} position={r.protein_change?.pos} />
          {r.residue_check && (
            <p className={`mt-3 text-xs ${r.residue_check.ok ? 'text-teal-200' : 'text-amber-200'}`}>
              {r.residue_check.ok ? '✓' : '⚠'} Reference residue {r.residue_check.position}: UniProt has <b>{r.residue_check.observed ?? '—'}</b>, input has <b>{r.residue_check.expected}</b>.
            </p>
          )}
          {fa && (
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Features covering the residue</div>
                {fa.covering.length ? fa.covering.map((f: any, i: number) => (
                  <div key={i} className="mb-1 text-xs text-slate-200">{f.type}: {f.description || '—'} ({f.start}–{f.end}) <CategoryChip category={f.category} small /></div>
                )) : <div className="text-xs text-slate-500">None annotated.</div>}
              </div>
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Known variants / mutagenesis at this residue</div>
                {fa.at_residue.length ? fa.at_residue.slice(0, 4).map((f: any, i: number) => (
                  <div key={i} className="mb-1 text-xs text-slate-300"><b className="text-slate-100">{f.original}{f.start}{(f.alternatives ?? []).join('/')}</b> — {f.description.slice(0, 180)}{f.description.length > 180 ? '…' : ''}</div>
                )) : <div className="text-xs text-slate-500">None annotated.</div>}
              </div>
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Sites within 5 residues (proximity only)</div>
                {fa.nearby.length ? fa.nearby.slice(0, 5).map((f: any, i: number) => (
                  <div key={i} className="mb-1 text-xs text-slate-300">{f.type} {f.start}{f.end !== f.start ? `–${f.end}` : ''} {f.description && `· ${f.description}`} <span className="text-slate-500">({f.distance} aa away)</span></div>
                )) : <div className="text-xs text-slate-500">None.</div>}
              </div>
            </div>
          )}
        </Card>
      )}

      {ov.clinvar_submissions?.length > 0 && (
        <Card title={`ClinVar submissions (${ov.clinvar_submissions.length})`} subtitle="Individual submitter interpretations — preserved, not collapsed"
          actions={<button className="text-xs text-cyan-300" onClick={() => setShowSubs(!showSubs)}>{showSubs ? 'Collapse' : 'Show all'}</button>}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-slate-400"><tr className="border-b border-line">
                <th className="py-1.5 pr-3">Submission</th><th className="pr-3">Submitter</th><th className="pr-3">Classification</th><th className="pr-3">Review status</th><th className="pr-3">Origin</th><th className="pr-3">Condition</th><th>Evaluated</th>
              </tr></thead>
              <tbody>
                {(showSubs ? ov.clinvar_submissions : ov.clinvar_submissions.slice(0, 8)).map((s: any) => (
                  <tr key={s.scv} className="border-b border-line/40 align-top">
                    <td className="py-1.5 pr-3 font-mono"><ExtLink href={s.url}>{s.scv}</ExtLink></td>
                    <td className="pr-3 text-slate-300">{s.submitter}</td>
                    <td className="pr-3 text-slate-100">{s.classification ?? '—'}{s.therapeutic_context?.DrugForTherapeuticAssertion ? ` · ${s.therapeutic_context.DrugForTherapeuticAssertion}` : ''}<div className="text-[10px] text-slate-500">{s.classification_type?.replace(/_/g, ' ')}</div></td>
                    <td className="pr-3 text-slate-400">{s.review_status}</td>
                    <td className="pr-3 text-slate-400">{s.origin}</td>
                    <td className="pr-3 text-slate-300">{(s.conditions ?? []).join('; ')}</td>
                    <td className="text-slate-400">{s.date_last_evaluated ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        {ov.civic && (
          <Card title="CIViC clinical evidence (cancer)" subtitle={ov.civic.profile ? `Molecular profile ${ov.civic.profile.name} · ${ov.civic.total} accepted items` : 'No exactly matching molecular profile'}
            actions={ov.civic.profile && <ExtLink href={ov.civic.profile.url} className="text-xs">CIViC ↗</ExtLink>}>
            {ov.civic.items?.length ? (
              <div className="max-h-80 overflow-auto">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-panel text-slate-400"><tr className="border-b border-line"><th className="py-1 pr-2">EID</th><th className="pr-2">Type</th><th className="pr-2">Lvl</th><th className="pr-2">Significance</th><th className="pr-2">Therapy</th><th>Disease</th></tr></thead>
                  <tbody>{ov.civic.items.map((i: any) => (
                    <tr key={i.eid} className="border-b border-line/40 align-top">
                      <td className="py-1 pr-2"><ExtLink href={i.url}>{i.eid}</ExtLink></td>
                      <td className="pr-2 text-slate-300">{i.type?.toLowerCase()}</td>
                      <td className="pr-2 font-semibold text-slate-100" title={i.level_label}>{i.level}</td>
                      <td className="pr-2 text-slate-300">{i.significance?.toLowerCase().replace('sensitivityresponse', 'sensitivity/response')}{i.direction === 'DOES_NOT_SUPPORT' && <span className="text-amber-300"> (does not support)</span>}</td>
                      <td className="pr-2 text-slate-300">{(i.therapies ?? []).join(' + ')}</td>
                      <td className="text-slate-400">{i.disease}</td>
                    </tr>))}
                  </tbody>
                </table>
              </div>
            ) : <Empty>{ov.civic.related_profiles?.length ? `Related composite profiles: ${ov.civic.related_profiles.map((p: any) => p.name).join(', ')}` : 'CIViC has no curated evidence for this exact variant.'}</Empty>}
            <p className="mt-2 text-[11px] text-slate-500">Disease-specific curated evidence (CC0). Not a treatment recommendation.</p>
          </Card>
        )}
        {ov.opentargets?.associations && (
          <Card title="Gene-level disease associations" subtitle={`Open Targets · ${ov.opentargets.associations.count} associated diseases for ${ov.gene?.symbol}`}
            actions={<ExtLink href={ov.opentargets.associations.url} className="text-xs">Open Targets ↗</ExtLink>}>
            <ul className="space-y-1.5">
              {ov.opentargets.associations.rows.slice(0, 10).map((row: any) => (
                <li key={row.disease_id} className="flex items-center gap-2 text-xs">
                  <span className="w-48 shrink-0 truncate text-slate-200" title={row.name}><ExtLink href={row.url}>{row.name}</ExtLink></span>
                  <span className="h-2 flex-1 rounded bg-slate-800"><span className="block h-2 rounded bg-orange-400/80" style={{ width: `${Math.round(row.score * 100)}%` }} /></span>
                  <span className="w-10 text-right font-mono text-slate-400">{row.score.toFixed(2)}</span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] text-slate-500">Association score: relative 0–1 aggregate across evidence types — not a probability and not variant-specific.</p>
            {ov.opentargets.drugs && (
              <div className="mt-3 border-t border-line pt-2 text-xs text-slate-400">
                {ov.opentargets.drugs.total_targeting} drug/clinical candidate(s) with a curated mechanism on {ov.gene?.symbol}
                {ov.opentargets.drugs.excluded_other_target?.length > 0 && <> · {ov.opentargets.drugs.excluded_other_target.length} listed candidate(s) act through other targets and are not drawn</>}.
              </div>
            )}
          </Card>
        )}
      </div>
    </div>
  );
}
