import { LOCALE_CHANGE_EVENT, formatTranslation, restoreLocalePreference, translate } from "./i18n";

type HistoryFacet = { value: string; count: number };
type HistoryMonth = { month: string; count: number };
type HistorySummary = {
  total: number;
  archived_total: number;
  months: HistoryMonth[];
  prompt_modes: HistoryFacet[];
  qualities: HistoryFacet[];
  ratios: HistoryFacet[];
  orientations: HistoryFacet[];
  backends: HistoryFacet[];
  providers: HistoryFacet[];
};
type HistoryTask = {
  task_id: string;
  created_at: string;
  updated_at: string;
  completed_at: string;
  status: string;
  mode: string;
  size: string;
  quality: string;
  prompt_mode: string;
  ratio: string;
  orientation: string;
  backend: string;
  provider: string;
  archived: boolean;
  generated_count: number;
  failed_count: number;
  total_count: number;
  thumbnail_url: string;
  prompt_preview: string;
};
type HistoryFilterKey = "month" | "prompt_mode" | "quality" | "ratio" | "orientation" | "backend" | "provider" | "archived";
type HistoryViewMode = "grid" | "list";

const HISTORY_FILTER_KEYS: HistoryFilterKey[] = ["month", "prompt_mode", "quality", "ratio", "orientation", "backend", "provider", "archived"];
const HISTORY_RATIO_OTHER_VALUE = "__other__";
const HISTORY_PAGE_LIMIT = 50;
const MAX_MOUNTED_TASK_CARDS = 300;
const HISTORY_REFERENCE_HANDOFF_KEY = "codex-image-history-reference-handoff";
const HISTORY_TASK_REUSE_HANDOFF_KEY = "codex-image-history-task-reuse-handoff";
const HISTORY_THEME_STORAGE_KEY = "codex-image-theme-preference";
const HISTORY_THUMBNAIL_CACHE_VERSION = "thumb-768-fit";

const historyState = {
  q: "",
  month: "",
  prompt_mode: "",
  quality: "",
  ratio: "",
  orientation: "",
  backend: "",
  provider: "",
  archived: "",
  sort: "newest",
  view: "grid" as HistoryViewMode,
  nextCursor: null as string | null,
  loading: false,
  exhausted: false,
  loadedTaskIds: new Set<string>(),
  selectedTaskIds: new Set<string>(),
  selectedTaskId: "",
  selectionAnchorTaskId: "",
  deleteConfirming: false,
  deleteUnselectedConfirmTaskId: "",
  detailTask: null as any,
  requestId: 0,
};

const els = {
  page: document.querySelector<HTMLElement>(".history-page"),
  total: document.querySelector<HTMLElement>("#historyTotal"),
  search: document.querySelector<HTMLInputElement>("#historySearch"),
  searchClear: document.querySelector<HTMLButtonElement>("#historySearchClear"),
  monthList: document.querySelector<HTMLElement>("#historyMonthList"),
  promptModeList: document.querySelector<HTMLElement>("#historyPromptModeList"),
  qualityList: document.querySelector<HTMLElement>("#historyQualityList"),
  ratioList: document.querySelector<HTMLElement>("#historyRatioList"),
  orientationList: document.querySelector<HTMLElement>("#historyOrientationList"),
  backendList: document.querySelector<HTMLElement>("#historyBackendList"),
  providerList: document.querySelector<HTMLElement>("#historyProviderList"),
  archiveList: document.querySelector<HTMLElement>("#historyArchiveList"),
  sort: document.querySelector<HTMLSelectElement>("#historySort"),
  viewToggle: document.querySelector<HTMLElement>("#historyViewToggle"),
  resultSummary: document.querySelector<HTMLElement>("#historyResultSummary"),
  bulkToolbar: document.querySelector<HTMLElement>("#historyBulkToolbar"),
  bulkCount: document.querySelector<HTMLElement>("#historyBulkCount"),
  bulkArchive: document.querySelector<HTMLButtonElement>("#historyBulkArchiveButton"),
  bulkRestore: document.querySelector<HTMLButtonElement>("#historyBulkRestoreButton"),
  bulkDelete: document.querySelector<HTMLButtonElement>("#historyBulkDeleteButton"),
  bulkDeleteCancel: document.querySelector<HTMLButtonElement>("#historyBulkDeleteCancelButton"),
  taskList: document.querySelector<HTMLElement>("#historyTaskList"),
  detail: document.querySelector<HTMLElement>("#historyDetail"),
  sentinel: document.querySelector<HTMLElement>("[data-history-load-more]"),
  refresh: document.querySelector<HTMLButtonElement>("#historyRefreshButton"),
};

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatDate(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 16).replace("T", " ");
  return date.toLocaleString(undefined, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function setText(element: HTMLElement | null, text: string): void {
  if (element) element.textContent = text;
}

function normalizeHistoryThemePreference(value: unknown): "system" | "light" | "dark" {
  return value === "light" || value === "dark" ? value : "system";
}

function resolveHistoryTheme(preference: "system" | "light" | "dark"): "light" | "dark" {
  if (preference === "light" || preference === "dark") return preference;
  return window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ? "dark" : "light";
}

function restoreHistoryThemePreference(): void {
  let saved = "system";
  try {
    saved = localStorage.getItem(HISTORY_THEME_STORAGE_KEY) || "system";
  } catch {
    saved = "system";
  }
  const preference = normalizeHistoryThemePreference(saved);
  document.documentElement.dataset.themePreference = preference;
  document.documentElement.dataset.theme = resolveHistoryTheme(preference);
}

function bindHistoryThemePreference(): void {
  window.matchMedia?.("(prefers-color-scheme: dark)")?.addEventListener?.("change", () => {
    if (document.documentElement.dataset.themePreference === "system") {
      restoreHistoryThemePreference();
    }
  });
}

function applyHistoryLocale(): void {
  restoreLocalePreference();
  document.title = translate("history.documentTitle");
}

function truncateText(value: unknown, limit: number): string {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length <= limit ? text : text.slice(0, limit - 1).trimEnd() + "…";
}

function historyFilterAttribute(key: HistoryFilterKey): string {
  return key.replace(/_/g, "-");
}

function facetDisplayValue(key: HistoryFilterKey, value: string): string {
  if (key === "prompt_mode") {
    if (value === "strict") return translate("history.promptMode.strict");
    if (value === "original") return translate("history.promptMode.original");
    if (value === "off") return translate("history.promptMode.off");
  }
  if (key === "quality") {
    if (value === "high") return translate("history.quality.high");
    if (value === "medium") return translate("history.quality.medium");
    if (value === "low") return translate("history.quality.low");
    if (value === "auto") return translate("history.quality.auto");
  }
  if (key === "ratio" && value === HISTORY_RATIO_OTHER_VALUE) return translate("history.ratioOther");
  return value;
}

function syncStateFromUrl(): void {
  const params = new URLSearchParams(window.location.search);
  historyState.q = params.get("q") || "";
  historyState.sort = params.get("sort") === "oldest" ? "oldest" : "newest";
  historyState.view = params.get("view") === "list" ? "list" : "grid";
  for (const key of HISTORY_FILTER_KEYS) {
    historyState[key] = params.get(key) || "";
  }
  historyState.selectedTaskId = params.get("task") || "";
  if (els.search) els.search.value = historyState.q;
  if (els.sort) els.sort.value = historyState.sort;
  syncHistoryViewMode();
}

function updateHistoryUrl(): void {
  const params = new URLSearchParams();
  if (historyState.q) params.set("q", historyState.q);
  if (historyState.sort !== "newest") params.set("sort", historyState.sort);
  if (historyState.view !== "grid") params.set("view", historyState.view);
  for (const key of HISTORY_FILTER_KEYS) {
    if (historyState[key]) params.set(key, historyState[key]);
  }
  if (historyState.selectedTaskId) params.set("task", historyState.selectedTaskId);
  const query = params.toString();
  const nextUrl = query ? `${window.location.pathname}?${query}` : window.location.pathname;
  window.history.replaceState(null, "", nextUrl);
}

async function loadSummary(): Promise<void> {
  try {
    const response = await fetch("/api/task-history/summary");
    const summary = await response.json() as HistorySummary;
    if (!response.ok) throw new Error((summary as any).detail || translate("history.summaryFailed"));
    setText(els.total, formatTranslation("history.total", { total: summary.total, archived: summary.archived_total }));
    renderFacetButtons(els.monthList, "month", summary.months.map((item) => ({ value: item.month, count: item.count })), translate("history.allMonths"));
    renderFacetButtons(els.promptModeList, "prompt_mode", summary.prompt_modes || [], translate("history.allPromptModes"));
    renderFacetButtons(els.qualityList, "quality", summary.qualities || [], translate("history.allQualities"));
    renderFacetButtons(els.ratioList, "ratio", summary.ratios, translate("history.allRatios"));
    renderFacetButtons(els.orientationList, "orientation", summary.orientations || [], translate("history.allOrientations"));
    renderFacetButtons(els.backendList, "backend", summary.backends || [], translate("history.allBackends"));
    renderFacetButtons(els.providerList, "provider", summary.providers || [], translate("history.allProviders"));
    syncArchiveButtons();
  } catch (error) {
    setText(els.total, errorMessage(error, translate("history.summaryFailed")));
  }
}

function renderFacetButtons(root: HTMLElement | null, key: HistoryFilterKey, items: HistoryFacet[], allLabel: string): void {
  if (!root) return;
  const current = String(historyState[key] || "");
  const attr = historyFilterAttribute(key);
  root.innerHTML = [
    `<button class="history-filter-button ${current ? "" : "active"}" type="button" data-history-${attr}="">${escapeHtml(allLabel)}</button>`,
    ...items.map((item) => {
      const active = current === item.value ? " active" : "";
      return `<button class="history-filter-button${active}" type="button" data-history-${attr}="${escapeHtml(item.value)}">${escapeHtml(facetDisplayValue(key, item.value))} <span>${item.count}</span></button>`;
    }),
  ].join("");
}

function syncArchiveButtons(): void {
  document.querySelectorAll<HTMLElement>("[data-history-archived]").forEach((button) => {
    button.classList.toggle("active", button.getAttribute("data-history-archived") === historyState.archived);
  });
}

function queryParams(cursor?: string | null): string {
  const params = new URLSearchParams();
  params.set("limit", String(HISTORY_PAGE_LIMIT));
  params.set("sort", historyState.sort);
  if (cursor) params.set("cursor", cursor);
  if (historyState.q) params.set("q", historyState.q);
  for (const key of HISTORY_FILTER_KEYS) {
    if (historyState[key]) params.set(key, historyState[key]);
  }
  return params.toString();
}

function syncHistoryViewMode(): void {
  const view = historyState.view === "list" ? "list" : "grid";
  historyState.view = view;
  els.taskList?.classList.toggle("history-view-grid", view === "grid");
  els.taskList?.classList.toggle("history-view-list", view === "list");
  els.viewToggle?.querySelectorAll<HTMLElement>("[data-history-view]").forEach((button) => {
    const active = button.dataset.historyView === view;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function setHistoryViewMode(view: string): void {
  historyState.view = view === "list" ? "list" : "grid";
  syncHistoryViewMode();
  updateHistoryUrl();
}

function setLoadMoreState(label: string, options: { hidden?: boolean; busy?: boolean } = {}): void {
  if (!els.sentinel) return;
  els.sentinel.textContent = label;
  els.sentinel.hidden = Boolean(options.hidden);
  els.sentinel.toggleAttribute("aria-busy", Boolean(options.busy));
}

function maybeLoadMoreFromScroll(): void {
  if (!els.taskList || historyState.loading || historyState.exhausted) return;
  const remaining = els.taskList.scrollHeight - els.taskList.scrollTop - els.taskList.clientHeight;
  if (remaining <= 320) void loadTasks();
}

async function loadTasks({ reset = false }: { reset?: boolean } = {}): Promise<void> {
  if (historyState.loading) return;
  if (!reset && historyState.exhausted) return;
  historyState.loading = true;
  const requestId = ++historyState.requestId;
  if (reset) {
    historyState.nextCursor = null;
    historyState.exhausted = false;
    historyState.loadedTaskIds.clear();
    historyState.selectedTaskIds.clear();
    historyState.selectionAnchorTaskId = "";
    historyState.deleteConfirming = false;
    if (els.taskList) els.taskList.innerHTML = "";
    renderBulkToolbar();
  }
  setLoadMoreState(translate("history.loadingMore"), { busy: true });
  const cursor = reset ? null : historyState.nextCursor;
  try {
    const response = await fetch(`/api/task-history/tasks?${queryParams(cursor)}`);
    const data = await response.json() as { tasks: HistoryTask[]; next_cursor: string | null; detail?: string };
    if (!response.ok) throw new Error(data.detail || translate("history.tasksFailed"));
    if (requestId !== historyState.requestId) return;
    renderTasks(data.tasks || [], { append: !reset });
    historyState.nextCursor = data.next_cursor || null;
    historyState.exhausted = !historyState.nextCursor;
    setLoadMoreState(
      historyState.exhausted ? translate("history.noMore") : "",
      { hidden: !historyState.exhausted },
    );
    window.requestAnimationFrame(maybeLoadMoreFromScroll);
  } catch (error) {
    if (requestId === historyState.requestId) renderTaskListMessage("history-error", errorMessage(error, translate("history.tasksFailed")));
    historyState.exhausted = false;
    setLoadMoreState(translate("history.loadFailed"));
  } finally {
    if (requestId === historyState.requestId) historyState.loading = false;
  }
}

function renderTasks(tasks: HistoryTask[], { append }: { append: boolean }): void {
  if (!els.taskList) return;
  syncHistoryViewMode();
  if (!append) els.taskList.innerHTML = "";
  const html = tasks
    .filter((task) => {
      if (historyState.loadedTaskIds.has(task.task_id)) return false;
      historyState.loadedTaskIds.add(task.task_id);
      return true;
    })
    .map(taskCardHtml)
    .join("");
  if (html) {
    els.taskList.querySelector(".history-empty, .history-error")?.remove();
    els.taskList.insertAdjacentHTML("beforeend", html);
  }
  trimMountedTaskCards();
  if (!els.taskList.querySelector(".history-task-card")) {
    renderTaskListMessage("history-empty", translate("history.noMatches"));
  }
  setText(els.resultSummary, formatTranslation("history.loadedCount", { count: historyState.loadedTaskIds.size }));
  updateTaskSelectionVisuals();
}

function renderTaskListMessage(className: string, message: string): void {
  if (!els.taskList) return;
  els.taskList.innerHTML = `<div class="${className}">${escapeHtml(message)}</div>`;
}

function trimMountedTaskCards(): void {
  if (!els.taskList) return;
  const cards = [...els.taskList.querySelectorAll<HTMLElement>(".history-task-card")];
  const overflow = cards.length - MAX_MOUNTED_TASK_CARDS;
  if (overflow <= 0) return;
  for (const card of cards.slice(0, overflow)) {
    const taskId = card.dataset.historyTaskCardId || "";
    historyState.selectedTaskIds.delete(taskId);
    if (historyState.selectionAnchorTaskId === taskId) historyState.selectionAnchorTaskId = "";
    card.remove();
  }
  let notice = els.taskList.querySelector<HTMLElement>(".history-window-notice");
  if (!notice) {
    notice = document.createElement("div");
    notice.className = "history-window-notice";
    els.taskList.prepend(notice);
  }
  notice.textContent = formatTranslation("history.windowNotice", { count: MAX_MOUNTED_TASK_CARDS });
}

function taskCardHtml(task: HistoryTask): string {
  const taskId = escapeHtml(task.task_id);
  const thumbnailUrl = historyThumbnailUrl(task);
  const thumb = thumbnailUrl
    ? `<img src="${escapeHtml(thumbnailUrl)}" alt="" loading="lazy" decoding="async" draggable="false">`
    : "";
  const counts = `${task.generated_count || 0}/${task.total_count || 0}`;
  const selected = historyState.selectedTaskIds.has(task.task_id);
  const active = historyState.selectedTaskId === task.task_id;
  const source = task.backend || task.provider || "";
  const promptMode = facetDisplayValue("prompt_mode", task.prompt_mode || "");
  const quality = facetDisplayValue("quality", task.quality || "");
  const metaItems = [
    formatDate(task.created_at),
    task.status,
    task.size || task.ratio || task.orientation || "",
    promptMode,
    quality,
    source,
    counts,
  ].filter(Boolean);
  return `
    <article
      class="history-task-card${active ? " active" : ""}${selected ? " selected" : ""}"
      data-history-task-card-id="${taskId}"
      role="option"
      aria-selected="${active ? "true" : "false"}"
    >
      <label class="history-task-select" aria-label="${escapeHtml(translate("history.selectTask"))}">
        <input type="checkbox" data-history-task-select="${taskId}" ${selected ? "checked" : ""}>
      </label>
      <span class="history-task-active-badge" aria-hidden="${active ? "false" : "true"}">${escapeHtml(translate("history.viewing"))}</span>
      <button class="history-task-open" type="button" data-history-task-id="${taskId}">
        <span class="history-task-thumb">${thumb}</span>
        <span class="history-task-copy">
          <span class="history-task-title">${escapeHtml(task.prompt_preview || task.mode || task.task_id)}</span>
          <span class="history-task-meta">
            ${metaItems.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
          </span>
        </span>
      </button>
    </article>
  `;
}

function historyThumbnailUrl(task: HistoryTask): string {
  const url = String(task.thumbnail_url || "");
  if (!url) return "";
  const staticThumbMatch = url.match(/(?:^|\/)(\d{14}-[a-f0-9]+)-image-(\d+)-thumb\.[a-z0-9]+(?:[?#].*)?$/i);
  if (url.includes("/outputs/thumbnails/") && staticThumbMatch && staticThumbMatch[1] === task.task_id) {
    const outputIndex = staticThumbMatch[2] || "1";
    return versionHistoryThumbnailUrl(`/api/tasks/${encodeURIComponent(task.task_id)}/outputs/${encodeURIComponent(outputIndex)}/thumbnail`);
  }
  return versionHistoryThumbnailUrl(url);
}

function versionHistoryThumbnailUrl(url: string): string {
  if (!url.startsWith("/api/tasks/") || !url.includes("/thumbnail")) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}v=${HISTORY_THUMBNAIL_CACHE_VERSION}`;
}

function updateTaskSelectionVisuals(taskId = historyState.selectedTaskId): void {
  els.taskList?.querySelectorAll<HTMLElement>(".history-task-card").forEach((card) => {
    const cardTaskId = card.dataset.historyTaskCardId || "";
    const active = Boolean(taskId && cardTaskId === taskId);
    const selected = historyState.selectedTaskIds.has(cardTaskId);
    card.classList.toggle("active", active);
    card.classList.toggle("selected", selected);
    card.setAttribute("aria-selected", active ? "true" : "false");
    const activeBadge = card.querySelector<HTMLElement>(".history-task-active-badge");
    activeBadge?.setAttribute("aria-hidden", active ? "false" : "true");
    const input = card.querySelector<HTMLInputElement>("[data-history-task-select]");
    if (input) input.checked = selected;
  });
}

function visibleHistoryTaskIds(): string[] {
  return Array.from(els.taskList?.querySelectorAll<HTMLElement>(".history-task-card[data-history-task-card-id]") || [])
    .map((card) => String(card.dataset.historyTaskCardId || ""))
    .filter(Boolean);
}

function applyHistoryTaskSelection(taskIds: string[], anchorTaskId = ""): void {
  historyState.selectedTaskIds = new Set(taskIds.filter(Boolean));
  if (anchorTaskId) historyState.selectionAnchorTaskId = anchorTaskId;
  historyState.deleteConfirming = false;
  updateTaskSelectionVisuals();
  renderBulkToolbar();
}

function toggleHistoryTaskSelection(taskId: string, anchor = true): void {
  if (!taskId) return;
  const next = new Set(historyState.selectedTaskIds);
  if (next.has(taskId)) {
    next.delete(taskId);
  } else {
    next.add(taskId);
  }
  historyState.selectedTaskIds = next;
  if (anchor) historyState.selectionAnchorTaskId = taskId;
  historyState.deleteConfirming = false;
  updateTaskSelectionVisuals();
  renderBulkToolbar();
}

function selectHistoryTaskRange(anchorTaskId: string, taskId: string): void {
  if (!taskId) return;
  const visibleIds = visibleHistoryTaskIds();
  const fallbackAnchor = historyState.selectionAnchorTaskId || historyState.selectedTaskId || taskId;
  const anchor = anchorTaskId || fallbackAnchor;
  const anchorIndex = visibleIds.indexOf(anchor);
  const targetIndex = visibleIds.indexOf(taskId);
  if (anchorIndex < 0 || targetIndex < 0) {
    applyHistoryTaskSelection([...historyState.selectedTaskIds, taskId], taskId);
    return;
  }
  const [start, end] = anchorIndex <= targetIndex ? [anchorIndex, targetIndex] : [targetIndex, anchorIndex];
  applyHistoryTaskSelection([...historyState.selectedTaskIds, ...visibleIds.slice(start, end + 1)], anchor);
}

function handleHistoryTaskShortcutSelection(taskId: string, event: MouseEvent | KeyboardEvent): boolean {
  if (!taskId || (!event.shiftKey && !event.metaKey && !event.ctrlKey)) return false;
  event.preventDefault();
  event.stopPropagation();
  if (event.shiftKey) {
    selectHistoryTaskRange(historyState.selectionAnchorTaskId || historyState.selectedTaskId || taskId, taskId);
    return true;
  }
  toggleHistoryTaskSelection(taskId);
  return true;
}

async function loadTaskDetail(taskId: string): Promise<void> {
  if (!taskId) return;
  historyState.selectedTaskId = taskId;
  historyState.deleteConfirming = false;
  historyState.deleteUnselectedConfirmTaskId = "";
  updateHistoryUrl();
  updateTaskSelectionVisuals(taskId);
  els.page?.classList.add("history-detail-open");
  renderDetailShell(translate("history.loadingDetail"));
  try {
    const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || translate("history.detailFailed"));
    renderTaskDetail(data.task || {});
  } catch (error) {
    renderDetailShell(errorMessage(error, translate("history.detailFailed")), "history-error");
  }
}

function renderDetailShell(message: string, className = "history-detail-empty"): void {
  if (!els.detail) return;
  els.detail.innerHTML = `
    <div class="history-detail-header">
      <div>
        <p class="history-detail-kicker">${escapeHtml(translate("history.detail"))}</p>
        <h2 class="history-detail-title">${escapeHtml(translate("history.detailTitle"))}</h2>
      </div>
      <button id="historyDetailClose" class="drawer-close-button history-detail-close" type="button" data-history-detail-close aria-label="${escapeHtml(translate("history.closeDetail"))}">×</button>
    </div>
    <div class="${className}">${escapeHtml(message)}</div>
  `;
}

function historyTaskModeLabel(mode: unknown): string {
  const value = String(mode || "");
  if (value === "generate") return translate("taskMode.generate");
  if (value === "edit") return translate("taskMode.edit");
  return value || translate("history.detail");
}

function renderTaskDetail(task: any): void {
  if (!els.detail) return;
  historyState.detailTask = task;
  const taskId = String(task.task_id || historyState.selectedTaskId || "");
  const urls = taskOutputRecords(task);
  const selectedCount = taskSelectedOutputIndexes(task).size;
  const images = urls.map((record, index) => historyDetailImageHtml(taskId, record, index, selectedCount)).join("");
  const zipHref = `/api/tasks/${encodeURIComponent(taskId)}/outputs.zip`;
  const canZip = urls.length > 1;
  const canDeleteUnselected = selectedCount > 0 && selectedCount < urls.length;
  const confirmingDeleteUnselected = historyState.deleteUnselectedConfirmTaskId === taskId;
  const title = detailTitle(task);
  els.detail.innerHTML = `
    <div class="history-detail-header">
      <div>
        <p class="history-detail-kicker">${escapeHtml(historyTaskModeLabel(task.mode))}</p>
        <h2 class="history-detail-title" title="${escapeHtml(task.prompt || title)}">${escapeHtml(title)}</h2>
      </div>
      <button id="historyDetailClose" class="drawer-close-button history-detail-close" type="button" data-history-detail-close aria-label="${escapeHtml(translate("history.closeDetail"))}">×</button>
    </div>
    <div class="history-detail-meta">
      <span>${escapeHtml(formatDate(task.created_at || ""))}</span>
      <span>${escapeHtml(task.status || "")}</span>
      <span>${escapeHtml(task.params?.size || task.output_size || "")}</span>
      <span>${escapeHtml(facetDisplayValue("prompt_mode", task.params?.prompt_fidelity || ""))}</span>
      <span>${escapeHtml(facetDisplayValue("quality", task.params?.quality || task.quality || ""))}</span>
      <span>${escapeHtml(task.backend || task.api_provider_name || "")}</span>
    </div>
    <div class="history-detail-actions">
      <button class="ghost-button text-sm" type="button" data-history-reuse-task="${escapeHtml(taskId)}">${escapeHtml(translate("history.reuseTask"))}</button>
      ${canZip ? `<a class="ghost-button text-sm" href="${escapeHtml(zipHref)}" download>${escapeHtml(translate("history.downloadAll"))}</a>` : ""}
      ${selectedCount > 1 ? `<a class="ghost-button text-sm" href="${escapeHtml(zipHref)}?selected=1" download>${escapeHtml(translate("history.downloadSelected"))}</a>` : ""}
      ${canDeleteUnselected ? `<button class="ghost-button text-sm danger-button" type="button" data-history-delete-unselected="${escapeHtml(taskId)}">${escapeHtml(confirmingDeleteUnselected ? translate("history.confirmDeleteUnselected") : translate("history.deleteUnselected"))}</button>` : ""}
      ${confirmingDeleteUnselected ? `<button class="ghost-button text-sm" type="button" data-history-delete-unselected-cancel>${escapeHtml(translate("action.cancel"))}</button>` : ""}
    </div>
    <div class="history-detail-images">${images || `<div class="history-detail-empty">${escapeHtml(translate("history.noPreview"))}</div>`}</div>
    ${promptCompareHtml(task)}
  `;
}

function detailTitle(task: any): string {
  return truncateText(task.prompt_preview || task.prompt || task.mode || task.task_id || translate("history.untitled"), 120);
}

function taskOutputRecords(task: any): Array<{ url: string; index: number; selected: boolean; revisedPrompt: string }> {
  const selectedIndexes = taskSelectedOutputIndexes(task);
  const records: Array<{ url: string; index: number; selected: boolean; revisedPrompt: string }> = [];
  const outputs = Array.isArray(task.outputs) ? task.outputs : [];
  outputs.forEach((output: any, fallbackIndex: number) => {
    if (!output || output.deleted || output.status === "deleted") return;
    const url = String(output.url || output.output_url || "");
    if (!url || output.status === "failed") return;
    const outputIndex = positiveInt(output.index) || fallbackIndex + 1;
    records.push({
      url,
      index: outputIndex,
      selected: selectedIndexes.has(outputIndex),
      revisedPrompt: String(output.revised_prompt || ""),
    });
  });
  if (records.length) return records;
  const urls = Array.isArray(task.output_urls) ? task.output_urls : (task.output_url ? [task.output_url] : []);
  return urls
    .filter(Boolean)
    .map((url: string, index: number) => {
      const outputIndex = index + 1;
      return {
        url: String(url),
        index: outputIndex,
        selected: selectedIndexes.has(outputIndex),
        revisedPrompt: String(task.revised_prompts?.[index] || task.revised_prompt || ""),
      };
    });
}

function historyDetailImageHtml(
  taskId: string,
  record: { url: string; index: number; selected: boolean; revisedPrompt: string },
  index: number,
  selectedCount: number,
): string {
  const selectedClass = record.selected ? " selected" : "";
  const selectedText = record.selected ? translate("history.selected") : translate("history.select");
  return `
    <div class="history-detail-image${selectedClass}">
      <button
        class="history-detail-image-preview"
        type="button"
        data-history-lightbox-url="${escapeHtml(record.url)}"
        aria-label="${escapeHtml(translate("history.openPreview"))}"
      >
        <img src="${escapeHtml(record.url)}" alt="" loading="lazy" decoding="async">
      </button>
      <div class="history-detail-image-actions">
        <button
          class="ghost-button text-sm"
          type="button"
          aria-pressed="${record.selected ? "true" : "false"}"
          data-history-output-selected-task-id="${escapeHtml(taskId)}"
          data-history-output-selected-index="${record.index}"
        >${selectedText}</button>
        <a class="ghost-button text-sm" href="${escapeHtml(record.url)}" download>${escapeHtml(formatTranslation("history.downloadIndex", { index: index + 1 }))}</a>
        <button class="ghost-button text-sm" type="button" data-history-reference-handoff-url="${escapeHtml(record.url)}">${escapeHtml(translate("history.addReference"))}</button>
        ${selectedCount === 1 && record.selected ? `<a class="ghost-button text-sm" href="${escapeHtml(record.url)}" download>${escapeHtml(translate("history.downloadSelected"))}</a>` : ""}
      </div>
    </div>
  `;
}

function taskSelectedOutputIndexes(task: any): Set<number> {
  const indexes = new Set<number>();
  if (Array.isArray(task.selected_output_indexes)) {
    task.selected_output_indexes.forEach((value: any) => {
      const index = positiveInt(value);
      if (index !== null) indexes.add(index);
    });
  }
  return indexes;
}

function promptCompareHtml(task: any): string {
  const originalPrompt = promptTextValue(task.prompt || "");
  const submittedPrompt = promptTextValue(task.prompt_for_model || "");
  const revisedPrompt = revisedPromptText(task);
  const seen = new Set<string>();
  const panels: string[] = [];
  const addPanel = (kind: string, title: string, text: string): boolean => {
    const value = promptTextValue(text);
    const key = normalizePromptForCompare(value);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    panels.push(promptPanelHtml(kind, title, value));
    return true;
  };

  addPanel("original", translate("history.promptOriginal"), originalPrompt);
  const hasRevisedPanel = addPanel("revised", translate("history.promptRevised"), revisedPrompt);
  if (!hasRevisedPanel) {
    addPanel("submitted", translate("history.promptSubmitted"), submittedPrompt);
  }
  return panels.length ? `<section class="history-prompt-compare" aria-label="${escapeHtml(translate("history.promptCompare"))}">${panels.join("")}</section>` : "";
}

function promptTextValue(value: unknown): string {
  return String(value || "").trim();
}

function normalizePromptForCompare(value: string): string {
  return promptTextValue(value).replace(/\s+/g, " ").trim();
}

function uniquePromptTexts(values: unknown[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  values.forEach((value) => {
    const text = promptTextValue(value);
    const key = normalizePromptForCompare(text);
    if (!key || seen.has(key)) return;
    seen.add(key);
    result.push(text);
  });
  return result;
}

function revisedPromptText(task: any): string {
  const values: unknown[] = [];
  if (Array.isArray(task.revised_prompts)) values.push(...task.revised_prompts);
  if (task.revised_prompt) values.push(task.revised_prompt);
  if (Array.isArray(task.outputs)) {
    task.outputs.forEach((output: any) => {
      if (output?.revised_prompt) values.push(output.revised_prompt);
    });
  }
  return uniquePromptTexts(values).join("\n\n");
}

function promptPanelHtml(kind: string, title: string, text: string): string {
  return `
    <article class="history-prompt-panel">
      <div class="history-prompt-panel-header">
        <h3>${escapeHtml(title)}</h3>
        <button
          class="ghost-button text-sm history-prompt-copy"
          type="button"
          data-history-copy-prompt-kind="${escapeHtml(kind)}"
          aria-label="${escapeHtml(formatTranslation("history.copyPromptPanel", { title }))}"
        >${escapeHtml(translate("history.copyPromptShort"))}</button>
      </div>
      <div class="history-detail-prompt">${escapeHtml(text || translate("history.promptEmpty"))}</div>
    </article>
  `;
}

function positiveInt(value: unknown): number | null {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function applyFilter(key: HistoryFilterKey, value: string): void {
  historyState[key] = value;
  historyState.selectedTaskId = "";
  historyState.deleteConfirming = false;
  const attr = historyFilterAttribute(key);
  document.querySelectorAll(`[data-history-${attr}]`).forEach((node) => {
    node.classList.toggle("active", (node as HTMLElement).getAttribute(`data-history-${attr}`) === value);
  });
  updateHistoryUrl();
  void loadTasks({ reset: true });
}

function renderBulkToolbar(): void {
  if (!els.bulkToolbar || !els.bulkCount) return;
  const count = historyState.selectedTaskIds.size;
  els.bulkToolbar.classList.toggle("hidden", count === 0);
  els.bulkToolbar.toggleAttribute("hidden", count === 0);
  els.bulkCount.textContent = count ? formatTranslation("history.selectedCount", { count }) : "";
  if (els.bulkDelete) {
    els.bulkDelete.textContent = historyState.deleteConfirming ? translate("history.confirmDelete") : translate("action.delete");
    els.bulkDelete.classList.toggle("danger-button", historyState.deleteConfirming);
  }
  els.bulkDeleteCancel?.classList.toggle("hidden", !historyState.deleteConfirming);
}

async function setTaskArchiveState(taskId: string, archived: boolean): Promise<void> {
  const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/archive`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ archived }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || (archived ? translate("taskActions.archiveFailed") : translate("archive.restoreFailed")));
}

async function archiveSelectedTasks(archived: boolean): Promise<void> {
  const ids = [...historyState.selectedTaskIds];
  if (!ids.length) return;
  setText(els.resultSummary, archived ? translate("archive.archiving") : translate("archive.restoring"));
  try {
    await Promise.all(ids.map((taskId) => setTaskArchiveState(taskId, archived)));
    historyState.selectedTaskIds.clear();
    historyState.deleteConfirming = false;
    await loadSummary();
    await loadTasks({ reset: true });
    setText(els.resultSummary, archived ? formatTranslation("batch.archivedCount", { count: ids.length }) : formatTranslation("archive.restoredCount", { count: ids.length }));
  } catch (error) {
    setText(els.resultSummary, errorMessage(error, archived ? translate("taskActions.archiveFailed") : translate("archive.restoreFailed")));
  } finally {
    renderBulkToolbar();
  }
}

async function deleteSelectedTasks(): Promise<void> {
  const ids = [...historyState.selectedTaskIds];
  if (!ids.length) return;
  if (!historyState.deleteConfirming) {
    historyState.deleteConfirming = true;
    renderBulkToolbar();
    return;
  }
  setText(els.resultSummary, translate("archive.deleting"));
  try {
    for (const taskId of ids) {
      const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}`, { method: "DELETE" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || translate("taskActions.deleteFailed"));
    }
    historyState.selectedTaskIds.clear();
    historyState.deleteConfirming = false;
    await loadSummary();
    await loadTasks({ reset: true });
    setText(els.resultSummary, formatTranslation("batch.deletedCount", { count: ids.length, skipped: "" }));
  } catch (error) {
    setText(els.resultSummary, errorMessage(error, translate("taskActions.deleteFailed")));
  } finally {
    renderBulkToolbar();
  }
}

async function updateOutputSelection(button: HTMLElement): Promise<void> {
  const taskId = button.dataset.historyOutputSelectedTaskId || historyState.selectedTaskId;
  const outputIndex = positiveInt(button.dataset.historyOutputSelectedIndex);
  if (!taskId || outputIndex === null) return;
  const selected = button.getAttribute("aria-pressed") !== "true";
  try {
    const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/outputs/${encodeURIComponent(String(outputIndex))}/selected`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selected }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || translate("taskActions.updated"));
    renderTaskDetail(data.task || {});
  } catch (error) {
    setText(els.resultSummary, errorMessage(error, translate("taskContext.actionFailed")));
  }
}

async function deleteUnselectedOutputs(taskId: string): Promise<void> {
  if (!taskId) return;
  if (historyState.deleteUnselectedConfirmTaskId !== taskId) {
    historyState.deleteUnselectedConfirmTaskId = taskId;
    renderTaskDetail(historyState.detailTask || {});
    return;
  }
  try {
    const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/outputs/delete-unselected`, { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || translate("taskActions.deleteFailed"));
    historyState.deleteUnselectedConfirmTaskId = "";
    renderTaskDetail(data.task || {});
    await loadTasks({ reset: true });
  } catch (error) {
    setText(els.resultSummary, errorMessage(error, translate("taskActions.deleteFailed")));
  }
}

function promptTextForKind(kind: string): string {
  const task = historyState.detailTask || {};
  if (kind === "submitted") return String(task.prompt_for_model || "").trim();
  if (kind === "revised") {
    return revisedPromptText(task);
  }
  return String(task.prompt || task.prompt_preview || "").trim();
}

async function writeClipboardText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.append(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

function setPromptCopyButtonFeedback(button: HTMLElement, message: string): void {
  const original = button.dataset.historyOriginalLabel || button.textContent || translate("history.copyPromptShort");
  button.dataset.historyOriginalLabel = original;
  button.textContent = message;
  button.classList.add("copied");
  window.setTimeout(() => {
    if (!button.isConnected) return;
    button.textContent = button.dataset.historyOriginalLabel || translate("history.copyPromptShort");
    button.classList.remove("copied");
  }, 1600);
}

async function copyPromptToClipboard(kind = "original", button?: HTMLElement): Promise<void> {
  const text = promptTextForKind(kind);
  if (!text) {
    if (button) {
      setPromptCopyButtonFeedback(button, translate("history.noPromptShort"));
    } else {
      setText(els.resultSummary, translate("history.noPrompt"));
    }
    return;
  }
  try {
    await writeClipboardText(text);
    if (button) setPromptCopyButtonFeedback(button, translate("history.promptCopiedShort"));
    setText(els.resultSummary, translate("history.promptCopied"));
  } catch (error) {
    if (button) setPromptCopyButtonFeedback(button, translate("history.promptCopyFailedShort"));
    setText(els.resultSummary, errorMessage(error, translate("history.promptCopyFailed")));
  }
}

function reuseHistoryTask(taskId: string): void {
  const task = historyState.detailTask || {};
  const actualTaskId = String(task.task_id || taskId || "");
  if (!actualTaskId) return;
  try {
    localStorage.setItem(HISTORY_TASK_REUSE_HANDOFF_KEY, JSON.stringify({
      task_id: actualTaskId,
      source: "history",
      added_at: new Date().toISOString(),
    }));
    window.location.href = "/";
  } catch (error) {
    setText(els.resultSummary, errorMessage(error, translate("taskContext.actionFailed")));
  }
}

function handoffReferenceToMain(url: string): void {
  if (!url) return;
  localStorage.setItem(HISTORY_REFERENCE_HANDOFF_KEY, JSON.stringify([{ url, source: "history", added_at: new Date().toISOString() }]));
  window.location.href = "/";
}

function ensureHistoryLightbox(): HTMLElement {
  let lightbox = document.querySelector<HTMLElement>(".history-lightbox");
  if (lightbox) return lightbox;
  lightbox = document.createElement("div");
  lightbox.className = "history-lightbox";
  lightbox.hidden = true;
  lightbox.innerHTML = `
    <button class="drawer-close-button history-lightbox-close" type="button" data-history-lightbox-close aria-label="${escapeHtml(translate("history.closePreview"))}">×</button>
    <img alt="">
  `;
  document.body.append(lightbox);
  return lightbox;
}

function openHistoryLightbox(url: string): void {
  if (!url) return;
  const lightbox = ensureHistoryLightbox();
  const image = lightbox.querySelector<HTMLImageElement>("img");
  if (image) image.src = url;
  lightbox.hidden = false;
  document.body.classList.add("history-lightbox-open");
}

function closeHistoryLightbox(): void {
  const lightbox = document.querySelector<HTMLElement>(".history-lightbox");
  if (!lightbox || lightbox.hidden) return;
  lightbox.hidden = true;
  const image = lightbox.querySelector<HTMLImageElement>("img");
  if (image) image.removeAttribute("src");
  document.body.classList.remove("history-lightbox-open");
}

function closeDetail(): void {
  historyState.selectedTaskId = "";
  els.page?.classList.remove("history-detail-open");
  updateHistoryUrl();
  updateTaskSelectionVisuals("");
  renderDetailShell(translate("history.detailEmpty"));
}

function bindEvents(): void {
  let searchTimer = 0;
  els.search?.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      historyState.q = els.search?.value.trim() || "";
      historyState.selectedTaskId = "";
      updateHistoryUrl();
      void loadTasks({ reset: true });
    }, 180);
  });
  els.searchClear?.addEventListener("click", () => {
    if (els.search) els.search.value = "";
    historyState.q = "";
    historyState.selectedTaskId = "";
    updateHistoryUrl();
    void loadTasks({ reset: true });
  });
  els.sort?.addEventListener("change", () => {
    historyState.sort = els.sort?.value === "oldest" ? "oldest" : "newest";
    historyState.selectedTaskId = "";
    updateHistoryUrl();
    void loadTasks({ reset: true });
  });
  document.addEventListener("change", (event) => {
    const target = event.target as HTMLElement | null;
    const checkbox = target?.closest<HTMLInputElement>("[data-history-task-select]");
    if (!checkbox) return;
    const taskId = checkbox.dataset.historyTaskSelect || "";
    if (checkbox.checked) {
      historyState.selectedTaskIds.add(taskId);
    } else {
      historyState.selectedTaskIds.delete(taskId);
    }
    historyState.selectionAnchorTaskId = taskId;
    historyState.deleteConfirming = false;
    updateTaskSelectionVisuals();
    renderBulkToolbar();
  });
  document.addEventListener("click", (event) => {
    const target = event.target as HTMLElement | null;
    const historySelect = target?.closest<HTMLElement>("[data-history-task-select]");
    if (historySelect) {
      if (handleHistoryTaskShortcutSelection(historySelect.dataset.historyTaskSelect || "", event)) return;
      event.stopPropagation();
      return;
    }
    const viewButton = target?.closest<HTMLElement>("[data-history-view]");
    if (viewButton) {
      setHistoryViewMode(viewButton.dataset.historyView || "grid");
      return;
    }
    const taskButton = target?.closest<HTMLElement>("[data-history-task-id]");
    if (taskButton) {
      if (handleHistoryTaskShortcutSelection(taskButton.dataset.historyTaskId || "", event)) return;
      void loadTaskDetail(taskButton.dataset.historyTaskId || "");
      return;
    }
    const selectButton = target?.closest<HTMLElement>("[data-history-output-selected-task-id]");
    if (selectButton) {
      void updateOutputSelection(selectButton);
      return;
    }
    const deleteUnselectedButton = target?.closest<HTMLElement>("[data-history-delete-unselected]");
    if (deleteUnselectedButton) {
      void deleteUnselectedOutputs(deleteUnselectedButton.dataset.historyDeleteUnselected || "");
      return;
    }
    const referenceHandoffButton = target?.closest<HTMLElement>("[data-history-reference-handoff-url]");
    if (referenceHandoffButton) {
      handoffReferenceToMain(referenceHandoffButton.dataset.historyReferenceHandoffUrl || "");
      return;
    }
    const copyPromptButton = target?.closest<HTMLElement>("[data-history-copy-prompt-kind]");
    if (copyPromptButton) {
      void copyPromptToClipboard(copyPromptButton.dataset.historyCopyPromptKind || "original", copyPromptButton);
      return;
    }
    const reuseTaskButton = target?.closest<HTMLElement>("[data-history-reuse-task]");
    if (reuseTaskButton) {
      reuseHistoryTask(reuseTaskButton.dataset.historyReuseTask || "");
      return;
    }
    const lightboxButton = target?.closest<HTMLElement>("[data-history-lightbox-url]");
    if (lightboxButton) {
      openHistoryLightbox(lightboxButton.dataset.historyLightboxUrl || "");
      return;
    }
    if (target?.closest("[data-history-lightbox-close]")) {
      closeHistoryLightbox();
      return;
    }
    const lightbox = target?.closest<HTMLElement>(".history-lightbox");
    if (lightbox && target === lightbox) {
      closeHistoryLightbox();
      return;
    }
    if (target?.closest("[data-history-delete-unselected-cancel]")) {
      historyState.deleteUnselectedConfirmTaskId = "";
      renderTaskDetail(historyState.detailTask || {});
      return;
    }
    if (target?.closest("[data-history-detail-close]")) {
      closeDetail();
      return;
    }
    for (const key of HISTORY_FILTER_KEYS) {
      const attr = historyFilterAttribute(key);
      const button = target?.closest<HTMLElement>(`[data-history-${attr}]`);
      if (button) {
        applyFilter(key, button.getAttribute(`data-history-${attr}`) || "");
        return;
      }
    }
  });
  els.bulkArchive?.addEventListener("click", () => void archiveSelectedTasks(true));
  els.bulkRestore?.addEventListener("click", () => void archiveSelectedTasks(false));
  els.bulkDelete?.addEventListener("click", () => void deleteSelectedTasks());
  els.bulkDeleteCancel?.addEventListener("click", () => {
    historyState.deleteConfirming = false;
    renderBulkToolbar();
  });
  els.refresh?.addEventListener("click", () => {
    void loadSummary();
    void loadTasks({ reset: true });
  });
  els.taskList?.addEventListener("dragstart", (event) => {
    const target = event.target as HTMLElement | null;
    if (target?.closest(".history-task-thumb img")) event.preventDefault();
  });
  els.taskList?.addEventListener("scroll", maybeLoadMoreFromScroll, { passive: true });
  document.addEventListener(LOCALE_CHANGE_EVENT, () => {
    document.title = translate("history.documentTitle");
    syncHistoryViewMode();
    syncArchiveButtons();
    els.taskList?.querySelectorAll<HTMLElement>(".history-task-active-badge").forEach((badge) => {
      badge.textContent = translate("history.viewing");
    });
    if (historyState.detailTask) {
      renderTaskDetail(historyState.detailTask);
    } else if (!historyState.selectedTaskId) {
      renderDetailShell(translate("history.detailEmpty"));
    }
    renderBulkToolbar();
    setLoadMoreState(historyState.loading
      ? translate("history.loadingMore")
      : historyState.exhausted
        ? translate("history.noMore")
        : "", {
      hidden: !historyState.loading && !historyState.exhausted,
      busy: historyState.loading,
    });
  });
  window.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const lightbox = document.querySelector<HTMLElement>(".history-lightbox");
    if (lightbox && !lightbox.hidden) {
      closeHistoryLightbox();
      return;
    }
    if (historyState.selectedTaskId) closeDetail();
  });
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

async function bootHistoryPage(): Promise<void> {
  restoreHistoryThemePreference();
  bindHistoryThemePreference();
  applyHistoryLocale();
  syncStateFromUrl();
  renderDetailShell(translate("history.detailEmpty"));
  bindEvents();
  await loadSummary();
  await loadTasks({ reset: true });
  if (historyState.selectedTaskId) {
    void loadTaskDetail(historyState.selectedTaskId);
  }
}

void bootHistoryPage();
