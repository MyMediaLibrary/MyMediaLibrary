(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.MMLLogic = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  const PROVIDER_OTHERS_KEY = '__others__';
  const PROVIDER_NONE_KEY = '__none__';
  const PROVIDER_OTHERS_ALIASES = new Set(['autres', 'others', 'other']);
  const SCORE_FILTER_RANGES = [
    { key: '0_20', level: 1 },
    { key: '20_40', level: 2 },
    { key: '40_60', level: 3 },
    { key: '60_80', level: 4 },
    { key: '80_100', level: 5 },
  ];

  function normalizeAudioLanguageCode(raw) {
    if (typeof raw !== 'string') return null;
    const code = raw.toLowerCase().trim();
    if (!code) return null;
    if (code === 'fr' || code === 'fra' || code === 'fre') return 'fra';
    return code;
  }

  function simplifyAudioLanguages(codes) {
    if (!Array.isArray(codes)) return 'UNKNOWN';
    const normalized = new Set();
    codes.forEach((code) => {
      const norm = normalizeAudioLanguageCode(code);
      if (norm) normalized.add(norm);
    });
    if (normalized.size === 0) return 'UNKNOWN';
    if (normalized.size === 1 && normalized.has('fra')) return 'VF';
    if (normalized.has('fra') && normalized.size > 1) return 'MULTI';
    return 'VO';
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
    const providers = (item.providers || []).join(' ');
    const audioSimple = item.audio_languages_simple || simplifyAudioLanguages(item.audio_languages || []);
    const audioSimpleAliases = audioSimple === 'VF'
      ? 'vf french francais fr'
      : (audioSimple === 'VO'
        ? 'vo original'
        : (audioSimple === 'MULTI' ? 'multi multilingual multilang' : 'unknown inconnu'));
    const videoCodecAliases = item.codec === 'H.265' ? 'hevc x265 h265' : (item.codec === 'H.264' ? 'avc x264 h264' : '');

    return [
      item.title,
      item.year,
      item.audio_codec,
      item.audio_codec_display,
      item.audio_codec_raw,
      item.codec,
      videoCodecAliases,
      item.resolution,
      audioSimple,
      audioSimpleAliases,
      providers
    ];
  }

  function applySearch(items, query) {
    const tokens = searchTokens(query);
    if (!tokens.length) return items;
    return items.filter((item) => {
      const idx = normalizeSearchText(getItemSearchFields(item).join(' '));
      return tokens.every((tok) => idx.includes(tok));
    });
  }

  function normalizeScoreRangeKey(raw) {
    if (raw === null || raw === undefined) return null;
    const value = String(raw).trim();
    if (!value) return null;
    if (SCORE_FILTER_RANGES.some((r) => r.key === value)) return value;
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return null;
    return SCORE_FILTER_RANGES.find((r) => r.level === numeric)?.key || null;
  }

  function getScoreRangeKey(input) {
    const level = (input && typeof input === 'object')
      ? getScoredQualityLevel(input)
      : getScoredQualityLevel({ quality: { score: input } });
    if (level === null) return null;
    return SCORE_FILTER_RANGES.find((r) => r.level === level)?.key || null;
  }

  function matchesScoreRange(score, rangeKey) {
    const normalized = normalizeScoreRangeKey(rangeKey);
    if (!normalized) return false;
    return getScoreRangeKey(score) === normalized;
  }

  function applySelectionFilter(items, activeSet, excludeMode, readValue, options = {}) {
    if (!activeSet || activeSet.size === 0) return items;
    const matchNoneWhenSelected = !!options.matchNoneWhenSelected;
    const withNoneExclusion = !!options.withNoneExclusion;
    return items.filter((item) => {
      const read = readValue(item);
      const values = Array.isArray(read) ? read.filter((v) => v !== null && v !== undefined) : [read];
      const hasNone = values.length === 0;
      const matches = values.some((value) => activeSet.has(value));
      if (excludeMode) {
        if (withNoneExclusion && activeSet.has(PROVIDER_NONE_KEY) && hasNone) return false;
        return !matches;
      }
      if (matchNoneWhenSelected && activeSet.has(PROVIDER_NONE_KEY) && hasNone) return true;
      return matches;
    });
  }

  function applyFilters(items, state) {
    let out = items.slice();
    if (state.activeType && state.activeType !== 'all') out = out.filter((i) => i.type === state.activeType);
    if (state.activeGroup && state.activeGroup !== 'all') out = out.filter((i) => i.group === state.activeGroup);
    if (state.activeCat && state.activeCat !== 'all') out = out.filter((i) => i.category === state.activeCat);
    if (state.activeResolution && state.activeResolution !== 'all') out = out.filter((i) => i.resolution === state.activeResolution);

    out = applySelectionFilter(out, state.activeCodecs, state.videoCodecExclude, (i) => i.codec || 'UNKNOWN');
    out = applySelectionFilter(out, state.activeAudioCodecs, state.audioCodecExclude, (i) => i.audio_codec || 'UNKNOWN');
    out = applySelectionFilter(
      out,
      state.activeAudioLanguages,
      state.audioLanguageExclude,
      (i) => i.audio_languages_simple || simplifyAudioLanguages(i.audio_languages)
    );
    out = applySelectionFilter(
      out,
      state.activeProviders,
      state.providerExclude,
      (i) => i.providers || [],
      { matchNoneWhenSelected: true, withNoneExclusion: true }
    );
    out = applySelectionFilter(
      out,
      new Set([...(state.activeQualityLevels || new Set())].map((k) => normalizeScoreRangeKey(k)).filter(Boolean)),
      state.qualityExclude,
      (i) => getScoreRangeKey(i)
    );

    return applySearch(out, state.searchQuery || '');
  }

  function filterItems(items, state) {
    return applyFilters(items, state);
  }

  function computeFilterCounts(items, state, field) {
    const nextState = { ...state };
    if (field === 'provider') nextState.activeProviders = new Set();
    if (field === 'codec') nextState.activeCodecs = new Set();
    if (field === 'audioCodec') nextState.activeAudioCodecs = new Set();
    if (field === 'audioLanguage') nextState.activeAudioLanguages = new Set();
    if (field === 'quality') nextState.activeQualityLevels = new Set();
    const scoped = applyFilters(items, nextState);
    const counts = {};
    if (field === 'quality') {
      SCORE_FILTER_RANGES.forEach((range) => { counts[range.key] = 0; });
    }
    scoped.forEach((item) => {
      if (field === 'provider') {
        const providers = item.providers || [];
        if (!providers.length) counts[PROVIDER_NONE_KEY] = (counts[PROVIDER_NONE_KEY] || 0) + 1;
        providers.forEach((name) => { counts[name] = (counts[name] || 0) + 1; });
      } else if (field === 'codec') {
        const key = item.codec || 'UNKNOWN';
        counts[key] = (counts[key] || 0) + 1;
      } else if (field === 'audioCodec') {
        const key = item.audio_codec || 'UNKNOWN';
        counts[key] = (counts[key] || 0) + 1;
      } else if (field === 'audioLanguage') {
        const key = item.audio_languages_simple || simplifyAudioLanguages(item.audio_languages);
        counts[key] = (counts[key] || 0) + 1;
      } else if (field === 'quality') {
        const key = getScoreRangeKey(item);
        if (key) counts[key] += 1;
      }
    });
    return counts;
  }

  function hasActiveFilters(state) {
    return state.activeType !== 'all'
      || state.activeGroup !== 'all'
      || state.activeCat !== 'all'
      || state.activeResolution !== 'all'
      || state.activeProviders.size > 0
      || state.activeCodecs.size > 0
      || state.activeAudioCodecs.size > 0
      || state.activeAudioLanguages.size > 0
      || state.activeQualityLevels.size > 0
      || state.providerExclude
      || state.videoCodecExclude
      || state.audioCodecExclude
      || state.audioLanguageExclude
      || state.qualityExclude
      || !!(state.searchQuery || '').trim();
  }

  function resetFiltersState() {
    return {
      activeType: 'all',
      activeGroup: 'all',
      activeCat: 'all',
      activeResolution: 'all',
      activeProviders: new Set(),
      activeCodecs: new Set(),
      activeAudioCodecs: new Set(),
      activeAudioLanguages: new Set(),
      activeQualityLevels: new Set(),
      providerExclude: false,
      videoCodecExclude: false,
      audioCodecExclude: false,
      audioLanguageExclude: false,
      qualityExclude: false,
      searchQuery: ''
    };
  }

  function isExportEnabled(libraryExportSource) {
    return !!libraryExportSource;
  }

  function canonicalProviderFilterKey(raw, options = {}) {
    const knownProviders = options.knownProviders || null;
    if (typeof raw !== 'string') return null;
    const key = raw.trim();
    if (!key) return null;
    const lower = key.toLowerCase();
    if (key === PROVIDER_OTHERS_KEY || PROVIDER_OTHERS_ALIASES.has(lower)) return PROVIDER_OTHERS_KEY;
    if (key === PROVIDER_NONE_KEY) return PROVIDER_NONE_KEY;
    if (knownProviders && !knownProviders.has(key)) return null;
    return key;
  }

  function groupedProviderCounts(items, providerGroupForName, providerNameFromEntry) {
    const byProvider = {};
    const readName = providerNameFromEntry || ((p) => p);
    const groupFor = providerGroupForName || ((name) => name);
    (items || []).forEach((item) => {
      const grouped = new Set();
      (item.providers || []).forEach((entry) => {
        const key = groupFor(readName(entry));
        if (key) grouped.add(key);
      });
      grouped.forEach((key) => {
        byProvider[key] = (byProvider[key] || 0) + 1;
      });
    });
    return byProvider;
  }

  function getQualityLevelFromScore(score) {
    const safeScore = Number.isFinite(Number(score)) ? Number(score) : 0;
    if (safeScore <= 20) return 1;
    if (safeScore <= 40) return 2;
    if (safeScore <= 60) return 3;
    if (safeScore <= 80) return 4;
    return 5;
  }

  function getItemQualityLevel(item) {
    const rawLevel = Number(item?.quality?.level);
    if (Number.isFinite(rawLevel) && rawLevel >= 1 && rawLevel <= 5) return rawLevel;
    return getQualityLevelFromScore(item?.quality?.score);
  }

  function getScoredQualityLevel(item) {
    const score = Number(item?.quality?.score);
    if (!Number.isFinite(score)) return null;
    const rawLevel = Number(item?.quality?.level);
    if (Number.isFinite(rawLevel) && rawLevel >= 1 && rawLevel <= 5) return rawLevel;
    return getQualityLevelFromScore(score);
  }

  function getQualityLevelClass(level) {
    const safeLevel = Number(level);
    if (safeLevel >= 1 && safeLevel <= 5) return `quality-lvl-${safeLevel}`;
    return 'quality-lvl-unknown';
  }

  return {
    normalizeAudioLanguageCode,
    simplifyAudioLanguages,
    normalizeSearchText,
    searchTokens,
    getItemSearchFields,
    applySearch,
    filterItems,
    applyFilters,
    hasActiveFilters,
    resetFiltersState,
    computeFilterCounts,
    isExportEnabled,
    canonicalProviderFilterKey,
    groupedProviderCounts,
    getQualityLevelFromScore,
    getItemQualityLevel,
    getScoredQualityLevel,
    getQualityLevelClass,
    normalizeScoreRangeKey,
    matchesScoreRange,
    getScoreRangeKey
  };
});
