import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const require = createRequire(import.meta.url);
const logic = require('../../../app/js/app.logic.js');
const items = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../fixtures/library_items.json'), 'utf8'));

function baseState() {
  return {
    activeType: 'all',
    activeGroup: 'all',
    activeCat: 'all',
    activeFolders: new Set(),
    activeResolutions: new Set(),
    activeProviders: new Set(),
    activeCodecs: new Set(),
    activeAudioCodecs: new Set(),
    activeAudioLanguages: new Set(),
    activeQualityLevels: new Set(),
    scoreMin: 0,
    scoreMax: 100,
    includeNoScore: true,
    providerExclude: false,
    resolutionExclude: false,
    videoCodecExclude: false,
    audioCodecExclude: false,
    audioLanguageExclude: false,
    folderExclude: false,
    qualityExclude: false,
    searchQuery: ''
  };
}

test('global search: title/year/codecs/resolution/language/provider', () => {
  assert.equal(logic.applySearch(items, 'dts').length >= 2, true);
  assert.equal(logic.applySearch(items, 'vf').some((i) => i.title === 'Film VF'), true);
  assert.equal(logic.applySearch(items, '4k netflix').length >= 2, true);
  assert.equal(logic.applySearch(items, '2023 hevc').some((i) => i.title === 'Film VF'), true);
});

test('filters include/exclude and reset state behavior', () => {
  const state = baseState();
  state.activeProviders.add('Netflix');
  let filtered = logic.filterItems(items, state);
  assert.equal(filtered.every((i) => (i.providers || []).includes('Netflix')), true);

  state.providerExclude = true;
  filtered = logic.filterItems(items, state);
  assert.equal(filtered.some((i) => i.title === 'Film VF'), false);
  assert.equal(filtered.some((i) => i.title === 'Film Multi'), true);

  state.providerExclude = false;
  filtered = logic.filterItems(items, state);
  assert.equal(filtered.length > 0, true);

  const reset = logic.resetFiltersState();
  assert.equal(logic.hasActiveFilters(reset), false);
  reset.activeAudioLanguages.add('VF');
  assert.equal(logic.hasActiveFilters(reset), true);
});

test('provider exclude keeps item only if a non-others provider remains', () => {
  const sample = [
    { title: 'OnlyOthers', providers: ['Autres'] },
    { title: 'NetflixAndOthers', providers: ['Netflix', 'Autres'] },
    { title: 'NetflixPrimeOthers', providers: ['Netflix', 'Prime Video', 'Autres'] },
  ];
  const state = baseState();
  state.activeProviders = new Set(['Netflix']);
  state.providerExclude = true;
  assert.deepEqual(logic.applyFilters(sample, state).map((i) => i.title), ['NetflixPrimeOthers']);
});

test('score filter defaults include unscored items', () => {
  const qualityItems = [
    { title: 'Unscored' },
    { title: 'Low', quality: { score: 18 } },
    { title: 'Mid', quality: { score: 55 } },
    { title: 'High', quality: { score: 90 } }
  ];
  const state = baseState();
  const filtered = logic.filterItems(qualityItems, state);
  assert.deepEqual(filtered.map((i) => i.title), ['Unscored', 'Low', 'Mid', 'High']);
});

test('resolution filter supports multi-select include/exclude and legacy single-value state', () => {
  const sample = [
    { title: 'A', resolution: '720p' },
    { title: 'B', resolution: '1080p' },
    { title: 'C', resolution: '4K' },
    { title: 'D' }
  ];
  const state = baseState();
  state.activeResolutions = new Set(['720p', '1080p']);
  assert.deepEqual(logic.applyFilters(sample, state).map((i) => i.title), ['A', 'B']);

  state.resolutionExclude = true;
  assert.deepEqual(logic.applyFilters(sample, state).map((i) => i.title), ['C', 'D']);

  const legacyState = baseState();
  legacyState.activeResolutions = undefined;
  legacyState.activeResolution = '4K';
  assert.deepEqual(logic.applyFilters(sample, legacyState).map((i) => i.title), ['C']);
});

test('missing values are handled as a selectable none value across filters', () => {
  const sample = [
    { title: 'MissingAll' },
    { title: 'ResOnly', resolution: '1080p' },
    { title: 'CodecOnly', codec: 'H.265' },
    { title: 'AudioCodecOnly', audio_codec: 'DTS' },
    { title: 'LangOnly', audio_languages_simple: 'VF' }
  ];

  const state = baseState();
  state.activeResolutions = new Set(['__none__']);
  assert.deepEqual(logic.applyFilters(sample, state).map((i) => i.title), ['MissingAll', 'CodecOnly', 'AudioCodecOnly', 'LangOnly']);
  state.resolutionExclude = true;
  assert.deepEqual(logic.applyFilters(sample, state).map((i) => i.title), ['ResOnly']);

  state.resolutionExclude = false;
  state.activeResolutions.clear();
  state.activeCodecs = new Set(['__none__']);
  assert.deepEqual(logic.applyFilters(sample, state).map((i) => i.title), ['MissingAll', 'ResOnly', 'AudioCodecOnly', 'LangOnly']);
  state.videoCodecExclude = true;
  assert.deepEqual(logic.applyFilters(sample, state).map((i) => i.title), ['CodecOnly']);
});

test('export button enablement and stale-safe behavior', () => {
  assert.equal(logic.isExportEnabled(null), false);
  assert.equal(logic.isExportEnabled(undefined), false);
  assert.equal(logic.isExportEnabled({ items: [] }), true);
});

test('normalizes legacy provider keys from persisted state', () => {
  assert.equal(logic.canonicalProviderFilterKey('autres'), '__others__');
  assert.equal(logic.canonicalProviderFilterKey('others'), '__others__');
  assert.equal(logic.canonicalProviderFilterKey('__others__'), '__others__');
  assert.equal(logic.canonicalProviderFilterKey('__none__'), '__none__');
  assert.equal(logic.canonicalProviderFilterKey('  Netflix  '), 'Netflix');
  assert.equal(logic.canonicalProviderFilterKey(''), null);
});

test('counts grouped providers once per item (no overcount in Others)', () => {
  const sample = [
    { providers: ['HiddenA', 'HiddenB'] }, // should count __others__ once
    { providers: ['Netflix', 'HiddenA'] }, // Netflix once, __others__ once
    { providers: ['Netflix', 'Netflix'] }, // Netflix once
  ];
  const counts = logic.groupedProviderCounts(
    sample,
    (name) => (name === 'Netflix' ? 'Netflix' : '__others__'),
    (entry) => entry
  );
  assert.deepEqual(counts, { __others__: 2, Netflix: 2 });
});

test('maps quality score and quality payload to 5-level ranking', () => {
  assert.equal(logic.getQualityLevelFromScore(0), 1);
  assert.equal(logic.getQualityLevelFromScore(20), 1);
  assert.equal(logic.getQualityLevelFromScore(21), 2);
  assert.equal(logic.getQualityLevelFromScore(40), 2);
  assert.equal(logic.getQualityLevelFromScore(41), 3);
  assert.equal(logic.getQualityLevelFromScore(60), 3);
  assert.equal(logic.getQualityLevelFromScore(61), 4);
  assert.equal(logic.getQualityLevelFromScore(80), 4);
  assert.equal(logic.getQualityLevelFromScore(81), 5);
  assert.equal(logic.getQualityLevelFromScore(100), 5);

  assert.equal(logic.getItemQualityLevel({ quality: { level: 4, score: 10 } }), 1);
  assert.equal(logic.getItemQualityLevel({ quality: { score: 84 } }), 5);
  assert.equal(logic.getItemQualityLevel({}), 1);
  assert.equal(logic.getQualityLevelClass(3), 'quality-lvl-3');
});

test('score range helpers handle boundaries and missing values', () => {
  assert.equal(logic.normalizeScoreRangeKey(1), '0_20');
  assert.equal(logic.normalizeScoreRangeKey('5'), '80_100');
  assert.equal(logic.normalizeScoreRangeKey('40_60'), '40_60');
  assert.equal(logic.normalizeScoreRangeKey('invalid'), null);
  assert.equal(logic.matchesScoreRange(0, '0_20'), true);
  assert.equal(logic.matchesScoreRange(20, '0_20'), true);
  assert.equal(logic.matchesScoreRange(21, '0_20'), false);
  assert.equal(logic.matchesScoreRange(100, '80_100'), true);
  assert.equal(logic.matchesScoreRange(undefined, '80_100'), false);
  assert.equal(logic.getScoreRangeKey({ quality: { score: 10, level: 5 } }), '0_20');
});

test('applyFilters handles multi-filters include/exclude consistently', () => {
  const sample = [
    {
      title: 'A',
      type: 'movie',
      group: 'g1',
      category: 'c1',
      resolution: '4K',
      codec: 'H.265',
      audio_codec: 'DTS',
      audio_languages_simple: 'VF',
      providers: ['Netflix'],
      quality: { score: 85 }
    },
    {
      title: 'B',
      type: 'tv',
      group: 'g2',
      category: 'c1',
      resolution: '1080p',
      codec: 'H.264',
      audio_codec: 'AAC',
      audio_languages_simple: 'VO',
      providers: ['Prime Video'],
      quality: { score: 35 }
    },
    {
      title: 'C',
      type: 'movie',
      group: 'g1',
      category: 'c2',
      resolution: '4K',
      codec: 'H.265',
      audio_codec: 'AAC',
      audio_languages_simple: 'MULTI',
      providers: [],
      quality: { score: 20 }
    },
    { title: 'D', type: 'movie', providers: ['Netflix'] }
  ];

  const state = baseState();
  state.activeType = 'movie';
  state.activeGroup = 'g1';
  state.activeFolders = new Set(['c1']);
  state.activeResolutions = new Set(['4K']);
  state.activeProviders = new Set(['Netflix']);
  state.activeCodecs = new Set(['H.265']);
  state.activeAudioCodecs = new Set(['DTS']);
  state.activeAudioLanguages = new Set(['VF']);
  state.scoreMin = 80;
  state.scoreMax = 100;
  state.includeNoScore = false;
  assert.deepEqual(logic.applyFilters(sample, state).map((i) => i.title), ['A']);

  state.resolutionExclude = true;
  assert.equal(logic.applyFilters(sample, state).length, 0);
  state.resolutionExclude = false;

  state.providerExclude = true;
  assert.deepEqual(logic.applyFilters(sample, state).map((i) => i.title), []);
  state.providerExclude = false;
  state.activeProviders = new Set(['__none__']);
  assert.deepEqual(logic.applyFilters(sample, state).map((i) => i.title), [], 'other active filters still apply');
  state.activeFolders.clear();
  state.activeAudioCodecs = new Set(['AAC']);
  state.activeAudioLanguages = new Set(['MULTI']);
  state.scoreMin = 0;
  state.scoreMax = 20;
  state.includeNoScore = false;
  assert.deepEqual(logic.applyFilters(sample, state).map((i) => i.title), ['C']);
});

test('score range + include_no_score behavior matches expected UX', () => {
  const qualityItems = [
    { title: 'Q0', quality: { score: 0 } },
    { title: 'Q10', quality: { score: 10 } },
    { title: 'Q50', quality: { score: 50 } },
    { title: 'Q80', quality: { score: 80 } },
    { title: 'NoScore' }
  ];
  const state = baseState();
  // B. Restriction excludes no-score when includeNoScore is false.
  state.scoreMin = 10;
  state.scoreMax = 50;
  state.includeNoScore = false;
  assert.deepEqual(logic.applyFilters(qualityItems, state).map((i) => i.title), ['Q10', 'Q50']);
  // C. Manual re-check includes no-score again with same range.
  state.includeNoScore = true;
  assert.deepEqual(logic.applyFilters(qualityItems, state).map((i) => i.title), ['Q10', 'Q50', 'NoScore']);
  // D. Back to 0-100 does not force includeNoScore value.
  state.scoreMin = 0;
  state.scoreMax = 100;
  state.includeNoScore = false;
  assert.deepEqual(logic.applyFilters(qualityItems, state).map((i) => i.title), ['Q0', 'Q10', 'Q50', 'Q80']);
  // E. Reset restores defaults.
  const reset = logic.resetFiltersState();
  assert.equal(reset.scoreMin, 0);
  assert.equal(reset.scoreMax, 100);
  assert.equal(reset.includeNoScore, true);
});

test('computeFilterCounts stays coherent with active filters and quality ranges', () => {
  const sample = [
    { title: 'A', providers: ['Netflix'], codec: 'H.265', audio_codec: 'DTS', audio_languages_simple: 'VF', quality: { score: 90 } },
    { title: 'B', providers: ['Netflix', 'Prime Video'], codec: 'H.264', audio_codec: 'AAC', audio_languages_simple: 'VO', quality: { score: 50 } },
    { title: 'C', providers: [], codec: 'H.264', audio_codec: 'AAC', audio_languages_simple: 'VO' }
  ];
  const state = baseState();
  state.activeProviders = new Set(['Netflix']);
  const codecCounts = logic.computeFilterCounts(sample, state, 'codec');
  assert.deepEqual(codecCounts, { 'H.265': 1, 'H.264': 1 });

  state.activeCodecs = new Set(['H.264']);
  const qualityCounts = logic.computeFilterCounts(sample, state, 'quality');
  assert.deepEqual(qualityCounts, { '0_20': 0, '20_40': 0, '40_60': 1, '60_80': 0, '80_100': 0 });
});

test('folder filter supports multi-select include/exclude and legacy single-folder state', () => {
  const sample = [
    { title: 'A', category: 'Films' },
    { title: 'B', category: 'Anime' },
    { title: 'C', category: 'Docs' },
    { title: 'D' }
  ];
  const state = baseState();
  state.activeFolders = new Set(['Films', 'Anime']);
  assert.deepEqual(logic.applyFilters(sample, state).map((i) => i.title), ['A', 'B']);

  state.folderExclude = true;
  assert.deepEqual(logic.applyFilters(sample, state).map((i) => i.title), ['C', 'D']);

  const legacyState = baseState();
  legacyState.activeFolders = undefined;
  legacyState.activeCat = 'Docs';
  assert.deepEqual(logic.applyFilters(sample, legacyState).map((i) => i.title), ['C']);
});
