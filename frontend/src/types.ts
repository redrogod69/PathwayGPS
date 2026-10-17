// Data contracts mirrored from backend/app (domain/model.py, pipeline/service.py).

export type Category = 'curated' | 'experimental' | 'association' | 'computational' | 'inferred' | 'hypothesis';
export type NodeType =
  | 'variant' | 'gene' | 'protein' | 'protein_region' | 'reactome_entity' | 'reaction' | 'pathway'
  | 'physical_entity' | 'interactor' | 'disease' | 'drug';

export interface Xref { db: string; id: string; url?: string | null }

export interface GNode {
  id: string; type: NodeType; label: string; source: string; subtitle?: string | null;
  xrefs: Xref[]; attributes: Record<string, any>; role: string; secondary: boolean; flags: string[]; tier: number;
}

export interface GEdge {
  id: string; source: string; target: string; type: string; label: string; evidence: string[];
  category: Category; categories: Category[]; secondary: boolean; attributes: Record<string, any>;
}

export interface Evidence {
  id: string; source: string; record_id: string; record_url?: string | null; evidence_type: string; category: Category;
  statement: string; retrieved_at?: string | null; release?: string | null; publications: string[];
  classification?: string | null; review_status?: string | null; origin?: string | null; direction?: string | null;
  method?: string | null; score?: { name: string; value: any; meaning: string } | null; inference?: string | null;
  limitations: string[]; context: Record<string, any>;
}

export interface Publication {
  pmid: string; title: string; journal?: string; year?: string; authors?: string[]; doi?: string | null; pmc?: string | null;
  pubtypes?: string[]; design?: string[]; url: string;
}

export interface SourceStatus {
  source: string; name: string; status: 'ok' | 'partial' | 'failed' | 'skipped'; calls: number; failed_calls: number;
  from_cache: number; stale_cache: number; last_retrieved_at?: string | null; errors: string[]; notes: string[];
  release?: string | null; license: string; homepage: string;
}

export interface Step { step: string; source: string; outcome: 'ok' | 'warning' | 'failed' | 'skipped'; detail: string }

export interface Resolution {
  query: string; input_type: string; status: string; message: string; parsed: any;
  gene?: any; protein?: any; protein_change?: { short: string; long: string; pos: number; ref: string; alt: string; kind: string } | null;
  clinvar_variation_id?: string | null; clinvar_alternatives: { variation_id: string; accession: string; title: string; url: string; query: string }[];
  residue_check?: { position: number; expected: string; observed?: string; ok: boolean; accession: string; length: number } | null;
  steps: Step[]; warnings: string[]; candidates: { label: string; query: string; reason: string }[]; resolved_via: string[];
}

export interface Conflict {
  kind: string; title: string; summary: string; explanation: string; source: string;
  positions: { label: string; count: number; records: { id: string; url?: string; submitter?: string; classification?: string; review_status?: string; origin?: string; date?: string; conditions?: string[] }[] }[];
}

export interface Gap { kind: string; message: string }

export interface Claim { text: string; evidence: string[]; kind: string }
export interface Synthesis { mode: string; model?: string | null; claims: Claim[]; disclaimer?: string; follow_up_searches?: string[]; rejected_claims?: number; message?: string }

export interface Impact {
  direct: { label: string; value: string; detail?: string; category: Category; source: string }[];
  downstream: { node_id: string; label: string; type: string; hops: number; verdict: string; disease_event: boolean }[];
  associations: { node_id: string; label: string; type: string; hops: number; verdict: string; level: string; sources?: string[] }[];
  hypotheses: { node_id: string; text: string; basis: string; category: string }[];
  counts: Record<string, number>;
  focus_pathway?: { stId: string; name: string; reactions_involving_protein: number; reason?: string } | null;
}

export interface Analysis {
  analysis_id: string; created_at: string; query: string; mode: string;
  snapshot: null | { id: string | null; saved_at?: string; original_created_at?: string; statement: string; workbench?: any };
  resolution: Resolution; root_id: string | null;
  graph: { nodes: GNode[]; edges: GEdge[]; evidence: Record<string, Evidence> };
  publications: Record<string, Publication>;
  conflicts: Conflict[]; gaps: Gap[]; impact: Impact | null; synthesis: Synthesis | null; ai_synthesis?: Synthesis | null;
  overview: any; sources: SourceStatus[]; limitations: string[]; display_rules?: Record<string, string>;
  assistant_suggestions?: string[] | null;
  ai: { enabled: boolean; sdk_installed: boolean; key_configured: boolean; model: string };
}

export interface PathHop {
  edge_id: string; from: string; to: string; from_label: string; to_label: string; type: string; label: string;
  direction: 'forward' | 'reverse'; category: Category; categories: Category[]; evidence_count: number; publication_count: number; sources: string[];
}
export interface PathResult {
  found: boolean; source: string; target: string; message?: string; nodes?: string[]; hops?: PathHop[]; verdict?: string; verdict_text?: string;
  weakest_category?: Category; reverse_hops?: number;
}

export interface WorkbenchNote {
  id: string; target_id: string; target_label: string; kind: 'observation' | 'question' | 'hypothesis'; text: string;
  evidence_ids: string[]; created: string;
}
export interface Workbench { notes: WorkbenchNote[]; marked: string[] }
