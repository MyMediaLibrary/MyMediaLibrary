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
    providerExclude: false,
    videoCodecExclude: false,
    audioCodecExclude: false,
    audioLanguageExclude: false,
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

test('export button enablement and stale-safe behavior', () => {
  assert.equal(logic.isExportEnabled(null), false);
  assert.equal(logic.isExportEnabled(undefined), false);
  assert.equal(logic.isExportEnabled({ items: [] }), true);
});
