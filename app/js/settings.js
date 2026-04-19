/**
 * MyMediaLibrary — Settings & Onboarding Module
 *
 * Handles all settings panel logic (open/close/save, folders, providers,
 * Jellyseerr, cron hints, mobile layout) and the first-run onboarding flow.
 *
 * Depends on globals populated by app.js at runtime:
 *   appConfig, libraryPathLabel, allItems, enablePlot, enableScore,
 *   CURRENT_LANG, PROVIDER_OTHERS_KEY,
 *   t(), escH(), isMobile(), isScoreEnabled(),
 *   saveConfig(), loadVersion(), loadTranslations(), applyTranslations(),
 *   _isFolderEnabled(), _isOthersProviderName(), _provVisible(),
 *   openMobileScanSheet(), closeMobileScanSheet()
 *
 * Exposed on window for HTML onclick compatibility and cross-module use:
 *   window.MMLSettings — { showOnboarding, openSettings, closeSettings,
 *                           loadSettings, updateTypeFilterVisibility }
 *   + individual global assignments for all HTML onclick targets
 */
(function () {
  'use strict';

  // ── Private constants ─────────────────────────────────────────────────────
  const _DEFAULT_ACCENT = '#7c6aff';

  // ── Settings private state ────────────────────────────────────────────────
  let _settingsJsrTestOk = false;
  let _settingsLayoutMode = null;

  // ── Onboarding private state ──────────────────────────────────────────────
  let _onbStep = 0;
  let _onbJsr = { enabled: false, url: '', key: '' };
  let _onbLogSeen = 0;
  let _langTimer = null;
  let _onbLang = 'fr';
  let _onbTheme = 'dark';

  const _ONB_TEXTS = {
    fr: {
      title: 'Bienvenue dans MyMediaLibrary',
      desc: 'Visualisez et explorez votre bibliothèque de films et séries en un coup d\'œil. Repérez les fichiers encombrants, les codecs ou résolutions à remplacer, les contenus déjà disponibles sur vos plateformes de streaming, et suivez l\'évolution de votre collection.',
      start: 'Commencer →',
    },
    en: {
      title: 'Welcome to MyMediaLibrary',
      desc: 'Visualize and explore your movie and TV library at a glance. Spot large files, outdated codecs or resolutions, content already available on your streaming platforms, and track your collection\'s growth with detailed statistics.',
      start: 'Get started →',
    },
  };

  // ── Settings: DOM helpers ─────────────────────────────────────────────────
  function _field(id) { return document.getElementById(id); }

  function _ro(id, val) {
    const el = _field(id);
    if (!el) return;
    if (el.type === 'checkbox') { el.checked = val; el.disabled = true; }
    else if (el.tagName === 'SELECT') { el.value = val; el.disabled = true; }
    else { el.value = val; el.readOnly = true; }
  }

  function _rw(id, val) {
    const el = _field(id);
    if (!el) return;
    if (el.type === 'checkbox') { el.checked = val; el.disabled = false; }
    else if (el.tagName === 'SELECT') { el.value = val; el.disabled = false; }
    else { el.value = val; el.readOnly = false; }
  }

  function _setSettingsCollapsed(targetId, collapsed) {
    const panel = targetId ? document.getElementById(targetId) : null;
    if (!panel) return;
    const btn = document.querySelector(`.settings-collapsible[data-target="${targetId}"]`);
    if (btn) btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    panel.classList.toggle('is-collapsed', collapsed);
    panel.style.display = collapsed ? 'none' : 'block';
  }

  // ── Settings: folder helpers (private to this module) ────────────────────
  function _setFolderEnabled(folder, enabled) {
    if (!folder) return;
    folder.enabled = !!enabled;
  }

  // ── Settings: type filter visibility ─────────────────────────────────────
  function _hasMultipleTypes() {
    const folders = appConfig.folders || [];
    const hasMovies = folders.some(f => !f.missing && f.type === 'movie');
    const hasTv = folders.some(f => !f.missing && f.type === 'tv');
    return hasMovies && hasTv && (appConfig.enable_movies ?? true) && (appConfig.enable_series ?? true);
  }

  function _updateTypeFilterVisibility() {
    const show = _hasMultipleTypes();
    ['typeSection', 'mobileTypeSection'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = show ? '' : 'none';
    });
  }

  // ── Settings: load / save ─────────────────────────────────────────────────
  function loadSettings() {
    if (!_field('cfgLibraryPath')) return;

    // Accent color — from appConfig (persisted in config.json)
    const accentEl = _field('cfgAccentColor');
    if (accentEl) {
      accentEl.value = appConfig.ui?.accent_color || _DEFAULT_ACCENT;
    }

    // enablePlot — from appConfig
    const epEl = _field('cfgEnablePlot');
    if (epEl) { epEl.checked = enablePlot; epEl.disabled = false; }

    // Library path — readonly, from library.json root field.
    _ro('cfgLibraryPath', libraryPathLabel || '');

    // Enable flags — editable, from appConfig
    _rw('cfgEnableMovies',  appConfig.enable_movies  ?? true);
    _rw('cfgEnableSeries',  appConfig.enable_series  ?? true);

    // Scan cron / log level / language — from appConfig.system (editable, stored in config.json)
    const sys = appConfig.system || {};
    _rw('cfgScanCron',  sys.scan_cron  || '0 3 * * *');
    _rw('cfgLogLevel',  sys.log_level  || 'INFO');
    _rw('cfgLanguage',  sys.language   || 'fr');
    _rw('cfgInventoryEnabled', sys.inventory_enabled === true);
    _rw('cfgEnableScore', isScoreEnabled());
    updateCronHint();

    // Jellyseerr — editable from appConfig
    _rw('cfgEnableJellyseerr', appConfig.jellyseerr?.enabled ?? false);
    _rw('cfgJellyseerrUrl',    appConfig.jellyseerr?.url    || '');
    _rw('cfgJellyseerrKey',    '');   // never pre-fill the key
    const jsrKeyInput = _field('cfgJellyseerrKey');
    if (jsrKeyInput) {
      const hasStoredKey = appConfig.jellyseerr?.apikey === '***';
      jsrKeyInput.placeholder = hasStoredKey ? t('settings.jellyseerr.apikey_saved') : '••••••••••••';
    }
    toggleJsrFields();

    renderFoldersUI();
    renderProviderToggles();
  }

  function saveSettings() {
    // Sync enablePlot immediately (no server roundtrip for preview)
    const epEl = _field('cfgEnablePlot');
    if (epEl && !epEl.disabled) enablePlot = epEl.checked;
  }

  async function saveSettingsAndClose() {
    saveSettings();
    const get = id => {
      const e = _field(id);
      if (!e || e.readOnly || e.disabled) return null;
      return e.type === 'checkbox' ? e.checked : e.value;
    };

    // Build partial config from editable fields
    const partial = {};

    const ep = get('cfgEnablePlot');
    if (ep !== null) { partial.ui = partial.ui||{}; partial.ui.synopsis_on_hover = ep; }

    const accentEl = _field('cfgAccentColor');
    if (accentEl && !accentEl.readOnly) {
      partial.ui = partial.ui||{};
      partial.ui.accent_color = accentEl.value;
    }

    const em = get('cfgEnableMovies');
    if (em !== null) partial.enable_movies = em;

    const es = get('cfgEnableSeries');
    if (es !== null) partial.enable_series = es;

    const jEnabled = get('cfgEnableJellyseerr');
    const jUrl     = get('cfgJellyseerrUrl');
    const jKeyRaw  = get('cfgJellyseerrKey');
    const jKey     = (typeof jKeyRaw === 'string') ? jKeyRaw.trim() : '';
    const hasNewJellyseerrKey = !!jKey && jKey !== '***';
    if (jEnabled !== null || jUrl !== null || hasNewJellyseerrKey) {
      partial.jellyseerr = partial.jellyseerr || {};
      if (jEnabled !== null)           partial.jellyseerr.enabled = jEnabled;
      if (jUrl     !== null)           partial.jellyseerr.url     = jUrl;
      if (hasNewJellyseerrKey)         partial.jellyseerr.apikey  = jKey;
    }

    // Gather folder type/activation — always include current state
    const folderUpdates = gatherFolderEdits();
    if (folderUpdates && shouldTriggerScan(appConfig, { folders: folderUpdates })) {
      partial.folders = folderUpdates;
    }

    // Gather provider visibility
    const provVis = gatherProviderVisibility();
    if (provVis !== undefined) partial.providers_visible = provVis;

    // Scan cron / log level / language → system block
    const cron = get('cfgScanCron');
    const logLevel = get('cfgLogLevel');
    const lang = get('cfgLanguage');
    const inventoryEnabled = get('cfgInventoryEnabled');
    const enableScoreCfg = get('cfgEnableScore');
    if (cron !== null || logLevel !== null || lang !== null || inventoryEnabled !== null || enableScoreCfg !== null) {
      partial.system = partial.system || {};
      if (cron !== null)     partial.system.scan_cron = cron;
      if (logLevel !== null) partial.system.log_level = logLevel;
      if (lang !== null)     partial.system.language  = lang;
      if (inventoryEnabled !== null) partial.system.inventory_enabled = inventoryEnabled;
      if (enableScoreCfg !== null) partial.system.enable_score = enableScoreCfg;
    }

    try {
      await saveConfig(partial);
      window.location.reload();
    } catch(e) {
      alert(t('settings.save_error', {msg: e.message}));
    }
  }

  // ── Settings: folders ─────────────────────────────────────────────────────
  function onFolderTypeChange(sel) {
    const idx = parseInt(sel.dataset.folderIdx);
    const val = sel.value === 'null' ? null : sel.value;
    if (appConfig.folders[idx]) {
      appConfig.folders[idx].type = val;
      if (val && val !== 'ignore') _setFolderEnabled(appConfig.folders[idx], true);
    }
    renderFoldersUI();
  }

  function renderFoldersUI() {
    const container = document.getElementById('cfgFoldersContainer');
    if (!container) return;
    const folders = appConfig.folders || [];
    if (!folders.length) {
      container.innerHTML = '<div class="settings-note">' + t('settings.library.no_folders') + '</div>';
      return;
    }
    const unknownCount = folders.filter(f => !f.missing && (f.type === null || f.type === undefined)).length;
    let html = '';
    if (unknownCount > 0) {
      html += '<div class="settings-note" style="border-left:3px solid #f7b731;padding-left:10px;margin-bottom:10px">'
        + '⚠ ' + t('settings.library.folder_unconfigured', {n: unknownCount, s: unknownCount>1?'s':''}) + '</div>';
    }
    html += '<table style="width:100%;border-collapse:collapse;font-size:13px">'
      + '<thead><tr>'
        + '<th style="text-align:left;padding:4px 8px;color:var(--muted);font-weight:500">'+t('settings.library.folder_col_name')+'</th>'
        + '<th style="text-align:left;padding:4px 8px;color:var(--muted);font-weight:500">'+t('settings.library.folder_col_type')+'</th>'
        + '<th style="text-align:left;padding:4px 8px;color:var(--muted);font-weight:500">'+t('settings.library.folder_col_enabled')+'</th>'
      + '</tr></thead><tbody>';
    folders.forEach((f, idx) => {
      const isMissing = !!f.missing;
      const typeOpts = [
        ['movie', t('settings.library.folder_types.movie')],
        ['tv', t('settings.library.folder_types.tv')],
        ['null', t('settings.library.folder_types.ignore')],
      ].map(([v, lbl]) =>
        '<option value="'+v+'"'+(String(f.type)===v?' selected':'')+'>'+lbl+'</option>'
      ).join('');
      html += '<tr style="border-top:1px solid var(--border)'+(isMissing?';opacity:0.5':'')+'">'
        + '<td style="padding:6px 8px;font-family:monospace;font-size:12px">'+escH(f.name)
          + (isMissing ? '<span style="display:inline;margin-left:6px;font-size:10px;color:#f97316;font-style:italic">'+t('settings.library.missing')+'</span>' : '')
          + '</td>'
        + '<td style="padding:6px 8px">'
          + (isMissing
            ? '<span style="color:var(--muted);font-size:12px">'+(f.type==='movie'?t('settings.library.folder_types.movie'):f.type==='tv'?t('settings.library.folder_types.tv'):'—')+'</span>'
            : '<select class="settings-input" style="padding:3px 6px;font-size:12px" data-folder-idx="'+idx+'" data-folder-key="type" onchange="onFolderTypeChange(this)">'
              + typeOpts + '</select>')
          + '</td>'
        + '<td style="padding:6px 8px">'
          + (!f.type || f.type === 'null' || isMissing
            ? '<span style="color:var(--muted);font-size:12px">—</span>'
            : '<label class="toggle-switch">'
              + '<input type="checkbox" data-folder-idx="'+idx+'" data-folder-key="enabled"'
              + (_isFolderEnabled(f) ? ' checked' : '')
              + '/><span class="toggle-switch-slider"></span></label>')
          + '</td>'
        + '</tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
  }

  function gatherFolderEdits() {
    const folders = JSON.parse(JSON.stringify(appConfig.folders || []));
    if (!folders.length) return null;
    // Always read current DOM state, then compare against previous scan-relevant
    // folder configuration to decide if we need to persist/trigger a scan.
    document.querySelectorAll('[data-folder-idx][data-folder-key]').forEach(el => {
      const idx = parseInt(el.dataset.folderIdx);
      const key = el.dataset.folderKey;
      if (!folders[idx]) return;
      if (el.type === 'checkbox') {
        if (key === 'enabled') _setFolderEnabled(folders[idx], el.checked);
        else folders[idx][key] = el.checked;
      }
      else { folders[idx][key] = el.value === 'null' ? null : el.value; }
    });
    return folders.map(folder => {
      const normalized = {...folder};
      normalized.enabled = _isFolderEnabled(normalized);
      delete normalized.visible;
      return normalized;
    });
  }

  function _normalizeFolderForScan(folder) {
    return {
      name: String(folder?.name || ''),
      type: folder?.type ?? null,
      enabled: folder?.enabled === true,
    };
  }

  function _foldersScanSignature(folders) {
    if (!Array.isArray(folders)) return '[]';
    const normalized = folders
      .map(_normalizeFolderForScan)
      .sort((a, b) => a.name.localeCompare(b.name));
    return JSON.stringify(normalized);
  }

  function shouldTriggerScan(oldConfig, newConfig) {
    if (!newConfig || !Array.isArray(newConfig.folders)) return false;
    const prevSig = _foldersScanSignature(oldConfig?.folders || []);
    const nextSig = _foldersScanSignature(newConfig.folders);
    return prevSig !== nextSig;
  }

  // ── Settings: provider toggles ────────────────────────────────────────────
  function renderProviderToggles() {
    const container = document.getElementById('cfgProviderToggles');
    if (!container) return;
    const provs = [...new Set(allItems.flatMap((i) => _getItemProvidersForSettings(i).map((p) => window._pname ? window._pname(p) : (p.name || p)).filter(Boolean)))]
      .filter((p) => !_isOthersProviderName(p))
      .sort();
    const hasHidden = allItems.some((i) =>
      _getItemProvidersForSettings(i).some((entry) => {
        const name = window._pname ? window._pname(entry) : (entry?.name || entry);
        return !!name && !_isOthersProviderName(name) && !_provVisible(name);
      })
    );
    if (!provs.length && !hasHidden) {
      container.innerHTML = '<div class="settings-note">' + t('settings.jellyseerr.no_provider_available') + '</div>';
      return;
    }
    let html = '';
    provs.forEach((prov) => {
      const checked = _provVisible(prov);
      html += '<div class="settings-row" style="margin-bottom:6px">'
        + '<label class="settings-label">'+escH(prov)+'</label>'
        + '<label class="toggle-switch"><input type="checkbox" class="prov-visibility-toggle" data-prov="'+escH(prov)+'"'
        + (checked ? ' checked' : '') + '/><span class="toggle-switch-slider"></span></label>'
        + '</div>';
    });
    if (hasHidden) {
      html += '<div class="settings-row" style="margin-bottom:6px;opacity:.85">'
        + '<label class="settings-label">'+escH(t('stats.others'))+'</label>'
        + '<label class="toggle-switch"><input type="checkbox" checked disabled title="'+escH(t('stats.others'))+'"/>'
        + '<span class="toggle-switch-slider"></span></label>'
        + '</div>';
    }
    container.innerHTML = html;
  }

  function gatherProviderVisibility() {
    const toggles = [...document.querySelectorAll('.prov-visibility-toggle')];
    if (!toggles.length) return [];
    return toggles.filter((el) => el.checked).map((el) => el.dataset.prov);
  }

  function _getItemProvidersForSettings(item) {
    const entries = (typeof window.getItemProviders === 'function') ? window.getItemProviders(item) : [];
    const result = [];
    const seenRaw = new Set();
    entries.forEach((entry) => {
      const raw = (entry && typeof entry === 'object')
        ? String(entry.name || '').trim()
        : String(entry || '').trim();
      if (!raw || seenRaw.has(raw)) return;
      seenRaw.add(raw);
      result.push(entry);
    });
    return result;
  }

  // ── Settings: Jellyseerr ──────────────────────────────────────────────────
  function toggleJsrFields() {
    const enabled = document.getElementById('cfgEnableJellyseerr')?.checked;
    const jellyFields = document.getElementById('cfgJellyseerrFields');
    const jellyBlock = document.getElementById('cfgJellyseerrBlock');
    const providersBlock = document.getElementById('cfgProvidersBlock');
    ['cfgJellyseerrUrl', 'cfgJellyseerrKey', 'cfgJsrTestBtn'].forEach(id => {
      const el = document.getElementById(id);
      if (el) { el.disabled = !enabled; el.style.opacity = enabled ? '' : '.45'; }
    });
    if (jellyFields) jellyFields.style.display = enabled ? '' : 'none';
    if (jellyBlock) jellyBlock.style.display = enabled ? '' : 'none';
    if (providersBlock) providersBlock.style.display = enabled ? '' : 'none';
    if (enabled) {
      _setSettingsCollapsed('settingsJellyseerrBody', true);
      _setSettingsCollapsed('settingsProvidersBody', true);
    }
    if (!enabled) {
      _settingsJsrTestOk = false;
      const res = document.getElementById('cfgJsrTestResult');
      if (res) res.textContent = '';
    }
  }

  async function _runJellyseerrConnectionTest(btn, res, onSuccess) {
    if (!res) return false;
    res.textContent = '…';
    res.style.color = 'var(--muted)';
    if (btn) btn.disabled = true;
    try {
      const r = await fetch('/api/jellyseerr/test');
      const d = await r.json();
      if (d.ok) {
        res.textContent = '✓ ' + t('onboarding.jsr_ok');
        res.style.color = '#34d399';
        if (typeof onSuccess === 'function') onSuccess();
        return true;
      }
      res.textContent = '✗ ' + (d.error || t('onboarding.jsr_fail'));
      res.style.color = '#f97316';
      return false;
    } catch (e) {
      res.textContent = '✗ ' + t('onboarding.jsr_fail');
      res.style.color = '#f97316';
      return false;
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function testJellyseerr() {
    const btn = document.getElementById('cfgJsrTestBtn');
    const res = document.getElementById('cfgJsrTestResult');
    if (!res) return;

    const enabled = document.getElementById('cfgEnableJellyseerr')?.checked ?? false;
    const url = (document.getElementById('cfgJellyseerrUrl')?.value || '').trim();
    const key = (document.getElementById('cfgJellyseerrKey')?.value || '').trim();

    try {
      await saveConfig({
        jellyseerr: {
          enabled,
          url,
          ...(key ? { apikey: key } : {}),
        },
      });
      _settingsJsrTestOk = await _runJellyseerrConnectionTest(btn, res);
    } catch (e) {
      _settingsJsrTestOk = false;
      res.textContent = '✗ ' + (e?.message || t('onboarding.jsr_fail'));
      res.style.color = '#f97316';
    }
  }

  // ── Settings: cron hint ───────────────────────────────────────────────────
  function _cronHint(cron) {
    if (!cron || typeof cron !== 'string') return '';
    const parts = cron.trim().split(/\s+/);
    if (parts.length !== 5) return t('settings.system.cron_hint_invalid');
    const [min, hour, dom, month, dow] = parts;
    const days = [
      t('settings.system.cron_days.sun'),
      t('settings.system.cron_days.mon'),
      t('settings.system.cron_days.tue'),
      t('settings.system.cron_days.wed'),
      t('settings.system.cron_days.thu'),
      t('settings.system.cron_days.fri'),
      t('settings.system.cron_days.sat')
    ];
    const months = [
      t('settings.system.cron_months.jan'),
      t('settings.system.cron_months.feb'),
      t('settings.system.cron_months.mar'),
      t('settings.system.cron_months.apr'),
      t('settings.system.cron_months.may'),
      t('settings.system.cron_months.jun'),
      t('settings.system.cron_months.jul'),
      t('settings.system.cron_months.aug'),
      t('settings.system.cron_months.sep'),
      t('settings.system.cron_months.oct'),
      t('settings.system.cron_months.nov'),
      t('settings.system.cron_months.dec')
    ];
    const isAll = v => v === '*';
    const isNum = v => /^\d+$/.test(v);
    // Simple common patterns
    if (isAll(dom) && isAll(month) && isAll(dow)) {
      if (isAll(min) && isAll(hour)) return t('settings.system.cron_hint_every_minute');
      if (isNum(min) && isNum(hour)) return t('settings.system.cron_hint_daily_at', { hour: hour.padStart(2, '0'), minute: min.padStart(2, '0') });
      if (isAll(min) && isNum(hour)) return t('settings.system.cron_hint_hourly_at_hour', { hour });
      if (isNum(min) && isAll(hour)) return t('settings.system.cron_hint_every_hour_at_minute', { minute: min.padStart(2, '0') });
    }
    if (isNum(min) && isNum(hour) && isAll(dom) && isAll(month) && isNum(dow)) {
      return t('settings.system.cron_hint_weekly_day_at', {
        day: days[parseInt(dow, 10)] || t('settings.system.cron_unknown_day'),
        hour: hour.padStart(2, '0'),
        minute: min.padStart(2, '0')
      });
    }
    if (isNum(min) && isNum(hour) && isNum(dom) && isAll(month) && isAll(dow)) {
      return t('settings.system.cron_hint_monthly_day_at', {
        day: dom,
        hour: hour.padStart(2, '0'),
        minute: min.padStart(2, '0')
      });
    }
    if (isNum(min) && isNum(hour) && isNum(dom) && isNum(month) && isAll(dow)) {
      return t('settings.system.cron_hint_yearly_date_at', {
        day: dom,
        month: months[parseInt(month, 10) - 1] || month,
        hour: hour.padStart(2, '0'),
        minute: min.padStart(2, '0')
      });
    }
    if (min === '0' && hour === '*/2' && isAll(dom) && isAll(month) && isAll(dow)) return t('settings.system.cron_hint_every_two_hours');
    const step = hour.match(/^\*\/(\d+)$/);
    if (step && isAll(dom) && isAll(month) && isAll(dow)) return t('settings.system.cron_hint_every_n_hours', { n: step[1] });
    return ''; // Unknown pattern — no hint
  }

  function updateCronHint() {
    const el = _field('cfgScanCron');
    const hint = document.getElementById('cfgCronHint');
    if (!hint) return;
    hint.textContent = el ? _cronHint(el.value) : '';
  }

  // ── Settings: collapse toggles ────────────────────────────────────────────
  function toggleSettingsCollapse(btn) {
    const targetId = btn?.dataset?.target;
    if (!btn || !targetId) return;
    const expanded = btn.getAttribute('aria-expanded') !== 'false';
    _setSettingsCollapsed(targetId, expanded);
  }

  // ── Settings: UI / layout ─────────────────────────────────────────────────
  function switchStab(btn, tabId) {
    if (isMobile()) return;
    document.querySelectorAll('.stab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.stab-panel').forEach(p => p.style.display = 'none');
    document.getElementById(tabId).style.display = 'block';
  }

  function applySettingsMobileLayout(options = {}) {
    const { resetMobile = false, resetDesktop = false } = options;
    const onMobile = isMobile();
    const mode = onMobile ? 'mobile' : 'desktop';
    const modeChanged = _settingsLayoutMode !== mode;
    _settingsLayoutMode = mode;
    const tabs = document.querySelector('.settings-tabs');
    const saveBtn = document.getElementById('settingsSaveBtn');
    if (tabs) tabs.style.display = onMobile ? 'none' : '';
    if (saveBtn) saveBtn.style.display = 'block';

    const panels = document.querySelectorAll('.stab-panel[data-mobile-panel]');
    const currentlyVisibleDesktopPanel = [...panels].find(panel => panel.style.display !== 'none')?.id || 'stab-library';
    const currentlyExpandedMobilePanel = [...panels].find(panel =>
      panel.querySelector('.settings-mobile-section-btn')?.getAttribute('aria-expanded') === 'true'
    )?.id || null;

    panels.forEach(panel => {
      const headerBtn = panel.querySelector('.settings-mobile-section-btn');
      const body = panel.querySelector('.settings-mobile-section-body');
      if (!headerBtn || !body) return;

      if (onMobile) {
        panel.style.display = 'block';
        if (resetMobile) {
          headerBtn.setAttribute('aria-expanded', 'false');
          body.classList.add('is-collapsed');
        } else if (modeChanged) {
          const shouldExpand = panel.id === currentlyVisibleDesktopPanel;
          headerBtn.setAttribute('aria-expanded', shouldExpand ? 'true' : 'false');
          body.classList.toggle('is-collapsed', !shouldExpand);
        }
      } else {
        let targetPanel = 'stab-library';
        if (!resetDesktop) {
          targetPanel = modeChanged ? (currentlyExpandedMobilePanel || 'stab-library') : currentlyVisibleDesktopPanel;
        }
        const isActive = panel.id === targetPanel;
        panel.style.display = isActive ? 'block' : 'none';
        headerBtn.setAttribute('aria-expanded', 'true');
        body.classList.remove('is-collapsed');
      }
    });

    const stabButtons = document.querySelectorAll('.stab');
    if (!onMobile && stabButtons.length) {
      let targetPanel = 'stab-library';
      if (!resetDesktop) {
        targetPanel = modeChanged ? (currentlyExpandedMobilePanel || 'stab-library') : currentlyVisibleDesktopPanel;
      }
      stabButtons.forEach(btn => {
        const onclick = btn.getAttribute('onclick') || '';
        btn.classList.toggle('active', onclick.includes(`'${targetPanel}'`));
      });
    }
  }

  function toggleMobileSettingsSection(btn) {
    if (!btn || !isMobile()) return;
    const panel = btn.closest('.stab-panel');
    const body = panel?.querySelector('.settings-mobile-section-body');
    if (!body) return;
    const willOpen = btn.getAttribute('aria-expanded') === 'false';
    document.querySelectorAll('.stab-panel[data-mobile-panel]').forEach(p => {
      const pBtn = p.querySelector('.settings-mobile-section-btn');
      const pBody = p.querySelector('.settings-mobile-section-body');
      if (!pBtn || !pBody) return;
      const isCurrent = p === panel;
      pBtn.setAttribute('aria-expanded', isCurrent && willOpen ? 'true' : 'false');
      pBody.classList.toggle('is-collapsed', !(isCurrent && willOpen));
    });
  }

  function openMobileScanFromSettings() {
    closeSettings();
    openMobileScanSheet();
  }

  function openSettings() {
    closeMobileScanSheet();
    _settingsJsrTestOk = false;
    loadSettings();
    loadVersion();
    renderProviderToggles();
    document.getElementById('settingsOverlay').style.display = 'flex';
    const btn = document.getElementById('settingsSaveBtn');
    if (btn) {
      btn.style.display = 'block'; // always show — config.json is always writable
      btn.disabled = false;
    }
    applySettingsMobileLayout({ resetMobile: true, resetDesktop: true });
  }

  function closeSettings() {
    document.getElementById('settingsOverlay').style.display = 'none';
  }

  async function logoutFromSettings() {
    const btn = document.getElementById('settingsLogoutBtn');
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    try {
      const r = await fetch('/api/logout', {
        method: 'POST',
        credentials: 'include',
      });
      if (!r.ok) throw new Error('logout failed');
      sessionStorage.removeItem('mediaAuth');
      closeSettings();
      window.location.reload();
    } catch (e) {
      btn.disabled = false;
      console.warn('logout failed:', e);
    }
  }

  function closeSettingsIfBackdrop(e) {
    if (e.target === document.getElementById('settingsOverlay')) closeSettings();
  }

  window.addEventListener('resize', () => {
    const overlay = document.getElementById('settingsOverlay');
    if (overlay && overlay.style.display !== 'none') applySettingsMobileLayout();
  });

  // ── Onboarding ────────────────────────────────────────────────────────────
  function _onbDocLang() {
    const fallbackLang = CURRENT_LANG === 'en' ? 'en' : 'fr';
    return _onbLang === 'en' ? 'en' : (_onbLang === 'fr' ? 'fr' : fallbackLang);
  }

  function _onbDocHref() {
    return '/docs.html?lang=' + _onbDocLang();
  }

  function _updateOnbDocLink() {
    const link = document.getElementById('onbDocLink');
    if (!link) return;
    link.href = _onbDocHref();
  }

  function _updateOnbLangDisplay(displayLang) {
    const txt = _ONB_TEXTS[displayLang] || _ONB_TEXTS.fr;
    const el = (id) => document.getElementById(id);
    if (el('onbWelcomeTitle')) el('onbWelcomeTitle').textContent = txt.title;
    if (el('onbWelcomeDesc'))  el('onbWelcomeDesc').textContent  = txt.desc;
    if (el('onbWelcomeStart')) el('onbWelcomeStart').textContent = txt.start;
    _updateOnbDocLink();
    ['onbLangFr','onbLangEn'].forEach(id => {
      const btn = el(id);
      if (!btn) return;
      const isDisplayed = (id === 'onbLangFr' && displayLang === 'fr') || (id === 'onbLangEn' && displayLang === 'en');
      const isSelected  = _onbLang !== null && ((id === 'onbLangFr' && _onbLang === 'fr') || (id === 'onbLangEn' && _onbLang === 'en'));
      if (isSelected) {
        // Manual selection: filled background
        btn.style.background  = 'var(--accent)';
        btn.style.borderColor = 'var(--accent)';
        btn.style.color       = '#fff';
        btn.style.boxShadow   = '';
        btn.style.transform   = '';
      } else if (isDisplayed) {
        // Auto-highlight: border only, transparent background
        btn.style.background  = 'transparent';
        btn.style.borderColor = 'var(--accent)';
        btn.style.color       = 'var(--text)';
        btn.style.boxShadow   = '0 0 0 3px rgba(124,106,255,.15)';
        btn.style.transform   = 'scale(1.04)';
      } else {
        // Default
        btn.style.background  = 'var(--surface)';
        btn.style.borderColor = 'var(--border)';
        btn.style.color       = 'var(--muted)';
        btn.style.boxShadow   = '';
        btn.style.transform   = '';
      }
    });
  }

  function _startLangToggle() {
    // Visual-only: highlight current language; if none selected yet use CURRENT_LANG
    _updateOnbLangDisplay(_onbLang || CURRENT_LANG);
    clearInterval(_langTimer);
    let showing = CURRENT_LANG;
    _langTimer = setInterval(() => {
      // Only auto-toggle display while no manual selection made
      if (_onbLang !== null) { clearInterval(_langTimer); _langTimer = null; return; }
      showing = showing === 'fr' ? 'en' : 'fr';
      _updateOnbLangDisplay(showing);
    }, 3000);
  }

  async function selectOnbLang(lang) {
    clearInterval(_langTimer);
    _langTimer = null;
    _onbLang = lang;
    _updateOnbLangDisplay(lang);
    // Enable Commencer button now that a language was manually selected
    const btn = document.getElementById('onbCommencerBtn');
    if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.style.cursor = 'pointer'; }
    if (lang !== CURRENT_LANG) {
      await loadTranslations(lang);
      applyTranslations();
      // Re-update display after translations loaded (button text may have changed)
      _updateOnbLangDisplay(lang);
      const startSpan = document.getElementById('onbWelcomeStart');
      if (startSpan) startSpan.textContent = (_ONB_TEXTS[lang] || _ONB_TEXTS.fr).start;
    }
  }

  function toggleOnboardingTheme() {
    _onbTheme = _onbTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', _onbTheme);
  }

  function showOnboarding() {
    _onbStep = 0;
    _onbLang = null;
    _onbTheme = appConfig.ui?.theme || 'dark';
    _onbJsr = {
      enabled: appConfig.jellyseerr?.enabled ?? false,
      url:     appConfig.jellyseerr?.url     || '',
      key:     '',
    };
    _onbLogSeen = 0;
    // Prefetch both i18n files so lang switching is instant (browser caches them)
    ['fr', 'en'].forEach(l => fetch(`/i18n/${l}.json?_=`+Date.now()).catch(()=>{}));
    const ov = document.getElementById('onboardingOverlay');
    if (ov) { ov.style.display = 'flex'; _onbRender(); }
  }

  function _onbRender() {
    // Step indicator: hidden on step 0, 3 bars for steps 1-3
    const stepsEl = document.getElementById('onbSteps');
    if (stepsEl) {
      if (_onbStep === 0) {
        stepsEl.innerHTML = '';
      } else {
        stepsEl.innerHTML = [1,2,3].map(n =>
          '<div style="width:40px;height:4px;border-radius:2px;background:'+(n===_onbStep?'var(--accent)':'var(--border)')+'"></div>'
        ).join('');
      }
    }

    const panel = document.getElementById('onbPanel');
    if (!panel) return;
    if      (_onbStep === 0) { panel.innerHTML = _onbStep0HTML(); _startLangToggle(); }
    else if (_onbStep === 1) panel.innerHTML = _onbStep1HTML();
    else if (_onbStep === 2) panel.innerHTML = _onbStep2HTML();
    else                     panel.innerHTML = _onbStep3HTML();

    // Nav buttons
    const prev = document.getElementById('onbPrevBtn');
    const next = document.getElementById('onbNextBtn');
    const skip = document.getElementById('onbSkipBtn');
    // Step 0: hide all nav buttons (step has its own Commencer button)
    if (_onbStep === 0) {
      if (prev) prev.style.display = 'none';
      if (next) next.style.display = 'none';
      if (skip) skip.style.display = 'none';
      return;
    }
    if (prev) prev.style.display = _onbStep >= 1 ? '' : 'none';
    if (next) {
      next.style.display = '';
      if (_onbStep === 3) { next.textContent = t('nav.launch_scan'); next.onclick = onbLaunchScan; }
      else                { next.textContent = t('nav.next');        next.onclick = onbNext; }
      // Step 1: disable next until at least 1 folder has movie/tv type
      // Step 2: disable next until Jellyseerr test passes
      if (_onbStep === 1) { next.disabled = true; _onbValidateStep1(); }
      else if (_onbStep === 2) { next.disabled = true; }
      else next.disabled = false;
    }
    if (skip) {
      skip.textContent = t('nav.skip');
      skip.style.display = _onbStep === 2 ? '' : 'none';
      if (_onbStep === 2) _updateOnbSkipStyle(skip);
    }
  }

  function _onbStep0HTML() {
    const btnBase = 'padding:7px 18px;border-radius:8px;border:1px solid var(--border);cursor:pointer;font-size:13px;font-weight:600;font-family:var(--font-display);transition:all .15s';
    const quickLinkBase = 'display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:8px 12px;border-radius:9px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:12px;font-weight:600;text-decoration:none;line-height:1.2;min-height:34px';
    return '<div style="text-align:center;padding:20px 0 10px">'
      + '<div style="font-size:48px;margin-bottom:16px">🎬</div>'
      // Language selector
      + '<div style="display:flex;gap:10px;justify-content:center;margin-bottom:24px">'
        + '<button id="onbLangFr" onclick="selectOnbLang(\'fr\')" style="'+btnBase+';background:var(--accent);border-color:var(--accent);color:#fff">🇫🇷 Français</button>'
        + '<button id="onbLangEn" onclick="selectOnbLang(\'en\')" style="'+btnBase+';background:var(--surface);color:var(--muted)">🇬🇧 English</button>'
      + '</div>'
      // Auto-toggling content
      + '<div id="onbWelcomeTitle" style="font-family:var(--font-display);font-weight:800;font-size:22px;margin-bottom:10px">Bienvenue dans MyMediaLibrary</div>'
      + '<div id="onbWelcomeDesc" style="font-size:13px;color:var(--muted);max-width:420px;margin:0 auto 28px;line-height:1.7;text-align:left">'
      + 'Visualisez et explorez votre bibliothèque de films et séries en un coup d\'œil.'
      + '</div>'
      + '<div style="display:flex;flex-wrap:wrap;justify-content:center;gap:8px;max-width:420px;margin:0 auto 22px">'
        + '<a href="https://github.com/MyMediaLibrary/MyMediaLibrary" target="_blank" rel="noopener" style="'+quickLinkBase+'">'
          + '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8a8.01 8.01 0 0 0 5.47 7.59c.4.07.55-.17.55-.38v-1.33c-2.22.48-2.69-.95-2.69-.95-.36-.91-.89-1.15-.89-1.15-.73-.5.06-.49.06-.49.81.06 1.24.84 1.24.84.72 1.23 1.89.87 2.35.66.07-.52.28-.87.5-1.07-1.77-.2-3.64-.89-3.64-3.96 0-.88.32-1.6.84-2.16-.08-.2-.36-1.02.08-2.12 0 0 .69-.22 2.26.82A7.73 7.73 0 0 1 8 4.08c.68 0 1.37.09 2.01.27 1.57-1.04 2.26-.82 2.26-.82.44 1.1.16 1.92.08 2.12.52.56.84 1.28.84 2.16 0 3.08-1.88 3.75-3.67 3.95.29.25.54.73.54 1.47v2.18c0 .22.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>'
          + '<span>GitHub</span>'
        + '</a>'
        + '<a id="onbDocLink" href="'+_onbDocHref()+'" target="_blank" rel="noopener" style="'+quickLinkBase+'">'
          + '<span>📘 Documentation</span>'
        + '</a>'
      + '</div>'
      + '<button id="onbCommencerBtn" onclick="onbNext()" disabled style="padding:10px 28px;border-radius:10px;background:var(--accent);color:#fff;border:none;cursor:not-allowed;font-size:14px;font-weight:600;opacity:.35;transition:opacity .2s">'
        + '<span id="onbWelcomeStart">Commencer →</span>'
      + '</button>'
      + '</div>';
  }

  function _onbStep1HTML() {
    const folders = appConfig.folders || [];
    let html = '<div style="margin-bottom:16px">'
      + '<div style="font-family:var(--font-display);font-weight:700;font-size:18px;margin-bottom:4px">'+t('onboarding.step_folders_title')+'</div>'
      + '<div style="font-size:13px;color:var(--muted)">'+t('onboarding.step_folders_desc')+'</div>'
      + '</div>';
    if (!folders.length) {
      return html + '<div style="color:var(--muted);font-size:13px;text-align:center;padding:32px 0">'+t('onboarding.no_folders')+'</div>';
    }
    const unconfigured = folders.filter(f => !f.missing && !(f._onbType || f.type)).length;
    if (unconfigured > 0) {
      html += '<div style="font-size:12px;color:#f7b731;margin-bottom:10px">'
        + '⚠ ' + t('onboarding.unconfigured', {n: unconfigured, s: unconfigured>1?'s':''}) + '</div>';
    }
    html += '<div style="display:flex;flex-direction:column;gap:6px;max-height:280px;overflow-y:auto;padding-right:2px">';
    folders.forEach((f, idx) => {
      const isMissing = !!f.missing;
      const cur = f._onbType !== undefined ? f._onbType : (f.type || '');
      html += '<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:8px;border:1px solid var(--border);'+(isMissing?'opacity:.45':'')+'">'
        + '<span style="font-family:monospace;font-size:12px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+escH(f.name)+'">'+escH(f.name)+'</span>'
        + (isMissing
          ? '<span style="font-size:11px;color:#f97316">'+t('onboarding.folder_missing')+'</span>'
          : '<select class="'+(cur?'has-value':'')+'" style="padding:4px 8px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:12px" onchange="_onbFolderChange('+idx+',this.value);this.classList.toggle(\'has-value\',!!this.value)">'
            + '<option value="">'+t('onboarding.folder_choose')+'</option>'
            + '<option value="movie"'+(cur==='movie'?' selected':'')+'>'+t('onboarding.folder_movie')+'</option>'
            + '<option value="tv"'+(cur==='tv'?' selected':'')+'>'+t('onboarding.folder_tv')+'</option>'
            + '<option value="ignore"'+(cur==='ignore'?' selected':'')+'>'+t('onboarding.folder_ignore')+'</option>'
            + '</select>')
        + '</div>';
    });
    html += '</div>';
    return html;
  }

  function _onbValidateStep1() {
    const next = document.getElementById('onbNextBtn');
    if (!next) return;
    const hasMedia = (appConfig.folders || []).some(f =>
      !f.missing && ['movie', 'tv'].includes(f._onbType !== undefined ? f._onbType : (f.type || ''))
    );
    next.disabled = !hasMedia;
  }

  function _onbFolderChange(idx, val) {
    if (appConfig.folders[idx]) {
      appConfig.folders[idx]._onbType = val;
    }
    _onbValidateStep1();
  }

  function _captureOnbJsr() {
    const enabled = document.getElementById('onbJsrEnabled')?.checked ?? _onbJsr.enabled;
    const url     = document.getElementById('onbJsrUrl')?.value ?? _onbJsr.url;
    const key     = document.getElementById('onbJsrKey')?.value ?? _onbJsr.key;
    _onbJsr = { enabled, url, key };
  }

  function _updateOnbSkipStyle(btn) {
    if (!btn) return;
    const enabled = document.getElementById('onbJsrEnabled')?.checked ?? _onbJsr.enabled;
    if (enabled) {
      // Jellyseerr on → Skip grayed (but clickable)
      btn.style.background  = 'transparent';
      btn.style.borderColor = 'var(--border)';
      btn.style.color       = 'var(--muted)';
    } else {
      // Jellyseerr off → Skip highlighted (violet)
      btn.style.background  = 'var(--accent)';
      btn.style.borderColor = 'var(--accent)';
      btn.style.color       = '#fff';
    }
  }

  function _onbJsrToggle() {
    const enabled = document.getElementById('onbJsrEnabled')?.checked;
    ['onbJsrUrl', 'onbJsrKey', 'onbJsrTestBtn'].forEach(id => {
      const el = document.getElementById(id);
      if (el) { el.disabled = !enabled; el.style.opacity = enabled ? '' : '.45'; }
    });
    // Update skip button style + reset next button (test no longer valid)
    _updateOnbSkipStyle(document.getElementById('onbSkipBtn'));
    const next = document.getElementById('onbNextBtn');
    if (next) next.disabled = true;
    // Clear previous test result
    const res = document.getElementById('onbJsrTestResult');
    if (res) { res.textContent = ''; }
  }

  function _onbStep2HTML() {
    const dis = _onbJsr.enabled ? '' : ' disabled';
    const disOp = _onbJsr.enabled ? '' : ';opacity:.45';
    return '<div style="margin-bottom:16px">'
      + '<div style="font-family:var(--font-display);font-weight:700;font-size:18px;margin-bottom:4px">'+t('onboarding.step_jsr_title')+'</div>'
      + '<div style="font-size:13px;color:var(--muted)">'+t('onboarding.step_jsr_desc')+'</div>'
      + '</div>'
      + '<div style="display:flex;flex-direction:column;gap:14px">'
      + '<div class="settings-row"><label class="settings-label">'+t('onboarding.jsr_enable')+'</label>'
        + '<label class="toggle-switch"><input type="checkbox" id="onbJsrEnabled"'+(_onbJsr.enabled?' checked':'')+' onchange="_onbJsrToggle()"/><span class="toggle-switch-slider"></span></label></div>'
      + '<div class="settings-row"><label class="settings-label">'+t('onboarding.jsr_url')+'</label>'
        + '<input type="url" id="onbJsrUrl" class="settings-input" placeholder="https://jellyseerr.domain.com" value="'+escH(_onbJsr.url)+'"'+dis+' style="'+disOp+'"/></div>'
      + '<div class="settings-row"><label class="settings-label">'+t('onboarding.jsr_apikey')+'</label>'
        + '<input type="password" id="onbJsrKey" class="settings-input" placeholder="API key" value="'+escH(_onbJsr.key)+'"'+dis+' style="'+disOp+'"/></div>'
      + '<div class="settings-row">'
        + '<button class="scan-btn" id="onbJsrTestBtn" onclick="onbTestJsr()"'+dis+' style="padding:5px 14px;font-size:12px'+disOp+'">'+t('onboarding.jsr_test')+'</button>'
        + '<span id="onbJsrTestResult" style="font-size:12px;margin-left:10px;color:var(--muted)"></span>'
      + '</div>'
      + '</div>';
  }

  function _onbStep3HTML() {
    const folders = appConfig.folders || [];
    const nMovies  = folders.filter(f => !f.missing && (f._onbType||f.type)==='movie').length;
    const nTv      = folders.filter(f => !f.missing && (f._onbType||f.type)==='tv').length;
    const nIgnored = folders.filter(f => !f.missing && ((f._onbType||f.type)==='ignore' || !(f._onbType||f.type))).length;
    const rows = [];
    if (nMovies)  rows.push('<b>'+nMovies+'</b> '+t(nMovies>1?'onboarding.summary_movies_pl':'onboarding.summary_movies',{n:nMovies}).replace(nMovies+' ',''));
    if (nTv)      rows.push('<b>'+nTv+'</b> '+t(nTv>1?'onboarding.summary_tv_pl':'onboarding.summary_tv',{n:nTv}).replace(nTv+' ',''));
    if (nIgnored) rows.push('<b>'+nIgnored+'</b> '+t(nIgnored>1?'onboarding.summary_ignored_pl':'onboarding.summary_ignored',{n:nIgnored}).replace(nIgnored+' ',''));
    return '<div style="margin-bottom:16px">'
      + '<div style="font-family:var(--font-display);font-weight:700;font-size:18px;margin-bottom:4px">'+t('onboarding.step_scan_title')+'</div>'
      + '<div style="font-size:13px;color:var(--muted)">'+t('onboarding.step_scan_desc')+'</div>'
      + '</div>'
      + '<div style="background:var(--bg);border-radius:10px;padding:16px 20px;font-size:13px;line-height:2">'
      + '<div>📁 '+(rows.length ? rows.join(', ') : '<span style="color:var(--muted)">'+t('onboarding.no_configured')+'</span>')+'</div>'
      + '<div>🔍 Jellyseerr : '+(_onbJsr.enabled&&_onbJsr.url ? '<span style="color:#34d399">'+t('onboarding.jsr_active')+' — '+escH(_onbJsr.url)+'</span>' : '<span style="color:var(--muted)">'+t('onboarding.jsr_inactive')+'</span>')+'</div>'
      + '</div>';
  }

  async function onbTestJsr() {
    const btn = document.getElementById('onbJsrTestBtn');
    const res = document.getElementById('onbJsrTestResult');
    if (!res) return;
    _captureOnbJsr();
    const onbKey = (_onbJsr.key || '').trim();
    await saveConfig({ jellyseerr: { enabled: _onbJsr.enabled, url: _onbJsr.url, ...(onbKey ? {apikey: onbKey} : {}) } });
    await _runJellyseerrConnectionTest(btn, res, () => {
      const next = document.getElementById('onbNextBtn');
      if (next) next.disabled = false;
    });
  }

  function onbNext() {
    if (_onbStep === 0) { clearInterval(_langTimer); _langTimer = null; }
    if (_onbStep === 2) _captureOnbJsr();
    if (_onbStep < 3) { _onbStep++; _onbRender(); }
  }

  function onbPrev() {
    if (_onbStep >= 1) { _onbStep--; _onbRender(); }
  }

  function onbSkip() {
    // Only shown on step 2 — Skip means disable Jellyseerr
    if (_onbStep === 2) {
      _captureOnbJsr();
      _onbJsr.enabled = false;
      _onbStep = 3; _onbRender();
    }
  }

  async function onbLaunchScan() {
    const btn = document.getElementById('onbNextBtn');
    if (btn) { btn.disabled = true; btn.textContent = t('onboarding.saving'); }

    // Build folder list: apply _onbType overrides, set enabled accordingly
    const folders = (appConfig.folders || []).map(f => {
      const tp = f._onbType !== undefined ? (f._onbType || null) : (f.type || null);
      const type = (tp === 'ignore') ? null : tp;
      const enabled = !!type;
      const clean = Object.fromEntries(Object.entries(f).filter(([k]) => k !== '_onbType'));
      return {...clean, type, enabled};
    });

    const partial = {
      folders,
      enable_movies: folders.some(f => f.type === 'movie'),
      enable_series: folders.some(f => f.type === 'tv'),
      jellyseerr: (() => {
        const onbKey = (_onbJsr.key || '').trim();
        return { enabled: _onbJsr.enabled, url: _onbJsr.url, ...(onbKey ? {apikey: onbKey} : {}) };
      })(),
      system: { language: _onbLang },
      ui: { theme: _onbTheme },
    };

    try {
      await saveConfig(partial);
    } catch(e) {
      alert(t('settings.save_error', {msg: e.message}));
      if (btn) { btn.disabled = false; btn.textContent = t('nav.launch_scan'); }
      return;
    }

    const mode = 'quick';
    try {
      await fetch('/api/scan/start', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({mode})});
    } catch(e) {}

    // Switch to live scan log view
    const panel = document.getElementById('onbPanel');
    if (panel) panel.innerHTML = '<div style="padding:8px 0">'
      + '<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">'
        + '<div class="spinner" style="width:18px;height:18px;border-width:2px"></div>'
        + '<span style="font-family:var(--font-display);font-weight:700;font-size:16px">'+t('onboarding.scanning')+'</span>'
      + '</div>'
      + '<div id="onbLogBox" style="background:var(--bg);border-radius:8px;padding:10px 12px;font-size:11px;font-family:monospace;color:var(--muted);max-height:220px;overflow-y:auto;line-height:1.6;word-break:break-all"></div>'
      + '<div id="onbDoneBtn" style="display:none;margin-top:16px;text-align:center">'
        + '<button onclick="document.getElementById(\'onboardingOverlay\').style.display=\'none\';loadLibrary();" '
          + 'style="padding:10px 28px;border-radius:10px;background:var(--accent);color:#fff;border:none;cursor:pointer;font-size:14px;font-weight:600">'+t('onboarding.open_library')+'</button>'
      + '</div>'
      + '</div>';
    const stepsEl = document.getElementById('onbSteps');
    if (stepsEl) stepsEl.innerHTML = '';
    ['onbSkipBtn','onbPrevBtn','onbNextBtn'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });
    _onbLogSeen = 0;
    _onbPollScan();
  }

  async function _onbPollScan() {
    try {
      const r = await fetch('/api/scan/status');
      const d = await r.json();
      const logBox = document.getElementById('onbLogBox');
      if (logBox) {
        const lines = (d.log || []).slice(_onbLogSeen);
        if (lines.length) {
          _onbLogSeen += lines.length;
          lines.forEach(line => {
            const div = document.createElement('div');
            div.textContent = line;
            logBox.appendChild(div);
          });
          logBox.scrollTop = logBox.scrollHeight;
        }
      }
      if (d.status === 'done' || d.status === 'error') {
        const spinnerRow = document.querySelector('#onbPanel .spinner')?.parentElement;
        if (spinnerRow) spinnerRow.style.display = 'none';
        const doneBtn = document.getElementById('onbDoneBtn');
        if (doneBtn) doneBtn.style.display = '';
        return;
      }
    } catch(e) {}
    setTimeout(_onbPollScan, 1500);
  }

  // ── DOM event bindings (replaces inline handlers removed from index.html) ─
  // cfgEnablePlot: real-time enablePlot sync while settings panel is open
  const _epEl = document.getElementById('cfgEnablePlot');
  if (_epEl) _epEl.addEventListener('change', saveSettings);

  // Jellyseerr URL/key: reset connection test state on any edit
  function _resetJsrTestState() {
    _settingsJsrTestOk = false;
    const res = document.getElementById('cfgJsrTestResult');
    if (res) res.textContent = '';
  }
  ['cfgJellyseerrUrl', 'cfgJellyseerrKey'].forEach(function (id) {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', _resetJsrTestState);
  });

  // ── Public API ────────────────────────────────────────────────────────────
  window.MMLSettings = {
    showOnboarding,
    openSettings,
    closeSettings,
    logoutFromSettings,
    loadSettings,
    updateTypeFilterVisibility: _updateTypeFilterVisibility,
  };

  // Global assignments for HTML onclick compatibility
  window.openSettings              = openSettings;
  window.closeSettings             = closeSettings;
  window.closeSettingsIfBackdrop   = closeSettingsIfBackdrop;
  window.logoutFromSettings        = logoutFromSettings;
  window.saveSettingsAndClose      = saveSettingsAndClose;
  window.toggleSettingsCollapse    = toggleSettingsCollapse;
  window.toggleMobileSettingsSection = toggleMobileSettingsSection;
  window.openMobileScanFromSettings = openMobileScanFromSettings;
  window.switchStab                = switchStab;
  window.toggleJsrFields           = toggleJsrFields;
  window.testJellyseerr            = testJellyseerr;
  window.updateCronHint            = updateCronHint;
  window.onFolderTypeChange        = onFolderTypeChange;
  window.showOnboarding            = showOnboarding;
  window.selectOnbLang             = selectOnbLang;
  window.toggleOnboardingTheme     = toggleOnboardingTheme;
  window._onbFolderChange          = _onbFolderChange;
  window._onbJsrToggle             = _onbJsrToggle;
  window.onbTestJsr                = onbTestJsr;
  window.onbNext                   = onbNext;
  window.onbPrev                   = onbPrev;
  window.onbSkip                   = onbSkip;
  window.onbLaunchScan             = onbLaunchScan;
  window._updateTypeFilterVisibility = _updateTypeFilterVisibility;

}());
