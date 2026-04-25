/**
 * MyMediaLibrary — Stats Panel Module
 * Extracted from app.js
 *
 * Internal structure:
 *   DATA LAYER    — buildStatsData(items) computes all aggregations
 *   RENDER LAYER  — primitives (makePie, makeCurve, makeVBar, switchablePie)
 *                   and assembly (buildStats, buildYearChart, buildCurveForPeriod)
 *
 * Dependencies are provided via init() to make them explicit.
 * Falls back to window.* if not initialized.
 */

(function() {
  'use strict';

  // ── MODULE DEPENDENCIES ──────────────────────────────────
  let deps = {
    filterItems: null,
    allItems: null,
    PALETTE: null,
    PROVIDER_OTHERS_KEY: null,
    getNormalizedVideoCodec: null,
    getNormalizedAudioCodec: null,
    getNormalizedResolution: null,
    getAudioLanguageSimple: null,
    getAudioLanguageSimpleDisplay: null,
    getAudioCodecDisplay: null,
    getFilterDisplayValue: null,
    getNormalizedGenres: null,
    getGenreDisplay: null,
    getNormalizedAudioChannels: null,
    getEnabledProvidersForItem: null,
    _itemProviderGroups: null,
    _providerGroupKey: null,
    _providerGroupLabel: null,
    _pname: null,
    _plogo: null,
    t: null,
    fmtSize: null,
    escH: null,
    MMLLogic: null,
    applyStatsFilter: null,
    isRecommendationsEnabled: null,
    visibleRecommendations: null,
    renderRecommendationFilterButtons: null,
    recPriorityLabel: null,
    recTypeLabel: null,
    recMedia: null,
    recScore: null,
    recSizeBytes: null,
    recommendationPriorityFilters: null,
    recommendationTypeFilters: null,
  };
  const STATS_SUBTABS = ['general', 'technical', 'evolution', 'recommendations'];
  const RECOMMENDATION_PRIORITIES = ['high', 'medium', 'low'];
  const RECOMMENDATION_TYPES = ['quality', 'space', 'languages', 'series', 'data'];
  const STATS_GENRE_OTHERS_KEY = '__genre_others__';
  let activeStatsSubtab = 'general';

  function getDep(name) {
    return deps[name] !== null && deps[name] !== undefined ? deps[name] : window[name];
  }

  function init(injectedDeps) {
    Object.assign(deps, injectedDeps || {});
  }

  // ── EVENT DELEGATION ─────────────────────────────────────
  function initializeEventHandlers() {
    document.addEventListener('click', (e) => {
      if (e.target.classList?.contains('pie-switch-btn')) {
        const handler = e.target.dataset.pie;
        if (handler) statSwitchPie(e.target);
      }
    });

    document.addEventListener('click', (e) => {
      if (e.target.dataset.period) {
        const curveControls = document.getElementById('curveControls');
        if (curveControls?.contains(e.target)) setCurvePeriod(e.target);
      }
    });

    document.addEventListener('click', (e) => {
      if (e.target.dataset.yearPeriod) {
        const yearControls = document.getElementById('yearControls');
        if (yearControls?.contains(e.target)) setYearPeriod(e.target);
      }
    });

    document.addEventListener('click', (e) => {
      if (!e.target.dataset.statsSubtab) return;
      const tabsHost = document.getElementById('statsSubtabs');
      if (tabsHost?.contains(e.target)) setStatsSubtab(e.target);
    });

    document.addEventListener('click', (e) => {
      const target = e.target.closest?.('[data-stats-filter-kind]');
      if (!target) return;
      const statsHost = document.getElementById('statsContent');
      if (!statsHost?.contains(target)) return;
      const kind = target.dataset.statsFilterKind;
      const value = target.dataset.statsFilterValue;
      if (!kind || value === undefined) return;
      const applyStatsFilter = getDep('applyStatsFilter');
      if (typeof applyStatsFilter !== 'function') return;
      applyStatsFilter(kind, value, {
        min: target.dataset.statsFilterMin,
        max: target.dataset.statsFilterMax,
      });
    });

    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const target = e.target.closest?.('[data-stats-filter-kind]');
      if (!target) return;
      const statsHost = document.getElementById('statsContent');
      if (!statsHost?.contains(target)) return;
      e.preventDefault();
      target.click();
    });

  }

  // ══════════════════════════════════════════════════════════
  //  DATA LAYER — pure aggregations, no HTML
  // ══════════════════════════════════════════════════════════

  function mapToSortedEntries(mapObj) {
    return Object.entries(mapObj).sort((a, b) => b[1] - a[1]);
  }

  function buildGenreTopEntries(byGenreMetric, items) {
    const sorted = mapToSortedEntries(byGenreMetric);
    const topEntries = sorted.slice(0, 12);
    const topKeys = new Set(topEntries.map(([genre]) => genre));
    const uncoveredItems = items.filter((item) => {
      const genres = getDep('getNormalizedGenres')(item);
      return !genres.some((genre) => topKeys.has(genre));
    });
    const othersCount = uncoveredItems.length;
    return [...topEntries, [STATS_GENRE_OTHERS_KEY, othersCount]];
  }

  function buildStatsData(items) {
    const C = window.MMLConstants.CHARTS;
    const NONE_KEY = window.MMLConstants.PROVIDER_NONE_KEY;

    // ── Category (folder) ────────────────────────────────────
    const byCategory = {}, byCategoryCount = {};
    items.forEach(i => {
      const c = i.category || i.group || '?';
      byCategory[c]      = (byCategory[c]      || 0) + (i.size_b || 0);
      byCategoryCount[c] = (byCategoryCount[c] || 0) + 1;
    });
    const category = {
      entriesSize:  Object.entries(byCategory).sort((a,b) => b[1]-a[1]),
      entriesCount: Object.entries(byCategoryCount).sort((a,b) => b[1]-a[1]),
    };

    // ── Video codec ──────────────────────────────────────────
    const byCodec = {}, byCodecCount = {};
    items.forEach(i => {
      const k = getDep('getNormalizedVideoCodec')(i);
      byCodec[k]      = (byCodec[k]      || 0) + (i.size_b || 0);
      byCodecCount[k] = (byCodecCount[k] || 0) + 1;
    });
    const codec = {
      entriesSize:  Object.entries(byCodec).sort((a,b) => b[1]-a[1]),
      entriesCount: Object.entries(byCodecCount).sort((a,b) => b[1]-a[1]),
    };

    // ── Audio codec ──────────────────────────────────────────
    const byAudioCodec = {}, byAudioCodecCount = {};
    items.forEach(i => {
      const k = getDep('getNormalizedAudioCodec')(i);
      byAudioCodec[k]      = (byAudioCodec[k]      || 0) + (i.size_b || 0);
      byAudioCodecCount[k] = (byAudioCodecCount[k] || 0) + 1;
    });
    const audioCodec = {
      entriesSize:  Object.entries(byAudioCodec).sort((a,b) => b[1]-a[1]),
      entriesCount: Object.entries(byAudioCodecCount).sort((a,b) => b[1]-a[1]),
    };

    // ── Audio languages ──────────────────────────────────────
    const byAudioLangCount = {}, byAudioLangSize = {};
    items.forEach(i => {
      const k = getDep('getAudioLanguageSimple')(i);
      byAudioLangCount[k] = (byAudioLangCount[k] || 0) + 1;
      byAudioLangSize[k]  = (byAudioLangSize[k]  || 0) + (i.size_b || 0);
    });
    const audioLang = {
      entriesCount: Object.entries(byAudioLangCount).sort((a,b) => b[1]-a[1]),
      entriesSize:  Object.entries(byAudioLangSize).sort((a,b) => b[1]-a[1]),
      hasData:      Object.keys(byAudioLangCount).length > 0,
    };

    // ── Genres ───────────────────────────────────────────────
    const byGenreCount = {};
    items.forEach((item) => {
      const genres = getDep('getNormalizedGenres')(item);
      genres.forEach((genre) => {
        byGenreCount[genre] = (byGenreCount[genre] || 0) + 1;
      });
    });
    const genres = {
      entriesCount: buildGenreTopEntries(byGenreCount, items),
      hasData: items.length > 0,
      referenceCount: items.length,
    };

    // ── Audio channels ───────────────────────────────────────
    const byAudioChannelsCount = {}, byAudioChannelsSize = {};
    items.forEach((item) => {
      const channel = getDep('getNormalizedAudioChannels')(item);
      byAudioChannelsCount[channel] = (byAudioChannelsCount[channel] || 0) + 1;
      byAudioChannelsSize[channel] = (byAudioChannelsSize[channel] || 0) + (item.size_b || 0);
    });
    const audioChannels = {
      entriesCount: mapToSortedEntries(byAudioChannelsCount),
      entriesSize: mapToSortedEntries(byAudioChannelsSize),
      hasData: Object.keys(byAudioChannelsCount).length > 0,
    };

    // ── Resolution ───────────────────────────────────────────
    const byRes = {}, byResCount = {};
    items.forEach(i => {
      const r = getDep('getNormalizedResolution')(i);
      byRes[r]      = (byRes[r]      || 0) + (i.size_b || 0);
      byResCount[r] = (byResCount[r] || 0) + 1;
    });
    const RES_ORDER = [...C.RESOLUTION_ORDER, NONE_KEY];
    const resRemaining = Object.keys(byRes).filter((r) => !RES_ORDER.includes(r));
    const resolution = {
      entriesSize:  [
        ...RES_ORDER.filter(r => byRes[r]).map(r => [r, byRes[r]]),
        ...resRemaining.filter(r => byRes[r]).map(r => [r, byRes[r]])
      ],
      entriesCount: [
        ...RES_ORDER.filter(r => byResCount[r]).map(r => [r, byResCount[r]]),
        ...resRemaining.filter(r => byResCount[r]).map(r => [r, byResCount[r]])
      ],
    };

    // ── Providers ────────────────────────────────────────────
    const groupedProviderCount = getDep('MMLLogic')?.groupedProviderCounts
      ? getDep('MMLLogic').groupedProviderCounts(items, getDep('_providerGroupKey'), getDep('_pname'))
      : (() => {
          const fb = {};
          items.forEach(i => getDep('_itemProviderGroups')(i).forEach(name => {
            fb[name] = (fb[name] || 0) + 1;
          }));
          return fb;
        })();

    const byProv = {};
    Object.entries(groupedProviderCount).forEach(([name, count]) => {
      byProv[name] = { count, logo: '' };
    });
    items.forEach(i => getScopedProviders(i).forEach(p => {
      const rawName = getDep('_pname')(p);
      const name    = getDep('_providerGroupKey')(rawName);
      if (!name || !byProv[name] || name === getDep('PROVIDER_OTHERS_KEY')) return;
      if (!byProv[name].logo) byProv[name].logo = getDep('_plogo')(p);
    }));

    const byProvSize = {};
    items.forEach(i => {
      getDep('_itemProviderGroups')(i).forEach(name => {
        byProvSize[name] = (byProvSize[name] || 0) + (i.size_b || 0);
      });
    });

    const providers = {
      entries:   Object.entries(byProv).sort((a,b) => b[1].count - a[1].count),
      bySize:    byProvSize,
      noneCount: items.filter(i => !getScopedProviders(i).length).length,
      noneSize:  items.filter(i => !getScopedProviders(i).length).reduce((s,i) => s+(i.size_b||0), 0),
      referenceCount: items.length,
      referenceSize: items.reduce((sum, i) => sum + (i.size_b || 0), 0),
    };

    // ── Timeline (daily + monthly buckets) ───────────────────
    const allByDay = {};
    items.forEach(i => {
      if (!i.added_at) return;
      const d   = new Date(i.added_at);
      const key = d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
      if (!allByDay[key]) allByDay[key] = { count: 0, size: 0 };
      allByDay[key].count++;
      allByDay[key].size += i.size_b || 0;
    });
    const allByMonth = {};
    Object.entries(allByDay).forEach(([k,v]) => {
      const mk = k.slice(0, 7);
      if (!allByMonth[mk]) allByMonth[mk] = { count: 0, size: 0 };
      allByMonth[mk].count += v.count;
      allByMonth[mk].size  += v.size;
    });
    const timeline = {
      allByDay,
      allByMonth,
      hasEnoughData: Object.keys(allByMonth).length >= 2,
    };

    // ── Release years ────────────────────────────────────────
    const byYearCount = {};
    items.forEach(i => {
      if (!i.year) return;
      const y = String(i.year);
      byYearCount[y] = (byYearCount[y] || 0) + 1;
    });
    const years = {
      entriesCount: Object.keys(byYearCount)
        .sort((a,b) => Number(a)-Number(b))
        .map(y => [y, byYearCount[y]]),
    };

    // ── Quality score distribution ────────────────────────────
    const qc = C.COLORS.QUALITY;
    const qualityTranches = [
      { key: 'range_0_20',   min:  0, max:  20, color: qc[0], label: getDep('t')('filters.score.range_0_20')   },
      { key: 'range_20_40',  min: 21, max:  40, color: qc[1], label: getDep('t')('filters.score.range_20_40')  },
      { key: 'range_40_60',  min: 41, max:  60, color: qc[2], label: getDep('t')('filters.score.range_40_60')  },
      { key: 'range_60_80',  min: 61, max:  80, color: qc[3], label: getDep('t')('filters.score.range_60_80')  },
      { key: 'range_80_100', min: 81, max: 100, color: qc[4], label: getDep('t')('filters.score.range_80_100') },
    ];
    const qualityCounts = qualityTranches.map(() => 0);
    let totalScore = 0, scoredCount = 0;
    items.forEach(i => {
      if (!i.quality) return;
      const s = Number(i.quality.score);
      if (!Number.isFinite(s)) return;
      totalScore += s; scoredCount++;
      const idx = qualityTranches.findIndex(tr => s >= tr.min && s <= tr.max);
      if (idx >= 0) qualityCounts[idx]++;
    });
    const quality = {
      tranches:    qualityTranches,
      counts:      qualityCounts,
      maxCount:    Math.max(...qualityCounts, 0),
      avgScore:    scoredCount ? (totalScore / scoredCount).toFixed(1) : null,
      scoredCount,
      hasData:     getDep('allItems').some(i => i.quality),
    };

    return { category, genres, codec, audioCodec, audioLang, audioChannels, resolution, providers, timeline, years, quality };
  }

  function getScopedProviders(item) {
    const enabled = getDep('getEnabledProvidersForItem');
    if (typeof enabled === 'function') return enabled(item);
    const fromDep = getDep('getItemProviders');
    if (typeof fromDep === 'function') return fromDep(item);
    const providers = item?.providers;
    if (providers && typeof providers === 'object' && !Array.isArray(providers)) {
      return Object.values(providers)
        .filter((values) => Array.isArray(values))
        .flat();
    }
    return Array.isArray(providers) ? providers : [];
  }

  // ══════════════════════════════════════════════════════════
  //  RENDER PRIMITIVES — pure SVG/HTML generators
  // ══════════════════════════════════════════════════════════

  function isStatsOtherValue(key) {
    return key === STATS_GENRE_OTHERS_KEY
      || key === getDep('PROVIDER_OTHERS_KEY')
      || key === getDep('t')('stats.others');
  }

  function statsFilterAttrs(kind, key, label, extra = {}, className = 'stats-clickable') {
    if (!kind || key === undefined || key === null || isStatsOtherValue(key)) return '';
    const escH = getDep('escH');
    let attrs = ' class="'+escH(className)+'" role="button" tabindex="0"'
      + ' data-stats-filter-kind="'+escH(kind)+'"'
      + ' data-stats-filter-value="'+escH(String(key))+'"'
      + ' title="'+escH(getDep('t')('stats.filter_on', { value: label }))+'"';
    if (extra.min !== undefined) attrs += ' data-stats-filter-min="'+escH(String(extra.min))+'"';
    if (extra.max !== undefined) attrs += ' data-stats-filter-max="'+escH(String(extra.max))+'"';
    return attrs;
  }

  function makePie(entries, colorFn, valFn, labelFn, fmtFn, options = {}) {
    const total = entries.reduce((s,[,v]) => s+valFn(v), 0);
    if (!total) return '';
    const percentBase = Number.isFinite(Number(options.percentBase)) && Number(options.percentBase) > 0
      ? Number(options.percentBase)
      : total;
    const formatPercent = (value) => `${((value / percentBase) * 100).toFixed(1)}%`;
    const formatValue = typeof options.valueFormatter === 'function'
      ? options.valueFormatter
      : (value) => fmtFn(value);
    const R=70, CX=80, CY=80, SIZE=160;
    let angle = -Math.PI/2, slices = '';
    entries.forEach(([k,v], idx) => {
      const val  = valFn(v);
      const frac = val/total;
      const a1   = angle, a2 = angle + frac*2*Math.PI;
      const x1=CX+R*Math.cos(a1), y1=CY+R*Math.sin(a1);
      const x2=CX+R*Math.cos(a2), y2=CY+R*Math.sin(a2);
      const large = frac > 0.5 ? 1 : 0;
      const col   = colorFn(k, idx);
      const label = labelFn(k);
      const attrs = statsFilterAttrs(options.filterKind, k, label);
      if (frac > 0.999) {
        slices += '<circle cx="'+CX+'" cy="'+CY+'" r="'+R+'" fill="'+col+'"'+attrs+'><title>'+getDep('escH')(label)+' — '+formatValue(val)+' ('+formatPercent(val)+')</title></circle>';
      } else {
        slices += '<path d="M'+CX+','+CY+' L'+x1.toFixed(2)+','+y1.toFixed(2)+' A'+R+','+R+' 0 '+large+',1 '+x2.toFixed(2)+','+y2.toFixed(2)+' Z" fill="'+col+'"'+attrs+'><title>'+getDep('escH')(label)+' — '+formatValue(val)+' ('+formatPercent(val)+')</title></path>';
      }
      angle = a2;
    });
    slices += '<circle cx="'+CX+'" cy="'+CY+'" r="'+(R*0.52)+'" fill="var(--surface)"/>';
    slices += '<text x="'+CX+'" y="'+(CY-7)+'" text-anchor="middle" font-size="11" font-weight="700" fill="var(--text)">'+entries.length+'</text>';
    slices += '<text x="'+CX+'" y="'+(CY+8)+'" text-anchor="middle" font-size="9" fill="var(--muted)">'+(entries.length>1?getDep('t')('stats.entries'):getDep('t')('stats.entry'))+'</text>';
    const svg    = '<svg viewBox="0 0 '+SIZE+' '+SIZE+'" width="'+SIZE+'" height="'+SIZE+'" style="flex-shrink:0">'+slices+'</svg>';
    const legend = '<div class="pie-legend">'+entries.slice(0,12).map(([k,v],idx) => {
      const val=valFn(v);
      const label = labelFn(k);
      const rowAttrs = statsFilterAttrs(options.filterKind, k, label, {}, 'pie-leg-row stats-clickable') || ' class="pie-leg-row"';
      return '<div'+rowAttrs+'>'
        +'<div class="pie-leg-dot" style="background:'+colorFn(k,idx)+'"></div>'
        +'<div class="pie-leg-label" title="'+getDep('escH')(label)+'">'+getDep('escH')(label)+'</div>'
        +'<div class="pie-leg-val">'+formatValue(val)+'</div>'
        +'<div class="pie-leg-pct">'+formatPercent(val)+'</div>'
        +'</div>';
    }).join('')+(entries.length>12?'<div style="font-size:11px;color:var(--muted);padding-top:2px">+' + (entries.length-12) + ' '+getDep('t')('stats.others')+'</div>':'')+'</div>';
    return '<div class="pie-wrap">'+svg+legend+'</div>';
  }

  function makeCurve(keys, vals, color, gradId, labelFn, titleFn) {
    const maxV = Math.max(...vals, 0);
    if (!maxV || keys.length < 2) return '<p style="font-size:12px;color:var(--muted)">'+getDep('t')('stats.not_enough_data')+'</p>';
    const W=800, H=140, PL=52, PR=16, PT=16, PB=28;
    const iW=W-PL-PR, iH=H-PT-PB, n=keys.length;
    const xs = keys.map((_,i) => PL+(n>1 ? i/(n-1)*iW : iW/2));
    const ys = vals.map(v => PT+iH-v/maxV*iH);
    const lineD = xs.map((x,i) => (i===0?'M':'L')+x.toFixed(1)+','+ys[i].toFixed(1)).join(' ');
    const areaD = lineD+' L'+xs[n-1].toFixed(1)+','+(PT+iH)+' L'+xs[0].toFixed(1)+','+(PT+iH)+' Z';
    let grid = '';
    for (let s=0; s<=3; s++) {
      const y2 = PT+iH-s/3*iH;
      grid += '<line x1="'+PL+'" y1="'+y2.toFixed(1)+'" x2="'+(W-PR)+'" y2="'+y2.toFixed(1)+'" stroke="var(--border)" stroke-width="1"/>';
      grid += '<text x="'+(PL-4)+'" y="'+(y2+4).toFixed(1)+'" text-anchor="end" font-size="9" fill="var(--muted)">'+labelFn(maxV*s/3)+'</text>';
    }
    const step = Math.max(1, Math.ceil(n/10));
    let xlbls = '';
    keys.forEach((k,i) => {
      if (i%step!==0 && i!==n-1) return;
      const parts = k.split('-');
      const lbl   = parts.length===3 ? parts[2]+'/'+parts[1] : parts[1]+'/'+parts[0].slice(2);
      xlbls += '<text x="'+xs[i].toFixed(1)+'" y="'+(PT+iH+16)+'" text-anchor="middle" font-size="9" fill="var(--muted)">'+lbl+'</text>';
    });
    const dots = xs.map((x,i) => '<circle cx="'+x.toFixed(1)+'" cy="'+ys[i].toFixed(1)+'" r="3" fill="'+color+'" stroke="var(--surface)" stroke-width="2"><title>'+keys[i]+' : '+titleFn(vals[i])+'</title></circle>').join('');
    return '<svg class="curve-svg" viewBox="0 0 '+W+' '+H+'" xmlns="http://www.w3.org/2000/svg">'
      +'<defs><linearGradient id="'+gradId+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="'+color+'" stop-opacity=".2"/><stop offset="100%" stop-color="'+color+'" stop-opacity="0"/></linearGradient></defs>'
      +grid+'<path d="'+areaD+'" fill="url(#'+gradId+')" />'
      +'<path d="'+lineD+'" fill="none" stroke="'+color+'" stroke-width="2" stroke-linejoin="round"/>'
      +dots+xlbls+'</svg>';
  }

  function makeVBar(entries, colorPalette) {
    if (!entries.length) return '';
    const maxVal = Math.max(...entries.map(e => e[1]), 0);
    if (!maxVal) return '';
    const W=800, H=160, PL=16, PR=16, PT=8, PB=40;
    const iW=W-PL-PR, iH=H-PT-PB, n=entries.length;
    const barWidth  = Math.max(6, Math.floor(iW/Math.max(n,1))-2);
    const spacing   = n>1 ? (iW-barWidth*n)/(n-1) : 0;
    const labelStep = Math.max(1, Math.ceil(n/12));
    let bars='', labels='', x=PL;
    entries.forEach(([label, val], idx) => {
      const barHeight = val/maxVal*iH;
      const y   = PT+iH-barHeight;
      const col = colorPalette[idx%colorPalette.length];
      bars   += '<rect x="'+x.toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+barWidth+'" height="'+barHeight.toFixed(1)+'" fill="'+col+'"><title>'+getDep('escH')(label)+' : '+val+'</title></rect>';
      if (idx%labelStep===0 || idx===n-1) {
        labels += '<text x="'+(x+barWidth/2).toFixed(1)+'" y="'+(PT+iH+20)+'" text-anchor="middle" font-size="11" fill="var(--muted)">'+getDep('escH')(label)+'</text>';
      }
      x += barWidth + spacing;
    });
    return '<svg class="curve-svg" viewBox="0 0 '+W+' '+H+'" xmlns="http://www.w3.org/2000/svg">'+bars+labels+'</svg>';
  }

  function switchablePie(id, title, sizeEntries, countEntries, colorFn, labelFn = k=>k, defaultUnit = 'size', options = {}) {
    const showCount = defaultUnit === 'count';
    const pieSize   = makePie(sizeEntries,  colorFn, v=>v, k=>labelFn(k), getDep('fmtSize'), { ...(options.size || {}), filterKind: options.filterKind });
    const pieCount  = makePie(countEntries, colorFn, v=>v, k=>labelFn(k), v=>String(v), { ...(options.count || {}), filterKind: options.filterKind });
    return '<div class="stats-block">'
      +'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border)">'
        +'<div class="stats-block-title" style="margin-bottom:0;padding-bottom:0;border-bottom:none">'+title+'</div>'
        +'<div class="pie-switch">'
          +'<button class="pie-switch-btn'+(showCount ? '' : ' active')+'" id="'+id+'BtnSize"  data-pie="'+id+'" data-unit="size"  >'+getDep('t')('stats.by_size')+'</button>'
          +'<button class="pie-switch-btn'+(showCount ? ' active' : '')+'" id="'+id+'BtnCount" data-pie="'+id+'" data-unit="count" >'+getDep('t')('stats.by_count')+'</button>'
        +'</div>'
      +'</div>'
      +'<div id="'+id+'PieSize"'+(showCount ? ' style="display:none"' : '')+'>'+pieSize+'</div>'
      +'<div id="'+id+'PieCount"'+(showCount ? '' : ' style="display:none"')+'>'+pieCount+'</div>'
      +'</div>';
  }

  function makeHorizontalBars(entries, labelFn, valueFormatter, percentBase, colorFn, options = {}) {
    if (!entries.length) return '';
    const maxValue = Math.max(...entries.map(([, value]) => Number(value) || 0), 0);
    if (!maxValue) return '';
    return '<div class="hbar-list">'
      +entries.map(([key, value], index) => {
        const numericValue = Number(value) || 0;
        const width = maxValue > 0 ? (numericValue / maxValue) * 100 : 0;
        const percent = percentBase > 0 ? Math.round((numericValue / percentBase) * 100) + ' %' : '0 %';
        const label = labelFn(key);
        const rowAttrs = statsFilterAttrs(options.filterKind, key, label, {}, 'hbar-item stats-clickable') || ' class="hbar-item"';
        return '<div'+rowAttrs+'>'
          +'<div class="hbar-label" title="'+getDep('escH')(label)+'">'+getDep('escH')(label)+'</div>'
          +'<div class="hbar-track"><div class="hbar-fill" style="width:'+width.toFixed(2)+'%;background:'+colorFn(key, index)+'"></div></div>'
          +'<div class="hbar-val">'+valueFormatter(numericValue)+' <span class="stat-row-sub">('+percent+')</span></div>'
          +'</div>';
      }).join('')
      +'</div>';
  }

  function getGenreLabel(key) {
    if (key === STATS_GENRE_OTHERS_KEY) return getDep('t')('stats.others');
    return getDep('getGenreDisplay')(key);
  }

  function renderGenresBlock(genreData) {
    if (!genreData.hasData) return '';
    const colorFn = (key, idx) => key === STATS_GENRE_OTHERS_KEY ? '#64748b' : getDep('PALETTE')[idx % getDep('PALETTE').length];
    const valueFormatter = (value) => String(Math.round(value));
    return '<div class="stats-block">'
      +'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border)">'
        +'<div class="stats-block-title" style="margin-bottom:0;padding-bottom:0;border-bottom:none">'+getDep('t')('stats.genres_chart_title')+'</div>'
      +'</div>'
      +makeHorizontalBars(genreData.entriesCount, getGenreLabel, valueFormatter, Number(genreData.referenceCount || 0), colorFn, { filterKind: 'genre' })
      +'</div>';
  }

  // ══════════════════════════════════════════════════════════
  //  RENDER LAYER — consume data, produce HTML
  // ══════════════════════════════════════════════════════════

  function buildYearChart(period, yearsData) {
    if (!yearsData.entriesCount.length) {
      return '<p style="font-size:12px;color:var(--muted)">'+getDep('t')('stats.not_enough_data')+'</p>';
    }
    let displayEntries = yearsData.entriesCount;
    if (period === 'decades') {
      const byDecade = {};
      yearsData.entriesCount.forEach(([y,v]) => {
        const decade    = Math.floor(Number(y)/10)*10;
        const decadeKey = decade+'-'+(decade+9);
        byDecade[decadeKey] = (byDecade[decadeKey] || 0) + v;
      });
      displayEntries = Object.entries(byDecade).sort((a,b) => Number(a[0].split('-')[0])-Number(b[0].split('-')[0]));
    }
    return makeVBar(displayEntries, getDep('PALETTE'));
  }

  function buildCurveForPeriod(period, timelineData) {
    const { allByDay, allByMonth } = timelineData;
    const now = new Date();
    let useDaily = false, curveKeys = [];
    if (period === '30d') {
      useDaily = true;
      const cutoff = new Date(now); cutoff.setDate(cutoff.getDate()-30);
      const ck = cutoff.getFullYear()+'-'+String(cutoff.getMonth()+1).padStart(2,'0')+'-'+String(cutoff.getDate()).padStart(2,'0');
      curveKeys = Object.keys(allByDay).filter(k => k>=ck).sort();
    } else {
      const mkeys = Object.keys(allByMonth).sort();
      if (period === '12m') {
        const cutoff = new Date(now); cutoff.setFullYear(cutoff.getFullYear()-1);
        const ck = cutoff.getFullYear()+'-'+String(cutoff.getMonth()+1).padStart(2,'0');
        curveKeys = mkeys.filter(k => k>=ck);
      } else {
        curveKeys = mkeys;
      }
    }
    const byK       = useDaily ? allByDay : allByMonth;
    const countVals = curveKeys.map(k => (byK[k]||{count:0}).count);
    const sizeVals  = curveKeys.map(k => (byK[k]||{size:0}).size);
    return '<div class="curve-label">'+getDep('t')('stats.items_added')+'</div>'
      +makeCurve(curveKeys, countVals, '#3b82f6', 'gradCount', v=>String(Math.round(v)), c=>String(c))
      +'<div class="curve-label" style="margin-top:20px">'+getDep('t')('stats.size_added')+'</div>'
      +makeCurve(curveKeys, sizeVals, '#ef4444', 'gradSize', getDep('fmtSize'), getDep('fmtSize'));
  }

  function recommendationStatsEnabled() {
    const fn = getDep('isRecommendationsEnabled');
    return typeof fn === 'function' && fn();
  }

  function recommendationPriorityColor(priority) {
    if (priority === 'high') return 'var(--priority-high-bg)';
    if (priority === 'medium') return 'var(--priority-medium-bg)';
    if (priority === 'low') return 'var(--priority-low-bg)';
    return '#64748b';
  }

  function recommendationTypeColor(type, idx) {
    const colors = {
      quality: '#7c6aff',
      space: '#16a34a',
      languages: '#0ea5e9',
      series: '#f97316',
      data: '#64748b',
    };
    return colors[type] || getDep('PALETTE')[idx % getDep('PALETTE').length];
  }

  function scoreBucket(score) {
    if (score === '' || score === null || score === undefined) return 'unknown';
    const n = Number(score);
    if (!Number.isFinite(n)) return 'unknown';
    if (n <= 20) return '0-20';
    if (n <= 40) return '21-40';
    if (n <= 60) return '41-60';
    if (n <= 80) return '61-80';
    return '81-100';
  }

  function recommendationCountBucket(count) {
    if (count <= 0) return '0';
    if (count === 1) return '1';
    if (count === 2) return '2';
    return '3plus';
  }

  function recCountBucketLabel(bucket) {
    return getDep('t')('stats.recommendations_per_media_' + bucket);
  }

  function increment(map, key, by = 1) {
    map[key] = (map[key] || 0) + by;
  }

  function makeStatsBlock(title, body) {
    return '<div class="stats-block"><div class="stats-block-title">'+getDep('escH')(title)+'</div>'+body+'</div>';
  }

  function makeRecommendationPie(title, entries, colorFn, labelFn, filterKind) {
    if (!entries.length) return '';
    return makeStatsBlock(title, makePie(entries, colorFn, v=>v, labelFn, v=>String(v), { filterKind }));
  }

  function makeRecommendationHBar(title, entries, labelFn, colorFn, options = {}) {
    if (!entries.length) return '';
    const total = Number(options.percentBase || entries.reduce((sum, [, value]) => sum + (Number(value) || 0), 0));
    return makeStatsBlock(title, makeHorizontalBars(entries, labelFn, v=>String(v), total, colorFn, options));
  }

  function makeFolderImpactBars(title, entries) {
    if (!entries.length) return '';
    const colorFn = (key, index) => getDep('PALETTE')[index % getDep('PALETTE').length];
    const body = '<div class="hbar-list">'
      + entries.map(([folder, info], index) => {
        const pct = Number(info.percent) || 0;
        return '<div class="hbar-item">'
          + '<div class="hbar-label" title="'+getDep('escH')(folder)+'">'+getDep('escH')(folder)+'</div>'
          + '<div class="hbar-track"><div class="hbar-fill" style="width:'+pct.toFixed(2)+'%;background:'+colorFn(folder, index)+'"></div></div>'
          + '<div class="hbar-val">'+Math.round(pct)+'% <span class="stat-row-sub">('+info.withRecommendations+'/'+info.total+')</span></div>'
          + '</div>';
      }).join('')
      + '</div>';
    return makeStatsBlock(title, body);
  }

  function buildRecommendationStatsData() {
    const visibleRecommendations = getDep('visibleRecommendations');
    const filterItems = getDep('filterItems');
    const allItems = getDep('allItems') || [];
    const recs = typeof visibleRecommendations === 'function' ? visibleRecommendations() : [];
    const visibleMedia = typeof filterItems === 'function' ? filterItems() : allItems;
    const mediaById = new Map(allItems.map((item) => [String(item.id || ''), item]));
    const recMedia = getDep('recMedia');
    const recScore = getDep('recScore');
    const recSizeBytes = getDep('recSizeBytes');

    const byPriority = {}, byType = {}, byFolder = {}, byScore = {};
    const recCountByMedia = {};
    const folderMediaTotals = {};
    const folderMediaWithRecommendations = {};
    const spaceMediaIds = new Set();

    recs.forEach((rec) => {
      const media = typeof recMedia === 'function' ? recMedia(rec, mediaById) : mediaById.get(String(rec?.media_ref?.id || '')) || {};
      const mid = String(rec?.media_ref?.id || '');
      const folder = media.category || media.group || '?';
      increment(byPriority, rec.priority || 'medium');
      increment(byType, rec.recommendation_type || 'data');
      increment(byFolder, folder);
      increment(recCountByMedia, mid);
      increment(byScore, scoreBucket(typeof recScore === 'function' ? recScore(media) : media?.quality?.score));
      if (!folderMediaWithRecommendations[folder]) folderMediaWithRecommendations[folder] = new Set();
      folderMediaWithRecommendations[folder].add(mid);
      if (rec.recommendation_type === 'space') spaceMediaIds.add(mid);
    });

    const perMediaBuckets = { '0': 0, '1': 0, '2': 0, '3plus': 0 };
    visibleMedia.forEach((media) => {
      increment(folderMediaTotals, media.category || media.group || '?');
      const bucket = recommendationCountBucket(recCountByMedia[String(media.id || '')] || 0);
      perMediaBuckets[bucket] += 1;
    });

    const folderImpact = Object.entries(folderMediaTotals).map(([folder, total]) => {
      const withRecommendations = folderMediaWithRecommendations[folder]?.size || 0;
      return [folder, {
        total,
        withRecommendations,
        percent: total > 0 ? (withRecommendations / total) * 100 : 0,
      }];
    }).sort((a, b) => b[1].percent - a[1].percent || b[1].withRecommendations - a[1].withRecommendations).slice(0, 10);

    const spaceSizeBytes = [...spaceMediaIds].reduce((sum, mid) => {
      const media = mediaById.get(String(mid)) || {};
      return sum + (typeof recSizeBytes === 'function' ? recSizeBytes(media) : Number(media.size_b || 0));
    }, 0);

    return {
      recs,
      visibleMedia,
      byPriority,
      byType,
      byFolder,
      byScore,
      perMediaBuckets,
      folderImpact,
      spaceSizeBytes,
      spaceMediaCount: spaceMediaIds.size,
    };
  }

  function recommendationStatsFilters() {
    const renderButtons = getDep('renderRecommendationFilterButtons');
    if (typeof renderButtons !== 'function') return '';
    const priorityLabel = getDep('recPriorityLabel');
    const typeLabel = getDep('recTypeLabel');
    return '<div class="rec-filters stats-rec-filters">'
      + '<div class="rec-filter-group rec-filter-priority"><div class="rec-filter-label">'+getDep('t')('recommendations.filters.priority')+'</div><div class="rec-filter-row">'
      + renderButtons(RECOMMENDATION_PRIORITIES, getDep('recommendationPriorityFilters'), 'toggleRecommendationPriorityFilter', priorityLabel, 'rec-priority-filter')
      + '</div></div>'
      + '<div class="rec-filter-group rec-filter-type"><div class="rec-filter-label">'+getDep('t')('recommendations.filters.type')+'</div><div class="rec-filter-row">'
      + renderButtons(RECOMMENDATION_TYPES, getDep('recommendationTypeFilters'), 'toggleRecommendationTypeFilter', typeLabel, 'provider-pill')
      + '</div></div>'
      + '</div>';
  }

  function buildRecommendationsStatsTab() {
    const data = buildRecommendationStatsData();
    const t = getDep('t');
    const escH = getDep('escH');
    const fmtSize = getDep('fmtSize');
    const recPriorityLabel = getDep('recPriorityLabel');
    const recTypeLabel = getDep('recTypeLabel');
    const filters = recommendationStatsFilters();
    if (!data.recs.length) {
      return filters + '<div class="empty rec-empty"><p>'+t('stats.recommendations_empty')+'</p></div>';
    }

    const priorityEntries = RECOMMENDATION_PRIORITIES.map((key) => [key, data.byPriority[key] || 0]).filter(([, value]) => value > 0);
    const typeEntries = RECOMMENDATION_TYPES.map((key) => [key, data.byType[key] || 0]).filter(([, value]) => value > 0);
    const folderEntries = Object.entries(data.byFolder).sort((a,b) => b[1]-a[1]).slice(0, 10);
    const perMediaEntries = ['0', '1', '2', '3plus'].map((key) => [key, data.perMediaBuckets[key] || 0]);
    const scoreEntries = ['0-20', '21-40', '41-60', '61-80', '81-100', 'unknown'].map((key) => [key, data.byScore[key] || 0]).filter(([, value]) => value > 0);

    const spaceKpi = '<div class="stat-kpi-grid">'
      + '<div class="stat-kpi"><div class="stat-kpi-label">'+escH(t('table.size'))+'</div><div class="stat-kpi-val">'+escH(fmtSize(data.spaceSizeBytes))+'</div><div class="stat-kpi-sub">'+escH(t('stats.recommendations_space_size_sub'))+'</div></div>'
      + '<div class="stat-kpi"><div class="stat-kpi-label">'+escH(t('stats.media_count'))+'</div><div class="stat-kpi-val">'+data.spaceMediaCount+'</div></div>'
      + '</div>';

    return filters
      + '<div class="stats-row">'
        + '<div>'+makeRecommendationPie(t('stats.recommendations_priority_distribution'), priorityEntries, recommendationPriorityColor, recPriorityLabel, 'recommendationPriority')+'</div>'
        + '<div>'+makeRecommendationPie(t('stats.recommendations_type_distribution'), typeEntries, recommendationTypeColor, recTypeLabel, 'recommendationType')+'</div>'
      + '</div>'
      + '<div class="stats-row">'
        + '<div>'+makeRecommendationHBar(t('stats.recommendations_folder_distribution'), folderEntries, k=>k, (k,i)=>getDep('PALETTE')[i%getDep('PALETTE').length], { filterKind: 'folder', percentBase: data.recs.length })+'</div>'
        + '<div>'+makeFolderImpactBars(t('stats.recommendations_media_by_folder'), data.folderImpact)+'</div>'
      + '</div>'
      + '<div class="stats-row">'
        + '<div>'+makeRecommendationPie(t('stats.recommendations_per_media'), perMediaEntries, (k,i)=>getDep('PALETTE')[i%getDep('PALETTE').length], recCountBucketLabel)+'</div>'
        + '<div>'+makeStatsBlock(t('stats.recommendations_space_size'), spaceKpi)+'</div>'
      + '</div>'
      + '<div class="stats-row">'
        + '<div>'+makeRecommendationHBar(t('stats.recommendations_score_distribution'), scoreEntries, k=>k === 'unknown' ? t('filters.unknown') : k, (k,i)=>getDep('PALETTE')[i%getDep('PALETTE').length], { percentBase: data.recs.length })+'</div>'
        + '<div></div>'
      + '</div>';
  }

  function renderQualityChart(quality) {
    if (!quality.hasData || !quality.scoredCount) return '';
    let html = '<div class="stats-block"><div class="stats-block-title">'+getDep('t')('stats.quality_score')+'</div>';
    quality.tranches.forEach((tr, i) => {
      const count = quality.counts[i];
      const pct   = quality.maxCount ? Math.round(100*count/quality.maxCount) : 0;
      html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"'
        + statsFilterAttrs('scoreRange', tr.key, tr.label, { min: tr.min, max: tr.max })
        + '>'
        +'<div style="width:68px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;color:var(--muted)">'+getDep('escH')(tr.label)+'</div>'
        +'<div style="flex:1;height:6px;background:var(--border);border-radius:2px;overflow:hidden"><div style="height:100%;width:'+pct+'%;background:'+tr.color+'"></div></div>'
        +'<div style="font-size:11px;color:var(--muted);width:30px;text-align:right">'+count+'</div>'
        +'</div>';
    });
    html += '<div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border);font-size:12px;color:var(--muted)">'+getDep('t')('stats.quality_average').replace('{score}', quality.avgScore)+'</div></div>';
    return html;
  }

  // ── Main assembly ─────────────────────────────────────────
  function buildStats(items) {
    if (!window.MMLState?.isLoaded || !items || !Array.isArray(items)) {
      return '<p style="color:var(--muted);padding:40px">'+getDep('t')('library.no_results')+'</p>';
    }
    if (!items.length) return '<p style="color:var(--muted);padding:40px">'+getDep('t')('library.no_results')+'</p>';

    const data = buildStatsData(items);
    const C    = window.MMLConstants.CHARTS;

    // Bind interactive re-render callbacks (need current data closure)
    window._buildYearChartGlobal        = (period) => buildYearChart(period, data.years);
    window._buildCurveForPeriodGlobal   = (period) => buildCurveForPeriod(period, data.timeline);

    // ── Color helpers ────────────────────────────────────────
    const categoryColorFn     = (k,idx) => getDep('PALETTE')[idx%getDep('PALETTE').length];
    const codecColorFn        = (k,idx) => C.COLORS.CODEC[idx%C.COLORS.CODEC.length];
    const audioCodecColorFn   = (k,idx) => C.COLORS.AUDIO_CODEC[idx%C.COLORS.AUDIO_CODEC.length];
    const audioLangColorFn    = (k,idx) => C.COLORS.AUDIO_LANG[idx%C.COLORS.AUDIO_LANG.length];
    const audioChannelsColorFn = (k,idx) => k === window.MMLConstants.PROVIDER_NONE_KEY ? '#64748b' : getDep('PALETTE')[idx%getDep('PALETTE').length];
    const resColorFn          = (k)     => k === window.MMLConstants.PROVIDER_NONE_KEY ? '#64748b' : (C.COLORS.RESOLUTION[k] || '#888');
    const provColors          = C.COLORS.PROVIDER;
    const noProviderKey       = window.MMLConstants.PROVIDER_NONE_KEY;
    const provColorFnWithNone = (k,i)  => k===noProviderKey ? '#555577' : provColors[i%provColors.length];

    // ── Provider entries with size ───────────────────────────
    const { entries: provEntries, bySize: byProvSize, noneCount, noneSize, referenceCount: provReferenceCount, referenceSize: provReferenceSize } = data.providers;
    const provCountEntries = [
      ...provEntries.map(([k,v]) => [k, v.count]),
      ...(noneCount > 0 ? [[noProviderKey, noneCount]] : []),
    ];
    const provSizeEntries = [
      ...provEntries.map(([k]) => [k, byProvSize[k]||0]),
      ...(noneSize  > 0 ? [[noProviderKey, noneSize]]  : []),
    ];
    const providerLabelFn = (key) => key === noProviderKey
      ? getDep('getFilterDisplayValue')(key, 'filters.no_provider')
      : getDep('_providerGroupLabel')(key);
    const audioChannelsLabelFn = (key) => getDep('getFilterDisplayValue')(key, 'filters.none');

    // ── Block HTML ───────────────────────────────────────────
    const provPieHtml = provCountEntries.length
      ? switchablePie(
          'prov',
          getDep('t')('stats.providers'),
          provSizeEntries,
          provCountEntries,
          provColorFnWithNone,
          providerLabelFn,
          'count',
          {
            size: {
              percentBase: Number(provReferenceSize || 0),
            },
            count: {
              percentBase: Number(provReferenceCount || 0),
              valueFormatter: (value) => String(value),
            },
            filterKind: 'provider',
          }
        )
      : '';
    const providersNoteHtml = provCountEntries.length
      ? '<div style="margin-top:8px;font-size:12px;color:var(--muted)">'+getDep('t')('stats.providers_overlap_note')+'</div>'
      : '';

    const yearChartHtml = data.years.entriesCount.length
      ? '<div class="stats-block">'
          +'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border)">'
            +'<div class="stats-block-title" style="margin-bottom:0;padding-bottom:0;border-bottom:none">'+getDep('t')('stats.release_years')+'</div>'
            +'<div id="yearControls" class="pie-switch">'
              +'<button class="pie-switch-btn active" data-year-period="years">'+getDep('t')('stats.years')+'</button>'
              +'<button class="pie-switch-btn" data-year-period="decades">'+getDep('t')('stats.decades')+'</button>'
            +'</div>'
          +'</div>'
          +'<div id="yearCharts">'+buildYearChart('years', data.years)+'</div>'
          +'</div>'
      : '';

    const curveHtml = data.timeline.hasEnoughData
      ? '<div class="stats-block">'
          +'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border)">'
            +'<div class="stats-block-title" style="margin-bottom:0;padding-bottom:0;border-bottom:none">'+getDep('t')('stats.monthly_evolution')+'</div>'
            +'<div id="curveControls" class="pie-switch">'
              +'<button class="pie-switch-btn"        data-period="all">'+getDep('t')('stats.all')+'</button>'
              +'<button class="pie-switch-btn active" data-period="12m">'+getDep('t')('stats.months_12')+'</button>'
              +'<button class="pie-switch-btn"        data-period="30d">'+getDep('t')('stats.days_30')+'</button>'
            +'</div>'
          +'</div>'
          +'<div id="curveCharts">'+buildCurveForPeriod('12m', data.timeline)+'</div>'
          +'</div>'
      : '';

    // ── Final layout ─────────────────────────────────────────
    const generalTabHtml = ''
      + '<div class="stats-row">'
          + '<div>'+(data.category.entriesSize.length ? switchablePie('category', getDep('t')('stats.categories'), data.category.entriesSize, data.category.entriesCount, categoryColorFn, k=>k, 'size', { filterKind: 'folder' }) : '')+'</div>'
          + '<div>'+renderGenresBlock(data.genres)+'</div>'
        + '</div>'
      + '<div class="stats-row">'
          + '<div>'+provPieHtml+providersNoteHtml+'</div>'
          + '<div>'+renderQualityChart(data.quality)+'</div>'
        + '</div>'
      + yearChartHtml;

    const technicalTabHtml = ''
      + '<div class="stats-row">'
          + '<div>'+(data.resolution.entriesSize.length ? switchablePie('res', getDep('t')('stats.resolution'), data.resolution.entriesSize, data.resolution.entriesCount, resColorFn, k=>getDep('getFilterDisplayValue')(k), 'count', { filterKind: 'resolution' }) : '')+'</div>'
          + '<div>'+(data.codec.entriesSize.length      ? switchablePie('codec', getDep('t')('stats.codec'), data.codec.entriesSize, data.codec.entriesCount, codecColorFn, k=>getDep('getFilterDisplayValue')(k), 'count', { filterKind: 'codec' }) : '')+'</div>'
        + '</div>'
      + '<div class="stats-row">'
          + '<div>'+(data.audioCodec.entriesSize.length ? switchablePie('audioCodec', getDep('t')('stats.audio_codec_chart_title'), data.audioCodec.entriesSize, data.audioCodec.entriesCount, audioCodecColorFn, getDep('getAudioCodecDisplay'), 'count', { filterKind: 'audioCodec' }) : '')+'</div>'
          + '<div>'+(data.audioLang.hasData             ? switchablePie('audioLang',  getDep('t')('stats.audio_languages_chart_title'), data.audioLang.entriesSize, data.audioLang.entriesCount, audioLangColorFn, getDep('getAudioLanguageSimpleDisplay'), 'count', { filterKind: 'audioLanguage' }) : '')+'</div>'
        + '</div>'
      + '<div class="stats-row">'
          + '<div>'+(data.audioChannels.hasData         ? switchablePie('audioChannels', getDep('t')('stats.audio_channels_chart_title'), data.audioChannels.entriesSize, data.audioChannels.entriesCount, audioChannelsColorFn, audioChannelsLabelFn, 'count', { filterKind: 'audioChannels' }) : '')+'</div>'
          + '<div></div>'
        + '</div>';

    const recommendationsAvailable = recommendationStatsEnabled();
    if (!recommendationsAvailable && activeStatsSubtab === 'recommendations') activeStatsSubtab = 'general';
    const evolutionTabHtml = curveHtml;
    const recommendationsTabHtml = recommendationsAvailable ? buildRecommendationsStatsTab() : '';
    const activeGeneral = activeStatsSubtab === 'general' ? ' active' : '';
    const activeTechnical = activeStatsSubtab === 'technical' ? ' active' : '';
    const activeEvolution = activeStatsSubtab === 'evolution' ? ' active' : '';
    const activeRecommendations = activeStatsSubtab === 'recommendations' ? ' active' : '';
    return ''
      + '<div id="statsSubtabs" class="stats-subtabs">'
        + '<button class="pie-switch-btn stats-subtab-btn'+activeGeneral+'" data-stats-subtab="general">'+getDep('t')('stats.subtab_general')+'</button>'
        + '<button class="pie-switch-btn stats-subtab-btn'+activeTechnical+'" data-stats-subtab="technical">'+getDep('t')('stats.subtab_technical')+'</button>'
        + '<button class="pie-switch-btn stats-subtab-btn'+activeEvolution+'" data-stats-subtab="evolution">'+getDep('t')('stats.subtab_evolution')+'</button>'
        + (recommendationsAvailable ? '<button class="pie-switch-btn stats-subtab-btn'+activeRecommendations+'" data-stats-subtab="recommendations">'+getDep('t')('stats.subtab_recommendations')+'</button>' : '')
      + '</div>'
      + '<div id="statsSubtab-general" class="stats-subtab-content'+activeGeneral+'">'+generalTabHtml+'</div>'
      + '<div id="statsSubtab-technical" class="stats-subtab-content'+activeTechnical+'">'+technicalTabHtml+'</div>'
      + '<div id="statsSubtab-evolution" class="stats-subtab-content'+activeEvolution+'">'+evolutionTabHtml+'</div>'
      + (recommendationsAvailable ? '<div id="statsSubtab-recommendations" class="stats-subtab-content'+activeRecommendations+'">'+recommendationsTabHtml+'</div>' : '');
  }

  // ── STATS PANEL ENTRY POINT ───────────────────────────────
  function renderStatsPanel() {
    const state = window.MMLState;
    if (!state?.isLoaded) {
      const el = document.getElementById('statsContent');
      if (el) el.innerHTML = '<p style="color:var(--muted);padding:40px">'
        + getDep('t')(state?.hasError ? 'library.scan_error' : 'library.loading')
        + '</p>';
      return;
    }
    const filterItems = getDep('filterItems');
    const allItems    = getDep('allItems');
    const items       = filterItems ? filterItems() : allItems;
    const el = document.getElementById('statsContent');
    if (el) el.innerHTML = buildStats(items);
  }

  // ── INTERACTIONS ──────────────────────────────────────────
  function statSwitchPie(el) {
    const id = el.dataset.pie, unit = el.dataset.unit;
    document.getElementById(id+'PieSize').style.display  = unit==='size'  ? '' : 'none';
    document.getElementById(id+'PieCount').style.display = unit==='count' ? '' : 'none';
    document.getElementById(id+'BtnSize').classList.toggle('active',  unit==='size');
    document.getElementById(id+'BtnCount').classList.toggle('active', unit==='count');
  }

  function setCurvePeriod(btn) {
    const controls = document.getElementById('curveControls');
    if (!controls) return;
    const period = btn.dataset.period;
    controls.querySelectorAll('.pie-switch-btn').forEach(b => b.classList.toggle('active', b===btn));
    const charts = document.getElementById('curveCharts');
    if (charts) charts.innerHTML = getDep('_buildCurveForPeriodGlobal')(period);
  }

  function setYearPeriod(btn) {
    const controls = document.getElementById('yearControls');
    if (!controls) return;
    const period = btn.dataset.yearPeriod;
    controls.querySelectorAll('.pie-switch-btn').forEach(b => b.classList.toggle('active', b===btn));
    const charts = document.getElementById('yearCharts');
    if (charts) charts.innerHTML = getDep('_buildYearChartGlobal')(period);
  }

  function setStatsSubtab(btn) {
    const next = btn.dataset.statsSubtab;
    if (!STATS_SUBTABS.includes(next)) return;
    activeStatsSubtab = next;
    const host = document.getElementById('statsSubtabs');
    if (host) {
      host.querySelectorAll('.stats-subtab-btn').forEach((button) => {
        button.classList.toggle('active', button.dataset.statsSubtab === next);
      });
    }
    STATS_SUBTABS.forEach((tab) => {
      const section = document.getElementById('statsSubtab-' + tab);
      if (section) section.classList.toggle('active', tab === next);
    });
  }

  // ── EXPORT API ────────────────────────────────────────────
  window.MMLStats = { renderStatsPanel, init };

  initializeEventHandlers();
})();
