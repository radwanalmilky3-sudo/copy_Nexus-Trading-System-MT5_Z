export interface AgentStatusRow {
  agent_id?: string;
  id?: string;
  status?: string;
  last_active?: string;
}

export type AgentStatusPayload =
  | { available: true; rows: AgentStatusRow[] }
  | { available: false; rows: [] };

function rowsFrom(value: unknown[]): AgentStatusRow[] {
  return value.filter(
    (row): row is AgentStatusRow => !!row && typeof row === 'object' && !Array.isArray(row),
  );
}

export function parseAgentStatusPayload(payload: unknown): AgentStatusPayload {
  if (Array.isArray(payload)) {
    return { available: true, rows: rowsFrom(payload) };
  }
  if (!payload || typeof payload !== 'object') {
    return { available: false, rows: [] };
  }
  const agents = (payload as { agents?: unknown }).agents;
  return Array.isArray(agents)
    ? { available: true, rows: rowsFrom(agents) }
    : { available: false, rows: [] };
}
