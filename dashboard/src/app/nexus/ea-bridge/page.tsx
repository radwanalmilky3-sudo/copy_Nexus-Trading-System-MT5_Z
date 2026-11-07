import { redirect } from 'next/navigation';

// المسار القديم — جسر MT5 أصبح تبويباً داخل الإعدادات.
export default function EaBridgeRedirect() {
  redirect('/nexus/settings?tab=ea_bridge');
}
