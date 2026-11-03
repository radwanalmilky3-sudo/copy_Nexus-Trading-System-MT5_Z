import assert from 'node:assert/strict';
import test from 'node:test';
import { saveNotificationPreferences } from '../src/components/settings/notification-preferences.ts';

test('network failure replaces stale success with an explicit save failure', async () => {
  const status = await saveNotificationPreferences(
    '/api/user/notification-preferences',
    {},
    { tts_enabled: true },
    async () => { throw new TypeError('Failed to fetch'); },
  );

  assert.match(status, /تعذر حفظ إعدادات التنبيهات: Failed to fetch/);
});

test('HTTP failure does not claim notification preferences were saved', async () => {
  const status = await saveNotificationPreferences(
    '/api/user/notification-preferences',
    {},
    { tts_enabled: true },
    async () => new Response('Forbidden', { status: 403 }),
  );

  assert.equal(status, 'فشل الحفظ: Forbidden');
});
