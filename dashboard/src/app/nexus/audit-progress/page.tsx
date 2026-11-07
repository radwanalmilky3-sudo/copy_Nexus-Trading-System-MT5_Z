import { redirect } from 'next/navigation';

// المسار القديم — دُمج في الإعدادات ← تبويب «المشروع والتدقيق».
export default function AuditProgressRedirect() {
  redirect('/nexus/settings?tab=project');
}
