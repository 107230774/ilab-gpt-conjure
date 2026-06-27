import { getEls } from "./dom";
import { getLegacyBridge } from "./state";

const MOBILE_WORKSPACE_TABS = new Set(["reference", "prompt", "settings", "preview"]);
let mobileWorkspaceInitialized = false;

function normalizeTab(tab: unknown): string {
  const value = String(tab || "").trim();
  return MOBILE_WORKSPACE_TABS.has(value) ? value : "reference";
}

function setMobileWorkspaceTab(tab: unknown): void {
  const nextTab = normalizeTab(tab);
  document.documentElement.dataset.mobileWorkspace = nextTab;
  document.querySelectorAll<HTMLElement>("[data-mobile-workspace-tab]").forEach((button: HTMLElement) => {
    const active = button.dataset.mobileWorkspaceTab === nextTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
  if (nextTab === "preview") {
    closeMobileHistoryDrawer();
  }
}

function openMobileHistoryDrawer(): void {
  document.documentElement.dataset.mobileHistoryOpen = "true";
  const els = getEls();
  els.mobileHistoryBackdrop?.classList.remove("hidden");
  els.mobileHistoryButton?.setAttribute("aria-expanded", "true");
}

function closeMobileHistoryDrawer(): void {
  delete document.documentElement.dataset.mobileHistoryOpen;
  const els = getEls();
  els.mobileHistoryBackdrop?.classList.add("hidden");
  els.mobileHistoryButton?.setAttribute("aria-expanded", "false");
}

function bindMobileWorkspaceEvents(): void {
  const els = getEls();
  els.mobileWorkspaceTabs?.addEventListener("click", (event: Event) => {
    const button = (event.target as Element | null)?.closest?.("[data-mobile-workspace-tab]") as HTMLElement | null;
    if (!button) return;
    setMobileWorkspaceTab(button.dataset.mobileWorkspaceTab);
  });
  els.mobileHistoryButton?.addEventListener("click", openMobileHistoryDrawer);
  els.mobileHistoryCloseButton?.addEventListener("click", closeMobileHistoryDrawer);
  els.mobileHistoryBackdrop?.addEventListener("click", closeMobileHistoryDrawer);
  els.queueButton?.addEventListener("click", () => {
    const state = getLegacyBridge().state;
    if ((state.queue?.waiting || []).length || (state.queue?.running || []).length) {
      setMobileWorkspaceTab("preview");
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || document.documentElement.dataset.mobileHistoryOpen !== "true") return;
    closeMobileHistoryDrawer();
  });
}

export function initMobileWorkspaceFeature(): void {
  if (mobileWorkspaceInitialized) return;
  mobileWorkspaceInitialized = true;
  setMobileWorkspaceTab(document.documentElement.dataset.mobileWorkspace || "reference");
  bindMobileWorkspaceEvents();
  Object.assign(getLegacyBridge().methods, {
    setMobileWorkspaceTab,
    openMobileHistoryDrawer,
    closeMobileHistoryDrawer,
  });
}
