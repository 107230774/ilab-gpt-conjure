import { getLegacyBridge } from "./state";
import { installYuanshuPathRuntime, setYuanshuScopeId, setYuanshuSessionId, yuanshuPath } from "./yuanshu-paths";

type YuanshuBootstrapPayload = {
  apiBase?: string;
  model?: string;
  userId?: number;
  token?: string;
  tokenExpiresAt?: string;
  keyId?: number;
  keyName?: string;
  groupId?: number;
  groupName?: string;
};

let bootstrapReadyTimerId: number | null = null;
let activeBootstrapScope = "";

function applyYuanshuChrome() {
  document.documentElement.dataset.yuanshuMode = "true";
  document.title = "元枢在线生图";
  const brandName = document.querySelector(".brand-name");
  const brandSubtitle = document.querySelector(".brand-subtitle");
  if (brandName) brandName.textContent = "元枢";
  if (brandSubtitle) brandSubtitle.textContent = "在线生图";
}

async function postYuanshuBootstrap(payload: YuanshuBootstrapPayload) {
  const response = await fetch(yuanshuPath("/api/yuanshu/bootstrap"), {
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

function postReadyToParent(): void {
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type: "yuanshu:image-playground-ready" }, window.location.origin);
  }
}

function startBootstrapReadyRetry(): void {
  postReadyToParent();
  if (bootstrapReadyTimerId !== null) return;
  bootstrapReadyTimerId = window.setInterval(postReadyToParent, 1000);
  window.addEventListener("pagehide", stopBootstrapReadyRetry, { once: true });
}

function stopBootstrapReadyRetry(): void {
  if (bootstrapReadyTimerId === null) return;
  window.clearInterval(bootstrapReadyTimerId);
  bootstrapReadyTimerId = null;
}

function resetYuanshuWorkspaceForScope(scopeId: string): void {
  const bridge = getLegacyBridge();
  const state = bridge.state;
  if (activeBootstrapScope === scopeId) return;
  activeBootstrapScope = scopeId;
  bridge.methods.revokeUploadPreviewUrls?.(state.images);
  state.images = [];
  state.tasks = [];
  state.selectedTaskId = null;
  state.previewTask = null;
  state.pendingTaskId = null;
  state.taskSearchHistoryResultIds = [];
  state.expandedTaskGroupKey = null;
  state.tasksRenderKey = null;
  state.queue = { waiting: [], running: [], summary: { waiting_count: 0, running_count: 0, channel_count: 0 } };
  state.queueRenderKey = null;
  bridge.methods.renderImageStrip?.();
  bridge.methods.renderTasks?.();
  bridge.methods.renderArchiveButton?.();
  bridge.methods.renderArchiveModal?.();
  bridge.methods.renderPreview?.();
  bridge.methods.updateRequestPreview?.();
}

export function initYuanshuModeFeature() {
  installYuanshuPathRuntime();
  applyYuanshuChrome();
  window.addEventListener("message", async (event) => {
    if (!isBootstrapMessage(event)) return;
    try {
      const bootstrap = await postYuanshuBootstrap(event.data.payload || {});
      const userId = String(bootstrap?.yuanshu?.user_id || event.data.payload?.userId || "anonymous");
      const scopeId = `user:${userId}`;
      setYuanshuSessionId(String(bootstrap?.yuanshu?.session_id || ""));
      setYuanshuScopeId(scopeId);
      resetYuanshuWorkspaceForScope(scopeId);
      stopBootstrapReadyRetry();
      const bridge = getLegacyBridge();
      bridge.state.authAvailable = true;
      bridge.state.mode = "generate";
      bridge.methods.setMode?.("generate");
      bridge.methods.setStatus?.("元枢在线生图已就绪", "ok");
      bridge.methods.refreshTaskNotificationScope?.();
      window.startRealtimeUpdates?.({ migrateLegacyArchives: false });
      await bridge.methods.refreshHealth?.();
      await bridge.methods.refreshGallery?.();
      await bridge.methods.refreshPromptTemplates?.();
      await bridge.methods.refreshPromptSnippets?.();
      await bridge.methods.refreshRecentAssets?.();
      await bridge.methods.refreshTasks?.({ preserveExistingOnEmpty: true });
      await window.refreshQueue?.();
    } catch (error) {
      const message = error instanceof Error ? error.message : "元枢在线生图初始化失败";
      getLegacyBridge().methods.setStatus?.(message, "error");
    }
  });
  startBootstrapReadyRetry();
}
