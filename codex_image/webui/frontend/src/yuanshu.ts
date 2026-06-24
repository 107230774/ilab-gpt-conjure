import { getLegacyBridge } from "./state";

type YuanshuBootstrapPayload = {
  apiBase?: string;
  model?: string;
  token?: string;
  tokenExpiresAt?: string;
  keyId?: number;
  keyName?: string;
  groupId?: number;
  groupName?: string;
};

function applyYuanshuChrome() {
  document.documentElement.dataset.yuanshuMode = "true";
  document.title = "元枢在线生图";
  const brandName = document.querySelector(".brand-name");
  const brandSubtitle = document.querySelector(".brand-subtitle");
  if (brandName) brandName.textContent = "元枢";
  if (brandSubtitle) brandSubtitle.textContent = "在线生图";
}

async function postYuanshuBootstrap(payload: YuanshuBootstrapPayload) {
  const response = await fetch("/api/yuanshu/bootstrap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "元枢在线生图初始化失败");
  }
  return data;
}

function isBootstrapMessage(event: MessageEvent): event is MessageEvent<{ type: string; payload: YuanshuBootstrapPayload }> {
  return event.origin === window.location.origin
    && event.data
    && typeof event.data === "object"
    && (event.data as { type?: unknown }).type === "yuanshu:image-playground-bootstrap";
}

export function initYuanshuModeFeature() {
  applyYuanshuChrome();
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type: "yuanshu:image-playground-ready" }, window.location.origin);
  }
  window.addEventListener("message", async (event) => {
    if (!isBootstrapMessage(event)) return;
    try {
      await postYuanshuBootstrap(event.data.payload || {});
      const bridge = getLegacyBridge();
      bridge.state.authAvailable = true;
      bridge.state.mode = "generate";
      bridge.methods.setMode?.("generate");
      bridge.methods.setStatus?.("元枢在线生图已就绪", "ok");
      await bridge.methods.refreshHealth?.();
    } catch (error) {
      const message = error instanceof Error ? error.message : "元枢在线生图初始化失败";
      getLegacyBridge().methods.setStatus?.(message, "error");
    }
  });
}
