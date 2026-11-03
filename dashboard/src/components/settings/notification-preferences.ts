export async function saveNotificationPreferences(
  url: string,
  headers: HeadersInit,
  preferences: unknown,
  request: typeof fetch = fetch,
): Promise<string> {
  try {
    const response = await request(url, {
      method: 'PUT',
      headers,
      body: JSON.stringify(preferences),
    });

    if (response.ok) return 'تم حفظ إعدادات التنبيهات الخاصة بحسابك.';
    return `فشل الحفظ: ${await response.text()}`;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return `تعذر حفظ إعدادات التنبيهات: ${detail}`;
  }
}
