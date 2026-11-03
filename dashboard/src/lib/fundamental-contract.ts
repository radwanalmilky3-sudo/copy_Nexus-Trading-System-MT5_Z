export interface DomainContractInput {
  state?: string;
  metadata?: Record<string, unknown>;
  details?: Array<Record<string, unknown>>;
}

export type ScoreState = 'AVAILABLE' | 'UNAVAILABLE';
export type EvidenceState = 'PRESENT' | 'NONE';
export type DomainState = 'DATA_AVAILABLE' | 'DEGRADED' | 'UNAVAILABLE';

export interface DomainContract {
  score_state: ScoreState;
  evidence_state: EvidenceState;
  evidence_count: number;
  domain_state: DomainState;
}

export function deriveDomainContract(domain?: DomainContractInput | null): DomainContract {
  if (!domain) {
    return { score_state: 'UNAVAILABLE', evidence_state: 'NONE', evidence_count: 0, domain_state: 'UNAVAILABLE' };
  }
  const declaredUnavailable =
    domain.state === 'unavailable' || domain.metadata?.state === 'unavailable';
  const score_state: ScoreState = declaredUnavailable ? 'UNAVAILABLE' : 'AVAILABLE';
  const evidence_count = domain.details?.length ?? 0;
  const evidence_state: EvidenceState = evidence_count > 0 ? 'PRESENT' : 'NONE';
  let domain_state: DomainState;
  if (score_state === 'AVAILABLE') {
    domain_state = 'DATA_AVAILABLE';
  } else if (evidence_count > 0) {
    domain_state = 'DEGRADED';
  } else {
    domain_state = 'UNAVAILABLE';
  }
  return { score_state, evidence_state, evidence_count, domain_state };
}
