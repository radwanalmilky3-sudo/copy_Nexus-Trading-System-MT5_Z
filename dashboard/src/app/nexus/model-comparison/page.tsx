import { redirect } from 'next/navigation';

// المسار القديم للشاشة المنفصلة — دُمجت في صفحة النماذج الموحّدة كتبويب داخلي.
export default function ModelComparisonRedirect() {
  redirect('/nexus/models?tab=compare');
}
