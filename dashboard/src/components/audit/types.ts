export type AuditStatus = 'pending' | 'in_progress' | 'done' | 'unknown';

export type AuditItem = {
  id: string;
  name: string;
  description?: string;
  parent_id?: string | null;
  status?: AuditStatus;
  is_current?: boolean;
  notes?: string;
  error?: string | null;
  fix?: string | null;
  code?: number | null;
  database?: number | null;
  dashboard?: number | null;
  tests?: number | null;
  audit?: number | null;
  [key: string]: unknown;
};

export type AuditSnapshot = {
  last_updated?: string;
  current_task?: { id?: string; name?: string } | string | null;
  items: AuditItem[];
};

export type AuditSectionState = 'ready' | 'empty' | 'unavailable';

export type AuditEvidence = {
  status: 'available' | 'degraded';
  source: string;
  state: {
    file: string;
    sha256: string | null;
    last_updated?: string;
    error?: string;
    progress: { total: number; done: number; completion_percent: number; by_status: Record<string, number> };
  };
  evidence: {
    count: number;
    files: Array<{ path: string; sha256: string | null; size_bytes: number | null; modified_at: string; error?: string }>;
  };
};
