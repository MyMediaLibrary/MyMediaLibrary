import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const appSource = fs.readFileSync(path.resolve(__dirname, '../../../app/js/app.js'), 'utf8');
const appCss = fs.readFileSync(path.resolve(__dirname, '../../../app/css/app.css'), 'utf8');
const settingsSource = fs.readFileSync(path.resolve(__dirname, '../../../app/js/settings.js'), 'utf8');
const statsSource = fs.readFileSync(path.resolve(__dirname, '../../../app/js/stats.js'), 'utf8');

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

test('loadLibrary resolves score feature from runtime config only', () => {
  const block = functionBlock(appSource, 'loadLibrary', '_dateYmd');
  assert.match(block, /enableScore = resolveScoreEnabled\(\);/, 'loadLibrary should resolve score from centralized config-driven helper');
  assert.doesNotMatch(block, /data\.meta/, 'loadLibrary should not depend on library meta payload');
  assert.doesNotMatch(block, /data\.config/, 'loadLibrary should not depend on embedded config payload');
});

test('loadLibrary restores active tab only after data is loaded', () => {
  const block = functionBlock(appSource, 'loadLibrary', '_dateYmd');
  assert.match(block, /window\.MMLState\.isLoaded\s*=\s*true;/, 'loadLibrary should mark state as loaded before tab switch');
  assert.match(block, /switchTab\(currentTab\);/, 'loadLibrary should re-render the active tab after loading data');
});

test('loadLibrary treats missing library.json as a first-run/empty-library state (no hard error)', () => {
  const block = functionBlock(appSource, 'loadLibrary', '_dateYmd');
  assert.match(block, /if \(r\.status === 404\) \{/, 'loadLibrary should branch explicitly on library.json 404');
  assert.match(block, /finishWithEmptyLibrary\(\);/, 'loadLibrary should provide a non-error empty-library fallback when onboarding is complete');
  assert.match(block, /finishWithOnboarding\(\);/, 'loadLibrary should keep onboarding flow when onboarding is still required');
  assert.doesNotMatch(block, /if \(r\.status === 404[\s\S]*throw new Error\('HTTP '\+r\.status\)/, 'loadLibrary should not throw a generic HTTP error for expected missing library.json');
});

test('loadSettings score toggle reflects effective runtime score state', () => {
  const block = functionBlock(settingsSource, 'loadSettings', 'toggleJsrFields');
  assert.match(block, /_rw\('cfgEnableScore', isScoreEnabled\(\)\);/, 'settings score checkbox should mirror effective score state');
  assert.doesNotMatch(block, /_rw\('cfgEnableScore', sys\.enable_score === true\);/, 'settings score checkbox should not depend on strict config boolean only');
});

test('score settings tab loads schema dynamically from dedicated API', () => {
  assert.match(settingsSource, /async function loadScoreSettings\(\)/, 'loadScoreSettings should be defined');
  assert.match(settingsSource, /fetch\('\/api\/settings\/score'\)/, 'score settings should be fetched from dedicated score API');
  assert.match(settingsSource, /_scoreSettingsDraft = _cloneJson\(_scoreSettingsMeta\.effective \|\| \{\}\);/, 'score settings should render from effective backend payload');
});

test('score settings save/reset call score-only endpoints', () => {
  assert.match(settingsSource, /async function _persistScoreSettings\(\)/, 'global score persistence helper should be defined');
  assert.match(settingsSource, /fetch\('\/api\/settings\/score', \{[\s\S]*method: 'PUT'/, 'score save should use PUT score endpoint');
  assert.match(settingsSource, /async function resetScoreSettings\(\)/, 'resetScoreSettings should be defined');
  assert.match(settingsSource, /fetch\('\/api\/settings\/score\/reset', \{[\s\S]*method: 'POST'/, 'score reset should use POST endpoint');
});

test('score tab uses global settings save and no dedicated score save button', () => {
  assert.match(settingsSource, /_isScoreTabActive\(\)/, 'settings should detect active score tab');
  assert.match(settingsSource, /await _persistScoreSettings\(\);/, 'global save should persist score configuration from score tab');
  assert.doesNotMatch(settingsSource, /window\.saveScoreSettings\s*=/, 'legacy dedicated score save export should be removed');
});

test('score settings use shared collapsible style and dynamic label fallback', () => {
  assert.match(settingsSource, /function _scoreLabel\(/, 'score label resolver should exist');
  assert.match(settingsSource, /settings\.score\.labels\./, 'score label resolver should use i18n mappings');
  assert.match(settingsSource, /function _humanizeScoreKey\(/, 'score label resolver should support humanized fallback');
  assert.match(settingsSource, /class=\"settings-collapsible\"/, 'score sections should reuse shared settings collapsible style');
});

test('score settings do not render a penalties section anymore', () => {
  assert.doesNotMatch(settingsSource, /function _renderScorePenalties\(/, 'penalties renderer should be removed');
  assert.match(settingsSource, /if \(key === 'weights' \|\| key === 'penalties'\) return;/, 'legacy penalties key should be ignored when rendering sections');
});

test('score weights renderer outputs dedicated grid container', () => {
  const block = functionBlock(settingsSource, '_renderScoreWeights', '_scoreSectionHelp');
  assert.match(block, /class=\"score-weights-grid\"/, 'weights block should render a dedicated grid container');
  assert.match(block, /settings\.score\.summary_pattern/, 'weights block should render score summary line');
  assert.match(block, /score-validation-status/, 'weights block should render a validation status');
  assert.match(block, /score-weights-total[\s\S]*score-validation-status/s, 'validation status should render just below total in the weights card');
  assert.match(settingsSource, /const _WEIGHT_KEYS = \['video', 'audio', 'languages', 'size'\];/, 'weights should use canonical keys');
  assert.match(settingsSource, /function _sumCanonicalWeights\(/, 'weights total should be centralized with canonical keys');
});

test('score weights invalid state should not use top status banner', () => {
  const renderBlock = functionBlock(settingsSource, '_renderScoreSettings', '_refreshScoreWeightStatusOnly');
  const refreshMatch = settingsSource.match(/function _refreshScoreWeightStatusOnly\(\)[\s\S]*?async function loadScoreSettings\(\)/);
  const refreshBlock = refreshMatch ? refreshMatch[0] : '';
  assert.doesNotMatch(renderBlock, /_setScoreStatus\(_scoreT\('settings\.score\.invalid_total'/, 'weights validation should not be rendered in top score status banner');
  assert.ok(refreshBlock.length > 0, 'refresh weights block should be found');
  assert.doesNotMatch(refreshBlock, /_setScoreStatus\(_scoreT\('settings\.score\.invalid_total'/, 'live weights validation should stay inside weights card');
  assert.doesNotMatch(settingsSource, /Object\.values\(weights\)\.reduce/, 'weights total must not sum unknown extra keys');
});

test('score enabled toggle updates score tab immediately without modal reopen', () => {
  assert.match(settingsSource, /const _scoreEnableEl = document\.getElementById\('cfgEnableScore'\);/, 'settings should bind a change listener on cfgEnableScore');
  assert.match(settingsSource, /_scoreEnableEl\.addEventListener\('change', function \(\) \{[\s\S]*_renderScoreSettings\(\);/s, 'score toggle change should immediately rerender score tab');
  const switchStabBlock = functionBlock(settingsSource, 'switchStab', 'applySettingsMobileLayout');
  assert.match(switchStabBlock, /else _renderScoreSettings\(\);/, 'switching back to score tab should refresh according to current local toggle state');
});

test('score settings render guided help and size min\/max layout', () => {
  assert.match(settingsSource, /function _scoreSectionHelp\(/, 'score section help resolver should exist');
  assert.match(settingsSource, /score-section-help/, 'score sections should render short help text');
  assert.match(settingsSource, /function _renderSizeProfiles\(/, 'size section should use dedicated renderer');
  assert.match(settingsSource, /function _renderMinMaxRange\(/, 'size renderer should support min\/max range rows');
  assert.match(settingsSource, /settings\.score\.labels\.min_short/, 'min\/max labels should use i18n keys');
  assert.match(settingsSource, /sectionKey === 'video'/, 'video section should have dedicated rendering');
  assert.match(settingsSource, /score-nested-collapsible/, 'video sub-sections should reuse collapsible UI');
  assert.match(appCss, /\.score-size-layout\{display:grid;grid-template-columns:1fr;gap:10px\}/, 'size section should be single-column to avoid overlap');
});

test('settings trigger scan only when folders changed', () => {
  const shouldTriggerScanBlock = functionBlock(settingsSource, 'shouldTriggerScan', 'renderProviderToggles');
  assert.match(shouldTriggerScanBlock, /_foldersScanSignature\(oldConfig\?\.folders \|\| \[\]\)/, 'scan trigger helper should compare previous folder snapshot');
  assert.match(shouldTriggerScanBlock, /_foldersScanSignature\(newConfig\.folders\)/, 'scan trigger helper should compare new folder snapshot');
  assert.match(shouldTriggerScanBlock, /return prevSig !== nextSig;/, 'scan trigger helper should only trigger on actual folder diff');

  const saveSettingsBlock = functionBlock(settingsSource, 'saveSettingsAndClose', 'onFolderTypeChange');
  assert.match(saveSettingsBlock, /shouldTriggerScan\(appConfig, \{ folders: folderUpdates \}\)/, 'settings save should gate folder payload behind shouldTriggerScan');
});

test('restoreState defers stats tab render until library load is complete', () => {
  const block = functionBlock(appSource, 'restoreState');
  assert.match(block, /currentTab = s\.currentTab;/, 'restoreState should persist desired tab');
  assert.doesNotMatch(block, /switchTab\(s\.currentTab\)/, 'restoreState should not render stats early before data load completion');
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

test('settings persist only providers visibility whitelist (no provider types)', () => {
  const saveSettingsBlock = functionBlock(settingsSource, 'saveSettingsAndClose', 'onFolderTypeChange');
  assert.match(saveSettingsBlock, /partial\.providers_visible = provVis;/, 'settings save should persist selected providers whitelist');
  assert.doesNotMatch(saveSettingsBlock, /providers_visible_types/, 'settings save should not persist provider type config');
});

test('stats providers rely on flat provider lists', () => {
  const buildStatsBlock = functionBlock(statsSource, 'buildStatsData', 'getScopedProviders');
  assert.match(buildStatsBlock, /getScopedProviders\(i\)/, 'stats should aggregate providers from selected provider types');
  assert.doesNotMatch(buildStatsBlock, /providers\.flatrate/, 'stats should not rely on flatrate-only provider extraction');
});

test('provider count chart displays raw counts without "media" unit suffix', () => {
  const block = functionBlock(statsSource, 'buildStats', 'renderStatsPanel');
  assert.match(block, /valueFormatter:\s*\(value\)\s*=>\s*String\(value\)/, 'provider count values should be displayed as raw numbers');
  assert.doesNotMatch(block, /stats\.media_count/, 'provider count chart should not append "media" unit text');
});

test('provider size chart uses library-size reference base (not cumulative provider-size base)', () => {
  const dataBlock = functionBlock(statsSource, 'buildStatsData', 'getScopedProviders');
  assert.match(dataBlock, /referenceSize:\s*items\.reduce\(\(sum, i\) => sum \+ \(i\.size_b \|\| 0\), 0\)/, 'provider stats should expose unique library-size reference base');

  const renderBlock = functionBlock(statsSource, 'buildStats', 'renderStatsPanel');
  assert.match(renderBlock, /size:\s*\{\s*percentBase:\s*Number\(provReferenceSize \|\| 0\)/, 'provider size pie should compute percentages against library-size reference base');
});

test('providers catalog loads runtime mapping API and logo catalog', () => {
  const block = functionBlock(appSource, 'loadProvidersCatalog');
  assert.match(block, /fetch\('\/api\/providers-map\?_=' \+ Date\.now\(\)\)/, 'providers mapping should come from runtime API');
  assert.match(block, /fetch\('\/providers_logo\.json\?_=' \+ Date\.now\(\)\)/, 'providers logos should come from dedicated logo catalog');
  assert.doesNotMatch(block, /\/providers\.json/, 'legacy providers.json bundle should no longer drive mapping');
});

test('provider resolution maps null-or-missing entries to Autres with logo fallback', () => {
  const block = functionBlock(appSource, 'resolveProvider', 'getProviderNames');
  assert.match(block, /const normalizedName =[\s\S]*\? mappedValue\.trim\(\)[\s\S]*: 'Autres';/, 'unmapped providers should resolve to Autres');
  assert.match(block, /PROVIDERS_LOGOS\[normalizedName\] \|\| PROVIDERS_LOGOS\['Autres'\]/, 'provider logo should fallback to Autres logo');
});

test('displayed providers are deduplicated post-mapping and ordered with Autres last', () => {
  const block = functionBlock(appSource, 'getDisplayedProviders', '_providerGroupKey');
  assert.match(block, /if \(!grouped\.has\(displayName\)\) grouped\.set\(displayName, resolved\);/, 'displayed providers should deduplicate after mapping');
  assert.match(block, /return a\.name\.localeCompare\(b\.name, undefined, \{ sensitivity: 'base' \}\);/, 'mapped providers should be sorted alphabetically');
  assert.match(block, /if \(aIsOthers && !bIsOthers\) return 1;/, 'Autres should be sorted after mapped providers');
  assert.match(block, /name: _isOthersProviderName\(entry\.name\) \? DISPLAY_OTHERS_NAME : entry\.name/, 'Autres display label should be normalized once');
});

test('provider exclude requires at least one remaining non-Autres provider', () => {
  const block = functionBlock(appSource, '_matchesProviderFilters', '_canonicalProviderFilterKey');
  assert.match(block, /return remaining\.some\(\(p\) => p !== PROVIDER_OTHERS_KEY\);/, 'exclude mode should keep item only when a non-Autres provider remains');
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
