/* SmartSpend service worker — v1
   App-shell + assets cache-first with background refresh; API calls and
   uploaded receipt images always hit the network (they must never be
   served stale). No offline page: the app requires connectivity for auth
   and data, the cache just makes repeat visits instant. */

const VERSION = 'smartspend-v1';
const ASSETS = ['/', '/index.html', '/manifest.webmanifest', '/favicon.svg'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(VERSION)
      .then((cache) => cache.addAll(ASSETS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;

  // Never intercept the API, uploaded media, or browser extensions.
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/media/')) return;
  if (!url.origin.startsWith('http') && !url.origin.startsWith('https')) return;

  // Stale-while-revalidate for everything else (same-origin).
  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.open(VERSION).then(async (cache) => {
        const cached = await cache.match(event.request);
        const network = fetch(event.request)
          .then((response) => {
            if (response.ok) cache.put(event.request, response.clone());
            return response;
          })
          .catch(() => cached);
        return cached || network;
      }),
    );
  }
});
