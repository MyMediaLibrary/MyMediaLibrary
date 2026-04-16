import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const appSource = fs.readFileSync(path.resolve(process.cwd(), 'app/js/app.js'), 'utf8');
const appCss = fs.readFileSync(path.resolve(process.cwd(), 'app/css/app.css'), 'utf8');
const settingsSource = fs.readFileSync(path.resolve(process.cwd(), 'app/settings.js'), 'utf8');
const statsSource = fs.readFileSync(path.resolve(process.cwd(), 'app/stats.js'), 'utf8');

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
  assert.match(block, /'folderSection': activeFolders/, 'folderSection should be mapped for select-all');
  assert.match(block, /'folderSectionMobile': activeFolders/, 'folderSectionMobile should be mapped for select-all');
});


test('renderQualityFilter auto-unchecks include_no_score only when leaving default range', () => {
  const block = functionBlock(appSource, 'renderQualityFilter', 'renderResolutionFilter');
  assert.match(block, /const prevDefault = scoreMin === 0 && scoreMax === 100;/, 'slider update should track default-range transition');
  assert.match(block, /if \(prevDefault && !nowDefault\) includeNoScore = false;/, 'include_no_score should auto-uncheck when restricting score range');
  assert.doesNotMatch(block, /if \(!nowDefault\) includeNoScore = true;/, 'include_no_score should never be auto-rechecked');
});

test('renderQualityFilter keeps drag updates visual-only and commits filtering on release', () => {
  const block = functionBlock(appSource, 'renderQualityFilter', 'renderResolutionFilter');
  assert.match(block, /function updateDraftFromSlider\(changed\)/, 'renderQualityFilter should track draft score values during drag');
  assert.match(block, /function commitDraftScoreRange\(\)/, 'renderQualityFilter should separate commit from draft updates');
  assert.match(block, /minInput\?\.addEventListener\('input', function\(\) \{ updateDraftFromSlider\('min'\); \}\);/, 'min slider input should only update draft values');
  assert.match(block, /maxInput\?\.addEventListener\('input', function\(\) \{ updateDraftFromSlider\('max'\); \}\);/, 'max slider input should only update draft values');
  assert.match(block, /addEventListener\('change', commitDraftScoreRange\)/, 'slider should commit score range on change');
  assert.match(block, /addEventListener\('pointerup', commitDraftScoreRange\)/, 'slider should commit score range on pointer release');
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
  assert.match(block, /getFilterDisplayValue\(k\)/, 'resolution should display a localized none value for missing metadata via centralized mapper');
  assert.doesNotMatch(block, /provider-pill/, 'resolution should no longer render legacy pill markup');
});

test('renderFolderFilter uses shared dropdown with include/exclude toggles', () => {
  const block = functionBlock(appSource, 'renderFolderFilter', 'qualityRangeLabel');
  assert.match(block, /renderFilterDropdown\(/, 'folders should reuse shared dropdown renderer');
  assert.match(block, /toggleFn:\s*'toggleFolderFilter'/, 'folders should use standard dropdown toggle');
  assert.match(block, /clearFn:\s*'clearFolderFilter'/, 'folders should use standard dropdown clear');
  assert.match(block, /onToggleExclude:\s*'toggleFolderExclude'/, 'folders should expose include\/exclude toggle');
  assert.match(block, /baseItems\('folder'\)/, 'folder counts should be scoped through shared baseItems logic');
});

test('loadLibrary resolves score feature from config first, then library metadata fallback', () => {
  const block = functionBlock(appSource, 'loadLibrary', '_dateYmd');
  assert.match(block, /resolveScoreEnabled\(libraryMetaScoreEnabled\)/, 'loadLibrary should use centralized score resolution');
  assert.doesNotMatch(block, /enableScore\s*=\s*data\.meta\.score_enabled/, 'loadLibrary should not directly trust stale library meta score flag');
});

test('loadSettings score toggle reflects effective runtime score state', () => {
  const block = functionBlock(settingsSource, 'loadSettings', 'toggleJsrFields');
  assert.match(block, /_rw\('cfgEnableScore', isScoreEnabled\(\)\);/, 'settings score checkbox should mirror effective score state');
  assert.doesNotMatch(block, /_rw\('cfgEnableScore', sys\.enable_score === true\);/, 'settings score checkbox should not depend on strict config boolean only');
});

test('codec filters keep UNKNOWN distinct from missing metadata', () => {
  const canonicalBlock = functionBlock(appSource, 'canonicalFilterMissingKey', 'normalizeFilterValue');
  assert.match(canonicalBlock, /if \(key === FILTER_NONE_KEY\) return FILTER_NONE_KEY;/, 'missing key mapper should only collapse explicit none placeholder');
  assert.doesNotMatch(canonicalBlock, /UNKNOWN/, 'missing key mapper should not collapse UNKNOWN into none');

  const codecFilterBlock = functionBlock(appSource, 'renderCodecFilter', 'renderAudioCodecFilter');
  assert.match(codecFilterBlock, /k === 'UNKNOWN' \? t\('filters\.unknown'\) : getFilterDisplayValue\(k\)/, 'video codec filter should display UNKNOWN with a distinct label');

  const audioCodecBlock = functionBlock(appSource, 'getAudioCodecDisplay', 'getNormalizedVideoCodec');
  assert.match(audioCodecBlock, /if \(normalized === 'UNKNOWN'\) return t\('filters\.unknown'\);/, 'audio codec display should keep UNKNOWN distinct');
});

test('tile metadata ellipsis pill can shrink in compact rows', () => {
  assert.match(appCss, /\.tl-meta-row\.tl-meta-row-ellipsis \.tl-pill-ellipsis\{flex:1 1 auto;min-width:0\}/, 'ellipsis pill should be shrinkable to preserve other compact badges');
});

test('audio language simplified stats keep all categories without auto-grouping into others', () => {
  const statsPanelBlock = functionBlock(statsSource, 'buildStatsData', 'makePie');
  assert.match(statsPanelBlock, /hasData:\s*Object\.keys\(byAudioLangCount\)\.length > 0/, 'audio language chart should be based on all simplified categories');
  assert.match(statsPanelBlock, /entriesCount:\s*Object\.entries\(byAudioLangCount\)\.sort\(/, 'audio language counts should be passed through without threshold grouping');
  assert.match(statsPanelBlock, /entriesSize:\s*Object\.entries\(byAudioLangSize\)\.sort\(/, 'audio language sizes should be passed through without threshold grouping');
  assert.doesNotMatch(statsPanelBlock, /audioLangThreshold/, 'audio language chart should not apply a 1% threshold');
  assert.doesNotMatch(statsPanelBlock, /audioLangOthersCount|audioLangOthersSize/, 'audio language chart should not aggregate categories into an others bucket');
});

test('filter order is centralized and explicit for desktop and mobile', () => {
  assert.match(appSource, /const FILTER_ORDER = \[\s*'type',\s*'folder',\s*'streaming',\s*'resolution',\s*'video_codec',\s*'audio_codec',\s*'audio_language',\s*'score'\s*\];/, 'filter order should be declared once in a stable canonical list');
  const reorderBlock = functionBlock(appSource, 'ensureScoreFilterLast', '_dropdownSelectAll');
  assert.match(reorderBlock, /const desktopOrder = \['type', \.\.\.FILTER_ORDER\.filter\(k => k !== 'type'\), 'storage'\];/, 'desktop order should be derived from centralized filter order');
  assert.match(reorderBlock, /const mobileOrder = \['type', \.\.\.FILTER_ORDER\.filter\(k => k !== 'type'\), 'storage'\];/, 'mobile order should be derived from the same centralized filter order');
});

test('score filter UI uses a standard section label and avoids header range duplication', () => {
  const block = functionBlock(appSource, 'renderQualityFilter', 'renderResolutionFilter');
  assert.match(block, /<div class=\"storage-title\">' \+ t\('filters\.score'\) \+ '<\/div>'/, 'score filter should render a standard section title above its panel');
  assert.match(block, /score-filter-current/, 'score filter should expose current selected range in its body');
  assert.doesNotMatch(block, /score-filter-title/, 'score filter should not use a custom embedded title row');
  assert.doesNotMatch(block, /score-filter-range/, 'score filter should not render the old top-right range label');
});
