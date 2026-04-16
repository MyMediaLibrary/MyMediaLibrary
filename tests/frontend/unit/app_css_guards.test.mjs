import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const cssSource = fs.readFileSync(path.resolve(__dirname, '../../../app/css/app.css'), 'utf8');

function cssBlock(source, selector, nextSelector) {
  const start = source.indexOf(selector);
  assert.notEqual(start, -1, `Selector ${selector} not found`);
  if (!nextSelector) return source.slice(start);
  const end = source.indexOf(nextSelector, start);
  assert.notEqual(end, -1, `Following selector ${nextSelector} not found`);
  return source.slice(start, end);
}

test('mobile filters panel reserves bottom-nav space to avoid overlap', () => {
  const panelBlock = cssBlock(cssSource, '.mobile-filters-panel{', '.mobile-filters-panel.open');
  assert.match(panelBlock, /bottom:var\(--mobile-nav-safe-height\)/, 'mobile filters panel should reserve bottom nav area');
  assert.match(panelBlock, /height:calc\(100dvh - 56px - var\(--mobile-nav-safe-height\)\)/, 'mobile filters panel height should subtract top bar + bottom nav');
  assert.match(panelBlock, /max-height:calc\(100dvh - 56px - var\(--mobile-nav-safe-height\)\)/, 'mobile filters panel max-height should match reserved layout');
});
