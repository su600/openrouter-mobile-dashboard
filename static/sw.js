// 极简 Service Worker：仅用于满足 PWA 可安装条件，不做离线缓存（保证数据始终最新）
self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  // 直接透传网络请求，不缓存，保证看板数据实时
  event.respondWith(fetch(event.request));
});
