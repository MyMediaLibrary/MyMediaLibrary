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
