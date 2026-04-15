/**
 * MyMediaLibrary — Stats Panel Module
 * Extracted from app.js
 *
 * Handles:
 * - Stats panel rendering (charts, aggregations, cross-tables)
 * - Switchable pie charts (size/count toggle)
 * - Monthly evolution curve
 * - Provider cross-tables
 *
 * Dependencies are provided via init() to make them explicit.
 * Falls back to window.* if not initialized.
 */

(function() {
  'use strict';

  // ── MODULE DEPENDENCIES ──────────────────────────────────
  // These are injected via init() or accessed from window as fallback
  let deps = {
    filterItems: null,
    allItems: null,
    PALETTE: null,
    PROVIDERS_META: null,
    providerCatalog: null,
    PROVIDER_OTHERS_KEY: null,
    getNormalizedVideoCodec: null,
    getNormalizedAudioCodec: null,
    getNormalizedResolution: null,
    getAudioLanguageSimple: null,
    getAudioLanguageSimpleDisplay: null,
    getAudioCodecDisplay: null,
    getFilterDisplayValue: null,
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

  function initializeEventHandlers() {
    // Delegate pie size/count toggles
    document.addEventListener('click', (e) => {
      if (e.target.classList?.contains('pie-switch-btn')) {
        const handler = e.target.dataset.pie;
        if (handler) {
          statSwitchPie(e.target);
        }
      }
    });

    // Delegate curve period switches
    document.addEventListener('click', (e) => {
      if (e.target.dataset.period) {
        const curveControls = document.getElementById('curveControls');
        if (curveControls?.contains(e.target)) {
          setCurvePeriod(e.target);
        }
      }
    });

    // Delegate year/decade period switches
    document.addEventListener('click', (e) => {
      if (e.target.dataset.yearPeriod) {
        const yearControls = document.getElementById('yearControls');
        if (yearControls?.contains(e.target)) {
          setYearPeriod(e.target);
        }
      }
    });
  }

  // ── STATS PANEL ──────────────────────────────────────
  function renderStatsPanel() {
    // Defensive: ensure data is ready
    const allItems = getDep('allItems');
    if (!allItems || !Array.isArray(allItems)) {
      const el = document.getElementById('statsContent');
      if (el) el.innerHTML = '<p style="color:var(--muted);padding:40px">'+getDep('t')('library.loading')+'</p>';
      return;
    }

    const filterItems = getDep('filterItems');
    const items = filterItems ? filterItems() : allItems;
    const el = document.getElementById('statsContent');
    if (el) el.innerHTML = buildStats(items);
  }

  function buildStats(items) {
    const allItems = getDep('allItems');

    // Defensive: ensure data is ready
    if (!allItems || !Array.isArray(allItems) || !items || !Array.isArray(items)) {
      return '<p style="color:var(--muted);padding:40px">'+getDep('t')('library.no_results')+'</p>';
    }

    if (!items.length) return '<p style="color:var(--muted);padding:40px">'+getDep('t')('library.no_results')+'</p>';

    // ── Helpers ──────────────────────────────────────────
    function makePie(entries, colorFn, valFn, labelFn, fmtFn) {
      const total = entries.reduce((s,[,v])=>s+valFn(v),0);
      if (!total) return '';
      const R=70, CX=80, CY=80, SIZE=160;
      let angle = -Math.PI/2;
      let slices = '';
      entries.forEach(([k,v],idx) => {
        const val = valFn(v);
        const frac = val/total;
        const a1 = angle, a2 = angle + frac*2*Math.PI;
        const x1=CX+R*Math.cos(a1), y1=CY+R*Math.sin(a1);
        const x2=CX+R*Math.cos(a2), y2=CY+R*Math.sin(a2);
        const large = frac > 0.5 ? 1 : 0;
        const col = colorFn(k,idx);
        if (frac > 0.999) {
          slices += '<circle cx="'+CX+'" cy="'+CY+'" r="'+R+'" fill="'+col+'"/>';
        } else {
          slices += '<path d="M'+CX+','+CY+' L'+x1.toFixed(2)+','+y1.toFixed(2)+' A'+R+','+R+' 0 '+large+',1 '+x2.toFixed(2)+','+y2.toFixed(2)+' Z" fill="'+col+'"><title>'+getDep('escH')(labelFn(k))+' — '+fmtFn(val)+' ('+Math.round(frac*100)+'%)</title></path>';
        }
        angle = a2;
      });
      // donut hole
      slices += '<circle cx="'+CX+'" cy="'+CY+'" r="'+(R*0.52)+'" fill="var(--surface)"/>';
      // center label
      slices += '<text x="'+CX+'" y="'+(CY-7)+'" text-anchor="middle" font-size="11" font-weight="700" fill="var(--text)">'+entries.length+'</text>';
      slices += '<text x="'+CX+'" y="'+(CY+8)+'" text-anchor="middle" font-size="9" fill="var(--muted)">'+(entries.length>1?getDep('t')('stats.entries'):getDep('t')('stats.entry'))+'</text>';

      const svg = '<svg viewBox="0 0 '+SIZE+' '+SIZE+'" width="'+SIZE+'" height="'+SIZE+'" style="flex-shrink:0">'+slices+'</svg>';
      const legend = '<div class="pie-legend">'+entries.slice(0,12).map(([k,v],idx)=>{
        const val=valFn(v), pct=Math.round(val/total*100);
        return '<div class="pie-leg-row">'
          +'<div class="pie-leg-dot" style="background:'+colorFn(k,idx)+'"></div>'
          +'<div class="pie-leg-label" title="'+getDep('escH')(labelFn(k))+'">'+getDep('escH')(labelFn(k))+'</div>'
          +'<div class="pie-leg-val">'+fmtFn(val)+'</div>'
          +'<div class="pie-leg-pct">'+pct+'%</div>'
          +'</div>';
      }).join('')+(entries.length>12?'<div style="font-size:11px;color:var(--muted);padding-top:2px">+' + (entries.length-12) + ' '+getDep('t')('stats.others')+'</div>':'')+'</div>';
      return '<div class="pie-wrap">'+svg+legend+'</div>';
    }

    // ── Aggregate by category (folder) ───────────────────
    const byCategory={}, byCategoryCount={};
    items.forEach(i=>{
      const c=i.category||i.group||'?';
      byCategory[c]=(byCategory[c]||0)+(i.size_b||0);
      byCategoryCount[c]=(byCategoryCount[c]||0)+1;
    });
    const categoryEntriesSize = Object.entries(byCategory).sort((a,b)=>b[1]-a[1]);
    const categoryEntriesCount = Object.entries(byCategoryCount).sort((a,b)=>b[1]-a[1]);

    // ── Codec ────────────────────────────────────────────
    const CODEC_COLORS = ['#f59e0b','#3b82f6','#10b981','#ef4444','#8b5cf6','#ec4899','#14b8a6'];
    const byCodec={}, byCodecCount={};
    items.forEach(i=>{
      const key = getDep('getNormalizedVideoCodec')(i);
      byCodec[key]=(byCodec[key]||0)+(i.size_b||0);
      byCodecCount[key]=(byCodecCount[key]||0)+1;
    });
    const codecColorFn=(k,idx)=>CODEC_COLORS[idx%CODEC_COLORS.length];
    const codecEntriesSize  = Object.entries(byCodec).sort((a,b)=>b[1]-a[1]);
    const codecEntriesCount = Object.entries(byCodecCount).sort((a,b)=>b[1]-a[1]);

    // ── Audio Codec ──────────────────────────────────────
    const AUDIO_CODEC_COLORS = ['#06b6d4','#f97316','#a3e635','#e879f9','#fb7185','#34d399','#fbbf24'];
    const byAudioCodec={}, byAudioCodecCount={};
    items.forEach(i=>{
      const key = getDep('getNormalizedAudioCodec')(i);
      byAudioCodec[key]=(byAudioCodec[key]||0)+(i.size_b||0);
      byAudioCodecCount[key]=(byAudioCodecCount[key]||0)+1;
    });
    const audioCodecColorFn=(k,idx)=>AUDIO_CODEC_COLORS[idx%AUDIO_CODEC_COLORS.length];
    const audioCodecEntriesSize  = Object.entries(byAudioCodec).sort((a,b)=>b[1]-a[1]);
    const audioCodecEntriesCount = Object.entries(byAudioCodecCount).sort((a,b)=>b[1]-a[1]);

    // ── Audio Languages ──────────────────────────────────
    const AUDIO_LANG_COLORS = ['#38bdf8','#fb923c','#4ade80','#f472b6','#a78bfa','#fbbf24','#34d399','#60a5fa','#f87171','#2dd4bf'];
    const byAudioLangCount={}, byAudioLangSize={};
    items.forEach(i=>{
      const key = getDep('getAudioLanguageSimpleDisplay')(getDep('getAudioLanguageSimple')(i));
      byAudioLangCount[key]=(byAudioLangCount[key]||0)+1;
      byAudioLangSize[key]=(byAudioLangSize[key]||0)+(i.size_b||0);
    });
    const hasLangData = Object.keys(byAudioLangCount).length > 0;
    const audioLangEntriesCount = Object.entries(byAudioLangCount).sort((a,b)=>b[1]-a[1]);
    const audioLangEntriesSize = Object.entries(byAudioLangSize).sort((a,b)=>b[1]-a[1]);
    const audioLangColorFn=(k,idx)=>AUDIO_LANG_COLORS[idx%AUDIO_LANG_COLORS.length];

    // ── Resolution ───────────────────────────────────────
    const RES_ORDER = ['4K','1080p','720p','SD'];
    const RES_COLORS = {'4K':'#a855f7','1080p':'#22c55e','720p':'#3b82f6','SD':'#78716c'};
    const byRes={}, byResCount={};
    items.forEach(i=>{
      const r=getDep('getNormalizedResolution')(i);
      byRes[r]=(byRes[r]||0)+(i.size_b||0);
      byResCount[r]=(byResCount[r]||0)+1;
    });
    const resColorFn=(k)=>RES_COLORS[k]||'#888';
    const resEntriesSize = RES_ORDER.filter(r=>byRes[r]).map(r=>[r,byRes[r]]);
    const resEntriesCount = RES_ORDER.filter(r=>byResCount[r]).map(r=>[r,byResCount[r]]);

    // ── Providers ─────────────────────────────────────────
    const groupedProviderCount = getDep('MMLLogic')?.groupedProviderCounts
      ? getDep('MMLLogic').groupedProviderCounts(items, getDep('_providerGroupKey'), getDep('_pname'))
      : (() => {
          const fallback = {};
          items.forEach(i => getDep('_itemProviderGroups')(i).forEach(name => {
            fallback[name] = (fallback[name] || 0) + 1;
          }));
          return fallback;
        })();
    const byProv = {};
    Object.entries(groupedProviderCount).forEach(([name, count]) => {
      byProv[name] = { count, logo: '' };
    });
    items.forEach(i => (i.providers || []).forEach(p => {
      const rawName = getDep('_pname')(p);
      const name = getDep('_providerGroupKey')(rawName);
      if (!name || !byProv[name] || name === getDep('PROVIDER_OTHERS_KEY')) return;
      if (!byProv[name].logo) byProv[name].logo = getDep('_plogo')(p);
    }));
    const provEntries=Object.entries(byProv).sort((a,b)=>b[1].count-a[1].count);
    const provColors=['#7c6aff','#ff6a6a','#4ecdc4','#f7b731','#a78bfa','#f97316','#34d399','#60a5fa','#f472b6'];

    // ── Monthly curve ─────────────────────────────────────
    const allByDay={};
    items.forEach(i=>{
      if(!i.added_at)return;
      const d=new Date(i.added_at);
      const key=d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
      if(!allByDay[key]) allByDay[key]={count:0,size:0};
      allByDay[key].count++; allByDay[key].size+=i.size_b||0;
    });
    const allByMonth={};
    Object.entries(allByDay).forEach(([k,v])=>{
      const mk=k.slice(0,7);
      if(!allByMonth[mk]) allByMonth[mk]={count:0,size:0};
      allByMonth[mk].count+=v.count; allByMonth[mk].size+=v.size;
    });
    const keys = Object.keys(allByMonth);

    // ── Years aggregation (count only — no size) ───────────
    const byYearCount={};
    items.forEach(i=>{
      if(!i.year) return;
      byYearCount[String(i.year)]=(byYearCount[String(i.year)]||0)+1;
    });
    const yearEntriesCount = Object.keys(byYearCount).sort((a,b)=>Number(a)-Number(b)).map(y=>[y,byYearCount[y]]);

    function buildYearChart(period) {
      if(!yearEntriesCount.length) return '<p style="font-size:12px;color:var(--muted)">'+getDep('t')('stats.not_enough_data')+'</p>';

      let displayEntries = yearEntriesCount;
      if(period==='decades') {
        const byDecade={};
        yearEntriesCount.forEach(([y,v])=>{
          const decade = Math.floor(Number(y)/10)*10;
          const decadeKey = decade+'-'+(decade+9);
          byDecade[decadeKey]=(byDecade[decadeKey]||0)+v;
        });
        displayEntries = Object.entries(byDecade).sort((a,b)=>Number(a[0].split('-')[0])-Number(b[0].split('-')[0]));
      }

      return makeVBar(displayEntries, getDep('PALETTE'));
    }
    window._buildYearChartGlobal = buildYearChart;

    function makeCurve(keys, vals, color, gradId, labelFn, titleFn) {
      const maxV=Math.max(...vals,0);
      if(!maxV||keys.length<2) return '<p style="font-size:12px;color:var(--muted)">'+getDep('t')('stats.not_enough_data')+'</p>';
      const W=800,H=140,PL=52,PR=16,PT=16,PB=28;
      const iW=W-PL-PR, iH=H-PT-PB, n=keys.length;
      const xs=keys.map((_,i2)=>PL+(n>1?i2/(n-1)*iW:iW/2));
      const ys=vals.map(v=>PT+iH-v/maxV*iH);
      const lineD=xs.map((x,i2)=>(i2===0?'M':'L')+x.toFixed(1)+','+ys[i2].toFixed(1)).join(' ');
      const areaD=lineD+' L'+xs[n-1].toFixed(1)+','+(PT+iH)+' L'+xs[0].toFixed(1)+','+(PT+iH)+' Z';
      let grid='';
      for(let s=0;s<=3;s++){
        const y2=PT+iH-s/3*iH;
        grid+='<line x1="'+PL+'" y1="'+y2.toFixed(1)+'" x2="'+(W-PR)+'" y2="'+y2.toFixed(1)+'" stroke="var(--border)" stroke-width="1"/>';
        grid+='<text x="'+(PL-4)+'" y="'+(y2+4).toFixed(1)+'" text-anchor="end" font-size="9" fill="var(--muted)">'+labelFn(maxV*s/3)+'</text>';
      }
      const step=Math.max(1,Math.ceil(n/10));
      let xlbls='';
      keys.forEach((k,i2)=>{
        if(i2%step!==0&&i2!==n-1)return;
        const parts=k.split('-');
        const lbl=parts.length===3 ? parts[2]+'/'+parts[1] : parts[1]+'/'+parts[0].slice(2);
        xlbls+='<text x="'+xs[i2].toFixed(1)+'" y="'+(PT+iH+16)+'" text-anchor="middle" font-size="9" fill="var(--muted)">'+lbl+'</text>';
      });
      const dots=xs.map((x,i2)=>'<circle cx="'+x.toFixed(1)+'" cy="'+ys[i2].toFixed(1)+'" r="3" fill="'+color+'" stroke="var(--surface)" stroke-width="2"><title>'+keys[i2]+' : '+titleFn(vals[i2])+'</title></circle>').join('');
      return '<svg class="curve-svg" viewBox="0 0 '+W+' '+H+'" xmlns="http://www.w3.org/2000/svg">'
        +'<defs><linearGradient id="'+gradId+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="'+color+'" stop-opacity=".2"/><stop offset="100%" stop-color="'+color+'" stop-opacity="0"/></linearGradient></defs>'
        +grid+'<path d="'+areaD+'" fill="url(#'+gradId+')" />'
        +'<path d="'+lineD+'" fill="none" stroke="'+color+'" stroke-width="2" stroke-linejoin="round"/>'
        +dots+xlbls+'</svg>';
    }

    function buildCurveForPeriod(period) {
      const now=new Date();
      let useDaily=false, curveKeys=[];
      if(period==='30d'){
        useDaily=true;
        const cutoff=new Date(now); cutoff.setDate(cutoff.getDate()-30);
        const ck=cutoff.getFullYear()+'-'+String(cutoff.getMonth()+1).padStart(2,'0')+'-'+String(cutoff.getDate()).padStart(2,'0');
        curveKeys=Object.keys(allByDay).filter(k=>k>=ck).sort();
      } else {
        let mkeys=Object.keys(allByMonth).sort();
        if(period==='12m'){
          const cutoff=new Date(now); cutoff.setFullYear(cutoff.getFullYear()-1);
          const ck=cutoff.getFullYear()+'-'+String(cutoff.getMonth()+1).padStart(2,'0');
          curveKeys=mkeys.filter(k=>k>=ck);
        } else {
          curveKeys=mkeys;
        }
      }
      const byK=useDaily?allByDay:allByMonth;
      const countVals=curveKeys.map(k=>(byK[k]||{count:0}).count);
      const sizeVals=curveKeys.map(k=>(byK[k]||{size:0}).size);
      return '<div class="curve-label">'+getDep('t')('stats.items_added')+'</div>'
        +makeCurve(curveKeys,countVals,'#3b82f6','gradCount',v=>String(Math.round(v)),c=>String(c))
        +'<div class="curve-label" style="margin-top:20px">'+getDep('t')('stats.size_added')+'</div>'
        +makeCurve(curveKeys,sizeVals,'#ef4444','gradSize',getDep('fmtSize'),getDep('fmtSize'));
    }
    window._buildCurveForPeriodGlobal = buildCurveForPeriod;

    function makeVBar(entries, colorPalette) {
      if(!entries.length) return '';
      const maxVal = Math.max(...entries.map(e=>e[1]),0);
      if(!maxVal) return '';

      const W=800, H=160, PL=16, PR=16, PT=8, PB=40;
      const iW=W-PL-PR, iH=H-PT-PB, n=entries.length;
      const barWidth = Math.max(6, Math.floor(iW/Math.max(n,1))-2);
      const spacing = n>1 ? (iW-barWidth*n)/(n-1) : 0;
      // Show at most ~12 labels on X axis to prevent overlap
      const labelStep = Math.max(1, Math.ceil(n/12));

      let bars='', labels='';
      let x = PL;
      entries.forEach(([label,val],idx)=>{
        const barHeight = val/maxVal*iH;
        const y = PT+iH-barHeight;
        const col = colorPalette[idx%colorPalette.length];

        bars += '<rect x="'+x.toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+barWidth+'" height="'+barHeight.toFixed(1)+'" fill="'+col+'"><title>'+getDep('escH')(label)+' : '+val+'</title></rect>';
        if(idx%labelStep===0 || idx===n-1) {
          labels += '<text x="'+(x+barWidth/2).toFixed(1)+'" y="'+(PT+iH+20)+'" text-anchor="middle" font-size="11" fill="var(--muted)">'+getDep('escH')(label)+'</text>';
        }

        x += barWidth + spacing;
      });

      return '<svg class="curve-svg" viewBox="0 0 '+W+' '+H+'" xmlns="http://www.w3.org/2000/svg">'
        +bars+labels+'</svg>';
    }

    // ── Category color helper ─────────────────────────────
    const hasCategories = categoryEntriesSize.length > 0;
    const categoryColorFn=(k,idx)=>getDep('PALETTE')[idx%getDep('PALETTE').length];

    function switchablePie(id, title, sizeEntries, countEntries, colorFn, labelFn = k => k, defaultUnit = 'size') {
      const showCountByDefault = defaultUnit === 'count';
      const pieSize  = makePie(sizeEntries,  colorFn, v=>v, k=>labelFn(k), getDep('fmtSize'));
      const pieCount = makePie(countEntries, colorFn, v=>v, k=>labelFn(k), v=>String(v));
      return '<div class="stats-block">'
        +'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border)">'
          +'<div class="stats-block-title" style="margin-bottom:0;padding-bottom:0;border-bottom:none">'+title+'</div>'
          +'<div class="pie-switch">'
            +'<button class="pie-switch-btn'+(showCountByDefault ? '' : ' active')+'" id="'+id+'BtnSize"  data-pie="'+id+'" data-unit="size"  >'+getDep('t')('stats.by_size')+'</button>'
            +'<button class="pie-switch-btn'+(showCountByDefault ? ' active' : '')+'" id="'+id+'BtnCount" data-pie="'+id+'" data-unit="count" >'+getDep('t')('stats.by_count')+'</button>'
          +'</div>'
        +'</div>'
        +'<div id="'+id+'PieSize"'+(showCountByDefault ? ' style="display:none"' : '')+'>'+pieSize+'</div>'
        +'<div id="'+id+'PieCount"'+(showCountByDefault ? '' : ' style="display:none"')+'>'+pieCount+'</div>'
        +'</div>';
    }

    // Provider pie (including "Aucun") — switchable taille/nombre
    const provColorFn=(k,i)=>provColors[i%provColors.length];
    const noProviderLabel = getDep('t')('filters.no_provider');
    const noneCount = items.filter(i=>!(i.providers&&i.providers.length)).length;
    const noneSize  = items.filter(i=>!(i.providers&&i.providers.length)).reduce((s,i)=>s+(i.size_b||0),0);
    const provCountEntries=[
      ...provEntries.map(([k,v])=>[k,v.count]),
      ...(noneCount>0 ? [[noProviderLabel,noneCount]] : []),
    ];
    const byProvSize={};
    items.forEach(i=>{
      getDep('_itemProviderGroups')(i).forEach(name => {
        byProvSize[name]=(byProvSize[name]||0)+(i.size_b||0);
      });
    });
    const provSizeEntries=[
      ...provEntries.map(([k])=>[k,byProvSize[k]||0]),
      ...(noneSize>0 ? [[noProviderLabel,noneSize]] : []),
    ];
    const provColorFnWithNone=(k,i)=> k===noProviderLabel ? '#555577' : provColors[i%provColors.length];
    const provPieHtml = provEntries.length
      ? switchablePie('prov',getDep('t')('stats.providers'), provSizeEntries, provCountEntries, provColorFnWithNone, getDep('_providerGroupLabel'), 'count')
      : '';

    // ── QUALITY SCORE (5 tranches 0-20/21-40/41-60/61-80/81-100) ──────────
    const qualityChartHtml = getDep('allItems').some(i=>i.quality) ? (()=>{
      const tranches = [
        { key: 'range_0_20',   min:  0, max:  20, color: '#ef4444', label: getDep('t')('filters.score.range_0_20')   },
        { key: 'range_20_40',  min: 21, max:  40, color: '#f97316', label: getDep('t')('filters.score.range_20_40')  },
        { key: 'range_40_60',  min: 41, max:  60, color: '#eab308', label: getDep('t')('filters.score.range_40_60')  },
        { key: 'range_60_80',  min: 61, max:  80, color: '#84cc16', label: getDep('t')('filters.score.range_60_80')  },
        { key: 'range_80_100', min: 81, max: 100, color: '#22c55e', label: getDep('t')('filters.score.range_80_100') },
      ];
      const counts = tranches.map(()=>0);
      let totalScore=0, scoredCount=0;
      items.forEach(i=>{
        if(!i.quality) return;
        const s = typeof i.quality.score==='number' ? i.quality.score : (i.quality.level||0)*20;
        totalScore+=s; scoredCount++;
        const idx = tranches.findIndex(tr=>s>=tr.min&&s<=tr.max);
        if(idx>=0) counts[idx]++;
      });
      if(!scoredCount) return '';
      const maxCount=Math.max(...counts,0);
      const avgScore=(totalScore/scoredCount).toFixed(1);
      let html='<div class="stats-block"><div class="stats-block-title">'+getDep('t')('stats.quality_score')+'</div>';
      tranches.forEach((tr,i)=>{
        const count=counts[i];
        const pct=maxCount?Math.round(100*count/maxCount):0;
        html+='<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><div style="width:68px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;color:var(--muted)">'+getDep('escH')(tr.label)+'</div><div style="flex:1;height:6px;background:var(--border);border-radius:2px;overflow:hidden"><div style="height:100%;width:'+pct+'%;background:'+tr.color+'"></div></div><div style="font-size:11px;color:var(--muted);width:30px;text-align:right">'+count+'</div></div>';
      });
      html+='<div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border);font-size:12px;color:var(--muted)">'+getDep('t')('stats.quality_average').replace('{score}',avgScore)+'</div></div>';
      return html;
    })() : '';

    // ── AUDIO LANGUAGE CHART ──────────────────────────────
    const audioLangChartHtml = hasLangData ? switchablePie('audioLang',getDep('t')('stats.audio_languages_chart_title'), audioLangEntriesSize, audioLangEntriesCount, audioLangColorFn, k => k, 'count') : '';

    // ── YEARS OF RELEASE CHART ────────────────────────────────
    const yearChartHtml = yearEntriesCount.length ? (()=>{
      return '<div class="stats-block">'
        +'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border)">'
          +'<div class="stats-block-title" style="margin-bottom:0;padding-bottom:0;border-bottom:none">'+getDep('t')('stats.release_years')+'</div>'
          +'<div id="yearControls" class="pie-switch">'
            +'<button class="pie-switch-btn active" data-year-period="years">'+getDep('t')('stats.years')+'</button>'
            +'<button class="pie-switch-btn" data-year-period="decades">'+getDep('t')('stats.decades')+'</button>'
          +'</div>'
        +'</div>'
        +'<div id="yearCharts">'+buildYearChart('years')+'</div>'
        +'</div>';
    })() : '';

    // ── Monthly curve ────────────────────────────────────────
    const curveHtml = keys.length >= 2
      ? '<div class="stats-block">'
        +'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border)">'
          +'<div class="stats-block-title" style="margin-bottom:0;padding-bottom:0;border-bottom:none">'+getDep('t')('stats.monthly_evolution')+'</div>'
          +'<div id="curveControls" class="pie-switch">'
            +'<button class="pie-switch-btn"        data-period="all"  >'+getDep('t')('stats.all')+'</button>'
            +'<button class="pie-switch-btn active" data-period="12m"  >'+getDep('t')('stats.months_12')+'</button>'
            +'<button class="pie-switch-btn"        data-period="30d"  >'+getDep('t')('stats.days_30')+'</button>'
          +'</div>'
        +'</div>'
        +'<div id="curveCharts">'+buildCurveForPeriod('12m')+'</div>'
        +'</div>'
      : '';

    // ── BUILD FINAL LAYOUT (SPEC: exactly 9 blocks) ──────────────────────
    // Block A-G: 6 pies (1/2 width) + 1 quality bars (1/2 width)
    // Block H: Years chart (FULL WIDTH)
    // Block I: Evolution curve (FULL WIDTH)

    return ''
      // Row 1: Dossiers (1/2) | Fournisseurs (1/2)
      + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;width:100%">'
        + '<div>'+(hasCategories ? switchablePie('category',getDep('t')('stats.categories'), categoryEntriesSize, categoryEntriesCount, categoryColorFn, k => k, 'size') : '')+'</div>'
        + '<div>'+provPieHtml+'</div>'
      + '</div>'
      // Row 2: Résolution (1/2) | Codec vidéo (1/2)
      + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;width:100%">'
        + '<div>'+(resEntriesSize.length ? switchablePie('res',getDep('t')('stats.resolution'), resEntriesSize, resEntriesCount, resColorFn, k => k, 'count') : '')+'</div>'
        + '<div>'+(codecEntriesSize.length ? switchablePie('codec',getDep('t')('stats.codec'), codecEntriesSize, codecEntriesCount, codecColorFn, k => getDep('getFilterDisplayValue')(k), 'count') : '')+'</div>'
      + '</div>'
      // Row 3: Codec audio (1/2) | Langues (1/2)
      + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;width:100%">'
        + '<div>'+(audioCodecEntriesSize.length ? switchablePie('audioCodec',getDep('t')('stats.audio_codec_chart_title'), audioCodecEntriesSize, audioCodecEntriesCount, audioCodecColorFn, getDep('getAudioCodecDisplay'), 'count') : '')+'</div>'
        + '<div>'+audioLangChartHtml+'</div>'
      + '</div>'
      // Row 4: Qualité (1/2) | [empty] (1/2)
      + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;width:100%">'
        + '<div>'+qualityChartHtml+'</div>'
        + '<div></div>'
      + '</div>'
      // Block H: Years (FULL WIDTH)
      + yearChartHtml
      // Block I: Evolution (FULL WIDTH)
      + curveHtml;
  }

  // ── STATS PANEL INTERACTIONS ──────────────────────────
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
    controls.querySelectorAll('.pie-switch-btn').forEach(b=>b.classList.toggle('active', b===btn));
    const charts = document.getElementById('curveCharts');
    if (charts) charts.innerHTML = getDep('_buildCurveForPeriodGlobal')(period);
  }

  function setYearPeriod(btn) {
    const controls = document.getElementById('yearControls');
    if (!controls) return;
    const period = btn.dataset.yearPeriod;
    controls.querySelectorAll('.pie-switch-btn').forEach(b=>b.classList.toggle('active', b===btn));
    const charts = document.getElementById('yearCharts');
    if (charts) charts.innerHTML = getDep('_buildYearChartGlobal')(period);
  }

  // ── EXPORT API ─────────────────────────────────────────
  window.MMLStats = {
    renderStatsPanel,
    init
  };

  // Initialize event delegation on module load
  initializeEventHandlers();
})();
