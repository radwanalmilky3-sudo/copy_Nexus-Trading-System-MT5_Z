import { redirect } from 'next/navigation';

// المسار القديم — مختبر البحث أصبح تبويباً داخل الإعدادات.
export default function ResearchLabRedirect() {
  redirect('/nexus/settings?tab=research_lab');
}
