import { FormEvent, useEffect, useRef, useState } from 'react';
import { Bot, Lightbulb, Send, Sparkles, User } from 'lucide-react';
import { api } from '../api';
import type { Analysis } from '../types';
import { SOURCE_LABEL } from '../lib/vocab';
import { CloseButton } from './Shell';
import { CategoryChip } from './ui';

interface Msg { role: 'user' | 'assistant'; content: string; citations?: string[]; mode?: string; notice?: string; time: string; follow?: string[] }

const now = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

function renderText(text: string) {
  // **bold** and [ev-…] markers (citations are rendered separately as chips)
  return text.split('\n').map((line, i) => (
    <p key={i} className="mb-1.5 last:mb-0">
      {line.replace(/\s*\[ev-[^\]]+\]/g, '').split(/(\*\*[^*]+\*\*)/).map((part, j) => part.startsWith('**') ? <b key={j} className="text-white">{part.slice(2, -2)}</b> : part)}
    </p>
  ));
}

export default function AssistantModal({ analysis, onClose, onEvidence }: { analysis: Analysis | null; onClose: () => void; onEvidence: (evidenceId: string) => void }) {
  const root = analysis?.graph.nodes.find((n) => n.id === analysis?.root_id);
  const key = analysis?.analysis_id ?? 'none';
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const ai = analysis?.ai?.enabled;
    setMsgs(analysis?.root_id ? [{
      role: 'assistant', time: now(), mode: ai ? 'claude' : 'retrieval',
      content: `Hello! I am your PathwayGPS Research Assistant, grounded in the evidence retrieved for **${root?.label}**${analysis.resolution.gene ? ` (${analysis.resolution.gene.symbol})` : ''}.\n` +
        `I can explain signalling mechanisms, separate curated from computational evidence, surface conflicts and gaps, and list therapies with curated evidence — every answer cites the evidence records it is built from.\n` +
        (ai ? `Mode: Claude (${analysis.ai.model}), restricted to the evidence ledger.` : 'Mode: evidence retrieval (no language model configured) — answers are assembled directly from source records.'),
    }] : [{ role: 'assistant', time: now(), content: 'Analyse a variant first (e.g. **EGFR L858R**). I only answer from evidence retrieved for the active analysis.' }]);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }); }, [msgs, busy]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const ask = async (text: string) => {
    if (!text.trim() || !analysis?.root_id || busy) return;
    const next: Msg[] = [...msgs, { role: 'user', content: text.trim(), time: now() }];
    setMsgs(next); setInput(''); setBusy(true);
    try {
      const res = await api.chat(analysis.analysis_id, next.filter((m, i) => i > 0).map((m) => ({ role: m.role, content: m.content })));
      setMsgs([...next, { role: 'assistant', content: res.answer, citations: res.citations, mode: res.mode, notice: res.notice, time: now(), follow: res.follow_up }]);
    } catch (e) {
      setMsgs([...next, { role: 'assistant', content: `Request failed: ${(e as Error).message}`, time: now() }]);
    } finally { setBusy(false); }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); ask(input); };
  const suggestions = msgs.length <= 1 ? (analysis?.assistant_suggestions ?? []).slice(0, 3) : (msgs[msgs.length - 1].follow ?? []).slice(0, 2);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }} role="dialog" aria-modal="true" aria-label="AI Research Assistant">
      <div className="flex h-[min(760px,92vh)] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-cyan-500/30 bg-panel shadow-2xl shadow-cyan-950/50">
        <div className="flex items-start justify-between gap-3 border-b border-slate-800 px-4 py-3">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-cyan-500/40 bg-cyan-500/10 text-cyan-300"><Sparkles className="h-4 w-4" /></span>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-bold text-white">PathwayGPS AI Research Assistant</span>
                {root && <span className="rounded-md border border-cyan-700/60 bg-cyan-950/60 px-2 py-0.5 font-mono text-[11px] font-bold text-cyan-300">Grounded in {root.label}</span>}
              </div>
              <div className="text-[11px] text-slate-400">Answers only from ClinVar, VEP, UniProt, Reactome, IntAct, Open Targets, CIViC and PubMed records in this analysis · not clinical advice</div>
            </div>
          </div>
          <CloseButton onClick={onClose} />
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {msgs.map((m, i) => (
            <div key={i} className={`flex gap-3 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border ${m.role === 'user' ? 'border-slate-700 bg-slate-800 text-slate-300' : 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300'}`}>
                {m.role === 'user' ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
              </span>
              <div className={`max-w-[85%] rounded-2xl border px-4 py-3 text-sm leading-relaxed ${m.role === 'user' ? 'border-cyan-500/30 bg-cyan-500/10 text-slate-100' : 'border-slate-800 bg-slate-900/70 text-slate-200'}`}>
                {renderText(m.content)}
                {m.notice && <p className="mt-2 text-[11px] text-amber-300">{m.notice}</p>}
                {m.citations && m.citations.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1 border-t border-slate-800 pt-2">
                    <span className="mr-1 text-[10px] uppercase tracking-wider text-slate-500">Evidence</span>
                    {m.citations.slice(0, 10).map((id) => {
                      const ev = analysis?.graph.evidence[id];
                      return (
                        <button key={id} onClick={() => onEvidence(id)} title={ev?.statement}
                          className="inline-flex items-center gap-1 rounded border border-slate-700 px-1.5 py-0.5 font-mono text-[10px] text-cyan-200 hover:border-cyan-400/60">
                          {ev && <CategoryChip category={ev.category} small />}{ev ? `${SOURCE_LABEL[ev.source] ?? ev.source}:${ev.record_id}`.slice(0, 32) : id}
                        </button>
                      );
                    })}
                  </div>
                )}
                <div className="mt-1.5 text-right font-mono text-[10px] text-slate-500">{m.mode && m.role === 'assistant' && i > 0 ? `${m.mode} · ` : ''}{m.time}</div>
              </div>
            </div>
          ))}
          {busy && <div className="flex items-center gap-2 pl-10 text-xs text-slate-400"><span className="h-3 w-3 animate-spin rounded-full border-2 border-cyan-400/30 border-t-cyan-300" />Consulting the evidence ledger…</div>}
          <div ref={end} />
        </div>
        {suggestions.length > 0 && (
          <div className="space-y-1.5 border-t border-slate-800 px-4 py-2.5">
            {suggestions.map((s) => (
              <button key={s} onClick={() => ask(s)} disabled={busy} className="flex w-full items-center gap-1.5 rounded-full border border-slate-800 bg-slate-900/60 px-3 py-1 text-left text-[11px] text-slate-300 hover:border-cyan-500/40 disabled:opacity-50">
                <Lightbulb className="h-3 w-3 shrink-0 text-amber-300" />{s}
              </button>
            ))}
          </div>
        )}
        <form onSubmit={submit} className="flex items-center gap-2 border-t border-slate-800 p-3">
          <input value={input} onChange={(e) => setInput(e.target.value)} disabled={!analysis?.root_id || busy} autoFocus
            placeholder={analysis?.root_id ? 'Ask about this variant, signalling cascades, or clinical evidence…' : 'Analyse a variant to start'}
            className="flex-1 rounded-xl border border-slate-800 bg-slate-950 px-4 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-cyan-500/70 focus:outline-none" />
          <button type="submit" disabled={!input.trim() || busy || !analysis?.root_id} aria-label="Send"
            className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-500 text-slate-950 hover:bg-cyan-400 disabled:opacity-40"><Send className="h-4 w-4" /></button>
        </form>
      </div>
    </div>
  );
}
