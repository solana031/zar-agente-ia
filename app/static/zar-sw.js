/* ZAR service worker: incoming "calls" and alerts through Web Push. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { title: 'ZAR', body: event.data && event.data.text() }; }
  const isCall = data.type === 'call';
  const url = isCall ? '/?zar_call=' + encodeURIComponent(data.id || '') : (data.url || '/');
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    windows.forEach(w => w.postMessage({ type: 'zar-push', data }));
    await self.registration.showNotification(isCall ? '📞 ZAR te llama' : (data.title || 'ZAR'), {
      body: isCall ? (data.title || '') + (data.body ? ' — ' + data.body : '') : (data.body || ''),
      tag: isCall ? 'zar-call-' + data.id : (data.tag || 'zar'),
      renotify: true, requireInteraction: isCall,
      vibrate: isCall ? [600, 300, 600, 300, 600, 300, 600] : [200],
      icon: '/static/zar-icon-192.png', badge: '/static/zar-icon-192.png',
      data: { url, call: isCall ? data.id : null },
      actions: isCall ? [{ action: 'answer', title: 'Contestar' }, { action: 'decline', title: 'Rechazar' }] : []
    });
  })());
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const data = event.notification.data || {};
  let url = data.url || '/';
  if (event.action === 'decline' && data.call) url = '/?zar_call=' + encodeURIComponent(data.call) + '&decline=1';
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const w of windows) {
      if (new URL(w.url).origin === self.location.origin) { await w.focus(); w.postMessage({ type: 'zar-open-call', url }); return; }
    }
    await self.clients.openWindow(url);
  })());
});
