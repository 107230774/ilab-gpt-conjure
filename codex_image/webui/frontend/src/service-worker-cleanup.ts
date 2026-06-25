const YUANSHU_SERVICE_WORKER_SCOPE = "/image-playground/";
const YUANSHU_CACHE_PREFIX = "yuanshu-image-playground-";
const CLEANUP_RELOAD_FLAG = "yuanshu-image-playground-sw-cleanup-reloaded";

function isYuanshuServiceWorker(registration: ServiceWorkerRegistration): boolean {
  try {
    return new URL(registration.scope).pathname.startsWith(YUANSHU_SERVICE_WORKER_SCOPE);
  } catch {
    return String(registration.scope || "").includes(YUANSHU_SERVICE_WORKER_SCOPE);
  }
}

function shouldReloadAfterCleanup(): boolean {
  try {
    if (sessionStorage.getItem(CLEANUP_RELOAD_FLAG) === "1") return false;
    sessionStorage.setItem(CLEANUP_RELOAD_FLAG, "1");
    return true;
  } catch {
    return false;
  }
}

export function cleanupLegacyYuanshuServiceWorker(): void {
  if (!("serviceWorker" in navigator) && !("caches" in window)) return;
  void (async () => {
    let changed = false;

    try {
      const registrations = await navigator.serviceWorker?.getRegistrations?.() || [];
      const yuanshuRegistrations = registrations.filter(isYuanshuServiceWorker);
      await Promise.all(yuanshuRegistrations.map((registration) => registration.unregister()));
      changed = changed || yuanshuRegistrations.length > 0 || Boolean(navigator.serviceWorker?.controller);
    } catch {
      // Best-effort cleanup; the next network load still uses no-store headers.
    }

    try {
      const keys = await caches.keys();
      const legacyKeys = keys.filter((key) => key.startsWith(YUANSHU_CACHE_PREFIX));
      await Promise.all(legacyKeys.map((key) => caches.delete(key)));
      changed = changed || legacyKeys.length > 0;
    } catch {
      // Cache Storage can be blocked in restricted browser contexts.
    }

    if (changed && shouldReloadAfterCleanup()) {
      window.location.reload();
    }
  })();
}
