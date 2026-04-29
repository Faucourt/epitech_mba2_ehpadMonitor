// Service Worker EHPAD — Alertes push même téléphone verrouillé
const CACHE = 'ehpad-sw-v1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

// Réception d'un push (même app fermée / tel verrouillé)
self.addEventListener('push', event => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch { payload = {}; }

  const level = payload.level ?? 0;
  const title = payload.title || 'Alerte EHPAD';
  const body = payload.body || 'Nouvelle alerte résident';
  const residentId = payload.resident_id || '';
  const alertId = payload.alert_id || '';

  // Vibration et urgence selon le niveau
  const isUrgent = level >= 4;
  const isCritical = level === 5;

  const options = {
    body,
    tag: alertId ? `ehpad-alert-${alertId}` : `ehpad-alert-${residentId}`,
    renotify: true,
    requireInteraction: isUrgent,      // reste visible jusqu'à interaction
    silent: false,
    vibrate: isCritical
      ? [300, 100, 300, 100, 300]      // N5 : vibration SOS
      : level >= 3
        ? [200, 100, 200]              // N3-N4 : double vibration
        : [100],                       // N1-N2 : simple
    data: { resident_id: residentId, level, alert_id: alertId, url: `/soignant` },
    actions: level >= 3 ? [
      { action: 'view', title: '👁 Voir le patient' },
      { action: 'ack', title: '✓ Acquitter' },
    ] : [
      { action: 'view', title: '👁 Voir' },
    ],
    badge: '/favicon.svg',
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// Clic sur la notification
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const data = event.notification.data || {};
  const residentId = data.resident_id;
  const action = event.action;

  let targetUrl = '/soignant';
  if (residentId) {
    targetUrl = action === 'ack'
      ? `/soignant`
      : `/mobile/resident/${residentId}`;
  }

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
      // Si une fenêtre est ouverte, la focaliser et naviguer
      for (const client of clientList) {
        if ('navigate' in client && 'focus' in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      // Sinon ouvrir une nouvelle fenêtre
      return self.clients.openWindow(targetUrl);
    })
  );
});
