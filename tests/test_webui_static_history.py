from __future__ import annotations

import unittest
from pathlib import Path


class WebUIStaticHistoryTests(unittest.TestCase):
    def test_history_page_uses_viewport_workbench_layout(self) -> None:
        html = Path("codex_image/webui/static/history.html").read_text(encoding="utf-8")
        styles = Path("codex_image/webui/static/styles/90-history.css").read_text(encoding="utf-8")

        self.assertIn('class="history-page"', html)
        self.assertIn('id="historyDetailClose"', html)
        self.assertRegex(styles, r"\.history-page\s*\{[^}]*height:\s*100dvh")
        self.assertRegex(styles, r"\.history-page\s*\{[^}]*overflow:\s*hidden")
        self.assertRegex(styles, r"\.history-results\s*\{[^}]*position:\s*relative")
        self.assertRegex(styles, r"\.history-results\s*\{[^}]*grid-template-rows:\s*auto\s+minmax\(0,\s*1fr\)\s+auto")
        self.assertRegex(styles, r"\.history-task-list\s*\{[^}]*overflow:\s*auto")
        self.assertRegex(styles, r"\.history-task-list\.history-view-grid\s*\{[^}]*grid-template-columns:\s*repeat\(auto-fill,\s*minmax\(170px,\s*1fr\)\)")
        self.assertRegex(styles, r"\.history-task-list\.history-view-grid\s*\{[^}]*grid-auto-rows:\s*minmax\(300px,\s*auto\)")
        self.assertRegex(styles, r"\.history-task-list\.history-view-list\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)")
        self.assertRegex(styles, r"\.history-task-list\.history-view-list \.history-task-card\s*\{[^}]*grid-template-columns:\s*40px\s+minmax\(0,\s*1fr\)")
        self.assertRegex(styles, r"\.history-task-list\.history-view-grid \.history-task-select\s*\{[^}]*width:\s*32px")
        self.assertRegex(styles, r"\.history-task-list\.history-view-grid \.history-task-select\s*\{[^}]*border:\s*0")
        self.assertRegex(styles, r"\.history-task-list\.history-view-grid \.history-task-select\s*\{[^}]*background:\s*transparent")
        self.assertRegex(styles, r"\.history-task-list\.history-view-grid \.history-task-select\s*\{[^}]*box-shadow:\s*none")
        self.assertRegex(styles, r"\.history-sidebar,\s*\.history-task-list,\s*\.history-detail,\s*\.history-detail-prompt\s*\{[^}]*scrollbar-color:\s*var\(--scrollbar-thumb\)\s+var\(--scrollbar-track\)")
        self.assertIn(".history-task-list::-webkit-scrollbar-thumb:hover", styles)
        self.assertRegex(styles, r"\.history-task-thumb img\s*\{[^}]*object-fit:\s*contain")
        self.assertRegex(styles, r"\.history-task-thumb img\s*\{[^}]*user-select:\s*none")
        self.assertRegex(styles, r"\.history-task-thumb img\s*\{[^}]*-webkit-user-drag:\s*none")
        self.assertNotRegex(styles, r"\.history-task-list\.history-view-grid\s+\.history-task-open\s*\{[^}]*min-height:\s*100%")
        self.assertRegex(styles, r"\.history-detail\s*\{[^}]*display:\s*flex")
        self.assertRegex(styles, r"\.history-detail\s*\{[^}]*flex-direction:\s*column")
        self.assertRegex(styles, r"\.history-detail\s*\{[^}]*overflow:\s*auto")
        self.assertNotRegex(styles, r"\.history-detail\s*\{[^}]*grid-template-rows:")
        self.assertRegex(
            styles,
            r"@media \(max-width:\s*1100px\)\s*\{[\s\S]*\.history-page\s*\{[^}]*grid-template-columns:\s*240px\s+minmax\(0,\s*1fr\)",
        )
        self.assertRegex(
            styles,
            r"@media \(max-width:\s*1100px\)\s*\{[\s\S]*\.history-detail\s*\{[^}]*position:\s*fixed",
        )
        self.assertRegex(styles, r"\.history-detail-title\s*\{[^}]*-webkit-line-clamp:\s*2")
        self.assertRegex(styles, r"\.history-filter-button\s*\{[^}]*min-height:\s*40px")

    def test_history_page_feature_contracts_are_complete(self) -> None:
        html = Path("codex_image/webui/static/history.html").read_text(encoding="utf-8")
        source = Path("codex_image/webui/frontend/src/history.ts").read_text(encoding="utf-8")

        for marker in [
            'id="historyOrientationList"',
            'id="historyBackendList"',
            'id="historyProviderList"',
            'id="historyPromptModeList"',
            'id="historyQualityList"',
            'id="historyRatioList"',
            'id="historySort"',
            'id="historyViewToggle"',
            'data-history-view="grid"',
            'data-history-view="list"',
            'class="history-task-list history-view-grid"',
            'id="historyBulkToolbar"',
            'id="historyBulkArchiveButton"',
            'id="historyBulkRestoreButton"',
            'id="historyBulkDeleteButton"',
            'id="historySearchClear"',
        ]:
            self.assertIn(marker, html)
        self.assertNotIn('id="historyStatusList"', html)
        self.assertNotIn('id="historySizeList"', html)

        for marker in [
            "selectedTaskIds: new Set<string>()",
            'selectionAnchorTaskId: ""',
            "exhausted: false",
            "syncStateFromUrl()",
            "updateHistoryUrl()",
            'view: "grid"',
            "syncHistoryViewMode()",
            "data-history-view",
            "history-view-grid",
            "history-view-list",
            "renderBulkToolbar()",
            "archiveSelectedTasks",
            "deleteSelectedTasks",
            "trimMountedTaskCards()",
            "historyState.exhausted",
            "historyState.selectedTaskIds",
            "visibleHistoryTaskIds",
            "applyHistoryTaskSelection",
            "toggleHistoryTaskSelection",
            "selectHistoryTaskRange",
            "handleHistoryTaskShortcutSelection",
            "event.shiftKey",
            "event.metaKey",
            "event.ctrlKey",
            "data-history-task-select",
            'draggable="false"',
            "HISTORY_THUMBNAIL_CACHE_VERSION",
            "historyThumbnailUrl",
            "versionHistoryThumbnailUrl",
            'url.includes("/outputs/thumbnails/")',
            'const separator = url.includes("?") ? "&" : "?";',
            "thumb-768-fit",
            "v=${HISTORY_THUMBNAIL_CACHE_VERSION}",
            'els.taskList?.addEventListener("dragstart"',
            "event.preventDefault()",
            "aria-selected",
            "role=\"option\"",
            "history-detail-title",
            "history-prompt-compare",
            "outputs.zip",
            "HISTORY_REFERENCE_HANDOFF_KEY",
            "data-history-reference-handoff-url",
            "try {",
            "catch (error)",
        ]:
            self.assertIn(marker, source)

        self.assertIn("backend", source)
        self.assertIn("provider", source)
        self.assertIn("orientation", source)
        self.assertIn("prompt_mode", source)
        self.assertIn("quality", source)
        self.assertIn("HISTORY_RATIO_OTHER_VALUE", source)
        self.assertIn('translate("history.ratioOther")', source)
        self.assertNotIn("statusList", source)
        self.assertNotIn("sizeList", source)
        self.assertIn("sort", source)

    def test_history_reference_handoff_is_consumed_by_main_page(self) -> None:
        history_source = Path("codex_image/webui/frontend/src/history.ts").read_text(encoding="utf-8")
        input_source = Path("codex_image/webui/frontend/src/input-sources.ts").read_text(encoding="utf-8")
        boot_source = Path("codex_image/webui/frontend/src/boot.ts").read_text(encoding="utf-8")

        self.assertIn('localStorage.setItem(HISTORY_REFERENCE_HANDOFF_KEY', history_source)
        self.assertIn('window.location.href = "/"', history_source)
        self.assertIn("function restoreHistoryReferenceHandoff()", input_source)
        self.assertIn("localStorage.removeItem(HISTORY_REFERENCE_HANDOFF_KEY)", input_source)
        self.assertIn("imageFileFromUrl(item.url", input_source)
        self.assertIn('restoreHistoryReferenceHandoff,', input_source)
        self.assertIn('call(methods, "restoreHistoryReferenceHandoff")', boot_source)

    def test_history_page_polish_i18n_and_detail_actions_contracts(self) -> None:
        html = Path("codex_image/webui/static/history.html").read_text(encoding="utf-8")
        source = Path("codex_image/webui/frontend/src/history.ts").read_text(encoding="utf-8")
        styles = Path("codex_image/webui/static/styles/90-history.css").read_text(encoding="utf-8")
        i18n_source = Path("codex_image/webui/frontend/src/i18n.ts").read_text(encoding="utf-8")

        for marker in [
            'data-i18n="history.back"',
            'data-i18n="history.title"',
            'data-i18n-attr="placeholder:history.searchPlaceholder"',
            'data-i18n="history.promptMode"',
            'data-i18n="history.quality"',
            'data-i18n="history.ratio"',
            'data-i18n="history.grid"',
            'data-i18n="history.list"',
            '<div id="historyLoadSentinel"',
            'data-history-load-more',
            'role="status"',
        ]:
            self.assertIn(marker, html)
        self.assertNotIn('data-i18n="history.status"', html)
        self.assertNotIn('data-i18n="history.size"', html)
        self.assertNotIn('<button id="historyLoadSentinel"', html)
        self.assertNotIn('class="brand-mark"', html)
        self.assertNotIn("⌘", html)

        for marker in [
            'import { LOCALE_CHANGE_EVENT, formatTranslation, restoreLocalePreference, translate } from "./i18n";',
            'const HISTORY_THEME_STORAGE_KEY = "codex-image-theme-preference"',
            'restoreHistoryThemePreference()',
            'document.addEventListener(LOCALE_CHANGE_EVENT',
            'HISTORY_TASK_REUSE_HANDOFF_KEY',
            'data-history-reuse-task',
            'data-history-copy-prompt-kind',
            'data-history-copy-prompt-kind="${escapeHtml(kind)}"',
            'copyPromptToClipboard',
            'promptTextForKind',
            'revisedPromptText',
            'uniquePromptTexts',
            'normalizePromptForCompare',
            'const hasRevisedPanel = addPanel("revised"',
            'history-prompt-panel-header',
            'history-task-active-badge',
            'translate("history.viewing")',
            'reuseHistoryTask',
            'data-history-lightbox-url',
            'openHistoryLightbox',
            'closeHistoryLightbox',
            'data-history-load-more',
            'setLoadMoreState',
            'function maybeLoadMoreFromScroll(',
            'els.taskList?.addEventListener("scroll"',
        ]:
            self.assertIn(marker, source)
        self.assertNotIn('els.sentinel?.addEventListener("click"', source)

        for marker in [
            '"history.back": "返回生成页"',
            '"history.back": "Back to generator"',
            '"history.copyPrompt": "复制提示词"',
            '"history.copyPrompt": "Copy prompt"',
            '"history.copyPromptShort": "复制"',
            '"history.copyPromptShort": "Copy"',
            '"history.promptSubmitted": "优化提示词"',
            '"history.promptSubmitted": "Optimized prompt"',
            '"history.viewing": "查看中"',
            '"history.viewing": "Viewing"',
            '"history.reuseTask": "复用任务"',
            '"history.reuseTask": "Reuse task"',
            '"status.reusedTask": "已复用历史任务 {taskId}"',
            '"status.reusedTask": "Reused historical task {taskId}"',
        ]:
            self.assertIn(marker, i18n_source)

        self.assertRegex(styles, r"\.history-task-card\.active\s*\{[^}]*box-shadow:")
        self.assertRegex(styles, r"\.history-task-card\.active\s*\{[^}]*inset 0 0 0 2px")
        self.assertRegex(styles, r"\.history-task-active-badge\s*\{[^}]*position:\s*absolute")
        self.assertRegex(styles, r"\.history-task-active-badge\s*\{[^}]*background:\s*color-mix\(in srgb,\s*var\(--primary-strong\) 92%,\s*transparent\)")
        self.assertRegex(styles, r"\.history-task-card\.active \.history-task-active-badge\s*\{[^}]*opacity:\s*1")
        self.assertRegex(styles, r"\.history-back-link\s*\{[^}]*display:\s*inline-flex")
        self.assertRegex(styles, r"\.history-back-link\s*\{[^}]*border:\s*1px solid")
        self.assertRegex(styles, r"\.history-back-link\s*\{[^}]*background:\s*color-mix")
        self.assertRegex(styles, r"\.history-back-link::before\s*\{[^}]*clip-path:")
        self.assertRegex(styles, r"\.history-back-link:hover,\s*\.history-back-link:focus-visible\s*\{[^}]*background:\s*var\(--primary\)")
        self.assertRegex(styles, r"\.history-task-card\.selected\s*\{[^}]*box-shadow:")
        self.assertRegex(styles, r"\.history-task-card\.selected::after\s*\{[^}]*border:")
        self.assertRegex(styles, r"\.history-task-card\.selected \.history-task-copy\s*\{[^}]*background:")
        self.assertRegex(styles, r"\.history-task-select\s*\{[^}]*opacity:\s*0\.")
        self.assertRegex(styles, r"\.history-task-select input\s*\{[^}]*appearance:\s*none")
        self.assertRegex(styles, r"\.history-task-select input:checked\s*\{[^}]*background:\s*var\(--primary\)")
        self.assertRegex(styles, r"\.history-task-select input:checked::before\s*\{[^}]*transform:\s*scale\(1\)")
        self.assertRegex(styles, r"\.history-task-card:hover \.history-task-select")
        self.assertRegex(styles, r"\.history-detail-image-preview\s*\{[^}]*place-items:\s*center")
        self.assertRegex(styles, r"\.history-detail-image-preview\s*\{[^}]*justify-items:\s*center")
        self.assertRegex(styles, r"\.history-detail-image-preview img\s*\{[^}]*margin:\s*0 auto")
        self.assertRegex(styles, r"\.history-detail-images\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)")
        self.assertRegex(styles, r"\.history-detail-images\s*\{[^}]*justify-items:\s*center")
        self.assertRegex(styles, r"\.history-detail-images\s*\{[^}]*width:\s*100%")
        self.assertRegex(styles, r"\.history-detail-actions\s*\{[^}]*justify-content:\s*safe center")
        self.assertRegex(styles, r"\.history-detail-actions\s*\{[^}]*width:\s*100%")
        self.assertRegex(styles, r"\.history-detail-actions\s*>\s*\*\s*\{[^}]*white-space:\s*nowrap")
        self.assertRegex(styles, r"\.history-detail-image-actions\s*\{[^}]*flex-wrap:\s*nowrap")
        self.assertRegex(styles, r"\.history-detail-image-actions\s*\{[^}]*justify-content:\s*safe center")
        self.assertRegex(styles, r"\.history-detail-image-actions\s*\{[^}]*width:\s*100%")
        self.assertRegex(styles, r"\.history-detail-image-actions\s*>\s*\*\s*\{[^}]*white-space:\s*nowrap")
        self.assertRegex(styles, r"\.history-prompt-panel-header\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s*auto")
        self.assertRegex(styles, r"\.history-prompt-copy\.copied\s*\{[^}]*background:\s*var\(--primary-light\)")
        self.assertRegex(styles, r"\.history-results\s*\{[^}]*env\(safe-area-inset-bottom")
        self.assertRegex(styles, r"\.history-sort-label\s+span\s*\{[^}]*white-space:\s*nowrap")
        self.assertRegex(styles, r"\.history-load-sentinel\s*\{[^}]*min-height:\s*24px")
        self.assertRegex(styles, r"\.history-load-sentinel\s*\{[^}]*pointer-events:\s*none")
        self.assertNotRegex(styles, r"\.history-load-sentinel\s*\{[^}]*cursor:\s*pointer")
        self.assertRegex(styles, r"\.history-bulk-toolbar\s*\{[^}]*position:\s*absolute")
        self.assertRegex(styles, r"\.history-bulk-toolbar\s*\{[^}]*top:\s*18px")
        self.assertRegex(styles, r"\.history-bulk-toolbar\s*\{[^}]*right:\s*18px")
        self.assertRegex(styles, r"\.history-bulk-toolbar\s*\{[^}]*box-shadow:\s*var\(--shadow-popover\)")
        self.assertIn(".history-lightbox", styles)
        self.assertIn(':root[data-theme="dark"] .history-task-card.selected', styles)

    def test_history_task_reuse_handoff_is_consumed_by_main_page(self) -> None:
        history_source = Path("codex_image/webui/frontend/src/history.ts").read_text(encoding="utf-8")
        selection_source = Path("codex_image/webui/frontend/src/task-selection.ts").read_text(encoding="utf-8")
        boot_source = Path("codex_image/webui/frontend/src/boot.ts").read_text(encoding="utf-8")

        self.assertIn('localStorage.setItem(HISTORY_TASK_REUSE_HANDOFF_KEY', history_source)
        self.assertIn('window.location.href = "/"', history_source)
        self.assertIn("async function restoreHistoryTaskReuseHandoff()", selection_source)
        self.assertIn("localStorage.removeItem(HISTORY_TASK_REUSE_HANDOFF_KEY)", selection_source)
        self.assertIn("applyTaskToForm(task)", selection_source)
        self.assertIn("await restoreTaskInputs(task", selection_source)
        self.assertIn('restoreHistoryTaskReuseHandoff,', selection_source)
        self.assertIn('call(methods, "restoreHistoryTaskReuseHandoff")', boot_source)
