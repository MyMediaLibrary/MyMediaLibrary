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

test('renderQualityFilter relies on shared dropdown and has no stale noneCount reference', () => {
  const block = functionBlock(appSource, 'renderQualityFilter', 'renderResolutionFilter');
  assert.match(block, /renderFilterDropdown\(/, 'renderQualityFilter should use shared renderFilterDropdown');
  assert.doesNotMatch(block, /\bnoneCount\b/, 'renderQualityFilter should not reference stale noneCount');
});

test('quality select-all wiring is mapped in _dropdownSelectAll', () => {
  const block = functionBlock(appSource, '_dropdownSelectAll', 'toggleProviderFilter');
  assert.match(block, /'qualitySection': activeQualityLevels/, 'qualitySection should be mapped for select-all');
  assert.match(block, /'qualitySectionMobile': activeQualityLevels/, 'qualitySectionMobile should be mapped for select-all');
});


test('renderQualityFilter keeps score ranges visible even when all counts are zero', () => {
  const block = functionBlock(appSource, 'renderQualityFilter', 'renderResolutionFilter');
  assert.match(block, /orderedKeys\s*=\s*SCORE_FILTER_RANGES\.map\(r => r\.key\)/, 'score filter should render all configured ranges');
  assert.doesNotMatch(block, /if\s*\(!total\)\s*\{\s*sec\.style\.display\s*=\s*'none'/, 'score filter should not hide when counts are zero');
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

test('renderResolutionFilter renders resolution labels without inline counts', () => {
  const block = functionBlock(appSource, 'renderResolutionFilter', 'clickResolution');
  assert.doesNotMatch(block, /counts\[r\]/, 'resolution pills should not inject per-resolution counts');
  assert.doesNotMatch(block, /margin-left:4px;font-size:11px/, 'resolution pills should not render the legacy inline count span');
});

test('loadLibrary resolves score feature from config first, then library metadata fallback', () => {
  const block = functionBlock(appSource, 'loadLibrary', '_dateYmd');
  assert.match(block, /resolveScoreEnabled\(libraryMetaScoreEnabled\)/, 'loadLibrary should use centralized score resolution');
  assert.doesNotMatch(block, /enableScore\s*=\s*data\.meta\.score_enabled/, 'loadLibrary should not directly trust stale library meta score flag');
});
