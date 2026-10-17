import { useState } from 'react';
import { api } from '../api';
import type { Evidence, Publication } from '../types';
import { shortDate } from '../lib/vocab';
import { CategoryChip, ExtLink, SourceChip, Spinner } from './ui';

export function PublicationRow({ pmid, pub }: { pmid: string; pub?: Publication }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<{ loading: boolean; error?: string; data?: Awaited<ReturnType<typeof api.abstract>> }>({ loading: false });
  const toggle = async () => {
    setOpen(!open);
    if (!open && !state.data && !state.loading) {
      setState({ loading: true });
      try {
        setState({ loading: false, data: await api.abstract(pmid) });
      } catch (e) {
        setState({ loading: false, error: (e as Error).message });
      }
    }
  };
  return (
    <li className="rounded-md border border-line/70 bg-ink/60 px-2.5 py-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 text-xs">
          {pub ? (
            <>
              <div className="font-medium text-slate-100">{pub.title}</div>
              <div className="mt-0.5 text-slate-400">
                {(pub.authors ?? []).join(', ')} · <i>{pub.journal}</i> {pub.year}
                {pub.design && pub.design.length > 0 && <span className="ml-1 rounded bg-violet-400/10 px-1 text-violet-200">{pub.design.join(', ')}</span>}
              </div>
            </>
          ) : (
            <div className="text-slate-300">PMID {pmid} <span className="text-slate-500">(metadata not retrieved)</span></div>
          )}
          <div className="mt-1 flex flex-wrap gap-2 text-[11px]">
            <ExtLink href={`https://pubmed.ncbi.nlm.nih.gov/${pmid}/`}>PMID {pmid}</ExtLink>
            {pub?.doi && <ExtLink href={`https://doi.org/${pub.doi}`}>DOI</ExtLink>}
            {pub?.pmc && <ExtLink href={`https://pmc.ncbi.nlm.nih.gov/articles/${pub.pmc}/`}>Full text (PMC)</ExtLink>}
          </div>
        </div>
        <button onClick={toggle} className="shrink-0 rounded border border-line px-1.5 py-0.5 text-[10px] text-slate-300 hover:border-cyan-400/60">
          {open ? 'Hide' : 'Abstract'}
        </button>
      </div>
      {open && (
        <div className="mt-2 border-t border-line/60 pt-2 text-xs leading-relaxed text-slate-300">
          {state.loading && <Spinner label="Fetching abstract from PubMed…" />}
          {state.error && <div className="text-rose-300">Abstract unavailable: {state.error}</div>}
          {state.data && (state.data.sections.length ? (
            <>
              {state.data.sections.map((s, i) => (
                <p key={i} className="mb-1.5">{s.label && <b className="text-slate-200">{s.label}: </b>}{s.text}</p>
              ))}
              <p className="text-[10px] text-slate-500">Shown on request from PubMed{state.data.copyright ? ` · ${state.data.copyright}` : ''}. Not stored or exported.</p>
            </>
          ) : <div className="text-slate-400">PubMed has no abstract for this record.</div>)}
        </div>
      )}
    </li>
  );
}

export function EvidenceCard({ ev, pubs }: { ev: Evidence; pubs: Record<string, Publication> }) {
  const [showAll, setShowAll] = useState(false);
  const list = showAll ? ev.publications : ev.publications.slice(0, 3);
  return (
    <article className="rounded-lg border border-line bg-ink/40 p-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <CategoryChip category={ev.category} small />
        <SourceChip source={ev.source} />
        <span className="text-[11px] text-slate-400">{ev.evidence_type}</span>
      </div>
      <p className="mt-2 text-sm leading-snug text-slate-100">{ev.statement}</p>
      <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-[11px]">
        {ev.classification && <><dt className="text-slate-500">Source classification</dt><dd className="text-slate-200">{ev.classification}</dd></>}
        {ev.review_status && <><dt className="text-slate-500">Review status</dt><dd className="text-slate-200">{ev.review_status}</dd></>}
        {ev.origin && <><dt className="text-slate-500">Origin</dt><dd className="text-slate-200">{ev.origin}</dd></>}
        {ev.direction && <><dt className="text-slate-500">Direction</dt><dd className="text-slate-200">{ev.direction.replace(/_/g, ' ').toLowerCase()}</dd></>}
        {ev.method && <><dt className="text-slate-500">Method</dt><dd className="text-slate-200">{ev.method}</dd></>}
        {ev.score && <><dt className="text-slate-500">{ev.score.name}</dt><dd className="text-slate-200">{String(ev.score.value)} <span className="text-slate-500">— {ev.score.meaning}</span></dd></>}
        {ev.context?.disease && <><dt className="text-slate-500">Disease context</dt><dd className="text-slate-200">{ev.context.disease}</dd></>}
        {ev.context?.date_last_evaluated && <><dt className="text-slate-500">Last evaluated</dt><dd className="text-slate-200">{ev.context.date_last_evaluated}</dd></>}
        <dt className="text-slate-500">Record</dt>
        <dd><ExtLink href={ev.record_url}>{ev.record_id}</ExtLink></dd>
        <dt className="text-slate-500">Retrieved</dt>
        <dd className="text-slate-300">{shortDate(ev.retrieved_at)}{ev.release ? ` · release ${ev.release}` : ''}</dd>
      </dl>
      {ev.inference && <p className="mt-2 rounded border border-slate-500/30 bg-slate-500/10 px-2 py-1 text-[11px] text-slate-300"><b>PathwayGPS inference:</b> {ev.inference}</p>}
      {ev.context?.description && <p className="mt-2 text-[11px] leading-relaxed text-slate-400">“{ev.context.description}” <span className="text-slate-500">— curator summary ({ev.source})</span></p>}
      {ev.context?.summation && <p className="mt-2 text-[11px] leading-relaxed text-slate-400">{ev.context.summation}… <span className="text-slate-500">— Reactome summation</span></p>}
      {ev.limitations.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-[11px] text-amber-200/90">
          {ev.limitations.map((l, i) => <li key={i}>⚠ {l}</li>)}
        </ul>
      )}
      {ev.publications.length > 0 ? (
        <div className="mt-2">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Supporting publications ({ev.publications.length})</div>
          <ul className="space-y-1.5">{list.map((p) => <PublicationRow key={p} pmid={p} pub={pubs[p]} />)}</ul>
          {ev.publications.length > 3 && (
            <button className="mt-1 text-[11px] text-cyan-300" onClick={() => setShowAll(!showAll)}>{showAll ? 'Show fewer' : `Show all ${ev.publications.length}`}</button>
          )}
        </div>
      ) : (
        <p className="mt-2 text-[11px] italic text-slate-500">No publication is attached to this record in the source; none is invented.</p>
      )}
    </article>
  );
}
