
// ── I18N ─────────────────────────────────────────────
let TRANSLATIONS = {};
let CURRENT_LANG = 'fr';

async function loadTranslations(lang) {
  try {
    const res = await fetch(`/i18n/${lang}.json?_=` + Date.now());
    if (!res.ok) return;
    TRANSLATIONS = await res.json();
    CURRENT_LANG = lang;
  } catch(e) { console.warn('i18n load error:', e); }
}

function t(key, vars = {}) {
  const keys = key.split('.');
  let val = keys.reduce((obj, k) => obj?.[k], TRANSLATIONS);
  if (typeof val !== 'string') {
    const labelVal = [...keys, 'label'].reduce((obj, k) => obj?.[k], TRANSLATIONS);
    if (typeof labelVal === 'string') val = labelVal;
  }
  if (typeof val !== 'string') { console.warn('Missing translation key:', key); return key; }
  Object.entries(vars).forEach(([k, v]) => { val = val.split(`{${k}}`).join(String(v)); });
  return val;
}

function applyTranslations() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.title = t(el.dataset.i18nTitle);
  });
}

let allItems=[], categories=[], groups=[];
  function safeArray(value) {
    return Array.isArray(value) ? value : [];
  }
  const FILTER_NONE_KEY = window.MMLConstants.PROVIDER_NONE_KEY;
  const FILTER_ORDER = [
    'type',
    'folder',
    'genre',
    'streaming',
    'audio_language',
    'score',
    'technical'
  ];
  const FILTER_SECTION_IDS = {
    type: { desktop: 'typeSection', mobile: 'mobileTypeSection' },
    storage: { desktop: 'storageSection', mobile: 'storageSectionMobile' },
    folder: { desktop: 'folderSection', mobile: 'folderSectionMobile' },
    genre: { desktop: 'genreSection', mobile: 'genreSectionMobile' },
    streaming: { desktop: 'providerSection', mobile: 'providerSectionMobile' },
    technical: { desktop: 'technicalSection', mobile: 'technicalSectionMobile' },
    audio_language: { desktop: 'audioLanguageSection', mobile: 'audioLanguageSectionMobile' },
    score: { desktop: 'qualitySection', mobile: 'qualitySectionMobile' },
  };
  let libraryExportSource = null; // raw library.json payload used for export
  let PROVIDERS_MAP = {};          // {raw_provider_name: display_provider_name|null} from /api/providers-map
  let PROVIDERS_LOGOS = {};        // {display_provider_name: logo_filename} from /providers_logo.json
  let audioCodecMapping = {};      // loaded from /audiocodec_mapping.json
  let audioLanguages = {};         // loaded from /audio_languages.json

  async function loadProvidersCatalog() {
    try {
      const [mapRes, logosRes] = await Promise.all([
        fetch('/api/providers-map?_=' + Date.now()),
        fetch('/providers_logo.json?_=' + Date.now()),
      ]);
      if (mapRes.ok) {
        const data = await mapRes.json();
        PROVIDERS_MAP = (data && typeof data === 'object') ? data : {};
      }
      if (logosRes.ok) {
        const data = await logosRes.json();
        PROVIDERS_LOGOS = (data && typeof data === 'object') ? data : {};
      }
    } catch(e) { console.warn('providers catalog load error:', e); }
  }

  async function loadAudioCodecMapping() {
    try {
      const res = await fetch('/audiocodec_mapping.json?_=' + Date.now());
      if (res.ok) audioCodecMapping = await res.json();
    } catch(e) { console.warn('audiocodec_mapping.json load error:', e); }
  }

  async function loadAudioLanguages() {
    try {
      const res = await fetch('/audio_languages.json?_=' + Date.now());
      if (res.ok) audioLanguages = await res.json();
    } catch(e) { console.warn('audio_languages.json load error:', e); }
  }

  function getLanguageDisplay(isoCode) {
    const lang = appConfig?.system?.language ?? 'fr';
    const entry = audioLanguages[isoCode];
    if (!entry) return isoCode ? isoCode.toUpperCase() : '?';
    return entry[lang] ?? entry['en'] ?? isoCode.toUpperCase();
  }

  function normalizeAudioLanguageCode(raw) {
    if (window.MMLLogic?.normalizeAudioLanguageCode) {
      return window.MMLLogic.normalizeAudioLanguageCode(raw);
    }
    if (typeof raw !== 'string') return null;
    const code = raw.toLowerCase().trim();
    if (!code) return null;
    if (code === 'fr' || code === 'fra' || code === 'fre') return 'fra';
    return code;
  }

  function simplifyAudioLanguages(codes) {
    if (window.MMLLogic?.simplifyAudioLanguages) {
      return window.MMLLogic.simplifyAudioLanguages(codes);
    }
    if (!Array.isArray(codes)) return FILTER_NONE_KEY;
    const normalized = new Set();
    codes.forEach(code => {
      const norm = normalizeAudioLanguageCode(code);
      if (norm) normalized.add(norm);
    });
    if (normalized.size === 0) return FILTER_NONE_KEY;
    if (normalized.size === 1 && normalized.has('fra')) return 'VF';
    if (normalized.has('fra') && normalized.size > 1) return 'MULTI';
    return 'VO';
  }

  function getAudioLanguageSimple(item) {
    const mapped = item?.audio_languages_simple;
    if (mapped === 'VF' || mapped === 'VO' || mapped === 'MULTI' || mapped === FILTER_NONE_KEY) return mapped;
    if (mapped === 'UNKNOWN') return FILTER_NONE_KEY; // legacy persisted value
    return simplifyAudioLanguages(item?.audio_languages ?? []);
  }

  function getAudioLanguageSimpleDisplay(value) {
    if (value === 'UNKNOWN') return t('filters.unknown');
    return getFilterDisplayValue(value);
  }

  function getAudioCodecDisplay(normalized) {
    if (!normalized || normalized === FILTER_NONE_KEY)
      return getFilterDisplayValue(FILTER_NONE_KEY);
    if (normalized === 'UNKNOWN') return t('filters.unknown');
    const entry = Object.values(audioCodecMapping.mapping ?? {})
      .find(e => e.normalized === normalized);
    return entry?.display ?? normalized;
  }

  function getNormalizedVideoCodec(item) {
    return item?.codec || FILTER_NONE_KEY;
  }

  function getNormalizedAudioCodec(item) {
    return item?.audio_codec || FILTER_NONE_KEY;
  }

  function getAudioCodecLabel(item) {
    const normalized = getNormalizedAudioCodec(item);
    if (normalized && normalized !== FILTER_NONE_KEY) {
      return getAudioCodecDisplay(normalized);
    }

    // Transitional legacy fallback: remove when backend stops emitting audio_codec_display.
    const legacyDisplay = typeof item?.audio_codec_display === 'string' ? item.audio_codec_display.trim() : '';
    if (legacyDisplay) return legacyDisplay;

    const raw = typeof item?.audio_codec_raw === 'string' ? item.audio_codec_raw.trim() : '';
    if (raw) return raw;

    return getFilterDisplayValue(FILTER_NONE_KEY);
  }

  function getNormalizedResolution(item) {
    return item?.resolution || FILTER_NONE_KEY;
  }

  function getNormalizedGenres(item) {
    if (!Array.isArray(item?.genres)) return [];
    const seen = new Set();
    const genres = [];
    item.genres.forEach((genre) => {
      const value = String(genre || '').trim();
      if (!value || seen.has(value)) return;
      seen.add(value);
      genres.push(value);
    });
    return genres;
  }

  function getNormalizedAudioChannels(item) {
    const value = String(item?.audio_channels || '').trim();
    return value || FILTER_NONE_KEY;
  }

  function canonicalFilterMissingKey(raw) {
    if (raw === null || raw === undefined) return null;
    const key = String(raw).trim();
    if (!key) return null;
    if (key === FILTER_NONE_KEY) return FILTER_NONE_KEY;
    return key;
  }

  function normalizeFilterValue(key) {
    const canonical = canonicalFilterMissingKey(key);
    return canonical || key;
  }

  function getFilterDisplayValue(key, noneTranslationKey = 'filters.unknown') {
    const normalized = normalizeFilterValue(key);
    if (normalized === FILTER_NONE_KEY) return t(noneTranslationKey);
    return normalized;
  }

  function getGenreDisplay(value) {
    const normalized = normalizeFilterValue(value);
    if (normalized === FILTER_NONE_KEY) return t('filters.none');
    const translated = TRANSLATIONS?.genres?.[normalized];
    return typeof translated === 'string' && translated.trim() ? translated : normalized;
  }

  function canonicalAudioLanguageFilterKey(raw) {
    const key = canonicalFilterMissingKey(raw);
    if (key === 'UNKNOWN') return FILTER_NONE_KEY; // legacy persisted value for audio language only
    return key;
  }

  function getQualityLevelFromScore(score) {
    if (window.MMLLogic?.getQualityLevelFromScore) {
      return window.MMLLogic.getQualityLevelFromScore(score);
    }
    const safeScore = Number.isFinite(Number(score)) ? Number(score) : 0;
    if (safeScore <= 20) return 1;
    if (safeScore <= 40) return 2;
    if (safeScore <= 60) return 3;
    if (safeScore <= 80) return 4;
    return 5;
  }

  function getItemQualityLevel(item) {
    if (window.MMLLogic?.getItemQualityLevel) {
      return window.MMLLogic.getItemQualityLevel(item);
    }
    return getQualityLevelFromScore(item?.quality?.score);
  }

  function getScoredQualityLevel(item) {
    if (window.MMLLogic?.getScoredQualityLevel) {
      return window.MMLLogic.getScoredQualityLevel(item);
    }
    const score = Number(item?.quality?.score);
    if (!Number.isFinite(score)) return null;
    return getQualityLevelFromScore(score);
  }

  function getQualityLevelClass(level) {
    if (window.MMLLogic?.getQualityLevelClass) {
      return window.MMLLogic.getQualityLevelClass(level);
    }
    const safeLevel = Number(level);
    if (safeLevel >= 1 && safeLevel <= 5) return `quality-lvl-${safeLevel}`;
    return 'quality-lvl-unknown';
  }

  function getQualityTooltipText(item) {
    if (!isScoreEnabled()) return '';
    const quality = item?.quality;
    const score = Number(quality?.score);
    if (!Number.isFinite(score)) return '';

    const video = Number(quality?.video);
    const audio = Number(quality?.audio);
    const languages = Number(quality?.languages);
    const size = Number(quality?.size);

    const lines = [
      `${t('quality_tooltip.score')}: ${Math.round(score)}`,
      '',
      `${t('quality_tooltip.video')}: ${Number.isFinite(video) ? Math.round(video) : 0}`,
      `${t('quality_tooltip.audio')}: ${Number.isFinite(audio) ? Math.round(audio) : 0}`,
      `${t('quality_tooltip.languages')}: ${Number.isFinite(languages) ? Math.round(languages) : 0}`,
      `${t('quality_tooltip.size')}: ${Number.isFinite(size) ? Math.round(size) : 0}`
    ];

    return lines.join('\n');
  }

  function escapeAttrMultiline(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
      .replace(/\r?\n/g, '&#10;');
  }

  function qualityBadgeHTML(item, extraClass = '') {
    if (!isScoreEnabled()) return '';
    const score = item?.quality?.score;
    if (!Number.isFinite(Number(score))) return '';
    const levelClass = getQualityLevelClass(getItemQualityLevel(item));
    const tooltip = getQualityTooltipText(item);
    const tooltipAttr = tooltip ? ' data-quality-tooltip="'+escapeAttrMultiline(tooltip)+'"' : '';
    const tooltipHandlers = tooltip
      ? ' onmouseenter="showQualityTooltip(this,event)" onmousemove="moveQualityTooltip(event)" onmouseleave="handleQualityBadgeLeave(this)"'
      : '';
    return '<span class="quality-badge '+levelClass+(extraClass ? ' '+extraClass : '')+'"'+tooltipAttr+tooltipHandlers+'>'+Math.round(Number(score))+'</span>';
  }

  function _providerRawName(entry) {
    if (entry && typeof entry === 'object') {
      return String(entry.rawName || entry.raw_name || entry.name || '').trim();
    }
    return String(entry || '').trim();
  }

  function resolveProvider(entry) {
    const rawName = _providerRawName(entry);
    if (!rawName) return { rawName: '', name: '', logoUrl: '' };
    const hasMapping = Object.prototype.hasOwnProperty.call(PROVIDERS_MAP, rawName);
    const mappedValue = hasMapping ? PROVIDERS_MAP[rawName] : null;
    const normalizedName = (typeof mappedValue === 'string' && mappedValue.trim())
      ? mappedValue.trim()
      : 'Autres';
    const logoFile = PROVIDERS_LOGOS[normalizedName] || PROVIDERS_LOGOS['Autres'];
    const logoFromCatalog = logoFile ? `/assets/providers/${logoFile}` : '';
    return {
      rawName,
      name: normalizedName,
      logoUrl: logoFromCatalog || '',
    };
  }

  function getProviderNames(item) {
    return getEnabledProviderNames(item);
  }

  function getItemProviders(item) {
    const providers = item?.providers;
    if (providers && typeof providers === 'object' && !Array.isArray(providers)) {
      return Object.values(providers)
        .filter((values) => Array.isArray(values))
        .flat();
    }
    return Array.isArray(providers) ? providers : [];
  }

  function getEnabledProvidersForItem(item) {
    const providers = getDisplayedProviders(item);
    if (!(providerExclude && activeProviders.size > 0)) return providers;
    if (providers.length === 0) return [];
    return providers.filter((entry) => {
      const key = _providerGroupKey(_pname(entry));
      return key && !activeProviders.has(key);
    });
  }

  function getEnabledProviderNames(item) {
    return getEnabledProvidersForItem(item).map((entry) => _pname(entry)).filter(Boolean);
  }

  // Helpers: canonicalize provider entries from library items.
  function _pname(p){ return resolveProvider(p).name; }
  function _plogo(p){
    const resolved = resolveProvider(p);
    if (!resolved.logoUrl) console.warn('Unmapped provider:', resolved.rawName || resolved.name);
    return resolved.logoUrl;
  }

  // Active category prefs (null = all active; Set = specific active names)
  let enabledCategories = null;
  let visibleProviders  = null;
  const PROVIDER_OTHERS_KEY     = window.MMLConstants.PROVIDER_OTHERS_KEY;
  const PROVIDER_OTHERS_ALIASES = new Set(window.MMLConstants.PROVIDER_OTHERS_ALIASES);
  const DISPLAY_OTHERS_NAME = 'Autres';
  function _catVisible(cat)  { return !enabledCategories || enabledCategories.has(cat); }
  function _isOthersProviderName(prov) {
    if (!prov) return false;
    return PROVIDER_OTHERS_ALIASES.has(String(prov).trim().toLowerCase());
  }
  function _provVisible(prov){
    if (_isOthersProviderName(prov) || prov === PROVIDER_OTHERS_KEY) return true;
    return !visibleProviders  || visibleProviders.has(prov);
  }
  function getDisplayedProviders(item, options = {}) {
    const visibleOnly = options.visibleOnly === true;
    const mappedOnly = options.mappedOnly === true;
    const grouped = new Map();
    getItemProviders(item).forEach((entry) => {
      const resolved = resolveProvider(entry);
      const displayName = resolved.name;
      if (!displayName) return;
      if (mappedOnly && _isOthersProviderName(displayName)) return;
      if (visibleOnly && !_provVisible(displayName)) return;
      if (!grouped.has(displayName)) grouped.set(displayName, resolved);
    });
    return [...grouped.values()]
      .sort((a, b) => {
        const aIsOthers = _isOthersProviderName(a.name);
        const bIsOthers = _isOthersProviderName(b.name);
        if (aIsOthers && !bIsOthers) return 1;
        if (!aIsOthers && bIsOthers) return -1;
        return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
      })
      .map((entry) => ({
        ...entry,
        name: _isOthersProviderName(entry.name) ? DISPLAY_OTHERS_NAME : entry.name,
      }));
  }
  function _providerGroupKey(prov) {
    if (!prov) return null;
    if (_isOthersProviderName(prov)) return PROVIDER_OTHERS_KEY;
    return _provVisible(prov) ? prov : PROVIDER_OTHERS_KEY;
  }
  function _providerGroupLabel(key) {
    return key === PROVIDER_OTHERS_KEY ? t('stats.others') : key;
  }
  function _itemProviderGroups(item) {
    const grouped = new Set();
    getEnabledProvidersForItem(item).forEach(p => {
      const n = _pname(p);
      const key = _providerGroupKey(n);
      if (key) grouped.add(key);
    });
    return grouped;
  }
  function _getProviderGroupsBeforeFilter(item) {
    const grouped = new Set();
    getDisplayedProviders(item).forEach((p) => {
      const n = _pname(p);
      const key = _providerGroupKey(n);
      if (key) grouped.add(key);
    });
    return grouped;
  }
  function _matchesProviderFilters(item) {
    if (activeProviders.size === 0) return true;
    const groupedProv = [..._getProviderGroupsBeforeFilter(item)];
    const hasNoProvider = groupedProv.length === 0;
    if (!providerExclude) {
      if (activeProviders.has(FILTER_NONE_KEY) && hasNoProvider) return true;
      return groupedProv.some((p) => activeProviders.has(p));
    }
    if (activeProviders.has(FILTER_NONE_KEY) && hasNoProvider) return false;
    if (hasNoProvider) return true;
    const remaining = groupedProv.filter((p) => !activeProviders.has(p));
    return remaining.some((p) => p !== PROVIDER_OTHERS_KEY);
  }
  function _canonicalProviderFilterKey(raw) {
    if (typeof raw !== 'string') return null;
    const key = raw.trim();
    if (!key) return null;
    const lower = key.toLowerCase();
    if (key === PROVIDER_OTHERS_KEY || PROVIDER_OTHERS_ALIASES.has(lower)) return PROVIDER_OTHERS_KEY;
    if (key === FILTER_NONE_KEY) return FILTER_NONE_KEY;
    const mapped = Object.prototype.hasOwnProperty.call(PROVIDERS_MAP, key)
      ? PROVIDERS_MAP[key]
      : undefined;
    if (typeof mapped === 'string' && mapped.trim()) return mapped.trim();
    if (mapped === null || mapped === undefined) return PROVIDER_OTHERS_KEY;
    return key;
  }
  function _hasHiddenProviders(items = allItems) {
    if (!visibleProviders) return false;
    return items.some(i => getDisplayedProviders(i, { mappedOnly: true }).some(p => {
      const name = _pname(p);
      return name && !_provVisible(name);
    }));
  }
  // Returns only the providers of an item that are currently visible
  function _itemVisProviders(item){ return getDisplayedProviders(item, { visibleOnly: true }); }

  let enablePlot=false, enableMovies=true, enableSeries=true, enableSeerr=true, enableScore=false, enableRecommendations=false;
  let activeGroup='all', activeType='all';
  let activeFolders = new Set();
  let activeResolutions = new Set();
  let activeCodecs = new Set(), activeAudioCodecs = new Set(), activeProviders = new Set();
  let activeGenres = new Set(), activeAudioChannels = new Set();
  let activeAudioLanguages = new Set();
  let activeQualityLevels = new Set();
  let scoreMin = 0;
  let scoreMax = 100;
  let includeNoScore = true;
  let audioCodecExclude = false;
  let videoCodecExclude = false;
  let providerExclude = false;
  let resolutionExclude = false;
  let genreExclude = false;
  let audioChannelsExclude = false;
  let audioLanguageExclude = false;
  let folderExclude = false;
  let qualityExclude = false;
  let technicalFiltersOpenDesktop = false;
  let technicalFiltersOpenMobile = false;
  const SCORE_FILTER_RANGES = [
    { key: '0_20', min: 0, max: 20, maxInclusive: false, labelKey: 'filters.score.range_0_20', level: 1 },
    { key: '20_40', min: 20, max: 40, maxInclusive: false, labelKey: 'filters.score.range_20_40', level: 2 },
    { key: '40_60', min: 40, max: 60, maxInclusive: false, labelKey: 'filters.score.range_40_60', level: 3 },
    { key: '60_80', min: 60, max: 80, maxInclusive: false, labelKey: 'filters.score.range_60_80', level: 4 },
    { key: '80_100', min: 80, max: 100, maxInclusive: true, labelKey: 'filters.score.range_80_100', level: 5 },
  ];

  function isFiltersDebugEnabled() {
    try {
      return window.__MML_DEBUG_FILTERS__ === true || localStorage.getItem('mml_debug_filters') === '1';
    } catch (e) {
      return window.__MML_DEBUG_FILTERS__ === true;
    }
  }

  function logFiltersDebug(message, payload) {
    if (!isFiltersDebugEnabled()) return;
    if (payload !== undefined) console.info('[filters]', message, payload);
    else console.info('[filters]', message);
  }
  let appConfig = {};            // loaded from /api/config
  let libraryPathLabel = '';     // from library.json root field: library_path
  let appVersionInfo = null;     // loaded from /version.json
  let recommendationsDoc = null;
  let recommendationTypeFilters = new Set();
  let recommendationPriorityFilters = new Set();
  let recommendationSort = { key: 'priority', dir: 'desc' };

  function resolveScoreEnabled() {
    const configScoreEnabled = appConfig?.score?.enabled;
    if (typeof configScoreEnabled === 'boolean') {
      return configScoreEnabled;
    }
    const legacyScoreEnabled = appConfig?.system?.enable_score;
    if (typeof legacyScoreEnabled === 'boolean') {
      return legacyScoreEnabled;
    }
    return false;
  }

  function isScoreEnabled() {
    return enableScore === true;
  }

  function resolveRecommendationsEnabled() {
    return isScoreEnabled() && appConfig?.recommendations?.enabled === true;
  }

  function isRecommendationsEnabled() {
    return enableRecommendations === true;
  }

  function sanitizeScoreState() {
    activeQualityLevels.clear();
    qualityExclude = false;
    scoreMin = 0;
    scoreMax = 100;
    includeNoScore = true;
    if (tSortCol === 'quality') tSortCol = null;
    ['sortSelect', 'sortSelectMobile'].forEach((id) => {
      const el = document.getElementById(id);
      if (el && (el.value === 'score-asc' || el.value === 'score-desc')) el.value = 'title-asc';
    });
  }

  function applyScoreFeatureVisibility() {
    const scoreOn = isScoreEnabled();
    if (!scoreOn) sanitizeScoreState();
    ['sortSelect', 'sortSelectMobile'].forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      ['score-asc', 'score-desc'].forEach((value) => {
        const option = el.querySelector(`option[value="${value}"]`);
        if (option) option.style.display = scoreOn ? '' : 'none';
      });
      if (!scoreOn && (el.value === 'score-asc' || el.value === 'score-desc')) {
        el.value = 'title-asc';
      }
    });
    ['qualitySection', 'qualitySectionMobile'].forEach((id) => {
      const sec = document.getElementById(id);
      if (!sec) return;
      if (!scoreOn) {
        sec.style.display = 'none';
        sec.innerHTML = '';
      }
    });
  }

  function applyRecommendationsFeatureVisibility() {
    const show = isRecommendationsEnabled();
    ['navRecommendations', 'mnavRecommendations'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.style.display = show ? '' : 'none';
    });
    const controls = document.getElementById('recommendationsControls');
    if (controls) controls.style.display = show && currentTab === 'recommendations' ? '' : 'none';
    if (!show) {
      recommendationsDoc = null;
      recommendationTypeFilters.clear();
      recommendationPriorityFilters.clear();
      if (currentTab === 'recommendations') currentTab = 'library';
      if (currentMobileTab === 'recommendations') currentMobileTab = 'library';
    }
  }

  function saveState() {
    try {
      localStorage.setItem('mediaState', JSON.stringify({
        activeGroup, activeType,
        activeFolders: [...activeFolders],
        activeResolutions: [...activeResolutions],
        activeCodecs: [...activeCodecs], activeAudioCodecs: [...activeAudioCodecs], activeProviders: [...activeProviders],
        activeGenres: [...activeGenres], activeAudioChannels: [...activeAudioChannels],
        activeAudioLanguages: [...activeAudioLanguages],
        activeQualityLevels: [...activeQualityLevels],
        scoreMin,
        scoreMax,
        includeNoScore,
        audioCodecExclude, videoCodecExclude, providerExclude, resolutionExclude, genreExclude, audioChannelsExclude, audioLanguageExclude, folderExclude, qualityExclude,
        currentTab, currentView,
        searchLib: document.getElementById('searchInput')?.value || '',
        sortVal: document.getElementById('sortSelect')?.value || '',
      }));
    } catch(e) {}
  }

  function restoreState() {
    try {
      const s = JSON.parse(localStorage.getItem('mediaState') || '{}');
      if (s.activeType)                       activeType        = s.activeType;
      if (s.activeGroup)                      activeGroup       = s.activeGroup;
      if (Array.isArray(s.activeFolders))     activeFolders     = new Set(s.activeFolders.filter(Boolean));
      else if (s.activeCat && s.activeCat !== 'all') activeFolders = new Set([s.activeCat]); // legacy single-folder state
      if (Array.isArray(s.activeProviders)) {
        activeProviders = new Set(
          s.activeProviders
            .map(v => _canonicalProviderFilterKey(v))
            .filter(Boolean)
        );
      }
      if (Array.isArray(s.activeResolutions)) {
        activeResolutions = new Set(s.activeResolutions.map(canonicalFilterMissingKey).filter(Boolean));
      } else if (s.activeResolution && s.activeResolution !== 'all') {
        // backward compatibility with legacy single-value resolution state
        activeResolutions = new Set([canonicalFilterMissingKey(s.activeResolution)].filter(Boolean));
      }
      if (Array.isArray(s.activeCodecs))      activeCodecs      = new Set(s.activeCodecs.map(canonicalFilterMissingKey).filter(Boolean));
      if (Array.isArray(s.activeAudioCodecs))     activeAudioCodecs     = new Set(s.activeAudioCodecs.map(canonicalFilterMissingKey).filter(Boolean));
      if (Array.isArray(s.activeGenres)) activeGenres = new Set(s.activeGenres.map(canonicalFilterMissingKey).filter(Boolean));
      if (Array.isArray(s.activeAudioChannels)) activeAudioChannels = new Set(s.activeAudioChannels.map(canonicalFilterMissingKey).filter(Boolean));
      if (Array.isArray(s.activeAudioLanguages)) activeAudioLanguages = new Set(s.activeAudioLanguages.map(canonicalAudioLanguageFilterKey).filter(Boolean));
      if (isScoreEnabled() && Array.isArray(s.activeQualityLevels)) {
        activeQualityLevels = new Set(
          s.activeQualityLevels
            .map(normalizeScoreRangeKey)
            .filter(Boolean)
        );
      }
      if (isScoreEnabled() && Number.isFinite(Number(s.scoreMin))) scoreMin = Math.max(0, Math.min(100, Number(s.scoreMin)));
      if (isScoreEnabled() && Number.isFinite(Number(s.scoreMax))) scoreMax = Math.max(0, Math.min(100, Number(s.scoreMax)));
      if (isScoreEnabled() && scoreMin > scoreMax) {
        const tmp = scoreMin;
        scoreMin = scoreMax;
        scoreMax = tmp;
      }
      if (isScoreEnabled() && s.includeNoScore !== undefined) includeNoScore = !!s.includeNoScore;
      if (s.audioCodecExclude !== undefined)     audioCodecExclude     = !!s.audioCodecExclude;
      if (s.videoCodecExclude !== undefined)     videoCodecExclude     = !!s.videoCodecExclude;
      if (s.providerExclude   !== undefined)     providerExclude       = !!s.providerExclude;
      if (s.resolutionExclude !== undefined)     resolutionExclude     = !!s.resolutionExclude;
      if (s.genreExclude !== undefined)          genreExclude          = !!s.genreExclude;
      if (s.audioChannelsExclude !== undefined)  audioChannelsExclude  = !!s.audioChannelsExclude;
      if (s.audioLanguageExclude !== undefined)  audioLanguageExclude  = !!s.audioLanguageExclude;
      if (s.folderExclude !== undefined)         folderExclude         = !!s.folderExclude;
      if (isScoreEnabled() && s.qualityExclude !== undefined) qualityExclude = !!s.qualityExclude;
      if (s.currentView)      setView(s.currentView, true);
      if (s.sortVal) {
        const el = document.getElementById('sortSelect');
        if (el) el.value = s.sortVal;
      }
      if (s.searchLib) {
        const el = document.getElementById('searchInput');
        if (el) el.value = s.searchLib;
      }
      // Re-render all filter pills with correct active states (no saveState)
      renderStorageBar();
      renderFolderFilter();
      renderGenreFilter();
      renderProviderFilter();
      renderResolutionFilter();
      renderCodecFilter();
      renderAudioCodecFilter();
      renderAudioChannelsFilter();
      renderTechnicalFilters();
      renderAudioLanguageFilter();
      renderQualityFilter();
      ensureScoreFilterLast();
      applyScoreFeatureVisibility();
      syncTypePills();
      if (s.currentTab === 'library' || s.currentTab === 'stats' || (s.currentTab === 'recommendations' && isRecommendationsEnabled())) {
        currentTab = s.currentTab;
      }
      updateGlobalResetButtons();
    } catch(e) {}
  }
  let currentView='grid', currentTab='library';
  let tSortCol=null, tSortDir=1;

  const PALETTE = window.MMLCore.PALETTE;

  let groupColorMap={}, catColorMap={};

  // ── LOAD ─────────────────────────────────────────────
  async function loadVersion() {
    try {
      const r = await fetch('/version.json?_='+Date.now());
      if (!r.ok) return;
      const v = await r.json();
      appVersionInfo = v;
      const el = document.getElementById('appVersionStr');
      if (!el) return;
      const parts = ['v' + (v.version || 'dev')];
      if (v.commit && v.commit !== 'dev') parts.push(v.commit);
      if (v.build_date) {
        const d = new Date(v.build_date);
        parts.push(d.toLocaleDateString(CURRENT_LANG === 'fr' ? 'fr-FR' : 'en-US', {year:'numeric',month:'long',day:'numeric'}));
      }
      el.textContent = parts.join(' • ');
    } catch(_) {}
    // Update doc link language
    const docLink = document.getElementById('settingsDocLink');
    if (docLink) {
      const lang = appConfig.system?.language || CURRENT_LANG || 'fr';
      docLink.href = '/docs.html?lang=' + (lang === 'en' ? 'en' : 'fr');
    }
  }

  async function loadLibrary() {
    window.MMLState.isLoading = true;
    window.MMLState.isLoaded  = false;
    window.MMLState.hasError  = false;
    window.MMLState.isLibraryMissing = false;
    await Promise.all([loadConfig(), loadProvidersCatalog(), loadAudioCodecMapping(), loadAudioLanguages()]);

    // Load translations for the configured language
    const lang = appConfig.system?.language || 'fr';
    if (lang !== CURRENT_LANG || !Object.keys(TRANSLATIONS).length) {
      await loadTranslations(lang);
    }
    applyTranslations();
    // Backend is the source of truth for onboarding state.
    const explicitNeedsOnboarding = (typeof appConfig.needs_onboarding === 'boolean')
      ? appConfig.needs_onboarding
      : null;
    const hasUsableFolders = Array.isArray(appConfig?.folders) && appConfig.folders.some((folder) => {
      if (!folder || typeof folder !== 'object') return false;
      const type = String(folder.type || '').trim().toLowerCase();
      if (!['movie', 'tv'].includes(type)) return false;
      const enabled = folder.enabled !== undefined ? folder.enabled : (folder.visible !== undefined ? folder.visible : true);
      return enabled !== false && !folder.missing;
    });
    const finishWithOnboarding = () => {
      window.MMLState.isLoading = false;
      window.MMLState.isLoaded = false;
      window.MMLState.hasError = false;
      window.MMLState.isLibraryMissing = false;
      libraryExportSource = null;
      updateExportJsonButtonState();
      showOnboarding();
    };
    const finishWithEmptyLibrary = () => {
      allItems = [];
      categories = [];
      groups = [];
      window.MMLState.items = allItems;
      window.MMLState.isLoading = false;
      window.MMLState.isLoaded = true;
      window.MMLState.hasError = false;
      window.MMLState.isLibraryMissing = true;
      libraryExportSource = null;
      document.getElementById('library').innerHTML='<div class="empty"><p>'+t('library.not_found')+'</p><small>'+t('library.run_scan')+'</small></div>';
      document.getElementById('scanInfo').textContent=t('library.run_scan');
      renderStorageBar();
      renderFolderFilter();
      renderGenreFilter();
      renderProviderFilter();
      renderResolutionFilter();
      renderCodecFilter();
      renderAudioCodecFilter();
      renderAudioChannelsFilter();
      renderTechnicalFilters();
      renderAudioLanguageFilter();
      renderQualityFilter();
      renderStats(filterItems());
      switchTab(currentTab);
      updateExportJsonButtonState();
    };
    if (explicitNeedsOnboarding === true) {
      finishWithOnboarding();
      return;
    }

    try {
      const lib = await _fetchLibraryJsonWithRetry();
      if (lib.missing) {
        // Missing library.json is expected before the first scan.
        // If onboarding is still required (explicitly or legacy missing flag + no usable folders),
        // keep onboarding flow. Otherwise show an empty-library state with scan prompt.
        if (explicitNeedsOnboarding === true || (explicitNeedsOnboarding === null && !hasUsableFolders)) {
          finishWithOnboarding();
        } else {
          finishWithEmptyLibrary();
        }
        return;
      }
      const data = lib.data;
      libraryExportSource = data;
      allItems = safeArray(data.items);
      categories = safeArray(data.categories);
      groups = safeArray(data.groups);
      if (visibleProviders === null) {
        const bootVisible = [...new Set(allItems.flatMap((item) => getEnabledProviderNames(item)).filter(Boolean))].sort();
        visibleProviders = new Set(bootVisible);
      }
      window.MMLState.items = allItems;
      allItems.forEach(i => {
        if (!i.audio_languages_simple) i.audio_languages_simple = getAudioLanguageSimple(i);
      });
      groups.forEach((g,i)=>{ groupColorMap[g]=PALETTE[i%PALETTE.length]; });
      categories.forEach((c,i)=>{ catColorMap[c]=PALETTE[i%PALETTE.length]; });

      // Inject dependencies into stats module
      window.MMLStats.init({
        filterItems,
        allItems,
        PALETTE,
        PROVIDER_OTHERS_KEY,
        getNormalizedVideoCodec,
        getNormalizedAudioCodec,
        getNormalizedResolution,
        getNormalizedGenres,
        getGenreDisplay,
        getNormalizedAudioChannels,
        getAudioLanguageSimple,
        getAudioLanguageSimpleDisplay,
        getAudioCodecDisplay,
        getFilterDisplayValue,
        getItemProviders,
        getEnabledProvidersForItem,
        _itemProviderGroups,
        _providerGroupKey,
        _providerGroupLabel,
        _pname,
        _plogo,
        t,
        fmtSize,
        escH,
        MMLLogic,
        renderStats,
        applyStatsFilter,
        isRecommendationsEnabled,
        visibleRecommendations,
        renderRecommendationFilterButtons,
        recPriorityLabel,
        recTypeLabel,
        recMedia,
        recScore,
        recSizeBytes,
        recommendationPriorityFilters,
        recommendationTypeFilters,
        activeFolders,
        getStatsScoreRangeState: () => ({ scoreMin, scoreMax, includeNoScore, qualityExclude }),
        updateGlobalResetButtons
      });

      const d=new Date(data.scanned_at);
      const locale = CURRENT_LANG === 'en' ? 'en-GB' : 'fr-FR';
      document.getElementById('scanInfo').innerHTML=
        t('library.last_scan')+' <span class="scan-ts-link" onclick="openLogViewer()" title="Voir le log">'+
        d.toLocaleDateString(locale)+' '+d.toLocaleTimeString(locale,{hour:'2-digit',minute:'2-digit'})+'</span>';
      libraryPathLabel = typeof data.library_path === 'string' ? data.library_path : '';
      if (libraryPathLabel) document.getElementById('brandSub').textContent = libraryPathLabel;
      enableScore = resolveScoreEnabled();
      enableRecommendations = resolveRecommendationsEnabled();
      applyScoreFeatureVisibility();
      applyRecommendationsFeatureVisibility();
      await loadRecommendations();
      renderStorageBar();
      renderFolderFilter();
      renderGenreFilter();
      renderProviderFilter();
      renderResolutionFilter();
      renderCodecFilter();
      renderAudioCodecFilter();
      renderAudioChannelsFilter();
      renderTechnicalFilters();
      renderAudioLanguageFilter();
      renderQualityFilter();
      restoreState();
      window.MMLState.isLoaded  = true;
      window.MMLState.isLoading = false;
      renderStats(filterItems());
      switchTab(currentTab);
      updateExportJsonButtonState();
    } catch(e) {
      const _is401 = String(e).includes('401');
      if (!_is401) console.error('loadLibrary error:', e);
      window.MMLState.isLoading = false;
      if (_is401) return; // 401: fetch interceptor already showed the login overlay — no error UI
      window.MMLState.hasError = true;
      window.MMLState.isLibraryMissing = false;
      libraryExportSource = null;
      const _emsg = String(e).includes('404') ? t('library.run_scan') : escH(String(e));
      document.getElementById('library').innerHTML='<div class="empty"><p>'+t('library.not_found')+'</p><small>'+_emsg+'</small></div>';
      document.getElementById('scanInfo').textContent=t('library.scan_error');
      updateExportJsonButtonState();
    }
  }

  function _dateYmd(d = new Date()) {
    return [
      d.getFullYear(),
      String(d.getMonth() + 1).padStart(2, '0'),
      String(d.getDate()).padStart(2, '0')
    ].join('-');
  }

  async function _getVersionForExport() {
    try {
      const r = await fetch('/version.json?_=' + Date.now());
      if (r.ok) {
        const data = await r.json();
        appVersionInfo = data;
        return data;
      }
    } catch(_) {}
    return appVersionInfo || { version: 'dev' };
  }

  async function exportLibraryJson() {
    if (!libraryExportSource) {
      alert(t('settings.system.export_unavailable'));
      return;
    }

    const exportedAt = new Date();
    const exportDate = _dateYmd(exportedAt);
    const versionInfo = await _getVersionForExport();
    const payload = {
      exported_at: exportedAt.toISOString(),
      export_date: exportDate,
      app_version: versionInfo.version || 'dev',
      app_version_meta: versionInfo,
      library: libraryExportSource
    };

    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
    const filename = `mymedialibrary-export-${exportDate}.json`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }


  // ── CONFIG ───────────────────────────────────────────
  function _isFolderEnabled(folder) {
    const enabled = folder?.enabled;
    if (enabled === undefined || enabled === null) return folder?.visible !== false;
    return enabled !== false;
  }

  function folderToCategoryName(name) {
    return name.replace(/[-_]/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  async function loadConfig() {
    // Migrate legacy mediaSettings from localStorage (one-time)
    const legacy = localStorage.getItem('mediaSettings');
    if (legacy) {
      try {
        const ls = JSON.parse(legacy);
        const mig = {};
        if (ls.enablePlot    !== undefined) { mig.ui = mig.ui||{}; mig.ui.synopsis_on_hover = ls.enablePlot; }
        if (ls.accentColor   !== undefined) { mig.ui = mig.ui||{}; mig.ui.accent_color = ls.accentColor; }
        const legacySeerrUrl = ls.seerrUrl ?? ls.jellyseerrUrl;
        const legacySeerrEnabled = ls.enableSeerr ?? ls.enableJellyseerr;
        if (legacySeerrUrl !== undefined || legacySeerrEnabled !== undefined) {
          mig.seerr = {};
          if (legacySeerrUrl     !== undefined) mig.seerr.url     = legacySeerrUrl;
          if (legacySeerrEnabled !== undefined) mig.seerr.enabled = legacySeerrEnabled;
        }
        if (Object.keys(mig).length) await saveConfig(mig);
      } catch(e) {}
      localStorage.removeItem('mediaSettings');
    }

    try {
      const r = await fetch('/api/config');
      if (!r.ok) return;
      appConfig = await r.json();
      if (typeof appConfig.needs_onboarding !== 'boolean' && typeof appConfig.system?.needs_onboarding === 'boolean') {
        appConfig.needs_onboarding = appConfig.system.needs_onboarding;
      }

      // UI prefs
      enablePlot       = appConfig.ui?.synopsis_on_hover ?? false;
      if (appConfig.ui?.theme)        document.documentElement.setAttribute('data-theme', appConfig.ui.theme);
      if (appConfig.ui?.accent_color) applyAccent(appConfig.ui.accent_color);

      // Apply default_sort if no session sort saved
      const sessionState = JSON.parse(localStorage.getItem('mediaState') || '{}');
      if (!sessionState.sortVal && appConfig.ui?.default_sort) {
        const el = document.getElementById('sortSelect');
        if (el) el.value = appConfig.ui.default_sort;
      }

      // Type visibility
      enableMovies     = appConfig.enable_movies ?? true;
      enableSeries     = appConfig.enable_series ?? true;
      enableSeerr = appConfig.seerr?.enabled ?? appConfig.jellyseerr?.enabled ?? false;
      enableScore      = resolveScoreEnabled();
      enableRecommendations = resolveRecommendationsEnabled();

      // Provider visibility: explicit whitelist from config
      const pv = appConfig.providers_visible;
      visibleProviders = Array.isArray(pv) ? new Set(pv) : null;

      // Active categories: derived from folders with enabled=false
      const folders = appConfig.folders || [];
      const hasHidden = folders.some(f => !_isFolderEnabled(f) && f.type && f.type !== 'ignore');
      if (hasHidden) {
        enabledCategories = new Set(
          folders
            .filter(f => _isFolderEnabled(f) && f.type && f.type !== 'ignore')
            .map(f => folderToCategoryName(f.name))
        );
      } else {
        enabledCategories = null;
      }

      _updateTypeFilterVisibility();
      applyScoreFeatureVisibility();
      applyRecommendationsFeatureVisibility();
    } catch(e) {
      if (!String(e).includes('401')) console.warn('loadConfig error:', e);
    }
  }

  async function saveConfig(partial) {
    try {
      const r = await fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(partial),
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      try {
        return await r.json();
      } catch (_) {
        return {};
      }
    } catch(e) {
      console.error('saveConfig error:', e);
      throw e;
    }
  }

  async function loadRecommendations() {
    if (!isRecommendationsEnabled()) {
      recommendationsDoc = null;
      return;
    }
    try {
      const r = await fetch('/api/recommendations?_=' + Date.now());
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const doc = await r.json();
      if (doc?.enabled === false) {
        recommendationsDoc = { enabled: false, generated_at: null, version: doc?.version || 1, items: [], error: null };
        enableRecommendations = false;
        applyRecommendationsFeatureVisibility();
        return;
      }
      recommendationsDoc = {
        enabled: doc?.enabled !== false,
        generated_at: doc?.generated_at || null,
        version: doc?.version || 1,
        items: Array.isArray(doc?.items) ? doc.items : [],
        error: null,
      };
    } catch (e) {
      console.warn('loadRecommendations error:', e);
      recommendationsDoc = { enabled: true, generated_at: null, version: 1, items: [], error: true };
    }
  }

  async function _fetchLibraryJsonWithRetry() {
    let parseError = null;
    for (let attempt = 0; attempt < 2; attempt++) {
      const libraryUrl = '/library.json?_=' + Date.now();
      const r = await fetch(libraryUrl);
      if (r.status === 404) return { missing: true };
      if (!r.ok) throw new Error('HTTP ' + r.status + ' while loading ' + libraryUrl);
      const body = await r.text();
      try {
        return { missing: false, data: JSON.parse(body) };
      } catch (_) {
        parseError = new Error('Invalid JSON in /library.json');
        if (attempt === 0) {
          await new Promise(resolve => setTimeout(resolve, 250));
          continue;
        }
      }
    }
    throw parseError || new Error('Invalid JSON in /library.json');
  }

  // ── STATS ────────────────────────────────────────────
  function renderStats(items) {
    const bytes=items.reduce((s,i)=>s+(i.size_b||0),0);
    const files=items.reduce((s,i)=>s+(i.file_count||0),0);
    const cats=new Set(items.map(i=>i.category)).size;
    const filtered=items.length < allItems.length;
    const elemLabel=filtered
      ? items.length+'<span style="font-size:11px;font-weight:400;color:var(--muted)"> / '+allItems.length+'</span>'
      : items.length;
    document.getElementById('statsBar').innerHTML=
      '<div class="stat"><div class="stat-val">'+elemLabel+'</div><div class="stat-label">'+t('stats.elements')+'</div></div>'+
      '<div class="stat"><div class="stat-val">'+cats+'</div><div class="stat-label">'+t('stats.categories')+'</div></div>'+
      '<div class="stat"><div class="stat-val">'+files.toLocaleString('fr-FR')+'</div><div class="stat-label">'+t('stats.files')+'</div></div>'+
      '<div class="stat"><div class="stat-val">'+fmtSize(bytes)+'</div><div class="stat-label">'+t('stats.disk')+'</div></div>';
    document.querySelectorAll('#mobileStatsBar').forEach(el=>{ el.innerHTML=document.getElementById('statsBar').innerHTML; });

  }

  // ── STORAGE + FILTER BAR ─────────────────────────────
  function renderStorageBar() {
    const sec=document.getElementById('storageSection');
    if (!allItems.length) { sec.style.display='none'; return; }
    const hasGroups=groups.length>0;
    let html='';

    // --- GROUP BAR (only if groups defined) ---
    if (hasGroups) {
      // aggregate items scoped to search + other filters (except group)
      const byG={};
      baseItems('group').forEach(i=>{ const g=i.group||'Autres'; byG[g]=(byG[g]||0)+(i.size_b||0); });
      const totalG=Object.values(byG).reduce((s,v)=>s+v,0);
      html+=barBlock(byG, totalG, activeGroup, groupColorMap,
        t('filters.by_group'), 'clickGroup', 'resetGroup');
    }

    if (!html) { sec.style.display='none'; sec.innerHTML=''; return; }
    sec.style.display='block';
    sec.innerHTML=html;

  }

  function barBlock(byKey, total, activeKey, cmap, title, clickFn, resetFn) {
    if (!total) return '';
    const sorted=Object.entries(byKey).sort((a,b)=>b[1]-a[1]);
    const resetCls='leg leg-reset'+(activeKey==='all'?' active':'');
    let pills='<div class="'+resetCls+'" onclick="'+resetFn+'()">'+t('filters.all')+'</div>';
    sorted.forEach(([k,v])=>{
      const col=cmap[k]||'#888';
      const cls='leg'+(activeKey===k?' active':'');
      const pct=(v/total*100).toFixed(1);
      pills+='<div class="'+cls+'" onclick="'+clickFn+"('"+escJ(k)+"')"+'" title="'+escH(k)+' — '+fmtSize(v)+'">'
        +'<div class="leg-dot" style="background:'+col+'"></div>'
        +'<span>'+escH(k)+'</span>'
        +'</div>';
    });
    return '<div class="storage-block"><div class="storage-title">'+title+'</div><div class="storage-legend">'+pills+'</div></div>';
  }
  
  function clickType(type) {
    activeType = (type !== 'all' && activeType === type) ? 'all' : type;
    syncTypePills();
    renderStorageBar();
    renderGenreFilter();
    renderProviderFilter();
    renderResolutionFilter();
    renderCodecFilter();
    renderAudioCodecFilter();
    renderAudioChannelsFilter();
    renderTechnicalFilters();
    onFilter();
  }

  function clickGroup(k){ activeGroup=activeGroup===k?'all':k; onFilter(); }
  function resetGroup() { activeGroup='all'; onFilter(); }
  function clickCat(k)  { if (activeFolders.has(k)) activeFolders.delete(k); else activeFolders.add(k); onFilter(); }
  function resetCat()   { activeFolders.clear(); onFilter(); }
  // ── DROPDOWN FILTER INFRASTRUCTURE ───────────────────
  let openDropdown = null;

  function toggleDropdown(containerId) {
    const wasOpen = openDropdown === containerId;
    if (openDropdown) {
      const panel = document.querySelector('#' + openDropdown + ' .filter-dropdown-panel');
      const chevron = document.querySelector('#' + openDropdown + ' .filter-dropdown-chevron');
      if (panel) panel.style.display = 'none';
      if (chevron) chevron.classList.remove('open');
      openDropdown = null;
    }
    if (!wasOpen) {
      const panel = document.querySelector('#' + containerId + ' .filter-dropdown-panel');
      const chevron = document.querySelector('#' + containerId + ' .filter-dropdown-chevron');
      if (panel) panel.style.display = 'block';
      if (chevron) chevron.classList.add('open');
      openDropdown = containerId;
    }
  }

  document.addEventListener('click', function(e) {
    if (openDropdown && !e.target.closest('.filter-dropdown')) {
      const panel = document.querySelector('#' + openDropdown + ' .filter-dropdown-panel');
      const chevron = document.querySelector('#' + openDropdown + ' .filter-dropdown-chevron');
      if (panel) panel.style.display = 'none';
      if (chevron) chevron.classList.remove('open');
      openDropdown = null;
    }
  });

  function hasActiveFilters() {
    const hasRecommendationFilters = recommendationTypeFilters.size > 0
      || recommendationPriorityFilters.size > 0
      || !!window.MMLStats?.hasActiveRecommendationStatsFilters?.();
    if (window.MMLLogic?.hasActiveFilters) {
      return hasRecommendationFilters || window.MMLLogic.hasActiveFilters({
        activeType,
        activeGroup,
        activeFolders,
        activeResolutions,
        activeProviders,
        activeCodecs,
        activeAudioCodecs,
        activeGenres,
        activeAudioChannels,
        activeAudioLanguages,
        activeQualityLevels,
        scoreMin,
        scoreMax,
        includeNoScore,
        providerExclude,
        resolutionExclude,
        genreExclude,
        audioChannelsExclude,
        videoCodecExclude,
        audioCodecExclude,
        audioLanguageExclude,
        folderExclude,
        qualityExclude,
        searchQuery: getSearchQuery(),
      });
    }
    return activeType !== 'all'
      || activeGroup !== 'all'
      || activeFolders.size > 0
      || activeResolutions.size > 0
      || activeProviders.size > 0
      || activeCodecs.size > 0
      || activeAudioCodecs.size > 0
      || activeGenres.size > 0
      || activeAudioChannels.size > 0
      || activeAudioLanguages.size > 0
      || (isScoreEnabled() && (scoreMin > 0 || scoreMax < 100 || !includeNoScore))
      || providerExclude
      || resolutionExclude
      || genreExclude
      || audioChannelsExclude
      || videoCodecExclude
      || audioCodecExclude
      || audioLanguageExclude
      || folderExclude
      || hasRecommendationFilters
      || getSearchQuery().length > 0;
  }

  function updateGlobalResetButtons() {
    const disabled = !hasActiveFilters();
    ['globalFilterResetBtn', 'globalFilterResetBtnMobile'].forEach(function(id) {
      const btn = document.getElementById(id);
      if (!btn) return;
      btn.disabled = disabled;
    });
  }

  function updateExportJsonButtonState() {
    const btn = document.getElementById('cfgExportJsonBtn');
    if (!btn) return;
    btn.disabled = !libraryExportSource;
  }

  function resetAllFilters() {
    activeType = 'all';
    activeGroup = 'all';
    activeFolders.clear();
    activeResolutions.clear();
    activeProviders.clear();
    activeCodecs.clear();
    activeAudioCodecs.clear();
    activeGenres.clear();
    activeAudioChannels.clear();
    activeAudioLanguages.clear();
    activeQualityLevels.clear();
    scoreMin = 0;
    scoreMax = 100;
    includeNoScore = true;
    providerExclude = false;
    resolutionExclude = false;
    genreExclude = false;
    audioChannelsExclude = false;
    videoCodecExclude = false;
    audioCodecExclude = false;
    audioLanguageExclude = false;
    folderExclude = false;
    qualityExclude = false;
    recommendationTypeFilters.clear();
    recommendationPriorityFilters.clear();
    window.MMLStats?.resetRecommendationStatsFilters?.({ render: false });

    const searchDesktop = document.getElementById('searchInput');
    if (searchDesktop) searchDesktop.value = '';
    const searchMobile = document.getElementById('searchInputMobile');
    if (searchMobile) searchMobile.value = '';
    const clearDesktop = document.getElementById('searchClear');
    if (clearDesktop) clearDesktop.style.display = 'none';
    const clearMobile = document.getElementById('searchClearMobile');
    if (clearMobile) clearMobile.style.display = 'none';

    onFilter();
  }

  function sortFilterOptionsByCount(options, getDisplay) {
    return options.slice().sort((a, b) => {
      if (b.count !== a.count) return b.count - a.count;
      const aLabel = String(getDisplay ? getDisplay(a.key) : a.key);
      const bLabel = String(getDisplay ? getDisplay(b.key) : b.key);
      return aLabel.localeCompare(bLabel, undefined, { sensitivity: 'base', numeric: true });
    });
  }

  function buildDropdownFilterModel({ counts, getDisplay, pinFirst, activeSet, sortOptions }) {
    const activeKeys = activeSet instanceof Set ? [...activeSet] : [];
    const activeLookup = new Set(activeKeys);
    const options = Object.keys(counts || {}).map((key) => ({
      key,
      count: Number(counts[key]) || 0
    })).filter(option => option.count > 0 || activeLookup.has(option.key));
    activeKeys.forEach((key) => {
      if (!key || options.some(option => option.key === key)) return;
      options.push({ key, count: 0 });
    });
    const pinned = pinFirst ? options.filter(option => option.key === pinFirst) : [];
    const remaining = pinFirst ? options.filter(option => option.key !== pinFirst) : options;
    const sortedRemaining = typeof sortOptions === 'function'
      ? sortOptions(remaining.slice(), getDisplay)
      : sortFilterOptionsByCount(remaining, getDisplay);
    return [
      ...pinned,
      ...sortedRemaining
    ];
  }

  function renderFilterDropdown({ containerId, counts, label, activeSet, toggleFn, clearFn, getDisplay, pinFirst, excludeMode, onToggleExclude, getOptionPrefixHtml, sortOptions }) {
    const sec = document.getElementById(containerId);
    if (!sec) return;
    const model = buildDropdownFilterModel({ counts, getDisplay, pinFirst, activeSet, sortOptions });
    const keys = model.map(option => option.key);
    if (!keys.length && activeSet.size === 0) { sec.style.display = 'none'; return; }
    sec.style.display = 'block';

    const isOpen = openDropdown === containerId;
    const hasValue = activeSet.size > 0;
    let triggerLabel;
    if (!hasValue) triggerLabel = t('filters.all');
    else if (excludeMode) {
      if (activeSet.size === 1) triggerLabel = t('filters.except') + ' ' + escH(getDisplay([...activeSet][0]));
      else triggerLabel = t('filters.except') + ' ' + t('filters.n_selected', { n: activeSet.size });
    } else {
      if (activeSet.size === 1) triggerLabel = escH(getDisplay([...activeSet][0]));
      else triggerLabel = t('filters.n_selected', { n: activeSet.size });
    }

    const clearBtn = hasValue
      ? '<span class="filter-dropdown-inline-clear" onclick="event.stopPropagation();' + clearFn + '()">✕</span>'
      : '';

    // Select-all state
    const allSelected = keys.length > 0 && keys.every(k => activeSet.has(k));
    const noneSelected = keys.every(k => !activeSet.has(k));
    const indeterminate = !allSelected && !noneSelected;
    const selectAllId = 'sa_' + containerId;

    let html = '<div class="storage-block">'
      + '<div class="storage-title">' + escH(label) + '</div>'
      + '<div class="filter-dropdown">'
      + '<div class="filter-dropdown-trigger' + (hasValue ? ' has-value' : '') + '" onclick="toggleDropdown(\'' + containerId + '\')">'
      + '<span class="filter-dropdown-label">' + triggerLabel + '</span>'
      + clearBtn
      + '<svg class="filter-dropdown-chevron' + (isOpen ? ' open' : '') + '" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>'
      + '</div>'
      + '<div class="filter-dropdown-panel"' + (isOpen ? '' : ' style="display:none"') + '>'
      + '<div class="filter-dropdown-header">'
      + '<label class="filter-dropdown-select-all" onclick="event.stopPropagation()">'
      + '<input type="checkbox" id="' + selectAllId + '"' + (allSelected ? ' checked' : '')
      + ' onchange="event.stopPropagation();_dropdownSelectAll(\'' + containerId + '\',\'' + clearFn + '\',this.checked)">'
      + '<span>' + t('filters.select_all') + '</span>'
      + '</label>';
    if (onToggleExclude) {
      const modeClass = excludeMode ? ' is-exclude' : ' is-include';
      const modeLabel = excludeMode ? t('filters.exclude') : t('filters.include');
      html += '<button class="filter-mode-toggle' + modeClass + '" type="button" onclick="event.stopPropagation();' + onToggleExclude + '()">' + modeLabel + '</button>';
    }
    html += '</div>';
    keys.forEach(function(key) {
      const checked = activeSet.has(key);
      const prefixHtml = typeof getOptionPrefixHtml === 'function' ? getOptionPrefixHtml(key) : '';
      html += '<div class="filter-dropdown-option" onclick="event.stopPropagation();' + toggleFn + '(this.dataset.key)" data-key="' + escH(key) + '">'
        + '<input type="checkbox"' + (checked ? ' checked' : '') + ' tabindex="-1">'
        + prefixHtml
        + '<span class="filter-dropdown-option-label">' + escH(getDisplay(key)) + '</span>'
        + '<span class="filter-dropdown-option-count">(' + (Number(counts?.[key]) || 0) + ')</span>'
        + '</div>';
    });
    html += '</div></div></div>';
    sec.innerHTML = html;
    // Set indeterminate state for select-all checkbox (can't be set in HTML)
    const saEl = sec.querySelector('#' + selectAllId);
    if (saEl && indeterminate) saEl.indeterminate = true;
  }

  function normalizeScoreRangeKey(raw) {
    if (raw === null || raw === undefined) return null;
    const value = String(raw).trim();
    if (!value) return null;
    if (SCORE_FILTER_RANGES.some(r => r.key === value)) return value;
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return null;
    if (numeric === 1) return '0_20';
    if (numeric === 2) return '20_40';
    if (numeric === 3) return '40_60';
    if (numeric === 4) return '60_80';
    if (numeric === 5) return '80_100';
    return null;
  }

  function getScoreRangeByKey(key) {
    return SCORE_FILTER_RANGES.find(r => r.key === key) || null;
  }

  function matchesScoreRange(score, rangeKey) {
    const value = Number(score);
    if (!Number.isFinite(value)) return false;
    const range = getScoreRangeByKey(rangeKey);
    if (!range) return false;
    return getQualityLevelFromScore(value) === range.level;
  }

  function getScoreRangeKey(score) {
    const range = SCORE_FILTER_RANGES.find(r => matchesScoreRange(score, r.key));
    return range ? range.key : null;
  }

  function ensureScoreFilterLast() {
    const desktopContainer = document.querySelector('.sidebar-filters');
    if (desktopContainer) {
      // Enforce canonical filter order first, keep storage as a separate contextual block at the end.
      const desktopOrder = ['type', ...FILTER_ORDER.filter(k => k !== 'type'), 'storage'];
      desktopOrder.forEach(key => {
        const sectionId = FILTER_SECTION_IDS[key]?.desktop;
        if (!sectionId) return;
        const section = document.getElementById(sectionId);
        if (section && section.parentElement === desktopContainer) desktopContainer.appendChild(section);
      });
    }
    const mobileContainer = document.querySelector('#mobileFiltersPanel .mobile-filters-body');
    if (mobileContainer) {
      const mobileOrder = ['type', ...FILTER_ORDER.filter(k => k !== 'type'), 'storage'];
      mobileOrder.forEach(key => {
        const sectionId = FILTER_SECTION_IDS[key]?.mobile;
        if (!sectionId) return;
        const section = document.getElementById(sectionId);
        if (section && section.parentElement === mobileContainer) mobileContainer.appendChild(section);
      });
    }
  }

  function _dropdownSelectAll(containerId, clearFn, checked) {
    const sec = document.getElementById(containerId);
    if (!sec) return;
    if (!checked) { window[clearFn] && window[clearFn](); return; }
    // Collect all keys from rendered options before any re-render
    const keys = [...sec.querySelectorAll('.filter-dropdown-option[data-key]')].map(el => el.dataset.key);
    if (!keys.length) return;
    // Determine the Set to update by mapping containerId to the active set variable
    const setMap = {
      'providerSection': activeProviders, 'providerSectionMobile': activeProviders, 'providerSectionTop': activeProviders,
      'resolutionSection': activeResolutions, 'resolutionSectionMobile': activeResolutions,
      'codecSection': activeCodecs, 'codecSectionMobile': activeCodecs,
      'audioCodecSection': activeAudioCodecs, 'audioCodecSectionMobile': activeAudioCodecs,
      'audioChannelsSection': activeAudioChannels, 'audioChannelsSectionMobile': activeAudioChannels,
      'genreSection': activeGenres, 'genreSectionMobile': activeGenres,
      'audioLanguageSection': activeAudioLanguages, 'audioLanguageSectionMobile': activeAudioLanguages,
      'folderSection': activeFolders, 'folderSectionMobile': activeFolders,
      'qualitySection': activeQualityLevels, 'qualitySectionMobile': activeQualityLevels,
    };
    const activeSet = setMap[containerId];
    if (activeSet) { keys.forEach(k => activeSet.add(k)); onFilter(); }
  }

  function toggleProviderFilter(key) { if (activeProviders.has(key)) activeProviders.delete(key); else activeProviders.add(key); onFilter(); }
  function clearProviderFilter() { activeProviders.clear(); onFilter(); }
  function toggleResolutionFilter(key) { if (activeResolutions.has(key)) activeResolutions.delete(key); else activeResolutions.add(key); onFilter(); }
  function clearResolutionFilter() { activeResolutions.clear(); onFilter(); }
  function toggleCodecFilter(key) { if (activeCodecs.has(key)) activeCodecs.delete(key); else activeCodecs.add(key); onFilter(); }
  function clearCodecFilter() { activeCodecs.clear(); onFilter(); }
  function toggleAudioCodecFilter(key) { if (activeAudioCodecs.has(key)) activeAudioCodecs.delete(key); else activeAudioCodecs.add(key); onFilter(); }
  function clearAudioCodecFilter() { activeAudioCodecs.clear(); onFilter(); }
  function toggleAudioChannelsFilter(key) { if (activeAudioChannels.has(key)) activeAudioChannels.delete(key); else activeAudioChannels.add(key); onFilter(); }
  function clearAudioChannelsFilter() { activeAudioChannels.clear(); onFilter(); }
  function toggleGenreFilter(key) { if (activeGenres.has(key)) activeGenres.delete(key); else activeGenres.add(key); onFilter(); }
  function clearGenreFilter() { activeGenres.clear(); onFilter(); }
  function toggleAudioLanguageFilter(key) { if (activeAudioLanguages.has(key)) activeAudioLanguages.delete(key); else activeAudioLanguages.add(key); onFilter(); }
  function clearAudioLanguageFilter() { activeAudioLanguages.clear(); onFilter(); }
  function toggleProviderExclude() { providerExclude = !providerExclude; onFilter(); }
  function toggleResolutionExclude() { resolutionExclude = !resolutionExclude; onFilter(); }
  function toggleVideoCodecExclude() { videoCodecExclude = !videoCodecExclude; onFilter(); }
  function toggleAudioCodecExclude() { audioCodecExclude = !audioCodecExclude; onFilter(); }
  function toggleAudioChannelsExclude() { audioChannelsExclude = !audioChannelsExclude; onFilter(); }
  function toggleGenreExclude() { genreExclude = !genreExclude; onFilter(); }
  function toggleAudioLanguageExclude() { audioLanguageExclude = !audioLanguageExclude; onFilter(); }
  function toggleFolderFilter(key) { if (activeFolders.has(key)) activeFolders.delete(key); else activeFolders.add(key); onFilter(); }
  function clearFolderFilter() { activeFolders.clear(); onFilter(); }
  function toggleFolderExclude() { folderExclude = !folderExclude; onFilter(); }
  function toggleQualityFilter(level) {
    const key = normalizeScoreRangeKey(level);
    if (!key) return;
    if (activeQualityLevels.has(key)) activeQualityLevels.delete(key); else activeQualityLevels.add(key);
    onFilter();
  }
  function clearQualityFilter() { activeQualityLevels.clear(); onFilter(); }
  function toggleQualityExclude() { qualityExclude = !qualityExclude; onFilter(); }

  function applyStatsSetToggle(activeSet, key, isExcludeMode) {
    if (!isExcludeMode && activeSet.has(key)) {
      activeSet.delete(key);
    } else {
      activeSet.add(key);
    }
  }

  function applyStatsFilter(kind, value, meta = {}) {
    const key = normalizeFilterValue(value);
    if (!key) return;
    if (kind === 'folder') {
      applyStatsSetToggle(activeFolders, key, folderExclude);
      folderExclude = false;
    } else if (kind === 'genre') {
      applyStatsSetToggle(activeGenres, key, genreExclude);
      genreExclude = false;
    } else if (kind === 'provider') {
      applyStatsSetToggle(activeProviders, _canonicalProviderFilterKey(key) || key, providerExclude);
      providerExclude = false;
    } else if (kind === 'resolution') {
      applyStatsSetToggle(activeResolutions, key, resolutionExclude);
      resolutionExclude = false;
    } else if (kind === 'codec') {
      applyStatsSetToggle(activeCodecs, key, videoCodecExclude);
      videoCodecExclude = false;
    } else if (kind === 'audioCodec') {
      applyStatsSetToggle(activeAudioCodecs, key, audioCodecExclude);
      audioCodecExclude = false;
    } else if (kind === 'audioLanguage') {
      applyStatsSetToggle(activeAudioLanguages, canonicalAudioLanguageFilterKey(key) || key, audioLanguageExclude);
      audioLanguageExclude = false;
    } else if (kind === 'audioChannels') {
      applyStatsSetToggle(activeAudioChannels, key, audioChannelsExclude);
      audioChannelsExclude = false;
    } else if (kind === 'recommendationPriority') {
      if (recommendationPriorityFilters.has(key)) recommendationPriorityFilters.delete(key);
      else recommendationPriorityFilters.add(key);
    } else if (kind === 'recommendationType') {
      if (recommendationTypeFilters.has(key)) recommendationTypeFilters.delete(key);
      else recommendationTypeFilters.add(key);
    } else if (kind === 'scoreRange' && isScoreEnabled()) {
      const min = Number(meta.min);
      const max = Number(meta.max);
      if (!Number.isFinite(min) || !Number.isFinite(max)) return;
      const nextMin = Math.max(0, Math.min(100, Math.min(min, max)));
      const nextMax = Math.max(0, Math.min(100, Math.max(min, max)));
      const isActiveIncludeRange = !qualityExclude && scoreMin === nextMin && scoreMax === nextMax && includeNoScore === false;
      qualityExclude = false;
      if (isActiveIncludeRange) {
        scoreMin = 0;
        scoreMax = 100;
        includeNoScore = true;
      } else {
        scoreMin = nextMin;
        scoreMax = nextMax;
        includeNoScore = false;
      }
    } else {
      return;
    }
    onFilter();
  }

  function toggleTechnicalFilters(isMobile) {
    if (isMobile) technicalFiltersOpenMobile = !technicalFiltersOpenMobile;
    else technicalFiltersOpenDesktop = !technicalFiltersOpenDesktop;
    renderTechnicalFilters();
  }

  // ── PROVIDER FILTER ──────────────────────────────────
  function renderProviderFilter() {
    const base = baseItems('provider');
    const counts = {};
    const noneCount = base.filter(i => getEnabledProvidersForItem(i).length === 0).length;
    if (noneCount > 0) counts[FILTER_NONE_KEY] = noneCount;
    base.forEach(i => {
      _itemProviderGroups(i).forEach(name => {
        counts[name] = (counts[name]||0) + 1;
      });
    });
    if (counts[PROVIDER_OTHERS_KEY] === undefined) counts[PROVIDER_OTHERS_KEY] = 0;
    ['providerSection', 'providerSectionMobile', 'providerSectionTop'].forEach(function(cid) {
      const sec = document.getElementById(cid);
      if (!enableSeerr) { if (sec) sec.style.display = 'none'; return; }
      renderFilterDropdown({ containerId: cid, counts, label: t('filters.streaming_fr'),
        activeSet: activeProviders, toggleFn: 'toggleProviderFilter', clearFn: 'clearProviderFilter',
        getDisplay: k => {
          if (k === FILTER_NONE_KEY) return getFilterDisplayValue(k, 'filters.no_provider');
          return _providerGroupLabel(k);
        }, pinFirst: FILTER_NONE_KEY,
        excludeMode: providerExclude, onToggleExclude: 'toggleProviderExclude' });
    });
  }

  function renderCodecFilter() {
    const base = baseItems('codec');
    const counts = {};
    base.forEach(i => {
      const key = getNormalizedVideoCodec(i);
      counts[key] = (counts[key] || 0) + 1;
    });
    ['codecSection', 'codecSectionMobile'].forEach(function(cid) {
      renderFilterDropdown({ containerId: cid, counts, label: t('filters.codec'),
        activeSet: activeCodecs, toggleFn: 'toggleCodecFilter', clearFn: 'clearCodecFilter',
        getDisplay: k => k === 'UNKNOWN' ? t('filters.unknown') : getFilterDisplayValue(k),
        excludeMode: videoCodecExclude, onToggleExclude: 'toggleVideoCodecExclude' });
    });
  }

  function renderAudioCodecFilter() {
    const base = baseItems('audioCodec');
    const counts = {};
    base.forEach(i => {
      const key = getNormalizedAudioCodec(i);
      counts[key] = (counts[key] || 0) + 1;
    });
    ['audioCodecSection', 'audioCodecSectionMobile'].forEach(function(cid) {
      renderFilterDropdown({ containerId: cid, counts, label: t('filters.audio_codec'),
        activeSet: activeAudioCodecs, toggleFn: 'toggleAudioCodecFilter', clearFn: 'clearAudioCodecFilter', getDisplay: k => getAudioCodecDisplay(k),
        excludeMode: audioCodecExclude, onToggleExclude: 'toggleAudioCodecExclude' });
    });
  }

  function renderAudioLanguageFilter() {
    const base = baseItems('audioLanguage');
    const counts = {};
    base.forEach(i => {
      const key = getAudioLanguageSimple(i);
      counts[key] = (counts[key] ?? 0) + 1;
    });
    if (Object.keys(counts).length === 0) {
      ['audioLanguageSection', 'audioLanguageSectionMobile'].forEach(function(cid) {
        const sec = document.getElementById(cid);
        if (sec) sec.style.display = 'none';
      });
      return;
    }
    ['audioLanguageSection', 'audioLanguageSectionMobile'].forEach(function(cid) {
      renderFilterDropdown({ containerId: cid, counts, label: t('filters.audio_language'),
        activeSet: activeAudioLanguages, toggleFn: 'toggleAudioLanguageFilter', clearFn: 'clearAudioLanguageFilter',
        getDisplay: k => getAudioLanguageSimpleDisplay(k),
        excludeMode: audioLanguageExclude, onToggleExclude: 'toggleAudioLanguageExclude' });
    });
  }

  function renderFolderFilter() {
    const base = baseItems('folder');
    const counts = {};
    base.forEach(i => {
      const key = i.category || FILTER_NONE_KEY;
      counts[key] = (counts[key] || 0) + 1;
    });
    ['folderSection', 'folderSectionMobile'].forEach(function(cid) {
      renderFilterDropdown({ containerId: cid, counts, label: t('filters.by_category'),
        activeSet: activeFolders, toggleFn: 'toggleFolderFilter', clearFn: 'clearFolderFilter',
        getDisplay: k => getFilterDisplayValue(k),
        excludeMode: folderExclude, onToggleExclude: 'toggleFolderExclude' });
    });
  }

  function renderGenreFilter() {
    const base = baseItems('genre');
    const counts = {};
    base.forEach((item) => {
      const genres = getNormalizedGenres(item);
      if (!genres.length) {
        counts[FILTER_NONE_KEY] = (counts[FILTER_NONE_KEY] || 0) + 1;
        return;
      }
      genres.forEach((genre) => {
        counts[genre] = (counts[genre] || 0) + 1;
      });
    });
    ['genreSection', 'genreSectionMobile'].forEach(function(cid) {
      renderFilterDropdown({ containerId: cid, counts, label: t('filters.genre'),
        activeSet: activeGenres, toggleFn: 'toggleGenreFilter', clearFn: 'clearGenreFilter',
        getDisplay: k => getGenreDisplay(k),
        excludeMode: genreExclude, onToggleExclude: 'toggleGenreExclude' });
    });
  }

  function qualityRangeLabel(key) {
    const range = getScoreRangeByKey(key);
    if (!range) return t('filters.unknown');
    return t(range.labelKey);
  }

  function renderQualityFilter() {
    if (!isScoreEnabled()) {
      ['qualitySection', 'qualitySectionMobile'].forEach(function(cid) {
        const sec = document.getElementById(cid);
        if (sec) {
          sec.style.display = 'none';
          sec.innerHTML = '';
        }
      });
      return;
    }
    ['qualitySection', 'qualitySectionMobile'].forEach(function(cid) {
      const sec = document.getElementById(cid);
      if (!sec) {
        console.warn('[filters] score filter target container not found', cid);
        return;
      }
      sec.style.display = '';
      sec.innerHTML = ''
        + '<div class="storage-block">'
        + '<div class="storage-title">' + t('filters.score') + '</div>'
        + '<div class="score-filter-panel">'
        + '  <div class="score-double-slider" style="--range-min:' + scoreMin + ';--range-max:' + scoreMax + ';">'
        + '    <div class="score-double-slider-track"></div>'
        + '    <div class="score-double-slider-selected"></div>'
        + '    <input type="range" class="score-slider score-slider-min" min="0" max="100" step="1" value="' + scoreMin + '" aria-label="' + t('filters.score') + ' min"/>'
        + '    <input type="range" class="score-slider score-slider-max" min="0" max="100" step="1" value="' + scoreMax + '" aria-label="' + t('filters.score') + ' max"/>'
        + '  </div>'
        + '  <div class="score-filter-meta"><div class="score-filter-current" aria-live="polite">' + scoreMin + '–' + scoreMax + '</div></div>'
        + '  <label class="score-filter-checkbox"><input type="checkbox" class="score-no-score-toggle"' + (includeNoScore ? ' checked' : '') + '/> ' + t('filters.score.include_no_score') + '</label>'
        + '</div></div>';
      const minInput = sec.querySelector('.score-slider-min');
      const maxInput = sec.querySelector('.score-slider-max');
      const noScoreInput = sec.querySelector('.score-no-score-toggle');
      const rangeText = sec.querySelector('.score-filter-current');
      const rangeWrap = sec.querySelector('.score-double-slider');

      let draftScoreMin = scoreMin;
      let draftScoreMax = scoreMax;
      let hasPendingDraft = false;

      function syncRangeText() {
        if (rangeText) rangeText.textContent = draftScoreMin + '–' + draftScoreMax;
        if (rangeWrap) {
          rangeWrap.style.setProperty('--range-min', String(draftScoreMin));
          rangeWrap.style.setProperty('--range-max', String(draftScoreMax));
        }
        if (minInput && maxInput) {
          const minOnTop = draftScoreMin >= draftScoreMax - 2;
          minInput.style.zIndex = minOnTop ? '3' : '2';
          maxInput.style.zIndex = minOnTop ? '2' : '3';
        }
      }
      function updateDraftFromSlider(changed) {
        const currentMin = Number(minInput?.value ?? draftScoreMin);
        const currentMax = Number(maxInput?.value ?? draftScoreMax);
        let nextMin = Number.isFinite(currentMin) ? currentMin : draftScoreMin;
        let nextMax = Number.isFinite(currentMax) ? currentMax : draftScoreMax;
        if (changed === 'min' && nextMin > nextMax) {
          nextMax = nextMin;
          if (maxInput) maxInput.value = String(nextMax);
        } else if (changed === 'max' && nextMax < nextMin) {
          nextMin = nextMax;
          if (minInput) minInput.value = String(nextMin);
        }
        draftScoreMin = Math.max(0, Math.min(100, Math.min(nextMin, nextMax)));
        draftScoreMax = Math.max(0, Math.min(100, Math.max(nextMin, nextMax)));
        if (minInput) minInput.value = String(draftScoreMin);
        if (maxInput) maxInput.value = String(draftScoreMax);
        hasPendingDraft = draftScoreMin !== scoreMin || draftScoreMax !== scoreMax;
        syncRangeText();
      }

      function commitDraftScoreRange() {
        if (!hasPendingDraft) return;
        const prevDefault = scoreMin === 0 && scoreMax === 100;
        scoreMin = draftScoreMin;
        scoreMax = draftScoreMax;
        const nowDefault = scoreMin === 0 && scoreMax === 100;
        if (prevDefault && !nowDefault) includeNoScore = false;
        if (noScoreInput) noScoreInput.checked = includeNoScore;
        hasPendingDraft = false;
        onFilter();
      }

      minInput?.addEventListener('input', function() { updateDraftFromSlider('min'); });
      maxInput?.addEventListener('input', function() { updateDraftFromSlider('max'); });
      minInput?.addEventListener('change', commitDraftScoreRange);
      maxInput?.addEventListener('change', commitDraftScoreRange);
      minInput?.addEventListener('pointerup', commitDraftScoreRange);
      maxInput?.addEventListener('pointerup', commitDraftScoreRange);
      minInput?.addEventListener('touchend', commitDraftScoreRange);
      maxInput?.addEventListener('touchend', commitDraftScoreRange);
      minInput?.addEventListener('mouseup', commitDraftScoreRange);
      maxInput?.addEventListener('mouseup', commitDraftScoreRange);
      noScoreInput?.addEventListener('change', function(e) {
        includeNoScore = !!e.target.checked;
        onFilter();
      });
      syncRangeText();
    });
  }

  function renderResolutionFilter() {
    const base = baseItems('resolution');
    const counts = {};
    base.forEach(i => {
      const key = getNormalizedResolution(i);
      counts[key] = (counts[key] || 0) + 1;
    });
    ['resolutionSection', 'resolutionSectionMobile'].forEach(function(cid) {
      renderFilterDropdown({
        containerId: cid,
        counts,
        label: t('filters.resolution'),
        activeSet: activeResolutions,
        toggleFn: 'toggleResolutionFilter',
        clearFn: 'clearResolutionFilter',
        getDisplay: k => getFilterDisplayValue(k),
        excludeMode: resolutionExclude,
        onToggleExclude: 'toggleResolutionExclude',
      });
    });
  }

  function renderAudioChannelsFilter() {
    const base = baseItems('audioChannels');
    const counts = {};
    base.forEach((item) => {
      const key = getNormalizedAudioChannels(item);
      counts[key] = (counts[key] || 0) + 1;
    });
    const sortAudioChannels = (options) => options.sort((a, b) => {
      if (a.key === FILTER_NONE_KEY && b.key !== FILTER_NONE_KEY) return 1;
      if (a.key !== FILTER_NONE_KEY && b.key === FILTER_NONE_KEY) return -1;
      const aNum = Number.parseFloat(a.key);
      const bNum = Number.parseFloat(b.key);
      const aIsNum = Number.isFinite(aNum);
      const bIsNum = Number.isFinite(bNum);
      if (aIsNum && bIsNum && bNum !== aNum) return bNum - aNum;
      if (aIsNum && !bIsNum) return -1;
      if (!aIsNum && bIsNum) return 1;
      return String(a.key).localeCompare(String(b.key), undefined, { sensitivity: 'base', numeric: true });
    });
    ['audioChannelsSection', 'audioChannelsSectionMobile'].forEach(function(cid) {
      renderFilterDropdown({
        containerId: cid,
        counts,
        label: t('filters.audio_channels'),
        activeSet: activeAudioChannels,
        toggleFn: 'toggleAudioChannelsFilter',
        clearFn: 'clearAudioChannelsFilter',
        getDisplay: k => getFilterDisplayValue(k, 'filters.none'),
        excludeMode: audioChannelsExclude,
        onToggleExclude: 'toggleAudioChannelsExclude',
        sortOptions: sortAudioChannels,
      });
    });
  }

  function renderTechnicalFilters() {
    const cfg = [
      { sectionId: 'technicalSection', bodyId: 'technicalBody', btnId: 'technicalToggleBtn', open: technicalFiltersOpenDesktop },
      { sectionId: 'technicalSectionMobile', bodyId: 'technicalBodyMobile', btnId: 'technicalToggleBtnMobile', open: technicalFiltersOpenMobile },
    ];
    cfg.forEach((entry) => {
      const section = document.getElementById(entry.sectionId);
      const body = document.getElementById(entry.bodyId);
      const btn = document.getElementById(entry.btnId);
      if (!section || !body || !btn) return;
      const hasVisibleChildren = [...body.children].some((child) => child.style.display !== 'none');
      if (!hasVisibleChildren) {
        section.style.display = 'none';
        return;
      }
      section.style.display = '';
      body.classList.toggle('is-collapsed', !entry.open);
      btn.setAttribute('aria-expanded', entry.open ? 'true' : 'false');
    });
  }

  function onFilter() {
    syncTypePills();
    renderStorageBar();
    renderFolderFilter();
    renderGenreFilter();
    renderProviderFilter();
    renderResolutionFilter();
    renderCodecFilter();
    renderAudioCodecFilter();
    renderAudioChannelsFilter();
    renderTechnicalFilters();
    renderAudioLanguageFilter();
    renderQualityFilter();
    ensureScoreFilterLast();
    renderStats(filterItems());
    if (currentTab==='library') render();
    else if (currentTab==='stats') window.MMLStats.renderStatsPanel();
    else if (currentTab==='recommendations') renderRecommendationsPanel();
    saveState();
    syncMobileFilters();
    updateGlobalResetButtons();
  }

  function syncTypePills() {
    ['#typeFilter', '#typeFilterTop', '#typeFilterMobile'].forEach(sel => {
      document.querySelectorAll(sel + ' .provider-pill').forEach(p => {
        const t = p.dataset.type || 'all';
        p.classList.toggle('active', activeType === 'all' ? !p.dataset.type : t === activeType);
      });
    });
  }

  // ── FILTER ITEMS ─────────────────────────────────────
  function getSearchQuery() {
    return document.getElementById('searchInput')?.value.toLowerCase().trim() || '';
  }

  function normalizeSearchText(value) {
    return String(value || '')
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, ' ')
      .replace(/[_-]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function searchTokens(query) {
    const normalized = normalizeSearchText(query);
    return normalized ? normalized.split(' ').filter(Boolean) : [];
  }

  function getItemSearchFields(item) {
    const providers = getProviderNames(item).join(' ');
    const runtimeItem = {
      title: item.title,
      year: item.year,
      audio_codec: getNormalizedAudioCodec(item),
      audio_codec_display: getAudioCodecLabel(item),
      audio_codec_raw: item.audio_codec_raw,
      codec: getNormalizedVideoCodec(item),
      resolution: getNormalizedResolution(item),
      audio_languages_simple: getAudioLanguageSimple(item),
      audio_languages: item.audio_languages,
      providers: providers ? providers.split(' ') : []
    };
    if (window.MMLLogic?.getItemSearchFields) {
      return window.MMLLogic.getItemSearchFields(runtimeItem);
    }
    const audioSimple = runtimeItem.audio_languages_simple;
    const audioSimpleAliases = audioSimple === 'VF'
      ? 'vf french francais fr'
      : (audioSimple === 'VO'
        ? 'vo original'
        : (audioSimple === 'MULTI'
          ? 'multi multilingual multilang'
          : 'unknown inconnu'));
    const videoCodecAliases = runtimeItem.codec === 'H.265' ? 'hevc x265 h265' : (runtimeItem.codec === 'H.264' ? 'avc x264 h264' : '');
    return [
      runtimeItem.title,
      runtimeItem.year,
      runtimeItem.audio_codec,
      runtimeItem.audio_codec_display,
      runtimeItem.audio_codec_raw,
      runtimeItem.codec,
      videoCodecAliases,
      runtimeItem.resolution,
      audioSimple,
      audioSimpleAliases,
      providers
    ];
  }

  const _itemSearchCache = new WeakMap();
  function getItemSearchIndex(item) {
    if (_itemSearchCache.has(item)) return _itemSearchCache.get(item);
    const idx = normalizeSearchText(getItemSearchFields(item).join(' '));
    _itemSearchCache.set(item, idx);
    return idx;
  }

  function applySearch(items, q) {
    if (!q) return items;
    const tokens = searchTokens(q);
    if (!tokens.length) return items;
    return items.filter(i => {
      const idx = getItemSearchIndex(i);
      return tokens.every(tok => idx.includes(tok));
    });
  }

  function filterItems() {
    // Visibility order:
    // 1. Settings — type enabled (enableMovies/enableSeries)
    // 2. Settings — active categories (enabledCategories)
    // 3. Sidebar filters — type, group, folders, provider, resolution, codec, search
    // Note: visibleProviders affects logos/filter display only, NOT item visibility
    const q = getSearchQuery();
    let items=allItems;
    if (!enableMovies)       items=items.filter(i=>i.type!=='movie');
    if (!enableSeries)       items=items.filter(i=>i.type!=='tv');
    if (enabledCategories)   items=items.filter(i=>_catVisible(i.category));
    if (activeType!=='all')  items=items.filter(i=>i.type===activeType);
    if (activeGroup!=='all') items=items.filter(i=>i.group===activeGroup);
    if (activeFolders.size > 0) {
      if (folderExclude) items = items.filter(i => !activeFolders.has(i.category || FILTER_NONE_KEY));
      else items = items.filter(i => activeFolders.has(i.category || FILTER_NONE_KEY));
    }
    if (enableSeerr && activeProviders.size > 0) {
      items = items.filter(_matchesProviderFilters);
    }
    if (activeResolutions.size > 0) {
      if (resolutionExclude) {
        items=items.filter(i=>!activeResolutions.has(getNormalizedResolution(i)));
      } else {
        items=items.filter(i=>activeResolutions.has(getNormalizedResolution(i)));
      }
    }
    if (activeCodecs.size > 0) {
      if (videoCodecExclude) {
        items=items.filter(i=>!activeCodecs.has(getNormalizedVideoCodec(i)));
      } else {
        items=items.filter(i=>activeCodecs.has(getNormalizedVideoCodec(i)));
      }
    }
    if (activeAudioCodecs.size > 0) {
      if (audioCodecExclude) {
        items=items.filter(i=>!activeAudioCodecs.has(getNormalizedAudioCodec(i)));
      } else {
        items=items.filter(i=>activeAudioCodecs.has(getNormalizedAudioCodec(i)));
      }
    }
    if (activeAudioChannels.size > 0) {
      if (audioChannelsExclude) {
        items = items.filter((i) => !activeAudioChannels.has(getNormalizedAudioChannels(i)));
      } else {
        items = items.filter((i) => activeAudioChannels.has(getNormalizedAudioChannels(i)));
      }
    }
    if (activeGenres.size > 0) {
      if (genreExclude) {
        items = items.filter((i) => {
          const genres = getNormalizedGenres(i);
          const hasNone = genres.length === 0;
          if (activeGenres.has(FILTER_NONE_KEY) && hasNone) return false;
          if (hasNone) return true;
          return !genres.some((g) => activeGenres.has(g));
        });
      } else {
        items = items.filter((i) => {
          const genres = getNormalizedGenres(i);
          const hasNone = genres.length === 0;
          if (activeGenres.has(FILTER_NONE_KEY) && hasNone) return true;
          return genres.some((g) => activeGenres.has(g));
        });
      }
    }
    if (activeAudioLanguages.size > 0) {
      if (audioLanguageExclude) {
        items=items.filter(i=>!activeAudioLanguages.has(getAudioLanguageSimple(i)));
      } else {
        items=items.filter(i=>activeAudioLanguages.has(getAudioLanguageSimple(i)));
      }
    }
    if (isScoreEnabled()) {
      items=items.filter(i=>{
        const score = Number(i?.quality?.score);
        const hasScore = Number.isFinite(score);
        const inRange = hasScore && score >= scoreMin && score <= scoreMax;
        if (includeNoScore) return inRange || !hasScore;
        return inRange;
      });
    }
    return applySearch(items, q);
  }

  // Base for filter rendering: all active filters applied EXCEPT the one being rendered
  // + settings-level visibility always applied + search always applied
  function baseItems(except) {
    const q = getSearchQuery();
    let items=allItems;
    if (!enableMovies)     items=items.filter(i=>i.type!=='movie');
    if (!enableSeries)     items=items.filter(i=>i.type!=='tv');
    if (enabledCategories)   items=items.filter(i=>_catVisible(i.category));
    if (activeType!=='all')  items=items.filter(i=>i.type===activeType);
    if (except!=='group'  && activeGroup!=='all') items=items.filter(i=>i.group===activeGroup);
    if (except!=='folder' && activeFolders.size > 0) {
      if (folderExclude) items = items.filter(i => !activeFolders.has(i.category || FILTER_NONE_KEY));
      else items = items.filter(i => activeFolders.has(i.category || FILTER_NONE_KEY));
    }
    if (except!=='provider' && activeProviders.size > 0) {
      items = items.filter(_matchesProviderFilters);
    }
    if (except!=='resolution' && activeResolutions.size > 0) {
      if (resolutionExclude) {
        items=items.filter(i=>!activeResolutions.has(getNormalizedResolution(i)));
      } else {
        items=items.filter(i=>activeResolutions.has(getNormalizedResolution(i)));
      }
    }
    if (except!=='codec' && activeCodecs.size > 0) {
      if (videoCodecExclude) {
        items=items.filter(i=>!activeCodecs.has(getNormalizedVideoCodec(i)));
      } else {
        items=items.filter(i=>activeCodecs.has(getNormalizedVideoCodec(i)));
      }
    }
    if (except!=='audioCodec' && activeAudioCodecs.size > 0) {
      if (audioCodecExclude) {
        items=items.filter(i=>!activeAudioCodecs.has(getNormalizedAudioCodec(i)));
      } else {
        items=items.filter(i=>activeAudioCodecs.has(getNormalizedAudioCodec(i)));
      }
    }
    if (except!=='audioChannels' && activeAudioChannels.size > 0) {
      if (audioChannelsExclude) {
        items = items.filter((i) => !activeAudioChannels.has(getNormalizedAudioChannels(i)));
      } else {
        items = items.filter((i) => activeAudioChannels.has(getNormalizedAudioChannels(i)));
      }
    }
    if (except!=='genre' && activeGenres.size > 0) {
      if (genreExclude) {
        items = items.filter((i) => {
          const genres = getNormalizedGenres(i);
          const hasNone = genres.length === 0;
          if (activeGenres.has(FILTER_NONE_KEY) && hasNone) return false;
          if (hasNone) return true;
          return !genres.some((g) => activeGenres.has(g));
        });
      } else {
        items = items.filter((i) => {
          const genres = getNormalizedGenres(i);
          const hasNone = genres.length === 0;
          if (activeGenres.has(FILTER_NONE_KEY) && hasNone) return true;
          return genres.some((g) => activeGenres.has(g));
        });
      }
    }
    if (except!=='audioLanguage' && activeAudioLanguages.size > 0) {
      if (audioLanguageExclude) {
        items=items.filter(i=>!activeAudioLanguages.has(getAudioLanguageSimple(i)));
      } else {
        items=items.filter(i=>activeAudioLanguages.has(getAudioLanguageSimple(i)));
      }
    }
    if (isScoreEnabled() && except!=='quality') {
      items=items.filter(i=>{
        const score = Number(i?.quality?.score);
        const hasScore = Number.isFinite(score);
        const inRange = hasScore && score >= scoreMin && score <= scoreMax;
        if (includeNoScore) return inRange || !hasScore;
        return inRange;
      });
    }
    return applySearch(items, q);
  }

  // ── RECOMMENDATIONS ─────────────────────────────────
  const RECOMMENDATION_TYPES = ['quality', 'space', 'languages', 'series', 'data'];
  const RECOMMENDATION_PRIORITIES = ['high', 'medium', 'low'];

  function recText(obj) {
    if (!obj || typeof obj !== 'object') return '';
    const lang = CURRENT_LANG === 'en' ? 'en' : 'fr';
    return obj[lang] || obj.fr || obj.en || '';
  }

  function recTypeLabel(type) {
    return t('recommendations.types.' + type);
  }

  function recPriorityLabel(priority) {
    return t('recommendations.priorities.' + priority);
  }

  function toggleRecommendationTypeFilter(type) {
    if (recommendationTypeFilters.has(type)) recommendationTypeFilters.delete(type);
    else recommendationTypeFilters.add(type);
    if (currentTab === 'recommendations') renderRecommendationsPanel();
    if (currentTab === 'stats') window.MMLStats.renderStatsPanel();
    updateGlobalResetButtons();
  }

  function toggleRecommendationPriorityFilter(priority) {
    if (recommendationPriorityFilters.has(priority)) recommendationPriorityFilters.delete(priority);
    else recommendationPriorityFilters.add(priority);
    if (currentTab === 'recommendations') renderRecommendationsPanel();
    if (currentTab === 'stats') window.MMLStats.renderStatsPanel();
    updateGlobalResetButtons();
  }

  function setRecommendationSort(key) {
    const [sortKey, sortDir] = String(key || 'priority:desc').split(':');
    recommendationSort = { key: sortKey || 'priority', dir: sortDir === 'asc' ? 'asc' : 'desc' };
    renderRecommendationsPanel();
  }

  function visibleRecommendations() {
    if (!isRecommendationsEnabled() || !recommendationsDoc) return [];
    const mediaById = new Map(allItems.map((item) => [String(item.id || ''), item]));
    const visibleMediaIds = new Set(filterItems().map((item) => String(item.id || '')));
    return (recommendationsDoc.items || []).filter((rec) => {
      const mid = String(rec?.media_ref?.id || '');
      if (!mid || !mediaById.has(mid) || !visibleMediaIds.has(mid)) return false;
      if (recommendationTypeFilters.size && !recommendationTypeFilters.has(rec.recommendation_type)) return false;
      if (recommendationPriorityFilters.size && !recommendationPriorityFilters.has(rec.priority)) return false;
      return true;
    });
  }

  function recMedia(rec, mediaById) {
    return mediaById.get(String(rec?.media_ref?.id || '')) || {};
  }

  function recMediaTitle(rec, media) {
    return media?.title || rec?.display?.title || '-';
  }

  function recMediaYear(rec, media) {
    return media?.year || rec?.display?.year || '';
  }

  function recScore(media) {
    const score = Number(media?.quality?.score);
    return Number.isFinite(score) ? Math.round(score) : '';
  }

  function recSizeBytes(media) {
    return Number(media?.size_b || 0);
  }

  function recSizeLabel(media) {
    return recSizeBytes(media) ? fmtSize(recSizeBytes(media)) : '';
  }

  function recSizeGb(media) {
    const sizeGb = Number(media?.size_gb);
    if (Number.isFinite(sizeGb) && sizeGb > 0) return Math.round(sizeGb * 100) / 100;
    const sizeB = recSizeBytes(media);
    return sizeB ? Math.round((sizeB / (1024 * 1024 * 1024)) * 100) / 100 : '';
  }

  function recResolution(media) {
    return media?.resolution ? getFilterDisplayValue(media.resolution) : '';
  }

  function recCompactInfo(media) {
    return [
      recScore(media) !== '' ? t('recommendations.info_score', { value: recScore(media) }) : '',
      recSizeLabel(media),
      recResolution(media),
      media?.codec ? getFilterDisplayValue(media.codec) : '',
      media?.audio_codec ? getAudioCodecLabel(media) : '',
      media?.audio_languages_simple ? getAudioLanguageSimpleDisplay(media.audio_languages_simple) : '',
    ].filter(Boolean).join(' • ');
  }

  function renderRecommendationFilterButtons(values, activeSet, fnName, labelPrefix, classPrefix) {
    return values.map((value) => {
      const active = activeSet.has(value) ? ' active' : '';
      const extra = classPrefix ? ' '+classPrefix+' '+classPrefix+'-'+value : '';
      return '<button class="rec-filter-btn'+extra+active+'" onclick="'+fnName+'(\''+escH(value)+'\')">'+escH(labelPrefix(value))+'</button>';
    }).join('');
  }

  function recSortValue(rec, media, key) {
    if (key === 'priority') return { high: 3, medium: 2, low: 1 }[rec.priority] ?? 0;
    if (key === 'type') return recTypeLabel(rec.recommendation_type || 'data').toLowerCase();
    if (key === 'title') return recMediaTitle(rec, media).toLowerCase();
    if (key === 'score') return Number.isFinite(Number(media?.quality?.score)) ? Number(media.quality.score) : -1;
    if (key === 'size') return recSizeBytes(media);
    if (key === 'resolution') return recResolution(media).toLowerCase();
    return '';
  }

  function sortedRecommendations(recs, mediaById) {
    const dir = recommendationSort.dir === 'desc' ? -1 : 1;
    const key = recommendationSort.key || 'priority';
    return recs.slice().sort((a, b) => {
      const ma = recMedia(a, mediaById);
      const mb = recMedia(b, mediaById);
      const av = recSortValue(a, ma, key);
      const bv = recSortValue(b, mb, key);
      let cmp = 0;
      if (typeof av === 'number' && typeof bv === 'number') cmp = av - bv;
      else cmp = String(av).localeCompare(String(bv), CURRENT_LANG === 'en' ? 'en' : 'fr', { sensitivity: 'base' });
      if (cmp !== 0) return cmp * dir;
      return recMediaTitle(a, ma).localeCompare(recMediaTitle(b, mb), CURRENT_LANG === 'en' ? 'en' : 'fr', { sensitivity: 'base' });
    });
  }

  function recSortControls() {
    const options = [
      ['priority:desc', t('recommendations.sort_options.priority_desc')],
      ['priority:asc', t('recommendations.sort_options.priority_asc')],
      ['type:desc', t('recommendations.sort_options.type_desc')],
      ['type:asc', t('recommendations.sort_options.type_asc')],
      ['title:asc', t('recommendations.sort_options.title_asc')],
      ['title:desc', t('recommendations.sort_options.title_desc')],
      ['score:desc', t('recommendations.sort_options.score_desc')],
      ['score:asc', t('recommendations.sort_options.score_asc')],
      ['size:desc', t('recommendations.sort_options.size_desc')],
      ['size:asc', t('recommendations.sort_options.size_asc')],
      ['resolution:desc', t('recommendations.sort_options.resolution_desc')],
      ['resolution:asc', t('recommendations.sort_options.resolution_asc')],
    ].map(([key, label]) => {
      const selected = (recommendationSort.key + ':' + recommendationSort.dir) === key ? ' selected' : '';
      return '<option value="'+escH(key)+'"'+selected+'>'+escH(label)+'</option>';
    }).join('');
    return '<div class="rec-filter-group rec-sort-group"><div class="rec-filter-label">'+t('recommendations.sort_by')+'</div>'
      + '<select class="tab-sort-select rec-sort-select" onchange="setRecommendationSort(this.value)">'+options+'</select></div>';
  }

  function exportRecommendationsCSV() {
    if (!isRecommendationsEnabled() || !recommendationsDoc) return;
    const mediaById = new Map(allItems.map((item) => [String(item.id || ''), item]));
    const recs = sortedRecommendations(visibleRecommendations(), mediaById);
    const headers = [
      'priority',
      'type',
      'title',
      'year',
      'score',
      'size_gb',
      'resolution',
      'video_codec',
      'audio_codec',
      'audio_channels',
      'audio_language_group',
      'audio_languages',
      'subtitle_languages',
      'message',
      'action',
    ];
    const rows = recs.map((rec) => {
      const media = recMedia(rec, mediaById);
      return [
        csvC(rec.priority || ''),
        csvC(rec.recommendation_type || ''),
        csvC(recMediaTitle(rec, media)),
        csvC(recMediaYear(rec, media)),
        csvC(recScore(media)),
        csvC(recSizeGb(media)),
        csvC(media.resolution || ''),
        csvC(media.codec || ''),
        csvC(media.audio_codec || ''),
        csvC(media.audio_channels || ''),
        csvC(media.audio_languages_simple || ''),
        csvC(Array.isArray(media.audio_languages) ? media.audio_languages.join(', ') : (media.audio_languages || '')),
        csvC(Array.isArray(media.subtitle_languages) ? media.subtitle_languages.join(', ') : (media.subtitle_languages || '')),
        csvC(recText(rec.message)),
        csvC(recText(rec.suggested_action)),
      ];
    });
    const csv = [headers.join(';'), ...rows.map((row) => row.join(';'))].join('\n');
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const now = new Date();
    a.href = url;
    a.download = 'mymedialibrary-recommendations-' + now.toISOString().slice(0,10) + '_' + now.toTimeString().slice(0,8).replace(/:/g,'-') + '.csv';
    a.click();
    URL.revokeObjectURL(url);
  }

  function renderRecommendationsPanel() {
    const host = document.getElementById('recommendationsContent');
    if (!host) return;
    if (!isRecommendationsEnabled()) {
      host.innerHTML = '';
      return;
    }
    const allRecItems = recommendationsDoc?.items || [];
    if (recommendationsDoc?.error) {
      host.innerHTML = '<div class="empty rec-empty"><p>'+t('recommendations.empty_error')+'</p></div>';
      return;
    }
    if (!recommendationsDoc || !allRecItems.length) {
      host.innerHTML = '<div class="empty rec-empty"><p>'+t('recommendations.empty_run_scan')+'</p></div>';
      return;
    }
    const recs = visibleRecommendations();
    const counts = {
      total: recs.length,
      high: recs.filter((r) => r.priority === 'high').length,
      quality: recs.filter((r) => r.recommendation_type === 'quality').length,
      space: recs.filter((r) => r.recommendation_type === 'space').length,
      languages: recs.filter((r) => r.recommendation_type === 'languages').length,
      series: recs.filter((r) => r.recommendation_type === 'series').length,
      data: recs.filter((r) => r.recommendation_type === 'data').length,
    };
    const kpis = [
      ['total', t('recommendations.kpis.total')],
      ['high', t('recommendations.kpis.high')],
      ['quality', t('recommendations.kpis.quality')],
      ['space', t('recommendations.kpis.space')],
      ['languages', t('recommendations.kpis.languages')],
      ['series', t('recommendations.kpis.series')],
      ['data', t('recommendations.kpis.data')],
    ].map(([key, label]) => '<div class="rec-kpi"><div class="rec-kpi-value">'+counts[key]+'</div><div class="rec-kpi-label">'+escH(label)+'</div></div>').join('');

    const filters = '<div class="rec-filters">'
      + '<div class="rec-filter-group rec-filter-priority"><div class="rec-filter-label">'+t('recommendations.filters.priority')+'</div><div class="rec-filter-row">'
      + renderRecommendationFilterButtons(RECOMMENDATION_PRIORITIES, recommendationPriorityFilters, 'toggleRecommendationPriorityFilter', recPriorityLabel, 'rec-priority-filter')
      + '</div></div>'
      + '<div class="rec-filter-group rec-filter-type"><div class="rec-filter-label">'+t('recommendations.filters.type')+'</div><div class="rec-filter-row">'
      + renderRecommendationFilterButtons(RECOMMENDATION_TYPES, recommendationTypeFilters, 'toggleRecommendationTypeFilter', recTypeLabel, 'provider-pill')
      + '</div></div>'
      + recSortControls()
      + '</div>';

    if (!recs.length) {
      host.innerHTML = '<div class="rec-page"><div class="rec-kpis">'+kpis+'</div>'+filters+'<div class="empty rec-empty"><p>'+t('recommendations.empty_filters')+'</p></div></div>';
      return;
    }
    const mediaById = new Map(allItems.map((item) => [String(item.id || ''), item]));
    const rows = sortedRecommendations(recs, mediaById).map((rec) => {
      const media = recMedia(rec, mediaById);
      const title = recMediaTitle(rec, media);
      const year = recMediaYear(rec, media);
      return '<tr>'
        + '<td><span class="rec-priority rec-priority-'+escH(rec.priority || 'medium')+'">'+escH(recPriorityLabel(rec.priority || 'medium'))+'</span></td>'
        + '<td>'+escH(recTypeLabel(rec.recommendation_type || 'data'))+'</td>'
        + '<td><strong>'+escH(title)+'</strong>'+(year ? '<span class="rec-muted"> ('+escH(year)+')</span>' : '')+'<div class="rec-info">'+escH(recCompactInfo(media))+'</div></td>'
        + '<td>'+escH(recText(rec.message))+'</td>'
        + '<td>'+escH(recText(rec.suggested_action))+'</td>'
        + '</tr>';
    }).join('');
    host.innerHTML = '<div class="rec-page"><div class="rec-kpis">'+kpis+'</div>'+filters
      + '<div class="rec-table-wrap"><table class="rec-table"><thead><tr>'
      + '<th>'+t('recommendations.table.priority')+'</th>'
      + '<th>'+t('recommendations.table.type')+'</th>'
      + '<th>'+t('recommendations.table.media')+'</th>'
      + '<th>'+t('recommendations.table.recommendation')+'</th>'
      + '<th>'+t('recommendations.table.action')+'</th>'
      + '</tr></thead><tbody>'+rows+'</tbody></table></div></div>';
  }

  // ── TABS ─────────────────────────────────────────────
  function switchTab(tab) {
    if (tab === 'recommendations' && !isRecommendationsEnabled()) tab = 'library';
    currentTab=tab;
    // Show/hide tab-bar controls depending on active tab
    const lc = document.getElementById('libraryControls');
    if (lc) lc.style.display = tab==='library' ? '' : 'none';
    const rc = document.getElementById('recommendationsControls');
    if (rc) rc.style.display = tab==='recommendations' ? '' : 'none';
    // Show/hide sort section in sidebar
    const ss = document.getElementById('sortSection');
    if (ss) ss.style.display = (tab==='library' && currentView==='grid') ? '' : 'none';
    // Panels
    document.getElementById('libraryPanel').classList.toggle('active',tab==='library');
    document.getElementById('statsPanel').classList.toggle('active',tab==='stats');
    document.getElementById('recommendationsPanel')?.classList.toggle('active',tab==='recommendations');
    // Nav buttons
    ['navLibrary','navStats','navRecommendations'].forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      const t = id.replace('navLibrary','library').replace('navStats','stats').replace('navRecommendations','recommendations');
      el.classList.toggle('active', t === tab);
    });
    if (tab==='library') render();
    else if (tab==='stats') window.MMLStats.renderStatsPanel();
    else if (tab==='recommendations') renderRecommendationsPanel();
    saveState();
  }

  // ── RENDER LIBRARY ───────────────────────────────────
  function render() {
    let items=filterItems();
    renderStats(items);
    const c=document.getElementById('library');
    if (!items.length) {
      c.className='';
      if (window.MMLState?.isLibraryMissing) {
        c.innerHTML='<div class="empty"><p>'+t('library.not_found')+'</p><small>'+t('library.run_scan')+'</small></div>';
      } else {
        c.innerHTML='<div class="empty"><p>'+t('library.no_results')+'</p><small>'+t('library.no_results_hint')+'</small></div>';
      }
      return;
    }
    if (currentView==='grid') { c.className=''; c.innerHTML=sortItems(items).map(cardHTML).join(''); }
    else { c.className='table-view'; c.innerHTML=tableHTML(sortItemsTable(items)); }
  }

  function getSidebarSortValue() {
    return document.getElementById('sortSelect')?.value || 'title-asc';
  }

  function parseQualityScore(item) {
    const raw = item?.quality?.score;
    if (raw === null || raw === undefined) return null;
    if (typeof raw === 'string' && raw.trim() === '') return null;
    const score = Number(raw);
    return Number.isFinite(score) ? score : null;
  }

  function compareBySidebarSort(a,b,v) {
    if (!isScoreEnabled() && (v === 'score-asc' || v === 'score-desc')) {
      v = 'title-asc';
    }
    if (v === 'score-asc' || v === 'score-desc') {
      const aScore = parseQualityScore(a);
      const bScore = parseQualityScore(b);
      const aHasScore = aScore !== null;
      const bHasScore = bScore !== null;
      if (!aHasScore && !bHasScore) return 0;
      if (!aHasScore) return 1;
      if (!bHasScore) return -1;
      return v === 'score-desc' ? bScore - aScore : aScore - bScore;
    }
    switch(v){
      case 'title-asc':    return (a.title||'').localeCompare(b.title||'');
      case 'title-desc':   return (b.title||'').localeCompare(a.title||'');
      case 'year-desc':    return (b.year||'0')-(a.year||'0');
      case 'year-asc':     return (a.year||'9999')-(b.year||'9999');
      case 'size-desc':    return (b.size_b||0)-(a.size_b||0);
      case 'size-asc':     return (a.size_b||0)-(b.size_b||0);
      case 'added-desc':   return (b.added_ts||0)-(a.added_ts||0);
      case 'category-asc': return (a.category||'').localeCompare(b.category||'');
      default:             return 0;
    }
  }

  function sortItems(items) {
    const v=getSidebarSortValue();
    return [...items].sort((a,b)=>compareBySidebarSort(a,b,v));
  }

  function sortByCol(col){
    if (!isScoreEnabled() && col === 'quality') return;
    tSortDir=tSortCol===col?tSortDir*-1:1; tSortCol=col; render();
  }

  function sortItemsTable(items) {
    if (!tSortCol) return sortItems(items);
    const col = tSortCol;
    const dir = tSortDir;
    return [...items].sort((a,b)=>{
      switch(col){
        case 'title':    return (a.title||'').localeCompare(b.title||'')*dir;
        case 'year':     return ((a.year||'0')-(b.year||'0'))*dir;
        case 'size':     return ((a.size_b||0)-(b.size_b||0))*dir;
        case 'files':    return ((a.file_count||0)-(b.file_count||0))*dir;
        case 'added':    return ((a.added_ts||0)-(b.added_ts||0))*dir;
        case 'quality': {
          if (!isScoreEnabled()) return 0;
          const aScore = parseQualityScore(a);
          const bScore = parseQualityScore(b);
          if (aScore === null && bScore === null) return 0;
          if (aScore === null) return 1;
          if (bScore === null) return -1;
          return (aScore-bScore)*dir;
        }
        case 'category': return (a.category||'').localeCompare(b.category||'')*dir;
        case 'group':    return (a.group||'').localeCompare(b.group||'')*dir;
      }
      return 0;
    });
  }

  function posterBlock(item) {
    if (item.poster) return '<div class="tl-poster"><img src="'+escH(item.poster)+'" alt="" loading="lazy"/></div>';
    return '<div class="tl-poster"><div class="tl-poster-ph">🎬</div></div>';
  }
  function providersBlock(item) {
    if (!enableSeerr) return '';
    const visP = _itemVisProviders(item);
    const hasProv = getEnabledProvidersForItem(item).length > 0;
    if (!visP.length) {
      if (!hasProv) {
        if (item.providers_fetched !== true) return '';
        return '<div class="tl-providers"><div class="tl-provider tl-provider-none" title="'+t('library.no_provider')+'">🚫</div></div>';
      }
      return ''; // has providers but all hidden by visibility prefs
    }
    const maxVisibleProviders = 5;
    const shown = visP.slice(0, maxVisibleProviders);
    const remaining = visP.length - shown.length;
    return '<div class="tl-providers">'
      + shown.map(p => {
          const name=_pname(p), logo=_plogo(p);
          return logo
            ? '<div class="tl-provider" title="'+escH(name)+'"><img src="'+escH(logo)+'" alt="'+escH(name)+'"/></div>'
            : '<span class="tl-provider-name">'+escH(name)+'</span>';
        }).join('')
      + (remaining > 0 ? '<span class="tl-provider-name" title="'+escH(t('stats.others'))+'">+'+remaining+'</span>' : '')
      + '</div>';
  }
  function cardHTML(item) {
    const plotText = (item.plot||'').trim();
    const qualityBadge = qualityBadgeHTML(item);
    const infoParts = [];
    if (item.group) infoParts.push('<span class="tl-cat tl-pill-ellipsis" style="color:#a78bfa">'+escH(item.group)+'</span>');
    infoParts.push('<span class="tl-size">'+escH(item.size)+'</span>');
    if (item.type==='tv'&&item.season_count) infoParts.push('<span class="tl-cat">'+item.season_count+'S</span>');
    if (item.type==='tv'&&item.episode_count) infoParts.push('<span class="tl-cat">'+item.episode_count+'ep</span>');
    if (item.type!=='tv'&&item.file_count!==undefined&&item.file_count!==1) {
      infoParts.push('<span class="tl-cat">'+(item.file_count>1?t('library.files_pl',{n:item.file_count}):t('library.files',{n:item.file_count}))+'</span>');
    }
    return '<div class="tl-card"'+(plotText?' data-plot="'+escH(plotText)+'"':'')+'>'
      +(qualityBadge?'<div class="tl-quality">'+qualityBadge+'</div>':'')
      + posterBlock(item)
      +'<div class="tl-body">'
        +'<div class="tl-title" title="'+escH(item.title)+'">'+escH(item.title)+'</div>'
        +'<div class="tl-meta">'
          +'<div class="tl-meta-row compact">'
            +(item.year?'<span class="tl-cat">'+escH(String(item.year))+'</span>':'')
            +'<span class="tl-cat">'+escH(item.category)+'</span>'
            +(item.resolution?'<span class="res-badge res-'+escH(item.resolution)+'">'+escH(item.resolution)+'</span>':'')
          +'</div>'
          +(infoParts.length ? '<div class="tl-meta-row tl-meta-row-ellipsis">'+infoParts.join('')+'</div>' : '')
        +'</div>'
        + providersBlock(item)
      +'</div>'
    +'</div>';
  }

  function th(col,label){ const s=tSortCol===col,i=s?(tSortDir===1?' &uarr;':' &darr;'):' &updownarrow;'; return '<th class="'+(s?'sorted':'')+'" onclick="sortByCol(\''+col+'\')">'+label+'<span class="si">'+i+'</span></th>'; }

  function tblProvidersHTML(item) {
    if (!enableSeerr) return '-';
    const hasProv = getEnabledProvidersForItem(item).length > 0;
    if (!hasProv) {
      if (item.providers_fetched !== true) return '-';
      return '<span title="'+t('library.no_provider')+'" style="font-size:14px">🚫</span>';
    }
    return '<div class="tbl-providers">'
      +_itemVisProviders(item).map(p=>{
        const name=_pname(p), logo=_plogo(p);
        return logo
          ?'<div class="tbl-provider" title="'+escH(name)+'"><img src="'+escH(logo)+'" alt="'+escH(name)+'"/></div>'
          :'<span class="tbl-provider-name">'+escH(name)+'</span>';
      }).join('')+'</div>';
  }
  function tableHTML(items) {
    const hg=items.some(i=>i.group);
    const hp=items.some(i=>i.poster||getEnabledProvidersForItem(i).length);
    const rows=items.map(item=>{
      // Mobile info cell: title + meta badges
      const mobileInfo = '<td class="col-mobile-info">'
        +'<div style="font-weight:600;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%">'+escH(item.title)+'</div>'
        +'<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;align-items:center;max-width:100%;overflow:hidden">'
          +(item.year?'<span class="tl-cat">'+escH(String(item.year))+'</span>':'')
          +'<span class="cat-badge">'+escH(item.category)+'</span>'
          +(qualityBadgeHTML(item, 'quality-badge-inline') || '')
          +(item.resolution?'<span class="res-badge res-'+escH(item.resolution)+'">'+escH(item.resolution)+'</span>':'')
          +(item.hdr?'<span class="badge badge-hdr">HDR</span>':'')
          +(item.codec?'<span class="badge badge-codec">'+escH(item.codec)+'</span>':'')
        +'</div>'
        +'<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;align-items:center;max-width:100%;overflow:hidden">'
          +'<span style="font-size:11px;color:var(--muted)">'+escH(item.size)+'</span>'
          +(item.type==='tv'&&item.season_count?'<span style="font-size:11px;color:var(--muted)">'+item.season_count+'S / '+item.episode_count+'Ep</span>':'')
          +(item.added_at?'<span style="font-size:11px;color:var(--muted)">'+fmtDate(item.added_at)+'</span>':'')
        +'</div>'
        +(()=>{ const p=tblProvidersHTML(item); return p?'<div style="margin-top:4px">'+p+'</div>':''; })()
        +'</td>';
      return '<tr>'
        +(hp?'<td class="col-poster">'+(item.poster?'<img src="'+escH(item.poster)+'" alt="" loading="lazy"/>':'<div class="ph">🎬</div>')+'</td>':'')
        +mobileInfo
        +'<td class="col-title">'+escH(item.title)+'</td>'
        +'<td class="col-year">'+escH(String(item.year||'-'))+'</td>'
        +(hg?'<td class="col-group">'+escH(item.group||'-')+'</td>':'')
        +'<td><span class="cat-badge">'+escH(item.category)+'</span></td>'
        +(isScoreEnabled() ? '<td>'+(qualityBadgeHTML(item, 'quality-badge-inline') || '-')+'</td>' : '')
        +'<td>'+(item.resolution?'<span class="res-badge res-'+escH(item.resolution)+'">'+escH(item.resolution)+'</span>':'-')+(item.hdr?' <span class="badge badge-hdr">HDR</span>':'')+'</td>'
        +'<td>'+(item.codec?'<span class="badge badge-codec">'+escH(item.codec)+'</span>':'-')+'</td>'
        +'<td>'+escH(getAudioCodecLabel(item))+'</td>'
        +'<td>'+escH(getAudioLanguageSimpleDisplay(getAudioLanguageSimple(item)))+'</td>'
        +'<td class="col-size">'+escH(item.size)+'</td>'
        +'<td class="col-files">'+(item.type==='tv'?(item.season_count||'-')+' S / '+(item.episode_count||'-')+' Ep':item.file_count!==undefined?(item.file_count>1?t('library.files_pl',{n:item.file_count}):t('library.files',{n:item.file_count})):'-')+'</td>'
        +'<td class="col-date">'+(item.added_at?fmtDate(item.added_at):'-')+'</td>'
        +(hp?'<td class="col-providers">'+tblProvidersHTML(item)+'</td>':'')
        +'</tr>';
    }).join('');
    return '<table class="media-table"><thead><tr>'
      +(hp?'<th style="width:44px"></th>':'')
      +th('title',t('table.title'))+th('year',t('table.year'))
      +(hg?th('group',t('table.group')):'')
      +th('category',t('table.category'))
      +(isScoreEnabled() ? th('quality',t('table.quality')) : '')
      +'<th>'+t('table.resolution')+'</th><th>'+t('table.codec')+'</th>'
      +'<th>'+t('table.audio_codec')+'</th><th>'+t('table.audio_languages')+'</th>'
      +th('size',t('table.size'))+th('files',t('table.files'))+th('added',t('table.added'))
      +(hp?'<th>'+t('table.streaming')+'</th>':'')
      +'</tr></thead><tbody>'+rows+'</tbody></table>';
  }

  // ── EXPORT CSV ───────────────────────────────────────
  function exportCSV() {
    const items=filterItems();
    const hg=items.some(i=>i.group);
    const includeScore = isScoreEnabled();
    const headers=[
      t('table.title'), t('table.year'), hg ? t('table.group') : null, t('table.category'),
      includeScore ? 'quality_score' : null,
      includeScore ? 'quality_level' : null,
      includeScore ? 'quality_video' : null,
      includeScore ? 'quality_audio' : null,
      includeScore ? 'quality_languages' : null,
      includeScore ? 'quality_size' : null,
      t('table.resolution'), 'HDR', t('table.codec'), t('table.audio_codec'),
      t('table.audio_languages')+' (simple)', t('table.audio_languages')+' (raw)', 'Runtime (min)',
      t('table.size'), 'Size (B)', t('table.files'), t('table.added'), t('table.streaming')
    ].filter(Boolean);
    const rows=items.map(i=>[
      csvC(i.title),csvC(i.year||''),
      hg?csvC(i.group||''):null,
      csvC(i.category),
      includeScore ? (Number.isFinite(Number(i.quality?.score)) ? Math.round(Number(i.quality.score)) : '') : null,
      includeScore ? (Number.isFinite(Number(i.quality?.score)) ? getItemQualityLevel(i) : '') : null,
      includeScore ? (i.quality?.video ?? '') : null,
      includeScore ? (i.quality?.audio ?? '') : null,
      includeScore ? (i.quality?.languages ?? '') : null,
      includeScore ? (i.quality?.size ?? '') : null,
      csvC(i.resolution||''),
      i.hdr?'Oui':'Non',
      csvC(i.codec||''),
      csvC(getAudioCodecLabel(i)),
      csvC(getAudioLanguageSimple(i)),
      csvC((i.audio_languages??[]).join(', ')),
      i.runtime_min||'',
      csvC(i.size),i.size_b||0,
      i.type==='tv'?((i.season_count||'')+' S / '+(i.episode_count||'')+' Ep'):(i.file_count!==undefined?i.file_count:''),
      i.added_at?fmtDate(i.added_at):'',
      csvC(getEnabledProviderNames(i).join(', '))
    ].filter(v=>v!==null));
    const csv=[headers.join(';'),...rows.map(r=>r.join(';'))].join('\n');
    const blob=new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8;'});
    const url=URL.createObjectURL(blob);
    const a=document.createElement('a');
    const now=new Date();
    a.href=url; a.download='mymedialibrary-'+now.toISOString().slice(0,10)+'_'+now.toTimeString().slice(0,8).replace(/:/g,'-')+'.csv';
    a.click(); URL.revokeObjectURL(url);
  }
  function csvC(v){ const s=String(v||''); return s.includes(';')||s.includes('"')||s.includes('\n')?'"'+s.replace(/"/g,'""')+'"':s; }

  // ── VIEW ─────────────────────────────────────────────
  function setView(v, silent) {
    const nextView = (v === 'table') ? 'table' : 'grid';
    if (currentView === nextView) return;
    currentView=nextView;
    document.getElementById('gridBtn').classList.toggle('active',nextView==='grid');
    document.getElementById('tableBtn').classList.toggle('active',nextView==='table');
    // Sort visible only in grid view
    const sortEl = document.getElementById('sortSelect');
    const sortSec = document.getElementById('sortSection');
    if (sortEl) sortEl.style.display = nextView==='grid' ? '' : 'none';
    if (sortSec) sortSec.style.display = nextView==='grid' ? '' : 'none';
    render();
    if (!silent) saveState();
  }

  // ── UTILS ────────────────────────────────────────────
  function fmtDate(iso){ if(!iso)return'-'; return new Date(iso).toLocaleDateString('fr-FR'); }
  const fmtSize = window.MMLCore.fmtSize;
  const escH    = window.MMLCore.escH;
  function escJ(s){ return String(s||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/\r/g,'').replace(/\n/g,' ').replace(/\u2028/g,' ').replace(/\u2029/g,' '); }
  // sanitizeStr: safe for JS string literals inside HTML attributes (onclick, onmouseenter…)
  const sanitizeStr = s => (s||'').replace(/\r?\n/g,' ').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'&quot;').replace(/\u2028/g,' ').replace(/\u2029/g,' ');

  document.getElementById('searchInput').addEventListener('input', function() {
    const btn = document.getElementById('searchClear');
    if (btn) btn.style.display = this.value.length > 0 ? 'block' : 'none';
    onFilter();
  });

  function clearSearch() {
    const inp = document.getElementById('searchInput');
    const btn = document.getElementById('searchClear');
    if (inp) inp.value = '';
    if (btn) btn.style.display = 'none';
    onFilter();
  }

  function onMobileSearchInput(val) {
    const desktop = document.getElementById('searchInput');
    if (desktop) desktop.value = val;
    const btn = document.getElementById('searchClearMobile');
    if (btn) btn.style.display = val.length > 0 ? 'block' : 'none';
    const btnD = document.getElementById('searchClear');
    if (btnD) btnD.style.display = val.length > 0 ? 'block' : 'none';
    onFilter();
  }

  function clearSearchMobile() {
    const mob = document.getElementById('searchInputMobile');
    const desktop = document.getElementById('searchInput');
    const btnM = document.getElementById('searchClearMobile');
    const btnD = document.getElementById('searchClear');
    if (mob) mob.value = '';
    if (desktop) desktop.value = '';
    if (btnM) btnM.style.display = 'none';
    if (btnD) btnD.style.display = 'none';
    onFilter();
  }
  document.getElementById('sortSelect').addEventListener('change', function() {
    render();
    saveState();
  });
  document.getElementById('sortSelectMobile')?.addEventListener('change', function() {
    const desktopSort = document.getElementById('sortSelect');
    if (desktopSort) desktopSort.value = this.value;
    render();
    saveState();
  });



  // ── STATS PANEL (delegated to stats.js) ──────────────
  // window.MMLStats.renderStatsPanel() is now provided by window.MMLStats

  const _DEFAULT_ACCENT = '#7c6aff';

  function _hexToRgba(hex, a) {
    const r=parseInt(hex.slice(1,3),16), g=parseInt(hex.slice(3,5),16), b=parseInt(hex.slice(5,7),16);
    return `rgba(${r},${g},${b},${a})`;
  }
  function applyAccent(color) {
    const r = document.documentElement;
    r.style.setProperty('--accent', color);
    r.style.setProperty('--accent-08', _hexToRgba(color, 0.08));
    r.style.setProperty('--accent-20', _hexToRgba(color, 0.20));
    r.style.setProperty('--accent-40', _hexToRgba(color, 0.40));
    const el = document.getElementById('cfgAccentColor');
    if (el && el.value !== color) el.value = color;
  }
  function resetAccent() {
    const el = document.getElementById('cfgAccentColor');
    if (el) el.value = _DEFAULT_ACCENT;
  }

  function toggleTheme() {
    const html = document.documentElement;
    const isLight = html.getAttribute('data-theme') === 'light';
    const newTheme = isLight ? 'dark' : 'light';
    html.setAttribute('data-theme', newTheme);
    const icon = document.getElementById('themeIcon');
    if (icon) {
      if (newTheme === 'dark') {
        icon.innerHTML = '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>';
      } else {
        icon.innerHTML = '<path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>';
      }
    }
    // Persist to config.json and update in-memory appConfig
    appConfig.ui = appConfig.ui || {};
    appConfig.ui.theme = newTheme;
    saveConfig({ ui: { theme: newTheme } }).catch(() => {
      // Revert on failure
      html.setAttribute('data-theme', isLight ? 'light' : 'dark');
      appConfig.ui.theme = isLight ? 'light' : 'dark';
    });
  }


  function switchYearView(btn, view) {
    const yr = document.getElementById('yearViewYear');
    const dc = document.getElementById('yearViewDecade');
    if (yr) yr.style.display = view==='year'   ? '' : 'none';
    if (dc) dc.style.display = view==='decade' ? '' : 'none';
    const by = document.getElementById('yearBtnYear');
    const bd = document.getElementById('yearBtnDecade');
    if (by) by.classList.toggle('active', view==='year');
    if (bd) bd.classList.toggle('active', view==='decade');
  }

  // ── SCAN ──────────────────────────────────────────────
  let _pollTimer = null;
  let _logOffset = 0;
  let _isScanning = false;

  function setScanControlsState(isScanning) {
    const wasScanning = _isScanning;
    _isScanning = !!isScanning;
    ['scanMainBtn', 'mobileSettingsScanBtn']
      .forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = _isScanning;
      });
    if (!wasScanning && _isScanning) {
      closeMobileScanSheet();
    }
  }

  function triggerScan() {
    if (_isScanning) return;
    closeMobileScanSheet();
    setScanControlsState(true);
    _logOffset = 0;
    openScanLog();

    fetch('/api/scan/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mode: 'default'}),
    })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        if (/already running/i.test(String(data.error))) {
          appendScanLog('[Info] ' + data.error, 'log-line');
          setScanStatus('running');
          setScanControlsState(true);
          startPoll();
          return;
        }
        appendScanLog('[Erreur] ' + data.error, 'log-err');
        setScanStatus('error');
        setScanControlsState(false);
        return;
      }
      startPoll();
    })
    .catch(err => {
      appendScanLog('[Erreur réseau] ' + err, 'log-err');
      setScanStatus('error');
      setScanControlsState(false);
    });
  }

  function startPoll() {
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTimer = setInterval(pollScanStatus, 1200);
  }

  function pollScanStatus() {
    fetch('/api/scan/status')
      .then(r => r.json())
      .then(data => {
        // Append new log lines
        const lines = safeArray(data.log);
        const newLines = lines.slice(_logOffset);
        _logOffset = lines.length;
        newLines.forEach(l => {
          const cls = /error|erreur|exception/i.test(l) ? 'log-err'
                    : /terminé|done|✓/i.test(l)         ? 'log-ok'
                    : 'log-line';
          appendScanLog(l, cls);
        });
        setScanStatus(data.status);
        setScanControlsState(data.status === 'running');
        if (data.status !== 'running') {
          clearInterval(_pollTimer);
          _pollTimer = null;
          // Reload library.json on success
          if (data.status === 'done') {
            setTimeout(() => loadLibrary(), 800);
            setTimeout(() => closeScanLog(), 5000);
          }
        }
      })
      .catch(() => { setScanControlsState(false); });
  }

  function openScanLog() {
    const panel = document.getElementById('scanLogPanel');
    panel.classList.remove('viewer');
    document.getElementById('scanLogTitle').textContent = 'Scan';
    document.getElementById('scanLogBody').innerHTML = '';
    setScanStatus('running');
    panel.classList.add('open');
  }

  function closeScanLog() {
    const panel = document.getElementById('scanLogPanel');
    panel.classList.remove('open');
    panel.classList.remove('viewer');
  }

  function openLogViewer() {
    const panel = document.getElementById('scanLogPanel');
    const body = document.getElementById('scanLogBody');
    document.getElementById('scanLogTitle').textContent = t('scan.log_title');
    body.innerHTML = '<div class="log-line" style="color:var(--muted)">'+t('scan.log_loading')+'</div>';
    setScanStatus('');
    panel.classList.add('viewer');
    panel.classList.add('open');
    fetch('/api/scan/log')
      .then(r => r.text())
      .then(txt => {
        body.innerHTML = '';
        txt.split('\n').forEach(line => {
          if (!line) return;
          const el = document.createElement('div');
          el.className = line.includes('[ERROR]') ? 'log-err'
                       : line.includes('[WARNING]') ? 'log-line'
                       : line.includes('✓') || line.includes('terminé') ? 'log-ok'
                       : 'log-line';
          el.textContent = line;
          body.appendChild(el);
        });
        body.scrollTop = body.scrollHeight;
      })
      .catch(() => { body.innerHTML = '<div class="log-err">'+t('scan.log_error')+'</div>'; });
  }

  function appendScanLog(line, cls) {
    const body = document.getElementById('scanLogBody');
    const el = document.createElement('div');
    el.className = cls || 'log-line';
    el.textContent = line;
    body.appendChild(el);
    body.scrollTop = body.scrollHeight;
  }

  function setScanStatus(status) {
    const dot = document.getElementById('scanStatusDot');
    dot.className = 'scan-status-dot ' + (status || '');
    const title = document.getElementById('scanLogTitle');
    const suffix = status === 'running' ? t('scan.status_running')
                 : status === 'done'    ? t('scan.status_done')
                 : status === 'error'   ? t('scan.status_error')
                 : '';
    title.textContent = 'Scan' + suffix;
  }

  function syncScanState() {
    fetch('/api/scan/status')
      .then(r => r.json())
      .then(data => {
        const running = data?.status === 'running';
        setScanControlsState(running);
        if (running) startPoll();
      })
      .catch(() => setScanControlsState(false));
  }

  // ── CURVE PERIOD SWITCH ──────────────────────────────

  // ── MOBILE NAV ───────────────────────────────────────
  let currentMobileTab = 'library';
  let mobileScanSheetOpen = false;

  function openMobileScanSheet() {
    if (_isScanning) return;
    mobileScanSheetOpen = true;
    document.getElementById('mobileScanSheet')?.classList.add('open');
  }

  function closeMobileScanSheet() {
    mobileScanSheetOpen = false;
    document.getElementById('mobileScanSheet')?.classList.remove('open');
  }

  function closeMobileScanSheetIfBackdrop(event) {
    if (event.target === event.currentTarget) closeMobileScanSheet();
  }

  function isMobile() { return window.innerWidth <= 768; }

  let mobileFiltersOpen = false;

  function toggleMobileFilters() {
    mobileFiltersOpen = !mobileFiltersOpen;
    const panel = document.getElementById('mobileFiltersPanel');
    const btn   = document.getElementById('mobileFilterBtn');
    if (panel) panel.classList.toggle('open', mobileFiltersOpen);
    if (btn)   btn.style.color = mobileFiltersOpen ? 'var(--accent)' : '';
    if (mobileFiltersOpen) syncMobileFilters();
  }

  function closeMobileFilters() {
    mobileFiltersOpen = false;
    const panel = document.getElementById('mobileFiltersPanel');
    const btn   = document.getElementById('mobileFilterBtn');
    if (panel) panel.classList.remove('open');
    if (btn)   btn.style.color = '';
  }

  function switchMobileTab(tab) {
    if (tab === 'recommendations' && !isRecommendationsEnabled()) tab = 'library';
    currentMobileTab = tab;
    closeMobileFilters();
    // Update nav buttons
    ['library','stats','recommendations'].forEach(t => {
      const btn = document.getElementById('mnav' + t.charAt(0).toUpperCase() + t.slice(1));
      if (btn) btn.classList.toggle('active', t === tab);
    });
    // Show/hide panels
    ['libraryPanel','statsPanel','recommendationsPanel'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.remove('active');
    });
    const el = document.getElementById(tab + 'Panel');
    if (el) el.classList.add('active');
    currentTab = tab;
    const lc2 = document.getElementById('libraryControls');
    if (lc2) lc2.style.display = tab==='library' ? '' : 'none';
    const rc2 = document.getElementById('recommendationsControls');
    if (rc2) rc2.style.display = tab==='recommendations' ? '' : 'none';
    if (tab === 'library') render();
    else if (tab === 'stats') window.MMLStats.renderStatsPanel();
    else if (tab === 'recommendations') renderRecommendationsPanel();
  }

  function syncMobileFilters() {
    // Sync search input value
    const mSearch = document.getElementById('searchInputMobile');
    const dSearch = document.getElementById('searchInput');
    if (mSearch && dSearch && mSearch.value !== dSearch.value) mSearch.value = dSearch.value;
    const mSort = document.getElementById('sortSelectMobile');
    const dSort = document.getElementById('sortSelect');
    if (mSort && dSort && mSort.value !== dSort.value) mSort.value = dSort.value;
    // Mirror filter sections to mobile panel
    // Mirror pills-based sections only; dropdown sections render directly to both desktop+mobile
    ['storageSection'].forEach(id => {
      const src = document.getElementById(id);
      const dst = document.getElementById(id + 'Mobile');
      if (src && dst) dst.innerHTML = src.innerHTML;
    });
    // Sync stats bar
    const sbSrc = document.getElementById('statsBar');
    document.querySelectorAll('#mobileStatsBar').forEach(el => {
      if (sbSrc) el.innerHTML = sbSrc.innerHTML;
    });
    // Sync type pills
    ['#typeFilterMobile'].forEach(sel => {
      document.querySelectorAll(sel + ' .provider-pill').forEach(p => {
        const t = p.dataset.type || 'all';
        p.classList.toggle('active', activeType==='all' ? !p.dataset.type : t===activeType);
      });
    });
  }

  // ── SETTINGS — delegated to settings.js ──────────────


  // ── LAYOUT TOGGLE ────────────────────────────────────
  

  





  // ── PLOT TOOLTIP ─────────────────────────────────────
  let _tt = null;
  let _ttTimer;
  let _scoreTt = null;

  function showPlot(el, text, delayMs = 400) {
    if (!enablePlot || isMobile()) return;
    if (!_tt) _tt = document.getElementById('plotTooltip');
    if (!text || !_tt) return;
    clearTimeout(_ttTimer);
    _ttTimer = setTimeout(() => {
      _tt.textContent = text;
      _tt.classList.add('visible');
    }, delayMs);
    document.addEventListener('mousemove', _moveTT);
  }

  function hidePlot() {
    clearTimeout(_ttTimer);
    if (_tt) _tt.classList.remove('visible');
    document.removeEventListener('mousemove', _moveTT);
  }

  function _moveTT(e) {
    if (!_tt) return;
    const x = e.clientX + 14, y = e.clientY + 14;
    const maxX = window.innerWidth  - _tt.offsetWidth  - 10;
    const maxY = window.innerHeight - _tt.offsetHeight - 10;
    _tt.style.left = Math.min(x, maxX) + 'px';
    _tt.style.top  = Math.min(y, maxY) + 'px';
  }

  function showQualityTooltip(el, event) {
    if (isMobile()) return;
    hidePlot();
    if (!_scoreTt) _scoreTt = document.getElementById('scoreTooltip');
    if (!_scoreTt) return;
    const text = el?.dataset?.qualityTooltip || '';
    if (!text) return;
    _scoreTt.textContent = text.replace(/&#10;/g, '\n');
    _scoreTt.classList.add('visible');
    moveQualityTooltip(event);
  }

  function moveQualityTooltip(e) {
    if (!_scoreTt || !_scoreTt.classList.contains('visible') || !e) return;
    const x = e.clientX + 14, y = e.clientY + 14;
    const maxX = window.innerWidth  - _scoreTt.offsetWidth  - 10;
    const maxY = window.innerHeight - _scoreTt.offsetHeight - 10;
    _scoreTt.style.left = Math.min(x, maxX) + 'px';
    _scoreTt.style.top  = Math.min(y, maxY) + 'px';
  }

  function hideQualityTooltip() {
    if (_scoreTt) _scoreTt.classList.remove('visible');
  }

  function handleQualityBadgeLeave(el) {
    hideQualityTooltip();
    if (!enablePlot || isMobile()) return;
    const card = el?.closest?.('.tl-card');
    if (!card || !card.matches(':hover')) return;
    const plotText = (card.getAttribute('data-plot') || '').trim();
    if (plotText) showPlot(card, plotText, 0);
  }

  // ── KEYBOARD SHORTCUTS ──────────────────────────────
  // Close mobile popovers on outside tap
  document.addEventListener('click', e => {
    if (mobileFiltersOpen) {
      const panel = document.getElementById('mobileFiltersPanel');
      const btn   = document.getElementById('mobileFilterBtn');
      if (panel && !panel.contains(e.target) && btn && !btn.contains(e.target)) {
        closeMobileFilters();
      }
    }
  });

  function focusGlobalSearch() {
    if (isMobile()) {
      if (!mobileFiltersOpen) toggleMobileFilters();
      const mInput = document.getElementById('searchInputMobile');
      if (mInput) {
        setTimeout(() => mInput.focus(), 0);
        return;
      }
    }
    const dInput = document.getElementById('searchInput');
    if (dInput) dInput.focus();
  }

  function escapeSearchInteraction() {
    const active = document.activeElement;
    const dInput = document.getElementById('searchInput');
    const mInput = document.getElementById('searchInputMobile');
    if (active === dInput || active === mInput) {
      if (active.value && active.value.length > 0) {
        if (active === dInput) clearSearch();
        else clearSearchMobile();
        return true;
      }
      active.blur();
      if (mobileFiltersOpen) closeMobileFilters();
      return true;
    }
    return false;
  }

  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      focusGlobalSearch();
      return;
    }

    if (e.key === 'Escape') {
      if (escapeSearchInteraction()) return;
      const overlay = document.getElementById('settingsOverlay');
      if (overlay && overlay.style.display !== 'none') closeSettings();
      if (mobileScanSheetOpen) closeMobileScanSheet();
    }
  });

  // ── SIDEBAR RESIZE ───────────────────────────────────
  const SIDEBAR_MIN = 300;
  const SIDEBAR_MAX = 500;
  (function(){
    const sidebar = document.getElementById('sidebar');
    const resizer = document.getElementById('sidebarResizer');
    // Apply saved sidebar width with constraints
    const savedWidth = parseInt(localStorage.getItem('sidebarWidth') ?? '320');
    const clampedWidth = Math.min(Math.max(savedWidth, SIDEBAR_MIN), SIDEBAR_MAX);
    sidebar.style.width = clampedWidth + 'px';
    let startX, startW;
    resizer.addEventListener('mousedown', function(e){
      startX = e.clientX;
      startW = sidebar.offsetWidth;
      resizer.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      function onMove(e){
        const newWidth = startW + e.clientX - startX;
        const w = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, newWidth));
        sidebar.style.width = w + 'px';
        localStorage.setItem('sidebarWidth', w);
      }
      function onUp(){
        resizer.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      }
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  })();

  // ── AUTH ─────────────────────────────────────────────
  async function checkAuth() {
    try {
      const r = await fetch('/api/auth');
      if (!r.ok) { initApp(); return; }
      const d = await r.json();
      if (!d.required) { initApp(); return; }
      // Load translations for the auth screen before the overlay is shown.
      // Language comes from /api/auth (config.json system.language), fallback to English.
      // This ensures button labels and error messages are never shown as raw i18n keys.
      if (!Object.keys(TRANSLATIONS).length) {
        await loadTranslations(d.language || 'en');
        applyTranslations();
      }
      if (d.authenticated) { initApp(); return; }
      var ov = document.getElementById('authOverlay');
      if (ov) { ov.style.display = 'flex'; }
      setTimeout(() => document.getElementById('authInput')?.focus(), 50);
    } catch(e) {
      initApp();
    }
  }

  async function submitAuth() {
    const input = document.getElementById('authInput');
    const btn   = document.getElementById('authBtn');
    const err   = document.getElementById('authError');
    if (!input) return;
    btn.disabled = true; btn.textContent = '…';
    try {
      const r = await fetch('/api/auth', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({password: input.value}),
      });
      if (r.status === 429) {
        if (err) { err.textContent = t('auth.rate_limited'); err.style.display = 'block'; }
        btn.disabled = false; btn.textContent = t('auth.enter');
        return;
      }
      const d = await r.json();
      if (d.ok) {
        sessionStorage.setItem('mediaAuth', '1'); // UI hint only — session is in the HttpOnly cookie
        document.getElementById('authOverlay').style.display = 'none';
        initApp();
      } else {
        if (err) { err.textContent = t('auth.wrong'); err.style.display = 'block'; }
        input.value = ''; input.focus();
        btn.disabled = false; btn.textContent = t('auth.enter');
      }
    } catch(e) {
      btn.disabled = false; btn.textContent = 'Entrer';
    }
  }

  function _initPlotDelegation() {
    const lib = document.getElementById('library');
    if (!lib || lib._plotDelegated) return;
    lib._plotDelegated = true;
    lib.addEventListener('mouseover', function (e) {
      const card = e.target.closest?.('.tl-card');
      if (!card || !card.dataset.plot) return;
      if (e.relatedTarget?.closest?.('.tl-card') !== card) showPlot(card, card.dataset.plot);
    });
    lib.addEventListener('mouseout', function (e) {
      const card = e.target.closest?.('.tl-card');
      if (card && e.relatedTarget?.closest?.('.tl-card') !== card) hidePlot();
    });
  }

  function initApp() {
    loadLibrary();
    syncScanState();
    _initPlotDelegation();
  }

  checkAuth();

(function(){
      const btn=document.getElementById('backToTop');
      const _mc=document.querySelector('.main-content');
      const _mbtn=document.getElementById('mobileBackToTop');
      if(_mc)_mc.addEventListener('scroll',function(){
        btn.style.opacity=_mc.scrollTop>300?'1':'0';
        if(_mbtn) _mbtn.style.opacity=_mc.scrollTop>300?'1':'0';
      });
    })();


// Start
document.body.classList.add('layout-sidebar');
