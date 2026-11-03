import { getAuthHeaders } from '@/lib/api-client';
import { withRequestTimeout } from '@/lib/request-timeout';
import type { AuditEvidence } from './types';

export async function loadAuditEvidence(signal?: AbortSignal): Promise<AuditEvidence> {
  return withRequestTimeout(async (requestSignal) => {
    const origin = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000';
    const response = await fetch(`${origin}/api/audit/progress`, {
      cache: 'no-store', headers: getAuthHeaders(), signal: requestSignal,
    });
    if (response.status === 401 && typeof window !== 'undefined') {
      window.localStorage.removeItem('nexus-token'); window.location.href = '/login';
    }
    if (!response.ok) throw new Error(`تعذر تحميل أدلة التدقيق: HTTP ${response.status}`);
    const result = await response.json() as AuditEvidence;
    if (!result || !['available', 'degraded'].includes(result.status) || !result.state?.progress || !Array.isArray(result.evidence?.files)) {
      throw new Error('استجابة أدلة التدقيق غير صالحة');
    }
    return result;
  }, signal);
}
