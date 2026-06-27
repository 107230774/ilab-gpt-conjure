import { getEls } from "./dom";
import { LOCALE_CHANGE_EVENT, translate } from "./i18n";

type GuideSection = {
  id: string;
  titleKey: string;
  bodyKeys: string[];
};

const GUIDE_SECTIONS: GuideSection[] = [
  {
    id: "quick-start",
    titleKey: "userGuide.quickStart",
    bodyKeys: [
      "userGuide.quickStart.1",
      "userGuide.quickStart.2",
      "userGuide.quickStart.3",
      "userGuide.quickStart.4",
      "userGuide.quickStart.5",
    ],
  },
  {
    id: "workspace",
    titleKey: "userGuide.workspace",
    bodyKeys: [
      "userGuide.workspace.history",
      "userGuide.workspace.references",
      "userGuide.workspace.prompt",
      "userGuide.workspace.settings",
      "userGuide.workspace.preview",
      "userGuide.workspace.top",
    ],
  },
  {
    id: "gallery",
    titleKey: "userGuide.gallery",
    bodyKeys: [
      "userGuide.gallery.1",
      "userGuide.gallery.2",
      "userGuide.gallery.3",
      "userGuide.gallery.4",
      "userGuide.gallery.5",
    ],
  },
  {
    id: "templates",
    titleKey: "userGuide.templates",
    bodyKeys: [
      "userGuide.templates.1",
      "userGuide.templates.2",
      "userGuide.templates.3",
      "userGuide.templates.4",
      "userGuide.templates.5",
    ],
  },
  {
    id: "results",
    titleKey: "userGuide.results",
    bodyKeys: [
      "userGuide.results.addReference",
      "userGuide.results.stage",
      "userGuide.results.prompt",
      "userGuide.results.download",
      "userGuide.results.refresh",
    ],
  },
  {
    id: "faq",
    titleKey: "userGuide.faq",
    bodyKeys: [
      "userGuide.faq.addReference",
      "userGuide.faq.runDisabled",
      "userGuide.faq.gallery",
      "userGuide.faq.stage",
      "userGuide.faq.templates",
    ],
  },
];

let userGuideInitialized = false;
const DEFAULT_GUIDE_SECTION_ID = GUIDE_SECTIONS[0]?.id || "quick-start";
let activeSectionId = DEFAULT_GUIDE_SECTION_ID;

function escapeHtml(value: string): string {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function sectionSearchText(section: GuideSection): string {
  return [
    translate(section.titleKey),
    ...section.bodyKeys.map((key) => translate(key)),
  ].join(" ").toLowerCase();
}

function matchingSections(query: string): GuideSection[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return GUIDE_SECTIONS;
  const matches = GUIDE_SECTIONS.filter((section) => sectionSearchText(section).includes(normalized));
  return matches.length ? matches : GUIDE_SECTIONS;
}

function renderUserGuide(): void {
  const els = getEls();
  if (!els.userGuideNav || !els.userGuideBody) return;
  const query = String(els.userGuideSearch?.value || "");
  const sections = matchingSections(query);
  if (!sections.some((section) => section.id === activeSectionId)) {
    activeSectionId = sections[0]?.id || DEFAULT_GUIDE_SECTION_ID;
  }

  els.userGuideNav.innerHTML = sections.map((section) => `
    <button
      class="user-guide-tab${section.id === activeSectionId ? " active" : ""}"
      type="button"
      data-user-guide-section="${escapeHtml(section.id)}"
      aria-pressed="${section.id === activeSectionId ? "true" : "false"}"
    >${escapeHtml(translate(section.titleKey))}</button>
  `).join("");

  els.userGuideBody.innerHTML = sections.map((section) => `
    <section class="user-guide-section${section.id === activeSectionId ? " active" : ""}" data-user-guide-panel="${escapeHtml(section.id)}">
      <h3>${escapeHtml(translate(section.titleKey))}</h3>
      <ol>
        ${section.bodyKeys.map((key) => `<li>${escapeHtml(translate(key))}</li>`).join("")}
      </ol>
    </section>
  `).join("");
}

function openUserGuide(): void {
  const els = getEls();
  els.userGuideDrawer?.classList.add("open");
  els.userGuideDrawer?.setAttribute("aria-hidden", "false");
  els.userGuideBackdrop?.classList.remove("hidden");
  els.userGuideButton?.setAttribute("aria-expanded", "true");
  renderUserGuide();
  window.setTimeout(() => els.userGuideSearch?.focus({ preventScroll: true }), 0);
}

function closeUserGuide(options: { restoreFocus?: boolean } = {}): void {
  const els = getEls();
  els.userGuideDrawer?.classList.remove("open");
  els.userGuideDrawer?.setAttribute("aria-hidden", "true");
  els.userGuideBackdrop?.classList.add("hidden");
  els.userGuideButton?.setAttribute("aria-expanded", "false");
  if (options.restoreFocus !== false) {
    els.userGuideButton?.focus?.({ preventScroll: true });
  }
}

function bindUserGuideEvents(): void {
  const els = getEls();
  els.userGuideButton?.addEventListener("click", openUserGuide);
  els.userGuideClose?.addEventListener("click", () => closeUserGuide());
  els.userGuideBackdrop?.addEventListener("click", () => closeUserGuide());
  els.userGuideSearch?.addEventListener("input", renderUserGuide);
  els.userGuideNav?.addEventListener("click", (event: Event) => {
    const button = (event.target as Element | null)?.closest?.("[data-user-guide-section]") as HTMLElement | null;
    if (!button) return;
    activeSectionId = button.dataset.userGuideSection || activeSectionId;
    renderUserGuide();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !els.userGuideDrawer?.classList.contains("open")) return;
    event.preventDefault();
    closeUserGuide();
  });
  document.addEventListener(LOCALE_CHANGE_EVENT, renderUserGuide);
}

export function initUserGuideFeature(): void {
  if (userGuideInitialized) return;
  userGuideInitialized = true;
  bindUserGuideEvents();
  renderUserGuide();
}
