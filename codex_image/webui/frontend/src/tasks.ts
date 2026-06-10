import { getLegacyBridge } from "./state";

const bridge = getLegacyBridge();
const state = bridge.state;
const els = bridge.els;

function legacyMethod(name: string, ...args: any[]): any {
  const method = getLegacyBridge().methods[name];
  if (typeof method !== "function") {
    throw new Error("Legacy bridge method " + name + " is not available");
  }
  return method(...args);
}

const updateTaskInState = (...args: any[]) => legacyMethod("updateTaskInState", ...args);
const cleanupSessionSelections = (...args: any[]) => legacyMethod("cleanupSessionSelections", ...args);
const renderTasks = (...args: any[]) => legacyMethod("renderTasks", ...args);
const renderArchiveButton = (...args: any[]) => legacyMethod("renderArchiveButton", ...args);
const renderArchiveModal = (...args: any[]) => legacyMethod("renderArchiveModal", ...args);
const renderPreview = (...args: any[]) => legacyMethod("renderPreview", ...args);
const migrateLegacyArchivedTasks = (...args: any[]) => legacyMethod("migrateLegacyArchivedTasks", ...args);
const revokeTaskUploadPreviewUrls = (...args: any[]) => legacyMethod("revokeTaskUploadPreviewUrls", ...args);
const taskHasViewableUpdate = (...args: any[]) => legacyMethod("taskHasViewableUpdate", ...args);
const markTaskViewed = (...args: any[]) => legacyMethod("markTaskViewed", ...args);

async function refreshTasks({ migrateLegacyArchives = false }: any = {}) {
  const requestSeq = ++state.tasksRequestSeq;
  const response = await fetch("/api/tasks/recent?limit=200");
  const data = await response.json();
  if (requestSeq !== state.tasksRequestSeq) return;
  await applyTasksSnapshot(data.tasks || [], { migrateLegacyArchives, requestSeq });
}

async function applyTasksSnapshot(tasks: any, { migrateLegacyArchives = false, requestSeq = state.tasksRequestSeq }: any = {}) {
  const previousLocalPendingTasks = state.tasks.filter((task: any) => task?.local_pending);
  const pendingTask = state.pendingTaskId ? state.tasks.find((task: any) => task.task_id === state.pendingTaskId) : null;
  state.tasks = Array.isArray(tasks) ? tasks : [];
  if (pendingTask?.local_pending && !state.tasks.some((task: any) => task.task_id === pendingTask.task_id)) {
    state.tasks.unshift(pendingTask);
  }
  const retainedTasks = new Set(state.tasks);
  previousLocalPendingTasks.forEach((task: any) => {
    if (!retainedTasks.has(task)) revokeTaskUploadPreviewUrls(task);
  });
  if (migrateLegacyArchives) {
    await migrateLegacyArchivedTasks();
    if (requestSeq !== state.tasksRequestSeq) return;
  }
  cleanupSessionSelections();
  renderTasks();
  renderArchiveButton();
  renderArchiveModal();
  renderPreview();
}

function applyTaskUpdate(task: any) {
  if (!updateTaskInState(task)) return;
  if (String(task.task_id) === String(state.selectedTaskId) && taskHasViewableUpdate(task)) {
    void markTaskViewed(task.task_id);
  }
  cleanupSessionSelections();
  renderTasks();
  renderArchiveButton();
  renderArchiveModal();
  renderPreview();
}

export function initTaskFeature() {
  Object.assign(getLegacyBridge().methods, {
    refreshTasks,
    applyTasksSnapshot,
    applyTaskUpdate,
  });
}
