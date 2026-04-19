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
  };

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
  }

  // ══════════════════════════════════════════════════════════
  //  DATA LAYER — pure aggregations, no HTML
  // ══════════════════════════════════════════════════════════

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
      const k = getDep('getAudioLanguageSimpleDisplay')(getDep('getAudioLanguageSimple')(i));
      byAudioLangCount[k] = (byAudioLangCount[k] || 0) + 1;
      byAudioLangSize[k]  = (byAudioLangSize[k]  || 0) + (i.size_b || 0);
    });
    const audioLang = {
      entriesCount: Object.entries(byAudioLangCount).sort((a,b) => b[1]-a[1]),
      entriesSize:  Object.entries(byAudioLangSize).sort((a,b) => b[1]-a[1]),
      hasData:      Object.keys(byAudioLangCount).length > 0,
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

    return { category, codec, audioCodec, audioLang, resolution, providers, timeline, years, quality };
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
      if (frac > 0.999) {
        slices += '<circle cx="'+CX+'" cy="'+CY+'" r="'+R+'" fill="'+col+'"/>';
      } else {
        slices += '<path d="M'+CX+','+CY+' L'+x1.toFixed(2)+','+y1.toFixed(2)+' A'+R+','+R+' 0 '+large+',1 '+x2.toFixed(2)+','+y2.toFixed(2)+' Z" fill="'+col+'"><title>'+getDep('escH')(labelFn(k))+' — '+formatValue(val)+' ('+formatPercent(val)+')</title></path>';
      }
      angle = a2;
    });
    slices += '<circle cx="'+CX+'" cy="'+CY+'" r="'+(R*0.52)+'" fill="var(--surface)"/>';
    slices += '<text x="'+CX+'" y="'+(CY-7)+'" text-anchor="middle" font-size="11" font-weight="700" fill="var(--text)">'+entries.length+'</text>';
    slices += '<text x="'+CX+'" y="'+(CY+8)+'" text-anchor="middle" font-size="9" fill="var(--muted)">'+(entries.length>1?getDep('t')('stats.entries'):getDep('t')('stats.entry'))+'</text>';
    const svg    = '<svg viewBox="0 0 '+SIZE+' '+SIZE+'" width="'+SIZE+'" height="'+SIZE+'" style="flex-shrink:0">'+slices+'</svg>';
    const legend = '<div class="pie-legend">'+entries.slice(0,12).map(([k,v],idx) => {
      const val=valFn(v);
      return '<div class="pie-leg-row">'
        +'<div class="pie-leg-dot" style="background:'+colorFn(k,idx)+'"></div>'
        +'<div class="pie-leg-label" title="'+getDep('escH')(labelFn(k))+'">'+getDep('escH')(labelFn(k))+'</div>'
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
    const pieSize   = makePie(sizeEntries,  colorFn, v=>v, k=>labelFn(k), getDep('fmtSize'));
    const pieCount  = makePie(countEntries, colorFn, v=>v, k=>labelFn(k), v=>String(v), options.count || {});
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

  function renderQualityChart(quality) {
    if (!quality.hasData || !quality.scoredCount) return '';
    let html = '<div class="stats-block"><div class="stats-block-title">'+getDep('t')('stats.quality_score')+'</div>';
    quality.tranches.forEach((tr, i) => {
      const count = quality.counts[i];
      const pct   = quality.maxCount ? Math.round(100*count/quality.maxCount) : 0;
      html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">'
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
    const categoryColorFn    = (k,idx) => getDep('PALETTE')[idx%getDep('PALETTE').length];
    const codecColorFn       = (k,idx) => C.COLORS.CODEC[idx%C.COLORS.CODEC.length];
    const audioCodecColorFn  = (k,idx) => C.COLORS.AUDIO_CODEC[idx%C.COLORS.AUDIO_CODEC.length];
    const audioLangColorFn   = (k,idx) => C.COLORS.AUDIO_LANG[idx%C.COLORS.AUDIO_LANG.length];
    const resColorFn         = (k)     => k === window.MMLConstants.PROVIDER_NONE_KEY ? '#64748b' : (C.COLORS.RESOLUTION[k] || '#888');
    const provColors         = C.COLORS.PROVIDER;
    const noProviderLabel    = getDep('t')('filters.no_provider');
    const provColorFnWithNone = (k,i)  => k===noProviderLabel ? '#555577' : provColors[i%provColors.length];

    // ── Provider entries with size ───────────────────────────
    const { entries: provEntries, bySize: byProvSize, noneCount, noneSize, referenceCount: provReferenceCount } = data.providers;
    const provCountEntries = [
      ...provEntries.map(([k,v]) => [k, v.count]),
      ...(noneCount > 0 ? [[noProviderLabel, noneCount]] : []),
    ];
    const provSizeEntries = [
      ...provEntries.map(([k]) => [k, byProvSize[k]||0]),
      ...(noneSize  > 0 ? [[noProviderLabel, noneSize]]  : []),
    ];

    // ── Block HTML ───────────────────────────────────────────
    const provPieHtml = provCountEntries.length
      ? switchablePie(
          'prov',
          getDep('t')('stats.providers'),
          provSizeEntries,
          provCountEntries,
          provColorFnWithNone,
          getDep('_providerGroupLabel'),
          'count',
          {
            count: {
              percentBase: Number(provReferenceCount || 0),
              valueFormatter: (value) => String(value),
            },
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
    return ''
      // Row 1: Dossiers | Fournisseurs
      + '<div class="stats-row">'
          + '<div>'+(data.category.entriesSize.length ? switchablePie('category', getDep('t')('stats.categories'), data.category.entriesSize, data.category.entriesCount, categoryColorFn, k=>k, 'size') : '')+'</div>'
          + '<div>'+provPieHtml+providersNoteHtml+'</div>'
        + '</div>'
      // Row 2: Résolution | Codec vidéo
      + '<div class="stats-row">'
          + '<div>'+(data.resolution.entriesSize.length ? switchablePie('res', getDep('t')('stats.resolution'), data.resolution.entriesSize, data.resolution.entriesCount, resColorFn, k=>getDep('getFilterDisplayValue')(k), 'count') : '')+'</div>'
          + '<div>'+(data.codec.entriesSize.length      ? switchablePie('codec', getDep('t')('stats.codec'), data.codec.entriesSize, data.codec.entriesCount, codecColorFn, k=>getDep('getFilterDisplayValue')(k), 'count') : '')+'</div>'
        + '</div>'
      // Row 3: Codec audio | Langues
      + '<div class="stats-row">'
          + '<div>'+(data.audioCodec.entriesSize.length ? switchablePie('audioCodec', getDep('t')('stats.audio_codec_chart_title'), data.audioCodec.entriesSize, data.audioCodec.entriesCount, audioCodecColorFn, getDep('getAudioCodecDisplay'), 'count') : '')+'</div>'
          + '<div>'+(data.audioLang.hasData             ? switchablePie('audioLang',  getDep('t')('stats.audio_languages_chart_title'), data.audioLang.entriesSize, data.audioLang.entriesCount, audioLangColorFn, k=>k, 'count') : '')+'</div>'
        + '</div>'
      // Row 4: Qualité | [vide]
      + '<div class="stats-row">'
          + '<div>'+renderQualityChart(data.quality)+'</div>'
          + '<div></div>'
        + '</div>'
      // Full width: Années de sortie
      + yearChartHtml
      // Full width: Évolution mensuelle
      + curveHtml;
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

  // ── EXPORT API ────────────────────────────────────────────
  window.MMLStats = { renderStatsPanel, init };

  initializeEventHandlers();
})();
