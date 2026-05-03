const CACHE = "chanakya-v5-v3";
const STATIC = [
  "/v5/",
  "/v5/static/manifest.json",
];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(STATIC))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  // API calls — network only, no cache
  if(e.request.url.includes("/api/")) {
    return;
  }
  e.respondWith(
    fetch(e.request)
      .then(res => {
        // Success — cache update करूया
        var clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
        return res;
      })
      .catch(() => caches.match(e.request)) // offline fallback
  );
});
