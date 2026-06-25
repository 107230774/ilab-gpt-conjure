const YUANSHU_BASE_PATH = "/image-playground";
let yuanshuSessionId = "";
let yuanshuScopeId = "";
let consecutiveUnavailableResponses = 0;

export function setYuanshuSessionId(value: string): void {
  yuanshuSessionId = String(value || "").trim();
  const win = window as typeof window & { __yuanshuSessionId?: string };
  win.__yuanshuSessionId = yuanshuSessionId;
  document.documentElement.dataset.yuanshuSessionId = yuanshuSessionId;
}

export function hasYuanshuSession(): boolean {
  return Boolean(getYuanshuSessionId());
}

export function getYuanshuSessionId(): string {
  const win = window as typeof window & { __yuanshuSessionId?: string };
  return yuanshuSessionId
    || String(win.__yuanshuSessionId || "").trim()
    || String(document.documentElement.dataset.yuanshuSessionId || "").trim();
}

export function setYuanshuScopeId(value: string): void {
  yuanshuScopeId = String(value || "").trim();
  document.documentElement.dataset.yuanshuScopeId = yuanshuScopeId;
}

export function currentYuanshuStorageScope(): string {
  return yuanshuScopeId || "default";
}

function isExternalUrl(value: string): boolean {
  return /^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(value);
}

export function yuanshuPath(path: string): string {
  const value = String(path || "");
  if (!value || isExternalUrl(value)) return value;
  if (value === YUANSHU_BASE_PATH || value.startsWith(`${YUANSHU_BASE_PATH}/`)) return value;
  if (value.startsWith("/")) return `${YUANSHU_BASE_PATH}${value}`;
  return value;
}

function normalizeRequestInfo(input: RequestInfo | URL): RequestInfo | URL {
  if (typeof input === "string") return yuanshuPath(input);
  if (input instanceof URL && input.origin === window.location.origin) {
    const normalized = yuanshuPath(`${input.pathname}${input.search}${input.hash}`);
    return new URL(normalized, window.location.origin);
  }
  return input;
}

export function installYuanshuPathRuntime(): void {
  const win = window as typeof window & { __yuanshuPathRuntimeInstalled?: boolean };
  if (win.__yuanshuPathRuntimeInstalled) return;
  win.__yuanshuPathRuntimeInstalled = true;

  const originalFetch = window.fetch.bind(window);
  window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const normalized = normalizeRequestInfo(input);
    const headers = new Headers(init?.headers || (normalized instanceof Request ? normalized.headers : undefined));
    if (yuanshuSessionId) {
      headers.set("X-Yuanshu-Session", yuanshuSessionId);
    }
    const response = await originalFetch(normalized, { ...(init || {}), headers });
    if (response.status === 401 || response.status === 403) {
      window.parent?.postMessage({ type: "yuanshu:image-playground-session-expired" }, window.location.origin);
    }
    if ([502, 503, 504].includes(response.status)) {
      consecutiveUnavailableResponses += 1;
      if (consecutiveUnavailableResponses >= 3) {
        (window as any).closeRealtimeUpdates?.();
        window.parent?.postMessage({ type: "yuanshu:image-playground-unavailable" }, window.location.origin);
      }
    } else if (response.status < 500) {
      consecutiveUnavailableResponses = 0;
    }
    return response;
  }) as typeof window.fetch;

  const NativeEventSource = window.EventSource;
  if (NativeEventSource) {
    window.EventSource = class YuanshuEventSource extends NativeEventSource {
      constructor(url: string | URL, eventSourceInitDict?: EventSourceInit) {
        const normalized = typeof url === "string" ? yuanshuPath(url) : normalizeRequestInfo(url);
        super(normalized as string | URL, eventSourceInitDict);
      }
    } as typeof EventSource;
  }
}
