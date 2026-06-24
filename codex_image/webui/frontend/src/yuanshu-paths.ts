const YUANSHU_BASE_PATH = "/image-playground";

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
  window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => originalFetch(normalizeRequestInfo(input), init)) as typeof window.fetch;

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

