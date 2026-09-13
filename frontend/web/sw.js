// BAROGROOVE Progressive Web App Service Worker
// Enables Chrome Desktop & Mobile "Install App" / "Save as Chrome App" prompt
// and provides resilient network-first navigation with offline fallback.

const CACHE_NAME = 'barogroove-pwa-v7';
const PRECACHE_URLS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/favicon.png',
  '/icons/Icon-192.png',
  '/icons/Icon-512.png'
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_URLS).catch(() => {});
    })
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') {
    return;
  }

  let url;
  try {
    url = new URL(req.url);
  } catch (_) {
    return;
  }

  // Never intercept cross-origin requests (e.g. Google Auth apis.google.com,
  // accounts.google.com, Firebase Auth *.firebaseapp.com, Spotify, Last.fm).
  if (url.origin !== self.location.origin) {
    return;
  }

  // Pass through backend API, MCP, and Firebase Auth helper paths directly.
  if (
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/mcp') ||
    url.pathname.startsWith('/__/auth/') ||
    url.pathname.startsWith('/auth/') ||
    url.pathname.startsWith('/callback')
  ) {
    return;
  }

  const isNavigation = req.mode === 'navigate';
  const isCodeOrDoc =
    isNavigation ||
    url.pathname.endsWith('.js') ||
    url.pathname.endsWith('.html');

  event.respondWith(
    fetch(req, isCodeOrDoc ? { cache: 'no-cache' } : undefined)
      .then((res) => {
        if (res && res.status === 200 && res.type === 'basic') {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
        }
        return res;
      })
      .catch(() =>
        caches.match(req).then((cached) => {
          if (cached) return cached;
          // Only return SPA index.html fallback for top-level page navigations.
          // Returning text/html for a failed script or asset request triggers
          // strict MIME-type (nosniff) execution failures.
          if (isNavigation) {
            return caches.match('/index.html');
          }
          return Response.error();
        })
      )
  );
});
