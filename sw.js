const CACHE = 'protokol-v9';
const ASSETS = [
  './',
  './index.html',
  './analytics.js',
  './plan.json',
  './manifest.webmanifest',
  './icon-192.png',
  './icon-512.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);

  // UI (nawigacja, index.html) i dane Garmina: siec najpierw (zawsze swiezy kod/dane), cache na offline.
  const shell = e.request.mode === 'navigate'
    || url.pathname.endsWith('/') || url.pathname.endsWith('/index.html')
    || url.pathname.endsWith('/plan.json')
    || (url.pathname.includes('garmin-') && url.pathname.endsWith('.json'));
  if (shell) {
    e.respondWith(
      fetch(e.request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      }).catch(() => caches.match(e.request).then((m) => m || caches.match('./index.html')))
    );
    return;
  }

  // Statyczne zasoby (ikony, manifest): cache najpierw (apka dziala offline).
  e.respondWith(
    caches.match(e.request).then((cached) => cached || fetch(e.request))
  );
});

// Poranny briefing (Web Push): pokaz powiadomienie z payloadu.
self.addEventListener('push', (e) => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch (_) { data = { body: e.data ? e.data.text() : '' }; }
  const title = data.title || 'Protokół — poranny briefing';
  const opts = {
    body: data.body || 'Twój plan na dziś jest gotowy.',
    icon: 'icon-192.png',
    badge: 'icon-192.png',
    tag: 'daily-briefing',
    renotify: true,
    data: { url: data.url || './' }
  };
  e.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || './';
  e.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of all) { if ('focus' in c) return c.focus(); }
    if (self.clients.openWindow) return self.clients.openWindow(url);
  })());
});
