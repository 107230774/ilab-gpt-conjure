import { getEls } from "./dom";
import { formatTranslation, LOCALE_CHANGE_EVENT, translate } from "./i18n";
import { getLegacyBridge, getState } from "./state";
import type { QueueState, RealtimePayload, WebUITask } from "./types";
import { getYuanshuSessionId, yuanshuPath } from "./yuanshu-paths";

const REALTIME_EVENTS_URL = "/api/events?stream=1";
const QUEUE_DISPATCH_RESYNC_DELAY_MS = 1500;
const YUANSHU_DASHBOARD_SNAPSHOT_LIMIT = 80;
const YUANSHU_ACTIVE_POLL_INTERVAL_MS = 5000;
const YUANSHU_IDLE_POLL_INTERVAL_MS = 20000;
const YUANSHU_COMPLETION_REFRESH_DELAYS_MS = [0, 500, 1500, 3000];
const TERMINAL_TASK_STATUSES = new Set(["completed", "failed", "partial_failed"]);
const YUANSHU_TASK_DETAIL_REFRESH_DELAYS_MS = [0, 700, 1800, 3500];
const ACTIVE_TASK_STATUSES = new Set(["submitting", "queued", "running"]);

type QueueTask = WebUITask & {
  output_size?: string;
  queue_position?: number;
  attempts?: number;
  max_attempts?: number;
  local_pending?: boolean;
  last_error?: string;
  retry_requested_at?: string;
  retrying_failed_slots?: unknown[];
};

let queueFeatureInitialized = false;
let yuanshuQueuePollTimerId: number | null = null;
let yuanshuQueuePollingActive = false;
let yuanshuDashboardSnapshotEtag = "";
let yuanshuDashboardSnapshotInFlight: Promise<void> | null = null;
let yuanshuCompletionRefreshTimerIds: number[] = [];
let yuanshuTaskDetailRefreshTimerIds: number[] = [];
let yuanshuVisibilityListenerInstalled = false;

function yuanshuSessionHeaders(): Headers {
  const headers = new Headers();
  const yuanshuSessionId = getYuanshuSessionId();
  if (yuanshuSessionId) {
    headers.set("X-Yuanshu-Session", yuanshuSessionId);
    headers.set("Cache-Control", "no-cache");
  }
  return headers;
}

function noStoreUrl(path: string): string {
  const separator = path.includes("?") ? "&" : "?";
  return yuanshuPath(`${path}${separator}_=${Date.now()}`);
}

export function initializeQueueFeature(): void {
  if (queueFeatureInitialized) return;
  queueFeatureInitialized = true;
  exposeQueueWindowApi();
  bindQueueControls();
  document.addEventListener(LOCALE_CHANGE_EVENT, renderQueue);
}

function exposeQueueWindowApi(): void {
  window.startRealtimeUpdates = startRealtimeUpdates;
  window.closeRealtimeUpdates = closeRealtimeUpdates;
  window.refreshQueue = refreshQueue;
  window.refreshDashboardSnapshot = refreshDashboardSnapshot;
  window.applyQueueState = applyQueueState;
  window.applyQueueTasks = applyQueueTasks;
  window.updateQueueElapsedDisplays = updateQueueElapsedDisplays;
}

function bindQueueControls(): void {
  const els = getEls();
  els.queueButton?.addEventListener("click", jumpToActiveTaskGroup);
}

export function startRealtimeUpdates({ migrateLegacyArchives = false } = {}): boolean {
  const state = getState();
  if (!window.EventSource) return false;
  if (isYuanshuEmbeddedMode()) {
    closeRealtimeUpdates();
    startYuanshuQueuePolling({ migrateLegacyArchives });
    return false;
  }
  closeRealtimeUpdates();
  state.realtimeSnapshotNeedsArchiveMigration = migrateLegacyArchives;
  const source = new EventSource(REALTIME_EVENTS_URL);
  state.realtimeSource = source;
  source.onmessage = (event) => {
    handleRealtimeMessage(event).catch((error: unknown) => {
      console.error(error);
      getLegacyBridge().methods.setStatus(errorMessage(error, translate("queue.realtimeUpdateFailed")), "error");
    });
  };
  source.onerror = () => {
    if (state.realtimeSource !== source) return;
    const shouldMigrateArchives = state.realtimeSnapshotNeedsArchiveMigration;
    closeRealtimeUpdates();
    state.realtimeSnapshotNeedsArchiveMigration = false;
    void refreshQueue();
    void getLegacyBridge().methods.refreshTasks({ migrateLegacyArchives: shouldMigrateArchives, preserveExistingOnEmpty: true });
    getLegacyBridge().methods.setStatus(translate("queue.realtimeDisconnected"), "error");
  };
  return true;
}

export function closeRealtimeUpdates(): void {
  const state = getState();
  stopYuanshuQueuePolling();
  if (!state.realtimeSource) return;
  state.realtimeSource.close();
  state.realtimeSource = null;
}

function isYuanshuEmbeddedMode(): boolean {
  return window.location.pathname.startsWith("/image-playground");
}

function startYuanshuQueuePolling({ migrateLegacyArchives = false } = {}): void {
  if (yuanshuQueuePollingActive) {
    void refreshDashboardSnapshot({ migrateLegacyArchives, force: true });
    return;
  }
  yuanshuQueuePollingActive = true;
  let shouldMigrateArchives = Boolean(migrateLegacyArchives);
  const poll = () => {
    yuanshuQueuePollTimerId = null;
    if (!yuanshuQueuePollingActive || document.hidden) return;
    void refreshDashboardSnapshot({ migrateLegacyArchives: shouldMigrateArchives }).finally(scheduleYuanshuNextPoll);
    shouldMigrateArchives = false;
  };
  if (!yuanshuVisibilityListenerInstalled) {
    yuanshuVisibilityListenerInstalled = true;
    document.addEventListener("visibilitychange", handleYuanshuVisibilityChange);
  }
  window.addEventListener("pagehide", stopYuanshuQueuePolling, { once: true });
  poll();
}

function stopYuanshuQueuePolling(): void {
  yuanshuQueuePollingActive = false;
  if (yuanshuQueuePollTimerId !== null) {
    window.clearTimeout(yuanshuQueuePollTimerId);
    yuanshuQueuePollTimerId = null;
  }
}

function handleYuanshuVisibilityChange(): void {
  if (!yuanshuQueuePollingActive) return;
  if (document.hidden) {
    if (yuanshuQueuePollTimerId !== null) {
      window.clearTimeout(yuanshuQueuePollTimerId);
      yuanshuQueuePollTimerId = null;
    }
    return;
  }
  void refreshDashboardSnapshot({ force: true }).finally(scheduleYuanshuNextPoll);
}

function scheduleYuanshuNextPoll(): void {
  if (!yuanshuQueuePollingActive || document.hidden || yuanshuQueuePollTimerId !== null) return;
  const delay = hasActiveQueueOrTask() ? YUANSHU_ACTIVE_POLL_INTERVAL_MS : YUANSHU_IDLE_POLL_INTERVAL_MS;
  yuanshuQueuePollTimerId = window.setTimeout(() => {
    yuanshuQueuePollTimerId = null;
    void refreshDashboardSnapshot().finally(scheduleYuanshuNextPoll);
  }, delay);
}

function hasActiveQueueOrTask(): boolean {
  const state = getState();
  const waiting = Array.isArray(state.queue?.waiting) ? state.queue.waiting : [];
  const running = Array.isArray(state.queue?.running) ? state.queue.running : [];
  if (waiting.length || running.length) return true;
  return (state.tasks || []).some((task) => ACTIVE_TASK_STATUSES.has(String(task?.status || "")));
}

export async function refreshDashboardSnapshot({
  migrateLegacyArchives = false,
  force = false,
}: {
  migrateLegacyArchives?: boolean;
  force?: boolean;
} = {}): Promise<void> {
  if (!isYuanshuEmbeddedMode()) {
    await refreshQueue();
    await getLegacyBridge().methods.refreshTasks?.({ migrateLegacyArchives, preserveExistingOnEmpty: true });
    return;
  }
  if (document.hidden && !force) return;
  if (yuanshuDashboardSnapshotInFlight) return yuanshuDashboardSnapshotInFlight;
  yuanshuDashboardSnapshotInFlight = fetchDashboardSnapshot({ migrateLegacyArchives })
    .finally(() => {
      yuanshuDashboardSnapshotInFlight = null;
    });
  return yuanshuDashboardSnapshotInFlight;
}

async function fetchDashboardSnapshot({ migrateLegacyArchives = false } = {}): Promise<void> {
  const bridge = getLegacyBridge();
  const state = bridge.state;
  const headers = yuanshuSessionHeaders();
  if (yuanshuDashboardSnapshotEtag) {
    headers.set("If-None-Match", yuanshuDashboardSnapshotEtag);
  }
  try {
    const response = await fetch(noStoreUrl(`/api/dashboard/snapshot?limit=${YUANSHU_DASHBOARD_SNAPSHOT_LIMIT}`), {
      cache: "no-store",
      headers,
    });
    if (response.status === 304) {
      updateQueueElapsedDisplays();
      return;
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || translate("queue.readFailed"));
    }
    const revision = String(data.revision || "");
    const etag = response.headers.get("ETag") || (revision ? `"${revision}"` : "");
    if (etag) yuanshuDashboardSnapshotEtag = etag;
    if (revision && state.dashboardSnapshotRevision === revision) {
      updateQueueElapsedDisplays();
      return;
    }
    state.dashboardSnapshotRevision = revision;
    applyQueueState(data.queue);
    await bridge.methods.applyTasksSnapshot?.(Array.isArray(data.tasks) ? data.tasks : [], {
      migrateLegacyArchives,
      preserveExistingOnEmpty: true,
      requestSeq: ++state.tasksRequestSeq,
    });
    applyQueueTasks(data.queue);
    state.realtimeSnapshotNeedsArchiveMigration = false;
  } catch (error: unknown) {
    bridge.methods.setStatus(errorMessage(error, translate("queue.readFailed")), "error");
  }
}

function scheduleYuanshuCompletionRefreshBurst(): void {
  if (!isYuanshuEmbeddedMode()) {
    void getLegacyBridge().methods.refreshTasks?.({ preserveExistingOnEmpty: true });
    return;
  }
  yuanshuCompletionRefreshTimerIds.forEach((timerId) => window.clearTimeout(timerId));
  yuanshuCompletionRefreshTimerIds = YUANSHU_COMPLETION_REFRESH_DELAYS_MS.map((delay) => window.setTimeout(() => {
    void refreshDashboardSnapshot({ force: true });
  }, delay));
}

async function refreshCompletedQueueSnapshot(): Promise<void> {
  const bridge = getLegacyBridge();
  bridge.state.tasksRenderKey = null;
  await bridge.methods.refreshTasks?.({ preserveExistingOnEmpty: false });
  bridge.methods.renderTasks?.();
  bridge.methods.renderPreview?.();
}

function scheduleYuanshuTaskDetailRefreshBurst(taskIds: Iterable<string>): void {
  const ids = [...new Set([...taskIds].map(String).filter(Boolean))];
  if (!ids.length) return;
  if (!isYuanshuEmbeddedMode()) {
    ids.forEach((taskId) => void refreshTaskDetailIntoSidebar(taskId));
    return;
  }
  yuanshuTaskDetailRefreshTimerIds.forEach((timerId) => window.clearTimeout(timerId));
  yuanshuTaskDetailRefreshTimerIds = [];
  ids.forEach((taskId) => {
    YUANSHU_TASK_DETAIL_REFRESH_DELAYS_MS.forEach((delay) => {
      const timerId = window.setTimeout(() => {
        void refreshTaskDetailIntoSidebar(taskId);
      }, delay);
      yuanshuTaskDetailRefreshTimerIds.push(timerId);
    });
  });
}

async function refreshTaskDetailIntoSidebar(taskId: string): Promise<void> {
  const bridge = getLegacyBridge();
  try {
    const response = await fetch(noStoreUrl(`/api/tasks/${encodeURIComponent(taskId)}`), {
      cache: "no-store",
      headers: yuanshuSessionHeaders(),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data?.task) return;
    bridge.methods.applyTaskUpdate?.(data.task);
    await refreshDashboardSnapshot({ force: true });
  } catch (error) {
    console.warn(error);
  }
}

export async function handleRealtimeMessage(event: MessageEvent): Promise<void> {
  if (!event.data) return;
  const payload = JSON.parse(String(event.data)) as RealtimePayload;
  await handleRealtimePayload(payload);
}

export async function handleRealtimePayload(payload: RealtimePayload | null | undefined): Promise<void> {
  const bridge = getLegacyBridge();
  const state = bridge.state;
  if (payload?.type === "snapshot") {
    applyQueueState(payload.queue);
    await bridge.methods.applyTasksSnapshot(payload.tasks || [], {
      migrateLegacyArchives: state.realtimeSnapshotNeedsArchiveMigration,
    });
    applyQueueTasks(payload.queue);
    state.realtimeSnapshotNeedsArchiveMigration = false;
    return;
  }
  if (payload?.type === "queue") {
    applyQueueState(payload.queue);
    applyQueueTasks(payload.queue);
    return;
  }
  if (payload?.type === "task") {
    const previousTask = state.tasks.find((item) => String(item.task_id) === String(payload.task?.task_id));
    bridge.methods.notifyTaskUpdate?.(previousTask, payload.task);
    bridge.methods.applyTaskUpdate(payload.task);
    if (TERMINAL_TASK_STATUSES.has(String(payload.task?.status || ""))) {
      scheduleYuanshuCompletionRefreshBurst();
      if (payload.task?.task_id) {
        scheduleYuanshuTaskDetailRefreshBurst([String(payload.task.task_id)]);
      }
    }
  }
}

export async function refreshQueue(): Promise<void> {
  if (isYuanshuEmbeddedMode()) {
    await refreshDashboardSnapshot({ force: true });
    return;
  }
  const bridge = getLegacyBridge();
  const state = bridge.state;
  const requestSeq = ++state.queueRequestSeq;
  const previousActiveTaskIds = currentActiveTaskIds();
  try {
    const response = await fetch(noStoreUrl("/api/queue"), {
      cache: "no-store",
      headers: yuanshuSessionHeaders(),
    });
    const data = await response.json();
    if (requestSeq !== state.queueRequestSeq) return;
    if (!response.ok) {
      throw new Error(data.detail || translate("queue.readFailed"));
    }
    const queue = normalizeQueueState(data);
    state.queue = queue;
    renderQueue();
    applyQueueTasks(queue, { previousActiveTaskIds });
  } catch (error: unknown) {
    bridge.methods.setStatus(errorMessage(error, translate("queue.readFailed")), "error");
  }
}

export function defaultQueueState(): QueueState {
  return { waiting: [], running: [], summary: { waiting_count: 0, running_count: 0, channel_count: 0 } };
}

export function normalizeQueueState(queue: QueueState | null | undefined): QueueState {
  const fallback = defaultQueueState();
  return {
    waiting: Array.isArray(queue?.waiting) ? queue.waiting : fallback.waiting,
    running: Array.isArray(queue?.running) ? queue.running : fallback.running,
    summary: queue?.summary || fallback.summary,
  };
}

export function invalidateQueueRequests(): void {
  getState().queueRequestSeq += 1;
}

export function applyQueueState(queue: QueueState | null | undefined): void {
  const state = getState();
  invalidateQueueRequests();
  state.queue = normalizeQueueState(queue);
  renderQueue();
}

export function renderQueue(): void {
  const bridge = getLegacyBridge();
  const state = bridge.state;
  const summary = state.queue.summary || {};
  const waitingCount = Number(summary.waiting_count ?? state.queue.waiting.length ?? 0);
  const runningCount = Number(summary.running_count ?? state.queue.running.length ?? 0);
  const channelCount = Number(summary.channel_count ?? 0);
  const usableChannelCount = Number(summary.usable_channel_count ?? channelCount);
  const dispatchPending = isQueueDispatchPending();

  renderQueueStatusChip({
    waitingCount,
    runningCount,
    channelCount,
    usableChannelCount,
    dispatchPending,
  });
  bridge.methods.updateDocumentTitle();
  if (dispatchPending) {
    scheduleQueueDispatchSync();
  } else {
    clearQueueDispatchSync();
  }
  const nextRenderKey = queueListRenderKey();
  if (state.queueRenderKey === nextRenderKey) {
    updateQueueElapsedDisplays();
    return;
  }
  state.queueRenderKey = nextRenderKey;
  renderActiveTaskGroupForQueueChange();
}

function renderActiveTaskGroupForQueueChange(): void {
  const bridge = getLegacyBridge();
  bridge.methods.renderTasks?.();
}

export function renderQueueStatusChip({
  waitingCount,
  runningCount,
  channelCount,
  usableChannelCount,
  dispatchPending,
}: {
  waitingCount: number;
  runningCount: number;
  channelCount: number;
  usableChannelCount: number;
  dispatchPending: boolean;
}): void {
  const els = getEls();
  const total = waitingCount + runningCount;
  const channelText = usableChannelCount === channelCount
    ? formatTranslation("queue.channel", { count: channelCount })
    : formatTranslation("queue.availableChannels", { usable: usableChannelCount, total: channelCount });
  const text = dispatchPending
    ? formatTranslation("queue.dispatching", { waiting: waitingCount })
    : total
      ? formatTranslation("queue.runningWaiting", { running: runningCount, waiting: waitingCount })
      : translate("queue.empty");
  const label = total
    ? formatTranslation("queue.statusLabel", { text, channelText })
    : translate("queue.emptyAria");
  if (els.queueStatusText) els.queueStatusText.textContent = text;
  if (els.queueButton) {
    els.queueButton.setAttribute("aria-label", label);
    els.queueButton.title = total ? translate("queue.jumpTitle") : translate("queue.emptyTitle");
    els.queueButton.classList.toggle("has-queue", total > 0 || dispatchPending);
  }
}

export function jumpToActiveTaskGroup(): void {
  const bridge = getLegacyBridge();
  const state = bridge.state;
  const hasActiveTasks = Boolean((state.queue.running || []).length || (state.queue.waiting || []).length);
  if (!hasActiveTasks) return;
  bridge.methods.revealActiveTaskGroup?.();
}

export function isQueueDispatchPending(): boolean {
  const state = getState();
  const summary = state.queue.summary || {};
  const waitingCount = Number(summary.waiting_count ?? state.queue.waiting.length ?? 0);
  const runningCount = Number(summary.running_count ?? state.queue.running.length ?? 0);
  const channelCount = Number(summary.channel_count ?? 0);
  const usableChannelCount = Number(summary.usable_channel_count ?? channelCount);
  return waitingCount > 0 && runningCount === 0 && usableChannelCount > 0;
}

export function scheduleQueueDispatchSync(): void {
  const state = getState();
  if (state.queueDispatchSyncTimerId) return;
  state.queueDispatchSyncTimerId = window.setTimeout(() => {
    state.queueDispatchSyncTimerId = null;
    if (isQueueDispatchPending()) {
      void refreshQueue();
    }
  }, QUEUE_DISPATCH_RESYNC_DELAY_MS);
}

export function clearQueueDispatchSync(): void {
  const state = getState();
  if (!state.queueDispatchSyncTimerId) return;
  window.clearTimeout(state.queueDispatchSyncTimerId);
  state.queueDispatchSyncTimerId = null;
}

function queueListRenderKey(): string {
  const state = getState();
  return JSON.stringify({
    summary: state.queue.summary || {},
    running: (state.queue.running || []).map((task) => [
      task.task_id,
      task.status,
      task.viewed_at,
      task.prompt,
      (task as QueueTask).channel_id,
      (task as QueueTask).account_id,
      task.started_at,
      (task as QueueTask).attempts,
    ]),
    waiting: (state.queue.waiting || []).map((task) => [
      task.task_id,
      task.status,
      task.prompt,
      task.params?.size,
      (task as QueueTask).queue_position,
    ]),
  });
}

function queueItemTitleText(task: WebUITask, position: number | null = null): string {
  const bridge = getLegacyBridge();
  const queueTask = task as QueueTask;
  const prefix = position ? `#${position}` : bridge.methods.formatTaskStatus(task) || translate("taskStatus.task");
  const mode = taskModeLabel(task);
  const count = formatTranslation("taskCard.count", { count: bridge.methods.taskTotalCount(task) });
  const size = queueTask.output_size || task.params?.size || "";
  return [prefix, mode, count, size].filter(Boolean).join(" · ");
}

function taskModeLabel(task: WebUITask): string {
  if (task.mode === "edit") return translate("taskMode.edit");
  if (task.mode === "generate") return translate("taskMode.generate");
  return "";
}

export async function promoteQueueTask(taskId: string | undefined): Promise<void> {
  const bridge = getLegacyBridge();
  if (!taskId) return;
  invalidateQueueRequests();
  try {
    const response = await fetch(`/api/queue/${encodeURIComponent(taskId)}/promote`, { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || translate("queue.promoteFailed"));
    applyQueueState(data);
    await bridge.methods.refreshTasks();
  } catch (error: unknown) {
    bridge.methods.setStatus(errorMessage(error, translate("queue.promoteFailed")), "error");
  }
}

export function moveQueueTask(taskId: string | undefined, direction: string | undefined): void {
  if (!taskId) return;
  const ids = (getState().queue.waiting || []).map((task) => task.task_id);
  const currentIndex = ids.indexOf(taskId);
  if (currentIndex < 0) return;
  const offset = direction === "up" ? -1 : direction === "down" ? 1 : 0;
  const nextIndex = currentIndex + offset;
  if (offset === 0 || nextIndex < 0 || nextIndex >= ids.length) return;
  const nextIds = ids.slice();
  const [moved] = nextIds.splice(currentIndex, 1);
  if (!moved) return;
  nextIds.splice(nextIndex, 0, moved);
  void reorderQueue(nextIds);
}

export function deleteQueuedTask(button: Element, taskId: string | undefined): void {
  const bridge = getLegacyBridge();
  if (!taskId) return;
  const task = bridge.state.queue.waiting.find((item) => item.task_id === taskId);
  const title = task ? queueItemTitleText(task, (task as QueueTask).queue_position || null) : taskId;
  bridge.methods.openConfirmPopover(button, {
    title: translate("queue.deleteWaitingTitleConfirm"),
    message: translate("queue.deleteWaitingMessage"),
    detail: title,
    confirmText: translate("action.delete"),
    onConfirm: async () => {
      await performDeleteQueuedTask(taskId);
    },
  });
}

export async function performDeleteQueuedTask(taskId: string): Promise<void> {
  const bridge = getLegacyBridge();
  const state = bridge.state;
  invalidateQueueRequests();
  try {
    const response = await fetch(`/api/queue/${encodeURIComponent(taskId)}`, { method: "DELETE" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || translate("queue.deleteQueuedFailed"));
    state.tasks = state.tasks.filter((item) => item.task_id !== taskId);
    if (state.selectedTaskId === taskId) {
      state.selectedTaskId = state.tasks[0]?.task_id || null;
    }
    applyQueueState({
      ...state.queue,
      waiting: state.queue.waiting.filter((item) => item.task_id !== taskId),
      summary: {
        ...(state.queue.summary || {}),
        waiting_count: Math.max(0, Number(state.queue.summary?.waiting_count || 0) - 1),
      },
    });
    await refreshQueue();
    await bridge.methods.refreshTasks();
    bridge.methods.renderPreview();
    bridge.methods.setStatus(translate("queue.queuedDeleted"), "ok");
  } catch (error: unknown) {
    bridge.methods.setStatus(errorMessage(error, translate("queue.deleteQueuedFailed")), "error");
  }
}

export function cancelRunningTask(button: Element, taskId: string | undefined): void {
  const bridge = getLegacyBridge();
  if (!taskId) return;
  const task = bridge.state.queue.running.find((item) => item.task_id === taskId);
  const title = task ? queueItemTitleText(task) : taskId;
  bridge.methods.openConfirmPopover(button, {
    title: translate("queue.cancelRunningTitleConfirm"),
    message: translate("queue.cancelRunningMessage"),
    detail: title,
    confirmText: translate("queue.cancelRunningConfirm"),
    onConfirm: async () => {
      await performCancelRunningTask(taskId);
    },
  });
}

async function performCancelRunningTask(taskId: string): Promise<void> {
  const bridge = getLegacyBridge();
  const state = bridge.state;
  invalidateQueueRequests();
  try {
    const response = await fetch(`/api/queue/${encodeURIComponent(taskId)}`, { method: "DELETE" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || translate("queue.cancelRunningFailed"));
    applyQueueState({
      ...state.queue,
      running: state.queue.running.filter((item) => item.task_id !== taskId),
      summary: {
        ...(state.queue.summary || {}),
        running_count: Math.max(0, Number(state.queue.summary?.running_count || 0) - 1),
      },
    });
    await refreshQueue();
    await bridge.methods.refreshTasks();
    bridge.methods.renderPreview();
    bridge.methods.setStatus(translate("queue.runningCancelled"), "ok");
  } catch (error: unknown) {
    bridge.methods.setStatus(errorMessage(error, translate("queue.cancelRunningFailed")), "error");
  }
}

export async function reorderQueue(taskIds: string[]): Promise<void> {
  const bridge = getLegacyBridge();
  invalidateQueueRequests();
  try {
    const response = await fetch(`/api/queue/reorder`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_ids: taskIds }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || translate("queue.reorderFailed"));
    applyQueueState(data);
    await bridge.methods.refreshTasks();
  } catch (error: unknown) {
    bridge.methods.setStatus(errorMessage(error, translate("queue.reorderFailed")), "error");
    await refreshQueue();
  }
}

export function handleQueueDragStart(event: DragEvent): void {
  const target = eventTargetElement(event);
  const item = event.currentTarget instanceof HTMLElement && event.currentTarget.dataset.queueTaskId
    ? event.currentTarget
    : target?.closest("[data-queue-task-id]");
  if (!(item instanceof HTMLElement)) return;
  const draggedId = item.dataset.queueTaskId || null;
  getState().queueDragTaskId = draggedId;
  if (event.dataTransfer && draggedId) {
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", draggedId);
  }
}

export function handleQueueDragOver(event: DragEvent): void {
  event.preventDefault();
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = "move";
  }
}

export function handleQueueDrop(event: DragEvent): void {
  event.preventDefault();
  event.stopPropagation();
  const state = getState();
  const draggedId = state.queueDragTaskId;
  if (!draggedId) return;
  const ids = (state.queue.waiting || []).map((task) => task.task_id);
  const nextIds = ids.filter((id) => id !== draggedId);
  const targetItem = eventTargetElement(event)?.closest("[data-queue-task-id]");
  const targetId = targetItem instanceof HTMLElement ? targetItem.dataset.queueTaskId : undefined;
  if (targetId === draggedId) return;
  if (!targetId) {
    nextIds.push(draggedId);
    void reorderQueue(nextIds);
    return;
  }
  const targetIndex = nextIds.indexOf(targetId);
  if (targetIndex < 0 || !(targetItem instanceof HTMLElement)) return;
  const targetRect = targetItem.getBoundingClientRect();
  const insertAfter = event.clientY > targetRect.top + targetRect.height / 2;
  nextIds.splice(insertAfter ? targetIndex + 1 : targetIndex, 0, draggedId);
  void reorderQueue(nextIds);
}

export function handleQueueDragEnd(_event: DragEvent): void {
  getState().queueDragTaskId = null;
}

export function applyQueueTasks(
  queue: QueueState | null | undefined,
  { previousActiveTaskIds = currentActiveTaskIds() }: { previousActiveTaskIds?: Set<string> } = {},
): void {
  const bridge = getLegacyBridge();
  const tasks = [
    ...(Array.isArray(queue?.waiting) ? queue.waiting : []),
    ...(Array.isArray(queue?.running) ? queue.running : []),
  ];
  const queueTaskIds = new Set(tasks.map((task) => String(task.task_id)));
  const needsTaskReconcile = activeTasksNeedQueueReconcile(queueTaskIds);
  const completedActiveTaskMissingFromQueue = activeTasksMissingFromQueue(previousActiveTaskIds, queueTaskIds);
  const missingActiveTaskIds = activeTaskIdsMissingFromQueue(previousActiveTaskIds, queueTaskIds);
  if (!tasks.length) {
    if (needsTaskReconcile || completedActiveTaskMissingFromQueue) {
      scheduleYuanshuCompletionRefreshBurst();
      scheduleYuanshuTaskDetailRefreshBurst(missingActiveTaskIds);
      void refreshCompletedQueueSnapshot();
    } else if (bridge.els.taskActiveList && !bridge.els.taskActiveList.classList.contains("hidden")) {
      bridge.state.tasksRenderKey = null;
      bridge.methods.renderTasks?.();
    }
    return;
  }
  let changed = false;
  let terminalTransition = false;
  tasks.forEach((task) => {
    const previousTask = bridge.state.tasks.find((item) => String(item.task_id) === String(task.task_id));
    bridge.methods.notifyTaskUpdate?.(previousTask, task);
    changed = bridge.methods.updateTaskInState(task) || changed;
    if (isTerminalTaskTransition(previousTask, task)) {
      terminalTransition = true;
    }
    if (String(task.task_id) === String(bridge.state.selectedTaskId) && bridge.methods.taskHasViewableUpdate(task)) {
      void bridge.methods.markTaskViewed(task.task_id);
    }
  });
  if (!changed) {
    if (needsTaskReconcile || completedActiveTaskMissingFromQueue) {
      scheduleYuanshuCompletionRefreshBurst();
      scheduleYuanshuTaskDetailRefreshBurst(missingActiveTaskIds);
    }
    return;
  }
  bridge.methods.cleanupSessionSelections();
  bridge.methods.renderTasks();
  bridge.methods.renderArchiveButton();
  bridge.methods.renderArchiveModal();
  bridge.methods.renderPreview();
  if (needsTaskReconcile || completedActiveTaskMissingFromQueue) {
    scheduleYuanshuCompletionRefreshBurst();
    scheduleYuanshuTaskDetailRefreshBurst(missingActiveTaskIds);
  }
  if (terminalTransition) {
    scheduleYuanshuCompletionRefreshBurst();
    scheduleYuanshuTaskDetailRefreshBurst(tasks
      .filter((task) => TERMINAL_TASK_STATUSES.has(String(task?.status || "")))
      .map((task) => String(task.task_id || "")));
  }
}

function isTerminalTaskTransition(previousTask: WebUITask | null | undefined, nextTask: WebUITask | null | undefined): boolean {
  const taskId = String(nextTask?.task_id || "");
  if (!taskId) return false;
  const nextStatus = String(nextTask?.status || "");
  if (!TERMINAL_TASK_STATUSES.has(nextStatus)) return false;
  const previousStatus = String(previousTask?.status || "");
  return !TERMINAL_TASK_STATUSES.has(previousStatus);
}

function activeTasksNeedQueueReconcile(queueTaskIds: Set<string>): boolean {
  const bridge = getLegacyBridge();
  return bridge.state.tasks.some((task) => {
    const taskId = String(task?.task_id || "");
    if (!taskId || queueTaskIds.has(taskId) || task?.local_pending) return false;
    const status = String(task?.status || "");
    return ACTIVE_TASK_STATUSES.has(status);
  });
}

function currentActiveTaskIds(): Set<string> {
  const bridge = getLegacyBridge();
  return new Set(
    bridge.state.tasks
      .filter((task) => {
        if (task?.local_pending) return false;
        const status = String(task?.status || "");
        return ACTIVE_TASK_STATUSES.has(status);
      })
      .map((task) => String(task.task_id || ""))
      .filter(Boolean),
  );
}

function activeTasksMissingFromQueue(previousActiveTaskIds: Set<string>, queueTaskIds: Set<string>): boolean {
  return activeTaskIdsMissingFromQueue(previousActiveTaskIds, queueTaskIds).size > 0;
}

function activeTaskIdsMissingFromQueue(previousActiveTaskIds: Set<string>, queueTaskIds: Set<string>): Set<string> {
  const missing = new Set<string>();
  for (const taskId of previousActiveTaskIds) {
    if (!queueTaskIds.has(taskId)) missing.add(taskId);
  }
  return missing;
}

export function updateQueueElapsedDisplays(): void {
  getLegacyBridge().methods.updateTaskElapsedDisplays?.();
}

function eventTargetElement(event: Event): Element | null {
  return event.target instanceof Element ? event.target : null;
}

function escapeHtml(value: unknown): string {
  return getLegacyBridge().methods.escapeHtml(value);
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
