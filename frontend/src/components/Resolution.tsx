import { useState } from 'react';
import type { Analysis } from '../types';
import { Button, Pill } from './ui';

const STATUS: Record<string, { label: string; tone: 'teal' | 'amber' | 'rose' | 'violet' | 'sky' | 'slate' }> = {
  resolved: { label: 'Resolved', tone: 'teal' },
  protein_level: { label: 'Protein-level only', tone: 'amber' },
  gene_level: { label: 'Gene-level exploration', tone: 'sky' },
  ambiguous: { label: 'Ambiguous input', tone: 'amber' },
  not_found: { label: 'Not found', tone: 'rose' },
  invalid: { label: 'Invalid input', tone: 'rose' },
  error: { label: 'Source error', tone: 'rose' },
};

export default function ResolutionBanner({ analysis, onQuery }: { analysis: Analysis; onQuery: (q: string) => void }) {
  const r = analysis.resolution;
  const [open, setOpen] = useState(r.status !== 'resolved');
  const s = STATUS[r.status] ?? { label: r.status, tone: 'slate' as const };
  const problem = ['ambiguous', 'not_found', 'invalid', 'error'].includes(r.status);
  return (
    <div className={`rounded-xl border ${problem ? 'border-amber-400/40 bg-amber-400/5' : 'border-line bg-panel/80'} px-4 py-3`}>
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone={s.tone}>{s.label}</Pill>
        <span className="text-xs text-slate-400">Input: <span className="font-mono text-slate-200">{r.query}</span> · detected as {r.input_type.replace(/_/g, ' ')}</span>
        {analysis.snapshot && <Pill tone="violet">Snapshot · data frozen {analysis.snapshot.saved_at ? new Date(analysis.snapshot.saved_at).toLocaleDateString() : ''}</Pill>}
        {analysis.mode === 'offline_replay' && <Pill tone="violet">Offline replay (cached responses)</Pill>}
        <button className="ml-auto text-xs text-cyan-300" onClick={() => setOpen(!open)}>{open ? 'Hide interpretation' : 'How was this interpreted?'}</button>
      </div>
      <p className="mt-2 text-sm text-slate-100">{r.message}</p>
      {r.warnings.length > 0 && (
        <ul className="mt-2 space-y-1">
          {r.warnings.map((w, i) => <li key={i} className="text-xs text-amber-200">⚠ {w}</li>)}
        </ul>
      )}
      {r.candidates.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs text-slate-400">Choose what you meant — PathwayGPS will not choose for you:</div>
          <div className="flex flex-wrap gap-2">
            {r.candidates.map((c) => (
              <Button key={c.query} variant="outline" onClick={() => onQuery(c.query)} title={c.reason}>{c.label}</Button>
            ))}
          </div>
        </div>
      )}
      {r.clinvar_alternatives.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-400">
          Other nucleotide-level records for this protein change:
          {r.clinvar_alternatives.map((a) => <Button key={a.variation_id} variant="outline" onClick={() => onQuery(a.query)} title={a.title}>{a.accession}</Button>)}
        </div>
      )}
      {open && r.steps.length > 0 && (
        <ol className="mt-3 space-y-1 border-t border-line pt-3">
          {r.steps.map((st, i) => (
            <li key={i} className="flex gap-2 text-xs">
              <span className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${st.outcome === 'ok' ? 'bg-teal-400' : st.outcome === 'warning' ? 'bg-amber-400' : st.outcome === 'failed' ? 'bg-rose-400' : 'bg-slate-500'}`} />
              <span className="w-44 shrink-0 text-slate-400">{st.step} <span className="text-slate-500">· {st.source}</span></span>
              <span className="text-slate-200">{st.detail}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
