import type { Category, NodeType } from '../types';

export const NODE_STYLE: Record<NodeType, { color: string; label: string; shape: string }> = {
  variant: { color: '#f472b6', label: 'Variant', shape: 'star' },
  gene: { color: '#34d399', label: 'Gene', shape: 'round-rectangle' },
  protein: { color: '#22d3ee', label: 'Protein', shape: 'round-rectangle' },
  protein_region: { color: '#5eead4', label: 'Protein feature', shape: 'round-tag' },
  reactome_entity: { color: '#f9a8d4', label: 'Curated mutant entity', shape: 'diamond' },
  pathway: { color: '#818cf8', label: 'Pathway', shape: 'round-hexagon' },
  reaction: { color: '#a78bfa', label: 'Reaction', shape: 'ellipse' },
  physical_entity: { color: '#c4b5fd', label: 'Downstream entity', shape: 'round-octagon' },
  interactor: { color: '#94a3b8', label: 'Interacting protein', shape: 'ellipse' },
  disease: { color: '#fb923c', label: 'Disease / phenotype', shape: 'round-triangle' },
  drug: { color: '#facc15', label: 'Drug / therapy', shape: 'round-diamond' },
};

export const CATEGORY_STYLE: Record<Category, { color: string; line: 'solid' | 'dashed' | 'dotted'; label: string; help: string }> = {
  curated: { color: '#2dd4bf', line: 'solid', label: 'Curated', help: 'Expert-curated database assertion (Reactome, ClinVar submission, CIViC, ChEMBL, UniProt manual annotation).' },
  experimental: { color: '#60a5fa', line: 'solid', label: 'Experimental', help: 'Experimental observation without pathway curation (IntAct interaction, UniProt mutagenesis).' },
  association: { color: '#fb923c', line: 'dashed', label: 'Association', help: 'Aggregated statistical / literature association (Open Targets). Gene-level, not mechanistic.' },
  computational: { color: '#38bdf8', line: 'dotted', label: 'Computational', help: 'Algorithmic prediction or rule-based annotation (VEP consequence, SIFT, PolyPhen, sequence-model features).' },
  inferred: { color: '#94a3b8', line: 'dashed', label: 'Inferred', help: 'Derived by PathwayGPS (e.g. coordinate overlap) or by orthology in Reactome.' },
  hypothesis: { color: '#f472b6', line: 'dotted', label: 'Hypothesis', help: 'User or AI suggestion that requires validation. Never evidence.' },
};

export const SOURCE_LABEL: Record<string, string> = {
  clinvar: 'ClinVar', pubmed: 'PubMed', ensembl: 'Ensembl VEP', uniprot: 'UniProt', reactome: 'Reactome', intact: 'IntAct',
  opentargets: 'Open Targets', civic: 'CIViC', user: 'User input', anthropic: 'Claude',
};

export const RELATION_LABEL: Record<string, string> = {
  VARIANT_IN_GENE: 'Variant located in gene',
  GENE_ENCODES_PROTEIN: 'Gene encodes protein',
  VARIANT_ALTERS_PROTEIN: 'Variant alters protein residue',
  VARIANT_IN_PROTEIN_REGION: 'Variant falls within protein feature',
  PROTEIN_HAS_REGION: 'Protein has annotated feature',
  VARIANT_REPRESENTED_AS: 'Variant curated as Reactome entity',
  MUTANT_ENTITY_IN_PATHWAY: 'Mutant entity participates in pathway',
  PROTEIN_PARTICIPATES_IN_PATHWAY: 'Protein participates in pathway',
  PROTEIN_PARTICIPATES_IN_REACTION: 'Protein participates in reaction',
  REACTION_PART_OF_PATHWAY: 'Reaction is part of pathway',
  REACTION_PRECEDES: 'Reaction precedes reaction',
  REACTION_PRODUCES: 'Reaction produces entity',
  ENTITY_INPUT_OF_REACTION: 'Entity is input of reaction',
  PROTEIN_INTERACTS_WITH_PROTEIN: 'Protein–protein interaction',
  VARIANT_ASSOCIATED_WITH_CONDITION: 'Variant classified / evidenced for condition',
  VARIANT_PREDICTIVE_FOR_THERAPY: 'Variant has predictive evidence for therapy',
  TARGET_ASSOCIATED_WITH_DISEASE: 'Gene associated with disease (gene-level)',
  DRUG_TARGETS_PROTEIN: 'Drug targets protein (mechanism)',
};

export const VERDICT_LABEL: Record<string, { text: string; tone: string }> = {
  supported_by_curated_or_experimental_evidence: { text: 'Fully supported', tone: 'text-teal-300 border-teal-400/40 bg-teal-400/10' },
  contains_association_steps: { text: 'Contains association', tone: 'text-orange-300 border-orange-400/40 bg-orange-400/10' },
  contains_computational_steps: { text: 'Contains prediction', tone: 'text-sky-300 border-sky-400/40 bg-sky-400/10' },
  contains_inferred_steps: { text: 'Contains inferred step', tone: 'text-slate-300 border-slate-400/40 bg-slate-400/10' },
  hypothesis: { text: 'Hypothesis', tone: 'text-pink-300 border-pink-400/40 bg-pink-400/10' },
};

export const EXPAND_ACTIONS: Partial<Record<NodeType, { action: string; label: string; help: string }[]>> = {
  protein: [{ action: 'all_pathways', label: 'Show all pathways', help: 'Add every Reactome pathway mapped to this protein.' }],
  pathway: [{ action: 'reactions', label: 'Reactions involving the protein', help: 'Add reactions of this pathway in which the protein participates.' }],
  reaction: [{ action: 'downstream', label: 'Trace downstream', help: 'Add Reactome following events (curated event order) and their outputs.' }],
  physical_entity: [{ action: 'consumers', label: 'Reactions consuming this', help: 'Add reactions that take this entity as an input.' }],
  reactome_entity: [{ action: 'consumers', label: 'Reactions consuming this', help: 'Add reactions that take this entity as an input.' }],
};

export function stars(n?: number | null) {
  if (n === null || n === undefined) return '';
  return '★'.repeat(n) + '☆'.repeat(Math.max(0, 4 - n));
}

export function shortDate(iso?: string | null) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  } catch {
    return iso;
  }
}
