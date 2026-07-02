const CACHE = 'protokol-v4';
const ASSETS = [
  './',
  './index.html',
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
