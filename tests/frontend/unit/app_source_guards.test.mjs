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
