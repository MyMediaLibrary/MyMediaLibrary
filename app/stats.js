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
 * Dependencies (from global scope):
 * - filterItems(), getNormalizedVideoCodec(), getNormalizedAudioCodec(), etc.
 * - t() for i18n
 * - fmtSize(), escH() utilities
 * - allItems, PALETTE, PROVIDERS_META, providerCatalog globals
 */

(function() {
  'use strict';

  // ── STATS PANEL ──────────────────────────────────────
  function renderStatsPanel() {
    const items = window.filterItems();
    document.getElementById('statsContent').innerHTML = buildStats(items);
  }

  function buildStats(items) {
    items = items || window.allItems;
    const isFiltered = items.length < window.allItems.length;
    if (!items.length) return '<p style="color:var(--muted);padding:40px">'+window.t('library.no_results')+'</p>';

    const totalBytes = items.reduce((s,i)=>s+(i.size_b||0),0);
    const totalFiles = items.reduce((s,i)=>s+(i.file_count||0),0);

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
          slices += '<path d="M'+CX+','+CY+' L'+x1.toFixed(2)+','+y1.toFixed(2)+' A'+R+','+R+' 0 '+large+',1 '+x2.toFixed(2)+','+y2.toFixed(2)+' Z" fill="'+col+'"><title>'+window.escH(labelFn(k))+' — '+fmtFn(val)+' ('+Math.round(frac*100)+'%)</title></path>';
        }
        angle = a2;
      });
      // donut hole
      slices += '<circle cx="'+CX+'" cy="'+CY+'" r="'+(R*0.52)+'" fill="var(--surface)"/>';
      // center label
      slices += '<text x="'+CX+'" y="'+(CY-7)+'" text-anchor="middle" font-size="11" font-weight="700" fill="var(--text)">'+entries.length+'</text>';
      slices += '<text x="'+CX+'" y="'+(CY+8)+'" text-anchor="middle" font-size="9" fill="var(--muted)">'+(entries.length>1?window.t('stats.entries'):window.t('stats.entry'))+'</text>';

      const svg = '<svg viewBox="0 0 '+SIZE+' '+SIZE+'" width="'+SIZE+'" height="'+SIZE+'" style="flex-shrink:0">'+slices+'</svg>';
      const legend = '<div class="pie-legend">'+entries.slice(0,12).map(([k,v],idx)=>{
        const val=valFn(v), pct=Math.round(val/total*100);
        return '<div class="pie-leg-row">'
          +'<div class="pie-leg-dot" style="background:'+colorFn(k,idx)+'"></div>'
          +'<div class="pie-leg-label" title="'+window.escH(labelFn(k))+'">'+window.escH(labelFn(k))+'</div>'
          +'<div class="pie-leg-val">'+fmtFn(val)+'</div>'
          +'<div class="pie-leg-pct">'+pct+'%</div>'
          +'</div>';
      }).join('')+(entries.length>12?'<div style="font-size:11px;color:var(--muted);padding-top:2px">+' + (entries.length-12) + ' autres</div>':'')+'</div>';
      return '<div class="pie-wrap">'+svg+legend+'</div>';
    }

    // ── Aggregate by group ────────────────────────────────
    const byGroup={}, byCat={}, byGroupCount={}, byCatCount={};
    items.forEach(i=>{
      const g=i.group||'Autres';
      byGroup[g]=(byGroup[g]||0)+(i.size_b||0);
      byGroupCount[g]=(byGroupCount[g]||0)+1;
      byCat[i.category]=(byCat[i.category]||0)+(i.size_b||0);
      byCatCount[i.category]=(byCatCount[i.category]||0)+1;
    });
    const groupEntriesSize = Object.entries(byGroup).sort((a,b)=>b[1]-a[1]);
    const groupEntriesCount = Object.entries(byGroupCount).sort((a,b)=>b[1]-a[1]);
    const catEntriesSize = Object.entries(byCat).sort((a,b)=>b[1]-a[1]);
    const catEntriesCount = Object.entries(byCatCount).sort((a,b)=>b[1]-a[1]);

    // ── Codec ────────────────────────────────────────────
    const CODEC_COLORS = ['#f59e0b','#3b82f6','#10b981','#ef4444','#8b5cf6','#ec4899','#14b8a6'];
    const byCodec={}, byCodecCount={};
    items.forEach(i=>{
      const key = window.getNormalizedVideoCodec(i);
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
      const key = window.getNormalizedAudioCodec(i);
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
      const key = window.getAudioLanguageSimpleDisplay(window.getAudioLanguageSimple(i));
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
      const r=window.getNormalizedResolution(i);
      byRes[r]=(byRes[r]||0)+(i.size_b||0);
      byResCount[r]=(byResCount[r]||0)+1;
    });
    const resColorFn=(k)=>RES_COLORS[k]||'#888';
    const resEntriesSize = RES_ORDER.filter(r=>byRes[r]).map(r=>[r,byRes[r]]);
    const resEntriesCount = RES_ORDER.filter(r=>byResCount[r]).map(r=>[r,byResCount[r]]);

    // ── Providers ─────────────────────────────────────────
    const groupedProviderCount = window.MMLLogic?.groupedProviderCounts
      ? window.MMLLogic.groupedProviderCounts(items, window._providerGroupKey, window._pname)
      : (() => {
          const fallback = {};
          items.forEach(i => window._itemProviderGroups(i).forEach(name => {
            fallback[name] = (fallback[name] || 0) + 1;
          }));
          return fallback;
        })();
    const byProv = {};
    Object.entries(groupedProviderCount).forEach(([name, count]) => {
      byProv[name] = { count, logo: '' };
    });
    items.forEach(i => (i.providers || []).forEach(p => {
      const rawName = window._pname(p);
      const name = window._providerGroupKey(rawName);
      if (!name || !byProv[name] || name === window.PROVIDER_OTHERS_KEY) return;
      if (!byProv[name].logo) byProv[name].logo = window._plogo(p);
    }));
    const provEntries=Object.entries(byProv).sort((a,b)=>b[1].count-a[1].count);
    const maxPC = provEntries[0]?.[1].count||1;
    const provColors=['#7c6aff','#ff6a6a','#4ecdc4','#f7b731','#a78bfa','#f97316','#34d399','#60a5fa','#f472b6'];

    // ── Provider x group cross table ──────────────────────
    const provNames=provEntries.map(([k])=>k);
    const provByGroup={};
    items.forEach(i=>{
      const g=i.group||'Autres';
      if(!provByGroup[g]) provByGroup[g]={};
      window._itemProviderGroups(i).forEach(n => { provByGroup[g][n]=(provByGroup[g][n]||0)+1; });
    });
    const provByCat={};
    items.forEach(i=>{
      if(!provByCat[i.category]) provByCat[i.category]={};
      window._itemProviderGroups(i).forEach(n => { provByCat[i.category][n]=(provByCat[i.category][n]||0)+1; });
    });

    function crossTable(rowEntries, rowColorFn, transpose) {
      if(!provNames.length) return '<p style="font-size:12px;color:var(--muted)">'+window.t('stats.no_provider_data')+'</p>';
      if (transpose) {
        const colKeys = rowEntries.map(([k])=>k);
        const colColorFn = rowColorFn;
        const headers = colKeys.map(k=>'<th style="color:'+colColorFn(k)+'">'+window.escH(k)+'</th>').join('');
        const rows = provNames.map((p,idx)=>{
          const logo=(p !== window.PROVIDER_OTHERS_KEY && (window.PROVIDERS_META[p]?.logo_url||window.providerCatalog[p]))?'<img class="cross-logo" src="'+window.escH(window.PROVIDERS_META[p]?.logo_url||window.providerCatalog[p]||'')+'" alt=""/>':'';
          const cells=rowEntries.map(([k,pmap])=>{
            const n=pmap[p]||0;
            return '<td style="color:'+(n?'var(--text)':'var(--border)')+';">'+(n||'–')+'</td>';
          }).join('');
          return '<tr><td style="font-weight:600">'+logo+window.escH(window._providerGroupLabel(p))+'</td>'+cells+'</tr>';
        }).join('');
        return '<div class="cross-wrap"><table class="cross-table"><thead><tr><th></th>'+headers+'</tr></thead><tbody>'+rows+'</tbody></table></div>';
      }
      const headers = provNames.map(p=>{
        const logo=(p !== window.PROVIDER_OTHERS_KEY && (window.PROVIDERS_META[p]?.logo_url||window.providerCatalog[p]))?'<img class="cross-logo" src="'+window.escH(window.PROVIDERS_META[p]?.logo_url||window.providerCatalog[p]||'')+'" alt=""/>':'';
        return '<th>'+logo+window.escH(window._providerGroupLabel(p))+'</th>';
      }).join('');
      const rows = rowEntries.map(([k,pmap])=>{
        const cells=provNames.map(p=>{
          const n=pmap[p]||0;
          return '<td style="color:'+(n?'var(--text)':'var(--border)')+';">'+(n||'–')+'</td>';
        }).join('');
        return '<tr><td style="font-weight:600;color:'+rowColorFn(k)+'">'+window.escH(k)+'</td>'+cells+'</tr>';
      }).join('');
      return '<div class="cross-wrap"><table class="cross-table"><thead><tr><th></th>'+headers+'</tr></thead><tbody>'+rows+'</tbody></table></div>';
    }

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

    function makeCurve(keys, vals, color, gradId, labelFn, titleFn) {
      const maxV=Math.max(...vals,0);
      if(!maxV||keys.length<2) return '<p style="font-size:12px;color:var(--muted)">'+window.t('stats.not_enough_data')+'</p>';
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
      let useDaily=false, keys=[];
      if(period==='30d'){
        useDaily=true;
        const cutoff=new Date(now); cutoff.setDate(cutoff.getDate()-30);
        const ck=cutoff.getFullYear()+'-'+String(cutoff.getMonth()+1).padStart(2,'0')+'-'+String(cutoff.getDate()).padStart(2,'0');
        keys=Object.keys(allByDay).filter(k=>k>=ck).sort();
      } else {
        let mkeys=Object.keys(allByMonth).sort();
        if(period==='12m'){
          const cutoff=new Date(now); cutoff.setFullYear(cutoff.getFullYear()-1);
          const ck=cutoff.getFullYear()+'-'+String(cutoff.getMonth()+1).padStart(2,'0');
          keys=mkeys.filter(k=>k>=ck);
        } else {
          keys=mkeys;
        }
      }
      const byK=useDaily?allByDay:allByMonth;
      const countVals=keys.map(k=>(byK[k]||{count:0}).count);
      const sizeVals=keys.map(k=>(byK[k]||{size:0}).size);
      return '<div class="curve-label">'+window.t('stats.items_added')+'</div>'
        +makeCurve(keys,countVals,'#3b82f6','gradCount',window.fmtSize,c=>String(c))
        +'<div class="curve-label" style="margin-top:20px">'+window.t('stats.size_added')+'</div>'
        +makeCurve(keys,sizeVals,'#ef4444','gradSize',window.fmtSize,window.fmtSize);
    }
    window._buildCurveForPeriodGlobal = buildCurveForPeriod;

    // ── Year/Decade aggregation ───────────────────────────
    const hasGroups = groupEntriesSize.length > 0;
    const groupColorFn=(k)=>window.PALETTE[window.allItems.findIndex(i=>(i.group||'Autres')===k)%window.PALETTE.length];
    const catColorFn=(k)=>window.PALETTE[window.allItems.findIndex(i=>i.category===k)%window.PALETTE.length];

    function switchablePie(id, title, sizeEntries, countEntries, colorFn, labelFn = k => k, defaultUnit = 'size') {
      const showCountByDefault = defaultUnit === 'count';
      const pieSize  = makePie(sizeEntries,  colorFn, v=>v, k=>labelFn(k), window.fmtSize);
      const pieCount = makePie(countEntries, colorFn, v=>v, k=>labelFn(k), v=>String(v));
      return '<div class="stats-block">'
        +'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border)">'
          +'<div class="stats-block-title" style="margin-bottom:0;padding-bottom:0;border-bottom:none">'+title+'</div>'
          +'<div class="pie-switch">'
            +'<button class="pie-switch-btn'+(showCountByDefault ? '' : ' active')+'" id="'+id+'BtnSize"  data-pie="'+id+'" data-unit="size"  onclick="window.MMLStats.statSwitchPie(this)">'+window.t('stats.by_size')+'</button>'
            +'<button class="pie-switch-btn'+(showCountByDefault ? ' active' : '')+'" id="'+id+'BtnCount" data-pie="'+id+'" data-unit="count" onclick="window.MMLStats.statSwitchPie(this)">'+window.t('stats.by_count')+'</button>'
          +'</div>'
        +'</div>'
        +'<div id="'+id+'PieSize"'+(showCountByDefault ? ' style="display:none"' : '')+'>'+pieSize+'</div>'
        +'<div id="'+id+'PieCount"'+(showCountByDefault ? '' : ' style="display:none"')+'>'+pieCount+'</div>'
        +'</div>';
    }

    // Group pies
    const groupPieSize = hasGroups ? makePie(groupEntriesSize, groupColorFn, v=>v, k=>k, window.fmtSize) : '';
    const groupPieCount = hasGroups ? makePie(groupEntriesCount, groupColorFn, v=>v, k=>k, v=>String(v)) : '';

    // Cat pies
    const catPieSize = makePie(catEntriesSize, catColorFn, v=>v, k=>k, window.fmtSize);
    const catPieCount = makePie(catEntriesCount, catColorFn, v=>v, k=>k, v=>String(v));

    // Provider pie (including "Aucun") — switchable taille/nombre
    const provColorFn=(k,i)=>provColors[i%provColors.length];
    const noProviderLabel = window.t('filters.no_provider');
    const noneCount = items.filter(i=>!(i.providers&&i.providers.length)).length;
    const noneSize  = items.filter(i=>!(i.providers&&i.providers.length)).reduce((s,i)=>s+(i.size_b||0),0);
    const provCountEntries=[
      ...provEntries.map(([k,v])=>[k,v.count]),
      ...(noneCount>0 ? [[noProviderLabel,noneCount]] : []),
    ];
    const byProvSize={};
    items.forEach(i=>{
      window._itemProviderGroups(i).forEach(name => {
        byProvSize[name]=(byProvSize[name]||0)+(i.size_b||0);
      });
    });
    const provSizeEntries=[
      ...provEntries.map(([k])=>[k,byProvSize[k]||0]),
      ...(noneSize>0 ? [[noProviderLabel,noneSize]] : []),
    ];
    const provColorFnWithNone=(k,i)=> k===noProviderLabel ? '#555577' : provColors[i%provColors.length];
    const provPieHtml = provEntries.length
      ? switchablePie('prov',window.t('stats.providers'), provSizeEntries, provCountEntries, provColorFnWithNone, window._providerGroupLabel, 'count')
      : '';

    // Cross tables
    const crossGroupRows = Object.entries(provByGroup).sort((a,b)=>Object.values(b[1]).reduce((s,v)=>s+v,0)-Object.values(a[1]).reduce((s,v)=>s+v,0));
    const crossCatRows = Object.entries(provByCat).sort((a,b)=>Object.values(b[1]).reduce((s,v)=>s+v,0)-Object.values(a[1]).reduce((s,v)=>s+v,0));

    // ── GLOBAL ENCART (always uses allItems, ignores filters) ──────────
    const globalMovies  = window.allItems.filter(i=>i.type==='movie').length;
    const globalSeries  = window.allItems.filter(i=>i.type==='tv').length;
    const globalBytes   = window.allItems.reduce((s,i)=>s+(i.size_b||0),0);
    const globalFiles   = window.allItems.reduce((s,i)=>s+(i.file_count||0),0);
    const globalEmph = '<span style="font-weight:700;color:var(--accent)">'+Math.round(100*items.length/window.allItems.length)+'%</span>';
    const globalText = window.allItems.length===items.length
      ? window.t('stats.global_all_items')
      : window.t('stats.global_filtered_items').replace('{items}', items.length + ' / ' + window.allItems.length).replace('{pct}', globalEmph);
    const globalHtml = '<div class="stats-block"><div class="stats-block-title">'+window.t('stats.library_stats')+'</div>'
      +'<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px">'
        +'<div style="display:flex;gap:8px"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="icon-sm"><rect x="3" y="2" width="18" height="20" rx="2" ry="2"/><line x1="8" y1="6" x2="16" y2="6"/><line x1="8" y1="10" x2="16" y2="10"/><line x1="8" y1="14" x2="16" y2="14"/></svg><div>'+globalMovies+' '+window.t('library.movies')+'</div></div>'
        +'<div style="display:flex;gap:8px"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="icon-sm"><rect x="3" y="2" width="18" height="20" rx="2" ry="2"/><line x1="8" y1="6" x2="16" y2="6"/><line x1="8" y1="10" x2="16" y2="10"/></svg><div>'+globalSeries+' '+window.t('library.series')+'</div></div>'
      +'</div>'
      +'<div style="color:var(--muted);font-size:12px;margin-bottom:16px">'+window.fmtSize(globalBytes)+' — '+globalFiles+' '+window.t('stats.files')+'</div>'
      +'<div style="color:var(--muted);font-size:12px">'+globalText+'</div>'
      +'</div>';

    // ── QUALITY SCORE ─────────────────────────────────────
    const qualityChartHtml = window.allItems.some(i=>i.quality) ? (()=>{
      const byScore={};
      items.forEach(i=>{
        if(!i.quality) return;
        const l=i.quality.level||0;
        byScore[l]=(byScore[l]||0)+1;
      });
      if(!Object.keys(byScore).length) return '';
      const scoreColorFn=(l)=>['#78716c','#f87171','#fb923c','#fbbf24','#4ade80','#22c55e'][Math.min(Math.max(l,0),5)];
      const scoreEntries=Object.entries(byScore).sort((a,b)=>Number(b[0])-Number(a[0]));
      const scoreLabels={0:window.t('quality_level.0'),1:window.t('quality_level.1'),2:window.t('quality_level.2'),3:window.t('quality_level.3'),4:window.t('quality_level.4'),5:window.t('quality_level.5')};
      return switchablePie('score',window.t('stats.quality_score'), scoreEntries, scoreEntries, scoreColorFn, l=>scoreLabels[l]||l, 'count');
    })() : '';

    // ── AUDIO LANGUAGE CHART ──────────────────────────────
    const audioLangChartHtml = hasLangData ? switchablePie('audioLang',window.t('stats.audio_languages_chart_title'), audioLangEntriesSize, audioLangEntriesCount, audioLangColorFn, k => k, 'count') : '';

    // ── Monthly curve ────────────────────────────────────────
    const curveHtml = keys.length >= 2
      ? buildCurveForPeriod('12m')
      + '<div id="curveControls" style="margin-top:12px;display:flex;gap:4px;justify-content:center">'
        +'<button class="pie-switch-btn"        data-period="all"  onclick="window.MMLStats.setCurvePeriod(this)">'+window.t('stats.all')+'</button>'
        +'<button class="pie-switch-btn active" data-period="12m"  onclick="window.MMLStats.setCurvePeriod(this)">'+window.t('stats.months_12')+'</button>'
        +'<button class="pie-switch-btn"        data-period="30d"  onclick="window.MMLStats.setCurvePeriod(this)">'+window.t('stats.days_30')+'</button>'
      +'</div>'
      +'<div id="curveCharts" style="margin-top:12px">'+buildCurveForPeriod('12m')+'</div>'
      : '';

    // Find if data has keys
    const allByDayKeys = Object.keys(allByDay);
    const keys = Object.keys(allByMonth);

    const topChartsHtml = [
      globalHtml,
      (hasGroups ? switchablePie('group',window.t('stats.groups'), groupEntriesSize, groupEntriesCount, groupColorFn, k => k, 'size') : ''),
      '<div class="stats-block"><div class="stats-block-title">'+window.t('stats.categories')+'</div>'+
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border)">' +
          '<div style="font-size:11px;color:var(--muted)">'+catEntriesSize.length+' '+window.t('stats.categories')+'</div>' +
        '</div>' +
        catEntriesSize.map((cat,idx)=>{
          function makeHBar(label, count, total, color) {
            const pct = Math.round(100*count/total);
            return '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><div style="width:40px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;color:var(--muted)" title="'+window.escH(label)+'">'+window.escH(label)+'</div><div style="flex:1;height:6px;background:var(--border);border-radius:2px;overflow:hidden"><div style="height:100%;width:'+pct+'%;background:'+color+'"></div></div><div style="font-size:11px;color:var(--muted);width:30px;text-align:right">'+pct+'%</div></div>';
          }
          return makeHBar(window.getFilterDisplayValue(cat[0]), cat[1], totalBytes, window.PALETTE[idx%window.PALETTE.length]);
        }).join('')+
      '</div>',
      provPieHtml,
      (resEntriesSize.length ? switchablePie('res',window.t('stats.resolution'), resEntriesSize, resEntriesCount, resColorFn, k => k, 'count') : ''),
      (codecEntriesSize.length ? switchablePie('codec',window.t('stats.codec'), codecEntriesSize, codecEntriesCount, codecColorFn, k => window.getFilterDisplayValue(k), 'count') : ''),
      (audioCodecEntriesSize.length ? switchablePie('audioCodec',window.t('stats.audio_codec_chart_title'), audioCodecEntriesSize, audioCodecEntriesCount, audioCodecColorFn, window.getAudioCodecDisplay, 'count') : ''),
      audioLangChartHtml,
      qualityChartHtml
    ].filter(Boolean).join('');

    // ── Year-decade view (full width) ─────────────────────
    const yearDecadeHtml = crossGroupRows.length > 0 && crossCatRows.length > 0
      ? '<div class="stats-block"><div class="stats-block-title">'+window.t('stats.providers_by_group')+'</div>'+crossTable(crossGroupRows, groupColorFn, false)+'</div>'
      + '<div class="stats-block"><div class="stats-block-title">'+window.t('stats.providers_by_category')+'</div>'+crossTable(crossCatRows, catColorFn, false)+'</div>'
      : '';

    return ''
      +'<div class="stats-row">'+topChartsHtml+'</div>'
      +yearDecadeHtml
      +'<div class="stats-block"><div class="stats-block-title">'+window.t('stats.monthly_evolution')+'</div>'+curveHtml+'</div>';
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
    if (charts) charts.innerHTML = window._buildCurveForPeriodGlobal(period);
  }

  // ── EXPORT API ─────────────────────────────────────────
  window.MMLStats = {
    renderStatsPanel,
    statSwitchPie,
    setCurvePeriod
  };
})();
