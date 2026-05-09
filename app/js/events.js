/**
 * MyMediaLibrary — Central event hub
 *
 * Binds all static HTML element listeners and sets up document-level event
 * delegation for dynamically generated content. Must be loaded last so every
 * referenced global function is already defined.
 *
 * No inline handlers (onclick="…" etc.) are used anywhere in this project;
 * this file is the single source of truth for all UI wiring.
 */

(function () {
  'use strict';

  // ── Static element bindings ───────────────────────────────────────────────

  function _bindStaticElements() {

    // Auth overlay
    var authInput = document.getElementById('authInput');
    if (authInput) {
      authInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') submitAuth();
      });
      authInput.addEventListener('input', function () {
        var err = document.getElementById('authError');
        if (err) err.style.display = 'none';
      });
      authInput.addEventListener('focus', function () {
        this.style.borderColor = 'var(--accent)';
      });
      authInput.addEventListener('blur', function () {
        this.style.borderColor = 'var(--border)';
      });
    }
    var authBtn = document.getElementById('authBtn');
    if (authBtn) {
      authBtn.addEventListener('click', submitAuth);
      authBtn.addEventListener('mouseover', function () {
        this.style.filter = 'brightness(1.15)';
      });
      authBtn.addEventListener('mouseout', function () {
        this.style.filter = '';
      });
    }

    // Mobile topbar
    document.getElementById('mobileFilterBtn')
      ?.addEventListener('click', toggleMobileFilters);
    document.getElementById('mobileThemeBtn')
      ?.addEventListener('click', toggleTheme);
    document.getElementById('mobileSettingsBtn')
      ?.addEventListener('click', openSettings);

    // Search
    document.getElementById('searchClear')
      ?.addEventListener('click', clearSearch);
    document.getElementById('globalFilterResetBtn')
      ?.addEventListener('click', resetAllFilters);

    // Technical filters toggle
    document.getElementById('technicalToggleBtn')
      ?.addEventListener('click', function () { toggleTechnicalFilters(false); });
    document.getElementById('technicalToggleBtnMobile')
      ?.addEventListener('click', function () { toggleTechnicalFilters(true); });

    // Sidebar: scan, settings icon, theme icon
    document.getElementById('scanMainBtn')
      ?.addEventListener('click', triggerScan);
    document.getElementById('sidebarSettingsBtn')
      ?.addEventListener('click', openSettings);
    document.getElementById('themeBtn')
      ?.addEventListener('click', toggleTheme);

    // Main navigation tabs
    document.getElementById('navLibrary')
      ?.addEventListener('click', function () { switchTab('library'); });
    document.getElementById('navStats')
      ?.addEventListener('click', function () { switchTab('stats'); });
    document.getElementById('navRecommendations')
      ?.addEventListener('click', function () { switchTab('recommendations'); });

    // View toggle + CSV exports
    document.getElementById('gridBtn')
      ?.addEventListener('click', function () { setView('grid'); });
    document.getElementById('tableBtn')
      ?.addEventListener('click', function () { setView('table'); });
    document.getElementById('exportCsvBtn')
      ?.addEventListener('click', exportCSV);
    document.getElementById('exportRecCsvBtn')
      ?.addEventListener('click', exportRecommendationsCSV);

    // Scan log panel close
    document.querySelector('.scan-log-close')
      ?.addEventListener('click', closeScanLog);

    // Settings panel: system-tab inputs
    document.getElementById('mobileSettingsScanBtn')
      ?.addEventListener('click', openMobileScanFromSettings);
    document.getElementById('cfgEnableSeerr')
      ?.addEventListener('change', toggleJsrFields);
    document.getElementById('cfgJsrTestBtn')
      ?.addEventListener('click', testSeerr);
    document.querySelector('.settings-color-reset')
      ?.addEventListener('click', resetAccent);
    document.getElementById('cfgScanCron')
      ?.addEventListener('input', updateCronHint);
    document.getElementById('cfgAuthEnabled')
      ?.addEventListener('change', syncSettingsAuthPasswordState);
    document.getElementById('cfgAuthPassword')
      ?.addEventListener('input', syncSettingsAuthPasswordState);
    document.getElementById('cfgAuthConfirm')
      ?.addEventListener('input', syncSettingsAuthPasswordState);
    document.getElementById('cfgExportJsonBtn')
      ?.addEventListener('click', exportLibraryJson);
    document.getElementById('settingsLogoutBtn')
      ?.addEventListener('click', logoutFromSettings);
    document.getElementById('settingsCloseBtn')
      ?.addEventListener('click', closeSettings);
    document.getElementById('settingsSaveBtn')
      ?.addEventListener('click', saveSettingsAndClose);
    document.getElementById('scoreResetBtn')
      ?.addEventListener('click', resetScoreSettings);

    // Mobile filters panel
    document.getElementById('searchInputMobile')
      ?.addEventListener('input', function () { onMobileSearchInput(this.value); });
    document.getElementById('searchClearMobile')
      ?.addEventListener('click', clearSearchMobile);
    document.getElementById('globalFilterResetBtnMobile')
      ?.addEventListener('click', resetAllFilters);

    // Mobile scan sheet
    document.getElementById('mobileScanStartBtn')
      ?.addEventListener('click', triggerScan);
    document.getElementById('mobileScanCancelBtn')
      ?.addEventListener('click', closeMobileScanSheet);

    // Mobile bottom navigation
    document.getElementById('mnavLibrary')
      ?.addEventListener('click', function () { switchMobileTab('library'); });
    document.getElementById('mnavStats')
      ?.addEventListener('click', function () { switchMobileTab('stats'); });
    document.getElementById('mnavRecommendations')
      ?.addEventListener('click', function () { switchMobileTab('recommendations'); });

    // Back-to-top buttons
    document.getElementById('mobileBackToTop')
      ?.addEventListener('click', function () {
        document.querySelector('.main-content')
          ?.scrollTo({ top: 0, behavior: 'smooth' });
      });
    document.getElementById('backToTop')
      ?.addEventListener('click', function () {
        document.querySelector('.main-content')
          ?.scrollTo({ top: 0, behavior: 'smooth' });
      });

    // Onboarding static nav buttons (content buttons bound via delegation below)
    document.getElementById('onbThemeToggle')
      ?.addEventListener('click', toggleOnboardingTheme);
    document.getElementById('onbSkipBtn')
      ?.addEventListener('click', onbSkip);
    document.getElementById('onbPrevBtn')
      ?.addEventListener('click', onbPrev);
    document.getElementById('onbNextBtn')
      ?.addEventListener('click', onbNext);
  }

  // ── Document-level event delegation ──────────────────────────────────────

  function _handleDocumentClick(e) {

    // Settings overlay backdrop — must fire on the overlay element itself
    if (e.target.id === 'settingsOverlay') {
      closeSettingsIfBackdrop(e);
      return;
    }

    // Mobile scan-sheet backdrop
    if (e.target.id === 'mobileScanSheet') {
      closeMobileScanSheetIfBackdrop(e);
      return;
    }

    // Settings stab tab buttons
    var stab = e.target.closest('.stab[data-stab]');
    if (stab) {
      switchStab(stab, stab.dataset.stab);
      return;
    }

    // Settings collapsible buttons (static HTML + dynamically generated score sections)
    var collapsible = e.target.closest('.settings-collapsible[data-target]');
    if (collapsible) {
      toggleSettingsCollapse(collapsible);
      return;
    }

    // Mobile settings section expand/collapse buttons
    var mobileSecBtn = e.target.closest('.settings-mobile-section-btn');
    if (mobileSecBtn) {
      toggleMobileSettingsSection(mobileSecBtn);
      return;
    }

    // Type filter pills (sidebar + mobile panel)
    var typeResetPill = e.target.closest('.provider-pill-reset');
    if (typeResetPill) {
      clickType('all');
      return;
    }
    var typePill = e.target.closest('.provider-pill[data-type]');
    if (typePill) {
      clickType(typePill.dataset.type);
      return;
    }

    // Filter dropdown — inline ✕ clear button.
    // Must be checked BEFORE .filter-dropdown-trigger because the clear span
    // is a child of that div; checking the trigger first would intercept the
    // click and call toggleDropdown() instead of the clear function.
    var fdClear = e.target.closest('.filter-dropdown-inline-clear');
    if (fdClear) {
      e.stopPropagation();
      var fdEl = fdClear.closest('.filter-dropdown[data-container-id]');
      var clearFn = fdEl?.dataset.clearFn;
      if (clearFn && typeof window[clearFn] === 'function') window[clearFn]();
      return;
    }

    // Filter dropdown — open/close trigger
    var fdTrigger = e.target.closest('.filter-dropdown-trigger');
    if (fdTrigger) {
      var cid = fdTrigger.closest('.filter-dropdown[data-container-id]')?.dataset.containerId;
      if (cid) toggleDropdown(cid);
      return;
    }

    // Filter dropdown — include / exclude mode toggle
    var fdMode = e.target.closest('.filter-mode-toggle');
    if (fdMode) {
      e.stopPropagation();
      var fdEl2 = fdMode.closest('.filter-dropdown[data-container-id]');
      var excludeFn = fdEl2?.dataset.excludeFn;
      if (excludeFn && typeof window[excludeFn] === 'function') window[excludeFn]();
      return;
    }

    // Filter dropdown — select-all label (stop propagation, checkbox handled in change)
    var saLabel = e.target.closest('.filter-dropdown-select-all');
    if (saLabel && !e.target.matches('input[type="checkbox"]')) {
      e.stopPropagation();
      return;
    }

    // Filter dropdown — individual option click
    var fdOpt = e.target.closest('.filter-dropdown-option');
    if (fdOpt) {
      e.stopPropagation();
      var fdEl3 = fdOpt.closest('.filter-dropdown[data-container-id]');
      var toggleFn = fdEl3?.dataset.toggleFn;
      if (toggleFn && typeof window[toggleFn] === 'function') {
        window[toggleFn](fdOpt.dataset.key);
      }
      return;
    }

    // Storage bar legend pills (group filter)
    var leg = e.target.closest('.leg[data-bar-fn]');
    if (leg) {
      var barFn = leg.dataset.barFn;
      var barKey = leg.dataset.barKey;
      if (barFn && typeof window[barFn] === 'function') {
        if (barKey !== undefined && barKey !== '') window[barFn](barKey);
        else window[barFn]();
      }
      return;
    }

    // Recommendation filter buttons
    var recBtn = e.target.closest('.rec-filter-btn[data-rec-fn]');
    if (recBtn) {
      var recFn = recBtn.dataset.recFn;
      if (recFn && typeof window[recFn] === 'function') {
        window[recFn](recBtn.dataset.recVal);
      }
      return;
    }

    // Library table sort column headers
    var th = e.target.closest('th[data-sort-col]');
    if (th) {
      sortByCol(th.dataset.sortCol);
      return;
    }

    // Scan timestamp link → open log viewer
    if (e.target.closest('.scan-ts-link')) {
      openLogViewer();
      return;
    }

    // Onboarding: language selector buttons (rendered dynamically inside #onbPanel)
    if (e.target.id === 'onbLangFr') { selectOnbLang('fr'); return; }
    if (e.target.id === 'onbLangEn') { selectOnbLang('en'); return; }

    // Onboarding: Commencer button (step 0)
    if (e.target.id === 'onbCommencerBtn' || e.target.closest('#onbCommencerBtn')) {
      onbNext();
      return;
    }

    // Onboarding: Seerr test button (step 2)
    if (e.target.id === 'onbJsrTestBtn') { onbTestJsr(); return; }

    // Onboarding: open library button (shown after scan completes)
    if (e.target.id === 'onbOpenLibraryBtn') {
      var overlay = document.getElementById('onboardingOverlay');
      if (overlay) overlay.style.display = 'none';
      if (typeof loadLibrary === 'function') loadLibrary();
      return;
    }
  }

  function _handleDocumentChange(e) {

    // Filter dropdown — select-all checkbox
    var saCheckbox = e.target.closest('.filter-dropdown-select-all input[type="checkbox"]');
    if (saCheckbox) {
      e.stopPropagation();
      var fd = saCheckbox.closest('.filter-dropdown[data-container-id]');
      var cid = fd?.dataset.containerId;
      var clearFn = fd?.dataset.clearFn;
      if (cid && clearFn) _dropdownSelectAll(cid, clearFn, e.target.checked);
      return;
    }

    // Recommendations sort select
    var recSort = e.target.closest('.rec-sort-select');
    if (recSort) {
      setRecommendationSort(recSort.value);
      return;
    }

    // Settings folder table — folder type select
    var folderTypeSel = e.target.closest('select[data-folder-key="type"]');
    if (folderTypeSel) {
      onFolderTypeChange(folderTypeSel);
      return;
    }

    // Onboarding step 1 — folder type select
    var onbFolderSel = e.target.closest('select[data-onb-folder-idx]');
    if (onbFolderSel) {
      var idx = parseInt(onbFolderSel.dataset.onbFolderIdx, 10);
      _onbFolderChange(idx, onbFolderSel.value);
      onbFolderSel.classList.toggle('has-value', !!onbFolderSel.value);
      return;
    }

    // Onboarding step 2 — Seerr enabled toggle
    if (e.target.id === 'onbJsrEnabled') { _onbJsrToggle(); return; }

    // Onboarding step 3 — feature toggles
    if (e.target.id === 'onbScoreEnabled' || e.target.id === 'onbInventoryEnabled') {
      _onbFeaturesToggle();
      return;
    }

    // Onboarding step 4 — auth toggle
    if (e.target.id === 'onbAuthEnabled') { _onbAuthToggle(); return; }
  }

  function _handleDocumentInput(e) {
    // Onboarding step 4 — password inputs
    if (e.target.id === 'onbAuthPassword' || e.target.id === 'onbAuthConfirm') {
      _onbAuthPasswordInput();
      return;
    }
  }

  // Quality badge tooltip delegation (mouseover/mousemove/mouseout bubble)
  function _handleDocumentMouseover(e) {
    var badge = e.target.closest('.quality-badge[data-quality-tooltip]');
    if (badge && typeof showQualityTooltip === 'function') {
      showQualityTooltip(badge, e);
    }
  }

  function _handleDocumentMousemove(e) {
    if (e.target.closest('.quality-badge[data-quality-tooltip]')
        && typeof moveQualityTooltip === 'function') {
      moveQualityTooltip(e);
    }
  }

  function _handleDocumentMouseout(e) {
    var badge = e.target.closest('.quality-badge[data-quality-tooltip]');
    if (badge && typeof handleQualityBadgeLeave === 'function') {
      handleQualityBadgeLeave(badge);
    }
  }

  function _bindDelegation() {
    document.addEventListener('click',     _handleDocumentClick);
    document.addEventListener('change',    _handleDocumentChange);
    document.addEventListener('input',     _handleDocumentInput);
    document.addEventListener('mouseover', _handleDocumentMouseover);
    document.addEventListener('mousemove', _handleDocumentMousemove);
    document.addEventListener('mouseout',  _handleDocumentMouseout);
  }

  // ── Boot ─────────────────────────────────────────────────────────────────

  function _init() {
    _bindStaticElements();
    _bindDelegation();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _init);
  } else {
    _init();
  }

}());
