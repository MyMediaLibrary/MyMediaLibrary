import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const appSource = fs.readFileSync(path.resolve('app/app.js'), 'utf8');

function functionBlock(source, functionName, nextFunctionName) {
  const start = source.indexOf(`function ${functionName}(`);
  assert.notEqual(start, -1, `Function ${functionName} not found`);
  if (!nextFunctionName) return source.slice(start);
  const end = source.indexOf(`\n  function ${nextFunctionName}(`, start);
  assert.notEqual(end, -1, `Following function ${nextFunctionName} not found`);
  return source.slice(start, end);
}

test('renderQualityFilter renders slider + include_no_score control and has no stale noneCount reference', () => {
  const block = functionBlock(appSource, 'renderQualityFilter', 'renderResolutionFilter');
  assert.match(block, /score-slider-min/, 'renderQualityFilter should render minimum score slider');
  assert.match(block, /score-slider-max/, 'renderQualityFilter should render maximum score slider');
  assert.match(block, /filters\.score\.include_no_score/, 'renderQualityFilter should render include-no-score checkbox');
  assert.doesNotMatch(block, /\bnoneCount\b/, 'renderQualityFilter should not reference stale noneCount');
});

test('quality select-all wiring is mapped in _dropdownSelectAll', () => {
  const block = functionBlock(appSource, '_dropdownSelectAll', 'toggleProviderFilter');
  assert.match(block, /'qualitySection': activeQualityLevels/, 'qualitySection should be mapped for select-all');
  assert.match(block, /'qualitySectionMobile': activeQualityLevels/, 'qualitySectionMobile should be mapped for select-all');
});


test('renderQualityFilter auto-unchecks include_no_score only when leaving default range', () => {
  const block = functionBlock(appSource, 'renderQualityFilter', 'renderResolutionFilter');
  assert.match(block, /const prevDefault = scoreMin === 0 && scoreMax === 100;/, 'slider update should track default-range transition');
  assert.match(block, /if \(prevDefault && !nowDefault\) includeNoScore = false;/, 'include_no_score should auto-uncheck when restricting score range');
  assert.doesNotMatch(block, /if \(!nowDefault\) includeNoScore = true;/, 'include_no_score should never be auto-rechecked');
});

test('standard dropdown sorting is centralized and stable by count then label', () => {
  const sortBlock = functionBlock(appSource, 'sortFilterOptionsByCount', 'buildDropdownFilterModel');
  assert.match(sortBlock, /if \(b\.count !== a\.count\) return b\.count - a\.count;/, 'options should be sorted by descending dynamic count');
  assert.match(sortBlock, /localeCompare\(/, 'equal counts should use stable label-based tie-breaker');

  const modelBlock = functionBlock(appSource, 'buildDropdownFilterModel', 'renderFilterDropdown');
  assert.match(modelBlock, /sortFilterOptionsByCount\(remaining, getDisplay\)/, 'dropdown model should use centralized sort helper');
  assert.match(modelBlock, /\.filter\(option => option\.count > 0 \|\| activeLookup\.has\(option\.key\)\)/, 'dropdown model should keep zero-count options only when currently active');
  assert.match(modelBlock, /activeKeys\.forEach/, 'dropdown model should restore active keys missing from counts');
});

test('renderFilterDropdown hides empty filters when no positive-count options remain', () => {
  const block = functionBlock(appSource, 'renderFilterDropdown', 'normalizeScoreRangeKey');
  assert.match(block, /if \(!keys\.length && activeSet\.size === 0\) \{ sec\.style\.display = 'none'; return; \}/, 'dropdown should stay visible when active values must remain clearable');
  assert.match(block, /buildDropdownFilterModel\(\{ counts, getDisplay, pinFirst, activeSet \}\)/, 'dropdown model should receive active set to preserve active zero-count options');
});

test('score filter is forced to last position after filter rendering', () => {
  const block = functionBlock(appSource, 'onFilter', 'syncTypePills');
  assert.match(block, /renderQualityFilter\(\);/, 'score filter should be rendered in onFilter');
  assert.match(block, /ensureScoreFilterLast\(\);/, 'score filter should be repositioned to last slot after rendering');
});

test('restoreState restores persisted quality exclude mode', () => {
  const block = functionBlock(appSource, 'restoreState');
  assert.match(block, /s\.qualityExclude !== undefined/, 'restoreState should read qualityExclude from persisted mediaState');
  assert.match(block, /qualityExclude\s*=\s*!!s\.qualityExclude/, 'restoreState should restore qualityExclude boolean');
});

test('score feature visibility is centrally applied and sanitizes stale score state', () => {
  const block = functionBlock(appSource, 'applyScoreFeatureVisibility', 'hasActiveFilters');
  assert.match(block, /if\s*\(!scoreOn\)\s*sanitizeScoreState\(\)/, 'score visibility should sanitize stale score state when disabled');
  assert.match(block, /option\.style\.display = scoreOn \? '' : 'none'/, 'score sort options should be hidden when score is disabled');
});

test('quality filter hard-disables itself when score feature is disabled', () => {
  const block = functionBlock(appSource, 'renderQualityFilter', 'renderResolutionFilter');
  assert.match(block, /if\s*\(!isScoreEnabled\(\)\)\s*\{/, 'renderQualityFilter should early-return when score is disabled');
});

test('renderResolutionFilter uses shared dropdown with include/exclude toggles', () => {
  const block = functionBlock(appSource, 'renderResolutionFilter', 'onFilter');
  assert.match(block, /renderFilterDropdown\(/, 'resolution should reuse shared dropdown renderer');
  assert.match(block, /toggleFn:\s*'toggleResolutionFilter'/, 'resolution should use standard dropdown toggle');
  assert.match(block, /clearFn:\s*'clearResolutionFilter'/, 'resolution should use standard dropdown clear');
  assert.match(block, /onToggleExclude:\s*'toggleResolutionExclude'/, 'resolution should expose include\/exclude toggle');
  assert.match(block, /t\('filters\.none'\)/, 'resolution should display a localized none value for missing metadata');
  assert.doesNotMatch(block, /provider-pill/, 'resolution should no longer render legacy pill markup');
});

test('loadLibrary resolves score feature from config first, then library metadata fallback', () => {
  const block = functionBlock(appSource, 'loadLibrary', '_dateYmd');
  assert.match(block, /resolveScoreEnabled\(libraryMetaScoreEnabled\)/, 'loadLibrary should use centralized score resolution');
  assert.doesNotMatch(block, /enableScore\s*=\s*data\.meta\.score_enabled/, 'loadLibrary should not directly trust stale library meta score flag');
});
