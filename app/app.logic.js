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

  function filterItems(items, state) {
    let out = items.slice();
    if (state.activeResolution !== 'all') out = out.filter((i) => i.resolution === state.activeResolution);

    if (state.activeAudioLanguages.size > 0) {
      if (state.audioLanguageExclude) {
        out = out.filter((i) => !state.activeAudioLanguages.has(i.audio_languages_simple || simplifyAudioLanguages(i.audio_languages)));
      } else {
        out = out.filter((i) => state.activeAudioLanguages.has(i.audio_languages_simple || simplifyAudioLanguages(i.audio_languages)));
      }
    }

    if (state.activeProviders.size > 0) {
      if (state.providerExclude) {
        out = out.filter((i) => !(i.providers || []).some((p) => state.activeProviders.has(p)));
      } else {
        out = out.filter((i) => (i.providers || []).some((p) => state.activeProviders.has(p)));
      }
    }

    return applySearch(out, state.searchQuery || '');
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
      || state.providerExclude
      || state.videoCodecExclude
      || state.audioCodecExclude
      || state.audioLanguageExclude
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
      providerExclude: false,
      videoCodecExclude: false,
      audioCodecExclude: false,
      audioLanguageExclude: false,
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

  return {
    normalizeAudioLanguageCode,
    simplifyAudioLanguages,
    normalizeSearchText,
    searchTokens,
    getItemSearchFields,
    applySearch,
    filterItems,
    hasActiveFilters,
    resetFiltersState,
    isExportEnabled,
    canonicalProviderFilterKey,
    groupedProviderCounts
  };
});
