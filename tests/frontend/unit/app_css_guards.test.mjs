import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const cssSource = [
  '../../../app/css/app.css',
  '../../../app/css/stats.css',
].map((file) => fs.readFileSync(path.resolve(__dirname, file), 'utf8')).join('\n');

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
  assert.match(cssSource, /--priority-high-bg:#dc2626[\s\S]*--priority-low-bg:#15803d/, 'dark theme should define strong priority colors');
  assert.match(cssSource, /\[data-theme="light"\][\s\S]*--priority-high-bg:#b91c1c[\s\S]*--priority-low-bg:#15803d/, 'light theme should define high-contrast priority colors');
  assert.match(cssSource, /\.rec-priority-filter\{[\s\S]*--priority-filter-idle-bg[\s\S]*--priority-filter-idle-border/, 'priority filters should have a neutral inactive state');
  assert.match(cssSource, /\.rec-priority-filter\.active\{[\s\S]*box-shadow/, 'priority filters should have a visible active outline');
  assert.match(cssSource, /\.rec-priority-high\{background:var\(--priority-high-bg\)[\s\S]*color:var\(--priority-high-text\)/, 'priority badges should use shared high priority palette');
  assert.match(cssSource, /\.rec-priority-medium\{background:var\(--priority-medium-bg\)[\s\S]*color:var\(--priority-medium-text\)/, 'priority badges should use shared medium priority palette');
  assert.match(cssSource, /\.rec-priority-low\{background:var\(--priority-low-bg\)[\s\S]*color:var\(--priority-low-text\)/, 'priority badges should use shared low priority palette');
});

test('stats recommendations layout supports local filters and full-width rows', () => {
  assert.match(cssSource, /\.stats-rec-filters\{grid-template-columns:3fr 5fr\}/, 'stats recommendations filters should keep priority/type proportions without sort');
  assert.match(cssSource, /\.stats-row-full\{grid-template-columns:1fr\}/, 'stats recommendations full-width rows should span one column');
});
