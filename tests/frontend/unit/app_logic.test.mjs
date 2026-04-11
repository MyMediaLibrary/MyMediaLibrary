import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const require = createRequire(import.meta.url);
const logic = require('../../../app/app.logic.js');
const items = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../fixtures/library_items.json'), 'utf8'));

function baseState() {
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
  assert.equal(filtered.some((i) => (i.providers || []).includes('Netflix')), false);

  state.providerExclude = false;
  filtered = logic.filterItems(items, state);
  assert.equal(filtered.length > 0, true);

  const reset = logic.resetFiltersState();
  assert.equal(logic.hasActiveFilters(reset), false);
  reset.activeAudioLanguages.add('VF');
  assert.equal(logic.hasActiveFilters(reset), true);
});

test('quality filter supports include/exclude with multi-select levels', () => {
  const state = baseState();
  state.activeQualityLevels = new Set([4, 5]);
  let filtered = logic.filterItems(items, state);
  assert.equal(filtered.every((i) => [4, 5].includes(logic.getItemQualityLevel(i))), true);

  state.qualityExclude = true;
  filtered = logic.filterItems(items, state);
  assert.equal(filtered.some((i) => [4, 5].includes(logic.getItemQualityLevel(i))), false);
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

  assert.equal(logic.getItemQualityLevel({ quality: { level: 4, score: 10 } }), 4);
  assert.equal(logic.getItemQualityLevel({ quality: { score: 84 } }), 5);
  assert.equal(logic.getItemQualityLevel({}), 1);
  assert.equal(logic.getQualityLevelClass(3), 'quality-lvl-3');
});
