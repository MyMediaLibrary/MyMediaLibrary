import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

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

test('score weights use 2-column desktop grid and 1-column mobile fallback', () => {
  assert.match(cssSource, /\.score-weights-grid\{display:grid;grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/, 'score weights should render in 2 columns on desktop');
  assert.match(cssSource, /@media\(max-width:768px\)\{[\s\S]*\.score-weights-grid\{grid-template-columns:1fr\}/, 'score weights should collapse to 1 column on mobile');
});

test('recommendation filters use priority type sort proportions and priority colors', () => {
  assert.match(cssSource, /\.rec-filters\{display:grid;grid-template-columns:3fr 5fr 2fr/, 'recommendation filters should follow 30/50/20 desktop proportions');
  assert.match(cssSource, /@media\(max-width:768px\)\{[\s\S]*\.rec-filters\{grid-template-columns:1fr\}/, 'recommendation filters should stack on mobile');
  assert.match(cssSource, /\.rec-filter-btn\.provider-pill/, 'recommendation type filters should reuse provider/type pill styling');
  assert.match(cssSource, /\.rec-priority-filter-high[\s\S]*#f87171/, 'high priority filters should use high badge color');
  assert.match(cssSource, /\.rec-priority-filter-medium[\s\S]*#facc15/, 'medium priority filters should use medium badge color');
  assert.match(cssSource, /\.rec-priority-filter-low[\s\S]*#cbd5e1/, 'low priority filters should use low badge color');
});
