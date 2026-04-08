
// ── I18N ─────────────────────────────────────────────
let TRANSLATIONS = {};
let CURRENT_LANG = 'fr';

async function loadTranslations(lang) {
  try {
    const res = await fetch(`/i18n/${lang}.json?_=` + Date.now());
    if (!res.ok) return;
    TRANSLATIONS = await res.json();
    CURRENT_LANG = lang;
  } catch(e) { console.warn('i18n load error:', e); }
}

function t(key, vars = {}) {
  const keys = key.split('.');
  let val = keys.reduce((obj, k) => obj?.[k], TRANSLATIONS);
  if (typeof val !== 'string') { console.warn('Missing translation key:', key); return key; }
  Object.entries(vars).forEach(([k, v]) => { val = val.split(`{${k}}`).join(String(v)); });
  return val;
}

function applyTranslations() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.title = t(el.dataset.i18nTitle);
  });
}

let allItems=[], categories=[], groups=[];
  let providerCatalog={};          // legacy fallback (old library.json without providers_meta)
  let PROVIDERS_META = {};         // {name: {logo, logo_url}} — canonical source since v2
  let PROVIDERS_LOGOS = {};        // {name: filename} — logos section from /providers.json
  let audioCodecMapping = {};      // loaded from /audiocodec_mapping.json

  async function loadProvidersLogos() {
    try {
      const res = await fetch('/providers.json?_=' + Date.now());
      if (res.ok) {
        const data = await res.json();
        PROVIDERS_LOGOS = (data && data.logos) ? data.logos : {};
      }
    } catch(e) { console.warn('providers.json load error:', e); }
  }

  async function loadAudioCodecMapping() {
    try {
      const res = await fetch('/audiocodec_mapping.json?_=' + Date.now());
      if (res.ok) audioCodecMapping = await res.json();
    } catch(e) { console.warn('audiocodec_mapping.json load error:', e); }
  }

  function getAudioCodecDisplay(normalized) {
    if (!normalized || normalized === 'UNKNOWN')
      return audioCodecMapping.fallback?.display ?? 'Unknown';
    const entry = Object.values(audioCodecMapping.mapping ?? {})
      .find(e => e.normalized === normalized);
    return entry?.display ?? normalized;
  }

  function getProviderLogo(name) {
    const logo = PROVIDERS_LOGOS[name];
    return logo ? `/assets/providers/${logo}` : null;
  }

  // Helpers: handle both string providers (new) and {name,logo} objects (legacy)
  function _pname(p){ return (p && typeof p==='object') ? (p.name||'') : (p||''); }
  function _plogo(p){
    const name = _pname(p);
    const logo = getProviderLogo(name) || PROVIDERS_META[name]?.logo_url || (p && typeof p==='object' ? p.logo : null) || providerCatalog[name] || '';
    if (!logo) console.warn('Unmapped provider:', name);
    return logo;
  }

  // Visibility prefs (null = all visible; Set = specific visible names)
  let visibleCategories = null;
  let visibleProviders  = null;
  function _catVisible(cat)  { return !visibleCategories || visibleCategories.has(cat); }
  function _provVisible(prov){ return !visibleProviders  || visibleProviders.has(prov); }
  // Returns only the providers of an item that are currently visible
  function _itemVisProviders(item){ return (item.providers||[]).filter(p=>_provVisible(_pname(p))); }

  let enablePlot=false, enableMovies=true, enableSeries=true, enableJellyseerr=true;
  let activeGroup='all', activeCat='all', activeProvider='all', activeResolution='all', activeType='all', activeCodec='all', activeAudioCodec='all';
  let appConfig = {};            // loaded from /api/config
  let serverConfig = {};         // from library.json config block

  function saveState() {
    try {
      localStorage.setItem('mediaState', JSON.stringify({
        activeGroup, activeCat, activeProvider, activeResolution, activeType, activeCodec, activeAudioCodec,
        currentTab, currentView,
        searchLib: document.getElementById('searchInput')?.value || '',
        sortVal: document.getElementById('sortSelect')?.value || '',
      }));
    } catch(e) {}
  }

  function restoreState() {
    try {
      const s = JSON.parse(localStorage.getItem('mediaState') || '{}');
      if (s.activeType)       activeType       = s.activeType;
      if (s.activeGroup)      activeGroup      = s.activeGroup;
      if (s.activeCat)        activeCat        = s.activeCat;
      if (s.activeProvider)   activeProvider   = s.activeProvider;
      if (s.activeResolution) activeResolution = s.activeResolution;
      if (s.activeCodec)      activeCodec      = s.activeCodec;
      if (s.activeAudioCodec) activeAudioCodec = s.activeAudioCodec;
      if (s.currentView)      setView(s.currentView, true);
      if (s.sortVal) {
        const el = document.getElementById('sortSelect');
        if (el) el.value = s.sortVal;
      }
      if (s.searchLib) {
        const el = document.getElementById('searchInput');
        if (el) el.value = s.searchLib;
      }
      // Re-render all filter pills with correct active states (no saveState)
      renderStorageBar();
      renderProviderFilter();
      renderResolutionFilter();
      renderCodecFilter();
      renderAudioCodecFilter();
      // Sync type pills
      if (s.activeType) {
        ['#typeFilter','#typeFilterTop'].forEach(sel => {
          document.querySelectorAll(sel+' .provider-pill').forEach(p => {
            const t = p.dataset.type || 'all';
            p.classList.toggle('active', s.activeType==='all' ? !p.dataset.type : t===s.activeType);
          });
        });
      }
      if (s.currentTab && s.currentTab === 'stats') switchTab(s.currentTab);
    } catch(e) {}
  }
  let currentView='grid', currentTab='library';
  let tSortCol=null, tSortDir=1;
  let providerColorMap={};

  const PALETTE=['#7c6aff','#ff6a6a','#4ecdc4','#f7b731','#a78bfa',
    '#f97316','#34d399','#60a5fa','#f472b6','#facc15',
    '#2dd4bf','#c084fc','#fb923c','#86efac','#93c5fd'];

  let groupColorMap={}, catColorMap={};

  // ── LOAD ─────────────────────────────────────────────
  async function loadVersion() {
    try {
      const r = await fetch('/version.json?_='+Date.now());
      if (!r.ok) return;
      const v = await r.json();
      const el = document.getElementById('appVersionStr');
      if (!el) return;
      const parts = ['v' + (v.version || 'dev')];
      if (v.commit && v.commit !== 'dev') parts.push(v.commit);
      if (v.build_date) {
        const d = new Date(v.build_date);
        parts.push(d.toLocaleDateString(CURRENT_LANG === 'fr' ? 'fr-FR' : 'en-US', {year:'numeric',month:'long',day:'numeric'}));
      }
      el.textContent = parts.join(' • ');
    } catch(_) {}
  }

  async function loadLibrary() {
    await Promise.all([loadConfig(), loadProvidersLogos(), loadAudioCodecMapping()]);

    // Load translations for the configured language
    const lang = appConfig.system?.language || 'fr';
    if (lang !== CURRENT_LANG || !Object.keys(TRANSLATIONS).length) {
      await loadTranslations(lang);
    }
    applyTranslations();

    // First-run: no folder has been assigned a type yet → show onboarding
    const folders = appConfig.folders || [];
    const hasConfigured = folders.some(f => f.type && f.type !== 'ignore' && !f.missing);
    if (!hasConfigured) { showOnboarding(); return; }

    try {
      const r = await fetch('./library.json?_='+Date.now());
      if (r.status === 404) { showOnboarding(); return; }
      if (!r.ok) throw new Error('HTTP '+r.status);
      const data = await r.json();
      allItems=data.items||[]; categories=data.categories||[]; groups=data.groups||[];
      // providers_meta: canonical logo source (new format)
      PROVIDERS_META = data.providers_meta || {};
      // Legacy fallback: old library.json used providers_catalog or embedded {name,logo} objects
      if (data.providers_catalog) providerCatalog = data.providers_catalog;
      allItems.forEach(i=>(i.providers||[]).forEach(p=>{
        if (p && typeof p==='object' && p.name && p.logo && !providerCatalog[p.name])
          providerCatalog[p.name] = p.logo;
      }));
      groups.forEach((g,i)=>{ groupColorMap[g]=PALETTE[i%PALETTE.length]; });
      categories.forEach((c,i)=>{ catColorMap[c]=PALETTE[i%PALETTE.length]; });
      // Build provider color map from unique provider names
      const pNames=[...new Set(allItems.flatMap(i=>(i.providers||[]).map(_pname)))].filter(Boolean).sort();
      pNames.forEach((n,i)=>{ providerColorMap[n]=PALETTE[(i+5)%PALETTE.length]; });
      const d=new Date(data.scanned_at);
      const locale = CURRENT_LANG === 'en' ? 'en-GB' : 'fr-FR';
      document.getElementById('scanInfo').innerHTML=
        t('library.last_scan')+' <span class="scan-ts-link" onclick="openLogViewer()" title="Voir le log">'+
        d.toLocaleDateString(locale)+' '+d.toLocaleTimeString(locale,{hour:'2-digit',minute:'2-digit'})+'</span>';
      if (data.library_path) document.getElementById('brandSub').textContent=data.library_path;
      if (data.config) serverConfig = data.config;
      renderStorageBar();
      renderProviderFilter();
      renderResolutionFilter();
      renderCodecFilter();
      restoreState();
      renderStats(filterItems());
      render();
    } catch(e) {
      console.error('loadLibrary error:', e);
      const _emsg = String(e).includes('404') ? t('library.run_scan') : escH(String(e));
      document.getElementById('library').innerHTML='<div class="empty"><p>'+t('library.not_found')+'</p><small>'+_emsg+'</small></div>';
      document.getElementById('scanInfo').textContent=t('library.scan_error');
    }
  }


  // ── CONFIG ───────────────────────────────────────────
  function folderToCategoryName(name) {
    return name.replace(/[-_]/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  async function loadConfig() {
    // Migrate legacy mediaSettings from localStorage (one-time)
    const legacy = localStorage.getItem('mediaSettings');
    if (legacy) {
      try {
        const ls = JSON.parse(legacy);
        const mig = {};
        if (ls.enablePlot    !== undefined) { mig.ui = mig.ui||{}; mig.ui.synopsis_on_hover = ls.enablePlot; }
        if (ls.accentColor   !== undefined) { mig.ui = mig.ui||{}; mig.ui.accent_color = ls.accentColor; }
        if (ls.jellyseerrUrl !== undefined || ls.enableJellyseerr !== undefined) {
          mig.jellyseerr = {};
          if (ls.jellyseerrUrl     !== undefined) mig.jellyseerr.url     = ls.jellyseerrUrl;
          if (ls.enableJellyseerr  !== undefined) mig.jellyseerr.enabled = ls.enableJellyseerr;
        }
        if (Object.keys(mig).length) await saveConfig(mig);
      } catch(e) {}
      localStorage.removeItem('mediaSettings');
    }

    try {
      const r = await fetch('/api/config');
      if (!r.ok) return;
      appConfig = await r.json();

      // UI prefs
      enablePlot       = appConfig.ui?.synopsis_on_hover ?? false;
      if (appConfig.ui?.theme)        document.documentElement.setAttribute('data-theme', appConfig.ui.theme);
      if (appConfig.ui?.accent_color) applyAccent(appConfig.ui.accent_color);

      // Apply default_sort if no session sort saved
      const sessionState = JSON.parse(localStorage.getItem('mediaState') || '{}');
      if (!sessionState.sortVal && appConfig.ui?.default_sort) {
        const el = document.getElementById('sortSelect');
        if (el) el.value = appConfig.ui.default_sort;
      }

      // Type visibility
      enableMovies     = appConfig.enable_movies ?? true;
      enableSeries     = appConfig.enable_series ?? true;
      enableJellyseerr = appConfig.jellyseerr?.enabled ?? false;

      // Provider visibility: [] = all visible; non-empty array = whitelist
      const pv = appConfig.providers_visible;
      visibleProviders = Array.isArray(pv) && pv.length > 0 ? new Set(pv) : null;

      // Category visibility: derived from folders with visible=false
      const folders = appConfig.folders || [];
      const hasHidden = folders.some(f => f.visible === false && f.type && f.type !== 'ignore');
      if (hasHidden) {
        visibleCategories = new Set(
          folders
            .filter(f => f.visible !== false && f.type && f.type !== 'ignore')
            .map(f => folderToCategoryName(f.name))
        );
      } else {
        visibleCategories = null;
      }

      _updateTypeFilterVisibility();
    } catch(e) {
      console.warn('loadConfig error:', e);
    }
  }

  async function saveConfig(partial) {
    try {
      const r = await fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(partial),
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
    } catch(e) {
      console.error('saveConfig error:', e);
      throw e;
    }
  }

  // ── STATS ────────────────────────────────────────────
  function renderStats(items) {
    const bytes=items.reduce((s,i)=>s+(i.size_b||0),0);
    const files=items.reduce((s,i)=>s+(i.file_count||0),0);
    const cats=new Set(items.map(i=>i.category)).size;
    const filtered=items.length < allItems.length;
    const elemLabel=filtered
      ? items.length+'<span style="font-size:11px;font-weight:400;color:var(--muted)"> / '+allItems.length+'</span>'
      : items.length;
    document.getElementById('statsBar').innerHTML=
      '<div class="stat"><div class="stat-val">'+elemLabel+'</div><div class="stat-label">'+t('stats.elements')+'</div></div>'+
      '<div class="stat"><div class="stat-val">'+cats+'</div><div class="stat-label">'+t('stats.categories')+'</div></div>'+
      '<div class="stat"><div class="stat-val">'+files.toLocaleString('fr-FR')+'</div><div class="stat-label">'+t('stats.files')+'</div></div>'+
      '<div class="stat"><div class="stat-val">'+fmtSize(bytes)+'</div><div class="stat-label">'+t('stats.disk')+'</div></div>';
    document.querySelectorAll('#mobileStatsBar').forEach(el=>{ el.innerHTML=document.getElementById('statsBar').innerHTML; });

  }

  // ── STORAGE + FILTER BAR ─────────────────────────────
  function renderStorageBar() {
    const sec=document.getElementById('storageSection');
    if (!allItems.length) { sec.style.display='none'; return; }
    const hasGroups=groups.length>0;
    let html='';

    // --- GROUP BAR (only if groups defined) ---
    if (hasGroups) {
      // aggregate items scoped to search + other filters (except group)
      const byG={};
      baseItems('group').forEach(i=>{ const g=i.group||'Autres'; byG[g]=(byG[g]||0)+(i.size_b||0); });
      const totalG=Object.values(byG).reduce((s,v)=>s+v,0);
      html+=barBlock(byG, totalG, activeGroup, groupColorMap,
        t('filters.by_group'), 'clickGroup', 'resetGroup');
    }

    // --- CATEGORY BAR (scoped to active group) ---
    const byC={};
    baseItems('cat').forEach(i=>{ byC[i.category]=(byC[i.category]||0)+(i.size_b||0); });
    const totalC=Object.values(byC).reduce((s,v)=>s+v,0);
    html+=barBlock(byC, totalC, activeCat, catColorMap,
      t('filters.by_category'), 'clickCat', 'resetCat');

    sec.style.display='block';
    sec.innerHTML=html;

  }

  function barBlock(byKey, total, activeKey, cmap, title, clickFn, resetFn) {
    if (!total) return '';
    const sorted=Object.entries(byKey).sort((a,b)=>b[1]-a[1]);
    const resetCls='leg leg-reset'+(activeKey==='all'?' active':'');
    let pills='<div class="'+resetCls+'" onclick="'+resetFn+'()">'+t('filters.all')+'</div>';
    sorted.forEach(([k,v])=>{
      const col=cmap[k]||'#888';
      const cls='leg'+(activeKey===k?' active':'');
      const pct=(v/total*100).toFixed(1);
      pills+='<div class="'+cls+'" onclick="'+clickFn+"('"+escJ(k)+"')"+'" title="'+escH(k)+' — '+fmtSize(v)+'">'
        +'<div class="leg-dot" style="background:'+col+'"></div>'
        +'<span>'+escH(k)+'</span>'
        +'</div>';
    });
    return '<div class="storage-block"><div class="storage-title">'+title+'</div><div class="storage-legend">'+pills+'</div></div>';
  }
  
  function clickType(type) {
    activeType = (type !== 'all' && activeType === type) ? 'all' : type;
    activeCat = 'all';
    ['#typeFilter', '#typeFilterTop', '#typeFilterMobile'].forEach(sel => {
      document.querySelectorAll(sel + ' .provider-pill').forEach(p => {
        const t = p.dataset.type || 'all';
        p.classList.toggle('active', activeType === 'all' ? !p.dataset.type : t === activeType);
      });
    });
    renderStorageBar();
    renderProviderFilter();
    renderResolutionFilter();
    renderCodecFilter();
    onFilter();
  }

  function clickGroup(k){ activeGroup=activeGroup===k?'all':k; activeCat='all'; onFilter(); }
  function resetGroup() { activeGroup='all'; activeCat='all'; onFilter(); }
  function clickCat(k)  { activeCat=activeCat===k?'all':k; onFilter(); }
  function resetCat()   { activeCat='all'; onFilter(); }
  function clickProvider(el){ const k=el.dataset.provider; activeProvider=activeProvider===k?'all':k; onFilter(); }
  function resetProvider(){ activeProvider='all'; onFilter(); }

  // ── PROVIDER FILTER ──────────────────────────────────
  function normalizeProvider(name) {
    return name || null; // normalization done in scanner.py
  }

  function renderProviderFilter() {
    const sec=document.getElementById('providerSection');
    if (!enableJellyseerr) { sec.style.display='none'; const st=document.getElementById('providerSectionTop'); if(st) st.style.display='none'; return; }
    let base=baseItems('provider');
    const byP={};
    base.forEach(i=>(i.providers||[]).forEach(p=>{
      const name=_pname(p); if (!name || !_provVisible(name)) return;
      if (!byP[name]) byP[name]={count:0, name, logo:_plogo(p)};
      byP[name].count++;
      if (!byP[name].logo) byP[name].logo=_plogo(p);
    }));
    const providers=Object.values(byP).sort((a,b)=>b.count-a.count);
    if (!providers.length){sec.style.display='none';return;}
    const resetCls='provider-pill provider-pill-reset'+(activeProvider==='all'?' active':'');
    const noneCls='provider-pill'+(activeProvider==='__none__'?' active':'');
    let pills='<div class="'+resetCls+'" onclick="resetProvider()">'+t('filters.all')+'</div>'
      +'<div class="'+noneCls+'" onclick="clickProvider(this)" data-provider="__none__" title="Sans plateforme reconnue">'+t('filters.none')+'</div>';
    providers.forEach(function(p){
      const cls='provider-pill'+(activeProvider===p.name?' active':'');
      const logo=p.logo?'<img src="'+escH(p.logo)+'" alt=""/>':'';
      pills+='<div class="'+cls+'" onclick="clickProvider(this)" data-provider="'+escH(p.name)+'" title="'+p.count+' element'+(p.count>1?'s':'')+'">'
        +logo+'<span>'+escH(p.name)+'</span></div>';
    });
    const phtml='<div class="storage-block"><div class="storage-title">'+t('filters.streaming_fr')+'</div><div class="provider-filter">'+pills+'</div></div>';
    sec.style.display='block';
    sec.innerHTML=phtml;
    // mirror to top bar
    const secTop=document.getElementById('providerSectionTop');
    if (secTop) { secTop.innerHTML=phtml; secTop.style.display='block'; }
  }
  function renderCodecFilter() {
    const sec = document.getElementById('codecSection');
    if (!sec) return;
    let base = baseItems('codec');
    const counts = {};
    base.forEach(i => { if (i.codec) counts[i.codec] = (counts[i.codec]||0)+1; });
    const codecs = Object.entries(counts).sort((a,b)=>b[1]-a[1]).map(([k])=>k);
    if (!codecs.length) { sec.style.display='none'; return; }
    const resetCls = 'provider-pill provider-pill-reset'+(activeCodec==='all'?' active':'');
    let pills = '<div class="'+resetCls+'" onclick="resetCodec()">'+t('filters.all')+'</div>';
    codecs.forEach(c => {
      const cls = 'provider-pill'+(activeCodec===c?' active':'');
      pills += '<div class="'+cls+'" onclick="clickCodec(this)" data-codec="'+escH(c)+'">'        +'<span class="badge badge-codec" style="margin-left:0">'+escH(c)+'</span>'        +'<span style="margin-left:4px;font-size:11px">'+counts[c]+'</span></div>';
    });
    sec.style.display = 'block';
    sec.innerHTML = '<div class="storage-block"><div class="storage-title">'+t('filters.codec')+'</div><div class="provider-filter">'+pills+'</div></div>';

  }

  function clickCodec(el) {
    const k = el.dataset.codec;
    activeCodec = activeCodec === k ? 'all' : k;
    onFilter();
  }

  function resetCodec() {
    activeCodec = 'all';
    onFilter();
  }

  function renderAudioCodecFilter() {
    const sec = document.getElementById('audioCodecSection');
    if (!sec) return;
    let base = baseItems('audioCodec');
    const counts = {};
    const displayMap = {};  // normalized → display label
    base.forEach(i => {
      const ac = i.audio_codec || 'UNKNOWN';
      counts[ac] = (counts[ac]||0)+1;
      if (!displayMap[ac]) displayMap[ac] = i.audio_codec_display ?? getAudioCodecDisplay(i.audio_codec);
    });
    const codecs = Object.entries(counts).sort((a,b)=>b[1]-a[1]).map(([k])=>k);
    if (!codecs.length) { sec.style.display='none'; return; }
    const resetCls = 'provider-pill provider-pill-reset'+(activeAudioCodec==='all'?' active':'');
    let pills = '<div class="'+resetCls+'" onclick="resetAudioCodec()">'+t('filters.all')+'</div>';
    codecs.forEach(c => {
      const label = c === 'UNKNOWN' ? t('filters.unknown') : escH(displayMap[c] || c);
      const cls = 'provider-pill'+(activeAudioCodec===c?' active':'');
      pills += '<div class="'+cls+'" onclick="clickAudioCodec(\''+escH(c)+'\')">'
        +'<span class="badge badge-codec" style="margin-left:0">'+label+'</span>'
        +'<span style="margin-left:4px;font-size:11px">'+counts[c]+'</span></div>';
    });
    sec.style.display = 'block';
    sec.innerHTML = '<div class="storage-block"><div class="storage-title">'+t('filters.audio_codec')+'</div><div class="provider-filter">'+pills+'</div></div>';
  }

  function clickAudioCodec(v) {
    activeAudioCodec = activeAudioCodec === v ? 'all' : v;
    onFilter();
  }

  function resetAudioCodec() {
    activeAudioCodec = 'all';
    onFilter();
  }

  function renderResolutionFilter() {
    const sec = document.getElementById('resolutionSection');
    if (!sec) return;
    let base = baseItems('resolution');
    const ORDER = ['4K','1080p','720p','SD'];
    const counts = {};
    base.forEach(i => { if (i.resolution) counts[i.resolution] = (counts[i.resolution]||0)+1; });
    const resolutions = ORDER.filter(r => counts[r]);
    if (!resolutions.length) { sec.style.display='none'; return; }
    const resetCls = 'provider-pill provider-pill-reset'+(activeResolution==='all'?' active':'');
    let pills = '<div class="'+resetCls+'" onclick="resetResolution()">'+t('filters.all')+'</div>';
    resolutions.forEach(r => {
      const cls = 'provider-pill'+(activeResolution===r?' active':'');
      pills += '<div class="'+cls+'" onclick="clickResolution(this)" data-res="'+r+'">'        +'<span class="res-badge res-'+r+'">'+r+'</span>'        +'<span style="margin-left:4px;font-size:11px">'+counts[r]+'</span>'        +'</div>';
    });
    sec.style.display='block';
    sec.innerHTML='<div class="storage-block"><div class="storage-title">'+t('filters.resolution')+'</div><div class="provider-filter">'+pills+'</div></div>';
    // mirror to top bar

  }

  function clickResolution(el) {
    const k = el.dataset.res;
    activeResolution = activeResolution === k ? 'all' : k;
    onFilter();
  }

  function resetResolution() {
    activeResolution = 'all';
    onFilter();
  }

  function onFilter() {
    renderStorageBar();
    renderProviderFilter();
    renderResolutionFilter();
    renderCodecFilter();
    renderAudioCodecFilter();
    renderStats(filterItems());
    if (currentTab==='library') render();
    else if (currentTab==='stats') renderStatsPanel();
    saveState();
    syncMobileFilters();
  }

  // ── FILTER ITEMS ─────────────────────────────────────
  function getSearchQuery() {
    return document.getElementById('searchInput')?.value.toLowerCase().trim() || '';
  }

  function applySearch(items, q) {
    if (!q) return items;
    return items.filter(i=>
      (i.title||'').toLowerCase().includes(q)||
      (i.raw||'').toLowerCase().includes(q)||
      (i.year||'').includes(q)||
      (i.category||'').toLowerCase().includes(q)||
      (i.group||'').toLowerCase().includes(q));
  }

  function filterItems() {
    // Visibility order:
    // 1. Settings — type enabled (enableMovies/enableSeries)
    // 2. Settings — category visible (visibleCategories)
    // 3. Sidebar filters — type, group, cat, provider, resolution, codec, search
    // Note: visibleProviders affects logos/filter display only, NOT item visibility
    const q = getSearchQuery();
    let items=allItems;
    if (!enableMovies)       items=items.filter(i=>i.type!=='movie');
    if (!enableSeries)       items=items.filter(i=>i.type!=='tv');
    if (visibleCategories)   items=items.filter(i=>_catVisible(i.category));
    if (activeType!=='all')  items=items.filter(i=>i.type===activeType);
    if (activeGroup!=='all') items=items.filter(i=>i.group===activeGroup);
    if (activeCat!=='all')   items=items.filter(i=>i.category===activeCat);
    if (enableJellyseerr) {
      if (activeProvider==='__none__') items=items.filter(i=>!(i.providers&&i.providers.length));
      else if (activeProvider!=='all') items=items.filter(i=>(i.providers||[]).some(p=>_pname(p)===activeProvider&&_provVisible(_pname(p))));
    }
    if (activeResolution!=='all') items=items.filter(i=>i.resolution===activeResolution);
    if (activeCodec!=='all')     items=items.filter(i=>i.codec===activeCodec);
    if (activeAudioCodec!=='all') items=items.filter(i=>(i.audio_codec||'UNKNOWN')===activeAudioCodec);
    return applySearch(items, q);
  }

  // Base for filter rendering: all active filters applied EXCEPT the one being rendered
  // + settings-level visibility always applied + search always applied
  function baseItems(except) {
    const q = getSearchQuery();
    let items=allItems;
    if (!enableMovies)     items=items.filter(i=>i.type!=='movie');
    if (!enableSeries)     items=items.filter(i=>i.type!=='tv');
    if (visibleCategories)   items=items.filter(i=>_catVisible(i.category));
    if (activeType!=='all')  items=items.filter(i=>i.type===activeType);
    if (except!=='group'  && activeGroup!=='all') items=items.filter(i=>i.group===activeGroup);
    if (except!=='cat'    && activeCat!=='all')   items=items.filter(i=>i.category===activeCat);
    if (except!=='provider') {
      if (activeProvider==='__none__') items=items.filter(i=>!(i.providers&&i.providers.length));
      else if (activeProvider!=='all') items=items.filter(i=>(i.providers||[]).some(p=>_pname(p)===activeProvider&&_provVisible(_pname(p))));
    }
    if (except!=='resolution' && activeResolution!=='all') items=items.filter(i=>i.resolution===activeResolution);
    if (except!=='codec'      && activeCodec!=='all')      items=items.filter(i=>i.codec===activeCodec);
    if (except!=='audioCodec' && activeAudioCodec!=='all') items=items.filter(i=>(i.audio_codec||'UNKNOWN')===activeAudioCodec);
    return applySearch(items, q);
  }

  // ── TABS ─────────────────────────────────────────────
  function switchTab(tab) {
    currentTab=tab;
    // Show/hide tab-bar controls depending on active tab
    const lc = document.getElementById('libraryControls');
    if (lc) lc.style.display = tab==='library' ? '' : 'none';
    // Show/hide sort section in sidebar
    const ss = document.getElementById('sortSection');
    if (ss) ss.style.display = (tab==='library' && currentView==='grid') ? '' : 'none';
    // Panels
    document.getElementById('libraryPanel').classList.toggle('active',tab==='library');
    document.getElementById('statsPanel').classList.toggle('active',tab==='stats');
    // Nav buttons
    ['navLibrary','navStats'].forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      const t = id.replace('navLibrary','library').replace('navStats','stats');
      el.classList.toggle('active', t === tab);
    });
    if (tab==='library') render();
    else if (tab==='stats') renderStatsPanel();
    saveState();
  }

  // ── RENDER LIBRARY ───────────────────────────────────
  function render() {
    let items=filterItems();
    renderStats(items);
    const c=document.getElementById('library');
    if (!items.length) { c.className=''; c.innerHTML='<div class="empty"><p>'+t('library.no_results')+'</p></div>'; return; }
    if (currentView==='grid') { c.className=''; c.innerHTML=sortItems(items).map(cardHTML).join(''); }
    else { c.className='table-view'; c.innerHTML=tableHTML(sortItemsTable(items)); }
  }

  function sortItems(items) {
    const v=document.getElementById('sortSelect').value;
    return [...items].sort((a,b)=>{
      switch(v){
        case 'title-asc':    return (a.title||'').localeCompare(b.title||'');
        case 'title-desc':   return (b.title||'').localeCompare(a.title||'');
        case 'year-desc':    return (b.year||'0')-(a.year||'0');
        case 'year-asc':     return (a.year||'9999')-(b.year||'9999');
        case 'size-desc':    return (b.size_b||0)-(a.size_b||0);
        case 'size-asc':     return (a.size_b||0)-(b.size_b||0);
        case 'added-desc':   return (b.added_ts||0)-(a.added_ts||0);
        case 'category-asc': return (a.category||'').localeCompare(b.category||'');
      }
    });
  }

  function sortByCol(col){ tSortDir=tSortCol===col?tSortDir*-1:1; tSortCol=col; render(); }

  function sortItemsTable(items) {
    if (!tSortCol) return items;
    return [...items].sort((a,b)=>{
      switch(tSortCol){
        case 'title':    return (a.title||'').localeCompare(b.title||'')*tSortDir;
        case 'year':     return ((a.year||'0')-(b.year||'0'))*tSortDir;
        case 'size':     return ((a.size_b||0)-(b.size_b||0))*tSortDir;
        case 'files':    return ((a.file_count||0)-(b.file_count||0))*tSortDir;
        case 'added':    return ((a.added_ts||0)-(b.added_ts||0))*tSortDir;
        case 'category': return (a.category||'').localeCompare(b.category||'')*tSortDir;
        case 'group':    return (a.group||'').localeCompare(b.group||'')*tSortDir;
      }
      return 0;
    });
  }

  function posterBlock(item) {
    if (item.poster) return '<div class="tl-poster"><img src="'+escH(item.poster)+'" alt="" loading="lazy"/></div>';
    return '<div class="tl-poster"><div class="tl-poster-ph">🎬</div></div>';
  }
  function providersBlock(item) {
    if (!enableJellyseerr) return '';
    const visP = _itemVisProviders(item);
    const hasProv = item.providers && item.providers.length > 0;
    if (!visP.length) {
      if (!hasProv) {
        if (item.providers_fetched !== true) return '';
        return '<div class="tl-providers"><div class="tl-provider tl-provider-none" title="'+t('library.no_provider')+'">🚫</div></div>';
      }
      return ''; // has providers but all hidden by visibility prefs
    }
    return '<div class="tl-providers">'
      + visP.map(p => {
          const name=_pname(p), logo=_plogo(p);
          return logo
            ? '<div class="tl-provider" title="'+escH(name)+'"><img src="'+escH(logo)+'" alt="'+escH(name)+'"/></div>'
            : '<span class="tl-provider-name">'+escH(name)+'</span>';
        }).join('')
      + '</div>';
  }
  function cardHTML(item) {
    const plotText = (item.plot||'').trim();
    return '<div class="tl-card"'+(plotText?' onmouseenter="showPlot(this,\''+sanitizeStr(plotText)+'\')" onmouseleave="hidePlot()"':'')+'>'  
      + posterBlock(item)
      +'<div class="tl-body">'
        +'<div class="tl-title" title="'+escH(item.title)+'">'+escH(item.title)+'</div>'
        +'<div class="tl-meta">'
          +(item.year?'<span class="tl-cat">'+item.year+'</span>':'')
          +(item.group?'<span class="tl-cat" style="color:#a78bfa">'+escH(item.group)+'</span>':'')
          +'<span class="tl-cat">'+escH(item.category)+'</span>'
          +'<span class="tl-size">'+escH(item.size)+'</span>'
          +(item.resolution?'<span class="res-badge res-'+item.resolution+'">'+item.resolution+'</span>':'')
          +(item.type==='tv'&&item.season_count?'<span class="tl-cat">'+item.season_count+'S</span>':'')+(item.type==='tv'&&item.episode_count?'<span class="tl-cat">'+item.episode_count+'ep</span>':'')+(item.type!=='tv'&&item.file_count!==undefined&&item.file_count!==1?'<span class="tl-cat">'+(item.file_count>1?t('library.files_pl',{n:item.file_count}):t('library.files',{n:item.file_count}))+'</span>':'')
        +'</div>'
        + providersBlock(item)
      +'</div>'
    +'</div>';
  }

  function th(col,label){ const s=tSortCol===col,i=s?(tSortDir===1?' &uarr;':' &darr;'):' &updownarrow;'; return '<th class="'+(s?'sorted':'')+'" onclick="sortByCol(\''+col+'\')">'+label+'<span class="si">'+i+'</span></th>'; }

  function tblProvidersHTML(item) {
    if (!enableJellyseerr) return '-';
    const hasProv = item.providers && item.providers.length > 0;
    if (!hasProv) {
      if (item.providers_fetched !== true) return '-';
      return '<span title="'+t('library.no_provider')+'" style="font-size:14px">🚫</span>';
    }
    return '<div class="tbl-providers">'
      +_itemVisProviders(item).map(p=>{
        const name=_pname(p), logo=_plogo(p);
        return logo
          ?'<div class="tbl-provider" title="'+escH(name)+'"><img src="'+escH(logo)+'" alt="'+escH(name)+'"/></div>'
          :'<span class="tbl-provider-name">'+escH(name)+'</span>';
      }).join('')+'</div>';
  }
  function tableHTML(items) {
    const hg=items.some(i=>i.group);
    const hp=items.some(i=>i.poster||(i.providers&&i.providers.length));
    const rows=items.map(item=>{
      // Mobile info cell: title + meta badges
      const mobileInfo = '<td class="col-mobile-info">'
        +'<div style="font-weight:600;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%">'+escH(item.title)+'</div>'
        +'<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;align-items:center;max-width:100%;overflow:hidden">'
          +(item.year?'<span class="tl-cat">'+item.year+'</span>':'')
          +'<span class="cat-badge">'+escH(item.category)+'</span>'
          +(item.resolution?'<span class="res-badge res-'+item.resolution+'">'+item.resolution+'</span>':'')
          +(item.hdr?'<span class="badge badge-hdr">HDR</span>':'')
          +(item.codec?'<span class="badge badge-codec">'+escH(item.codec)+'</span>':'')
        +'</div>'
        +'<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;align-items:center;max-width:100%;overflow:hidden">'
          +'<span style="font-size:11px;color:var(--muted)">'+escH(item.size)+'</span>'
          +(item.type==='tv'&&item.season_count?'<span style="font-size:11px;color:var(--muted)">'+item.season_count+'S / '+item.episode_count+'Ep</span>':'')
          +(item.added_at?'<span style="font-size:11px;color:var(--muted)">'+fmtDate(item.added_at)+'</span>':'')
        +'</div>'
        +(()=>{ const p=tblProvidersHTML(item); return p?'<div style="margin-top:4px">'+p+'</div>':''; })()
        +'</td>';
      return '<tr>'
        +(hp?'<td class="col-poster">'+(item.poster?'<img src="'+escH(item.poster)+'" alt="" loading="lazy"/>':'<div class="ph">🎬</div>')+'</td>':'')
        +mobileInfo
        +'<td class="col-title">'+escH(item.title)+'</td>'
        +'<td class="col-year">'+(item.year||'-')+'</td>'
        +(hg?'<td class="col-group">'+escH(item.group||'-')+'</td>':'')
        +'<td><span class="cat-badge">'+escH(item.category)+'</span></td>'
        +'<td>'+(item.resolution?'<span class="res-badge res-'+item.resolution+'">'+item.resolution+'</span>':'-')+(item.hdr?' <span class="badge badge-hdr">HDR</span>':'')+'</td>'
        +'<td>'+(item.codec?'<span class="badge badge-codec">'+escH(item.codec)+'</span>':'-')+'</td>'
        +'<td class="col-size">'+escH(item.size)+'</td>'
        +'<td class="col-files">'+(item.type==='tv'?(item.season_count||'-')+' S / '+(item.episode_count||'-')+' Ep':item.file_count!==undefined?(item.file_count>1?t('library.files_pl',{n:item.file_count}):t('library.files',{n:item.file_count})):'-')+'</td>'
        +'<td class="col-date">'+(item.added_at?fmtDate(item.added_at):'-')+'</td>'
        +(hp?'<td class="col-providers">'+tblProvidersHTML(item)+'</td>':'')
        +'</tr>';
    }).join('');
    return '<table class="media-table"><thead><tr>'
      +(hp?'<th style="width:44px"></th>':'')
      +th('title',t('table.title'))+th('year',t('table.year'))
      +(hg?th('group',t('table.group')):'')
      +th('category',t('table.category'))
      +'<th>'+t('table.resolution')+'</th><th>'+t('table.codec')+'</th>'
      +th('size',t('table.size'))+th('files',t('table.files'))+th('added',t('table.added'))
      +(hp?'<th>'+t('table.streaming')+'</th>':'')
      +'</tr></thead><tbody>'+rows+'</tbody></table>';
  }

  // ── EXPORT CSV ───────────────────────────────────────
  function exportCSV() {
    const items=filterItems();
    const hg=items.some(i=>i.group);
    const headers=['Titre','Annee',hg?'Groupe':null,'Categorie','Resolution','HDR','Codec','Runtime (min)','Taille','Taille (octets)','Fichiers','Ajoute le','Streaming'].filter(Boolean);
    const rows=items.map(i=>[
      csvC(i.title),csvC(i.year||''),
      hg?csvC(i.group||''):null,
      csvC(i.category),
      csvC(i.resolution||''),
      i.hdr?'Oui':'Non',
      csvC(i.codec||''),
      i.runtime_min||'',
      csvC(i.size),i.size_b||0,
      i.type==='tv'?((i.season_count||'')+' S / '+(i.episode_count||'')+' Ep'):(i.file_count!==undefined?i.file_count:''),
      i.added_at?fmtDate(i.added_at):'',
      csvC((i.providers||[]).join(', '))
    ].filter(v=>v!==null));
    const csv=[headers.join(';'),...rows.map(r=>r.join(';'))].join('\n');
    const blob=new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8;'});
    const url=URL.createObjectURL(blob);
    const a=document.createElement('a');
    const now=new Date();
    a.href=url; a.download='mymedialibrary-'+now.toISOString().slice(0,10)+'_'+now.toTimeString().slice(0,8).replace(/:/g,'-')+'.csv';
    a.click(); URL.revokeObjectURL(url);
  }
  function csvC(v){ const s=String(v||''); return s.includes(';')||s.includes('"')||s.includes('\n')?'"'+s.replace(/"/g,'""')+'"':s; }

  // ── VIEW ─────────────────────────────────────────────
  function setView(v, silent) {
    currentView=v;
    document.getElementById('gridBtn').classList.toggle('active',v==='grid');
    document.getElementById('tableBtn').classList.toggle('active',v==='table');
    // Sort visible only in grid view
    const sortEl = document.getElementById('sortSelect');
    const sortSec = document.getElementById('sortSection');
    if (sortEl) sortEl.style.display = v==='grid' ? '' : 'none';
    if (sortSec) sortSec.style.display = v==='grid' ? '' : 'none';
    render();
  }

  // ── UTILS ────────────────────────────────────────────
  function fmtDate(iso){ if(!iso)return'-'; return new Date(iso).toLocaleDateString('fr-FR'); }
  function fmtSize(b){ if(!b)return'0 B'; const u=['B','KB','MB','GB','TB']; let i=0; while(b>=1024&&i<u.length-1){b/=1024;i++;} return b.toFixed(1)+' '+u[i]; }
  function escH(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/\r?\n/g,' '); }
  function escJ(s){ return String(s||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/\r/g,'').replace(/\n/g,' ').replace(/\u2028/g,' ').replace(/\u2029/g,' '); }
  // sanitizeStr: safe for JS string literals inside HTML attributes (onclick, onmouseenter…)
  const sanitizeStr = s => (s||'').replace(/\r?\n/g,' ').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'&quot;').replace(/\u2028/g,' ').replace(/\u2029/g,' ');

  document.getElementById('searchInput').addEventListener('input',()=>{ onFilter(); });
  document.getElementById('sortSelect').addEventListener('change',render);



  // ── STATS PANEL ──────────────────────────────────────
  function renderStatsPanel() {
    const items = filterItems();
    document.getElementById('statsContent').innerHTML = buildStats(items);
  }

  function buildStats(items) {
    items = items || allItems;
    const isFiltered = items.length < allItems.length;
    if (!items.length) return '<p style="color:var(--muted);padding:40px">'+t('library.no_results')+'</p>';

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
          slices += '<path d="M'+CX+','+CY+' L'+x1.toFixed(2)+','+y1.toFixed(2)+' A'+R+','+R+' 0 '+large+',1 '+x2.toFixed(2)+','+y2.toFixed(2)+' Z" fill="'+col+'"><title>'+escH(labelFn(k))+' — '+fmtFn(val)+' ('+Math.round(frac*100)+'%)</title></path>';
        }
        angle = a2;
      });
      // donut hole
      slices += '<circle cx="'+CX+'" cy="'+CY+'" r="'+(R*0.52)+'" fill="var(--surface)"/>';
      // center label
      slices += '<text x="'+CX+'" y="'+(CY-7)+'" text-anchor="middle" font-size="11" font-weight="700" fill="var(--text)">'+entries.length+'</text>';
      slices += '<text x="'+CX+'" y="'+(CY+8)+'" text-anchor="middle" font-size="9" fill="var(--muted)">'+(entries.length>1?t('stats.entries'):t('stats.entry'))+'</text>';

      const svg = '<svg viewBox="0 0 '+SIZE+' '+SIZE+'" width="'+SIZE+'" height="'+SIZE+'" style="flex-shrink:0">'+slices+'</svg>';
      const legend = '<div class="pie-legend">'+entries.slice(0,12).map(([k,v],idx)=>{
        const val=valFn(v), pct=Math.round(val/total*100);
        return '<div class="pie-leg-row">'
          +'<div class="pie-leg-dot" style="background:'+colorFn(k,idx)+'"></div>'
          +'<div class="pie-leg-label" title="'+escH(labelFn(k))+'">'+escH(labelFn(k))+'</div>'
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
      if (!i.codec) return;
      byCodec[i.codec]=(byCodec[i.codec]||0)+(i.size_b||0);
      byCodecCount[i.codec]=(byCodecCount[i.codec]||0)+1;
    });
    const codecColorFn=(k,idx)=>CODEC_COLORS[idx%CODEC_COLORS.length];
    const codecEntriesSize  = Object.entries(byCodec).sort((a,b)=>b[1]-a[1]);
    const codecEntriesCount = Object.entries(byCodecCount).sort((a,b)=>b[1]-a[1]);

    // ── Audio Codec ──────────────────────────────────────
    const AUDIO_CODEC_COLORS = ['#06b6d4','#f97316','#a3e635','#e879f9','#fb7185','#34d399','#fbbf24'];
    const byAudioCodec={}, byAudioCodecCount={};
    items.forEach(i=>{
      const ac = i.audio_codec || 'UNKNOWN';
      if (ac === 'UNKNOWN') return;  // skip unknowns in pie chart
      const label = i.audio_codec_display ?? getAudioCodecDisplay(i.audio_codec);
      byAudioCodec[label]=(byAudioCodec[label]||0)+(i.size_b||0);
      byAudioCodecCount[label]=(byAudioCodecCount[label]||0)+1;
    });
    const audioCodecColorFn=(k,idx)=>AUDIO_CODEC_COLORS[idx%AUDIO_CODEC_COLORS.length];
    const audioCodecEntriesSize  = Object.entries(byAudioCodec).sort((a,b)=>b[1]-a[1]);
    const audioCodecEntriesCount = Object.entries(byAudioCodecCount).sort((a,b)=>b[1]-a[1]);

    // ── Resolution ───────────────────────────────────────
    const RES_ORDER = ['4K','1080p','720p','SD'];
    const RES_COLORS = {'4K':'#a855f7','1080p':'#22c55e','720p':'#3b82f6','SD':'#78716c'};
    const byRes={}, byResCount={};
    items.forEach(i=>{
      const r=i.resolution||'Inconnu';
      byRes[r]=(byRes[r]||0)+(i.size_b||0);
      byResCount[r]=(byResCount[r]||0)+1;
    });
    const resColorFn=(k)=>RES_COLORS[k]||'#888';
    const resEntriesSize = RES_ORDER.filter(r=>byRes[r]).map(r=>[r,byRes[r]]);
    const resEntriesCount = RES_ORDER.filter(r=>byResCount[r]).map(r=>[r,byResCount[r]]);


    // ── Providers ─────────────────────────────────────────
    const byProv={};
    items.forEach(i=>(i.providers||[]).forEach(p=>{
      const name=_pname(p); if(!name||!_provVisible(name))return;
      if(!byProv[name]) byProv[name]={count:0, logo:_plogo(p)};
      byProv[name].count++;
      if(!byProv[name].logo) byProv[name].logo=_plogo(p);
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
      (i.providers||[]).forEach(p=>{ const n=_pname(p); if(n&&_provVisible(n)) provByGroup[g][n]=(provByGroup[g][n]||0)+1; });
    });
    const provByCat={};
    items.forEach(i=>{
      if(!provByCat[i.category]) provByCat[i.category]={};
      (i.providers||[]).forEach(p=>{ const n=_pname(p); if(n&&_provVisible(n)) provByCat[i.category][n]=(provByCat[i.category][n]||0)+1; });
    });

    function crossTable(rowEntries, rowColorFn, transpose) {
      if(!provNames.length) return '<p style="font-size:12px;color:var(--muted)">'+t('stats.no_provider_data')+'</p>';
      if (transpose) {
        // providers as rows, groups/cats as columns
        const colKeys = rowEntries.map(([k])=>k);
        const colColorFn = rowColorFn;
        const headers = colKeys.map(k=>'<th style="color:'+colColorFn(k)+'">'+escH(k)+'</th>').join('');
        const rows = provNames.map((p,idx)=>{
          const logo=(PROVIDERS_META[p]?.logo_url||providerCatalog[p])?'<img class="cross-logo" src="'+escH(PROVIDERS_META[p]?.logo_url||providerCatalog[p]||'')+'" alt=""/>':'';
          const cells=rowEntries.map(([k,pmap])=>{
            const n=pmap[p]||0;
            return '<td style="color:'+(n?'var(--text)':'var(--border)')+';">'+(n||'–')+'</td>';
          }).join('');
          return '<tr><td style="font-weight:600">'+logo+escH(p)+'</td>'+cells+'</tr>';
        }).join('');
        return '<div class="cross-wrap"><table class="cross-table"><thead><tr><th></th>'+headers+'</tr></thead><tbody>'+rows+'</tbody></table></div>';
      }
      const headers = provNames.map(p=>{
        const logo=(PROVIDERS_META[p]?.logo_url||providerCatalog[p])?'<img class="cross-logo" src="'+escH(PROVIDERS_META[p]?.logo_url||providerCatalog[p]||'')+'" alt=""/>':'';
        return '<th>'+logo+escH(p)+'</th>';
      }).join('');
      const rows = rowEntries.map(([k,pmap])=>{
        const cells=provNames.map(p=>{
          const n=pmap[p]||0;
          return '<td style="color:'+(n?'var(--text)':'var(--border)')+';">'+(n||'–')+'</td>';
        }).join('');
        return '<tr><td style="font-weight:600;color:'+rowColorFn(k)+'">'+escH(k)+'</td>'+cells+'</tr>';
      }).join('');
      return '<div class="cross-wrap"><table class="cross-table"><thead><tr><th></th>'+headers+'</tr></thead><tbody>'+rows+'</tbody></table></div>';
    }

    // ── Monthly curve ─────────────────────────────────────
    // Build daily index
    const allByDay={};
    items.forEach(i=>{
      if(!i.added_at)return;
      const d=new Date(i.added_at);
      const key=d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
      if(!allByDay[key]) allByDay[key]={count:0,size:0};
      allByDay[key].count++; allByDay[key].size+=i.size_b||0;
    });
    // Build monthly index
    const allByMonth={};
    Object.entries(allByDay).forEach(([k,v])=>{
      const mk=k.slice(0,7);
      if(!allByMonth[mk]) allByMonth[mk]={count:0,size:0};
      allByMonth[mk].count+=v.count; allByMonth[mk].size+=v.size;
    });

    function makeCurve(keys, vals, color, gradId, labelFn, titleFn) {
      const maxV=Math.max(...vals,0);
      if(!maxV||keys.length<2) return '<p style="font-size:12px;color:var(--muted)">'+t('stats.not_enough_data')+'</p>';
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
        if(period==='6m'){
          const cutoff=new Date(now); cutoff.setMonth(cutoff.getMonth()-6);
          const ck=cutoff.getFullYear()+'-'+String(cutoff.getMonth()+1).padStart(2,'0');
          mkeys=mkeys.filter(k=>k>=ck);
        } else if(period==='12m'){
          const cutoff=new Date(now); cutoff.setMonth(cutoff.getMonth()-12);
          const ck=cutoff.getFullYear()+'-'+String(cutoff.getMonth()+1).padStart(2,'0');
          mkeys=mkeys.filter(k=>k>=ck);
        } else if(period==='year'){
          const yr=String(now.getFullYear());
          mkeys=mkeys.filter(k=>k.startsWith(yr));
        }
        keys=mkeys;
      }
      const idx=useDaily?allByDay:allByMonth;
      if(keys.length<2) return '<p style="font-size:12px;color:var(--muted)">'+t('stats.not_enough_period')+'</p>';
      return '<div class="curve-label">'+t('stats.items_added')+'</div>'
        +makeCurve(keys,keys.map(k=>(idx[k]||{count:0}).count),'var(--accent)','cg1',v=>Math.round(v),v=>v+' ajout'+(v>1?'s':''))
        +'<div class="curve-label" style="margin-top:20px">'+t('stats.size_added')+'</div>'
        +makeCurve(keys,keys.map(k=>(idx[k]||{size:0}).size),'#4ecdc4','cg2',v=>fmtSize(Math.round(v)),v=>fmtSize(v));
    }

    // Expose for period switch
    _buildCurveForPeriodGlobal = buildCurveForPeriod;

    // Curve controls HTML
    const hasDates=Object.keys(allByMonth).length>0;
    const curveHtml=hasDates ? (
      '<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:14px" id="curveControls">'
        +'<div class="pie-switch">'
          +'<button class="pie-switch-btn"        data-period="all"  onclick="setCurvePeriod(this)">'+t('stats.all')+'</button>'
          +'<button class="pie-switch-btn active" data-period="12m"  onclick="setCurvePeriod(this)">'+t('stats.months_12')+'</button>'
          +'<button class="pie-switch-btn"        data-period="30d"  onclick="setCurvePeriod(this)">'+t('stats.days_30')+'</button>'
        +'</div>'
      +'</div>'
      +'<div id="curveCharts">'+buildCurveForPeriod('12m')+'</div>'
    ) : '<p style="font-size:12px;color:var(--muted)">'+t('stats.not_enough_dated')+'</p>';

    // ── Build HTML ─────────────────────────────────────────
    const hasGroups=groups.length>0;
    const hasProviders=provEntries.length>0;

    // Color helpers
    const groupColorFn=(k,i)=>groupColorMap[k]||PALETTE[i%PALETTE.length];
    const catColorFn=(k,i)=>catColorMap[k]||PALETTE[i%PALETTE.length];

    function switchablePie(id, title, sizeEntries, countEntries, colorFn) {
      const pieSize  = makePie(sizeEntries,  colorFn, v=>v, k=>k, fmtSize);
      const pieCount = makePie(countEntries, colorFn, v=>v, k=>k, v=>String(v));
      return '<div class="stats-block">'
        +'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border)">'
          +'<div class="stats-block-title" style="margin-bottom:0;padding-bottom:0;border-bottom:none">'+title+'</div>'
          +'<div class="pie-switch">'
            +'<button class="pie-switch-btn active" id="'+id+'BtnSize"  data-pie="'+id+'" data-unit="size"  onclick="statSwitchPie(this)">'+t('stats.by_size')+'</button>'
            +'<button class="pie-switch-btn"        id="'+id+'BtnCount" data-pie="'+id+'" data-unit="count" onclick="statSwitchPie(this)">'+t('stats.by_count')+'</button>'
          +'</div>'
        +'</div>'
        +'<div id="'+id+'PieSize">'+pieSize+'</div>'
        +'<div id="'+id+'PieCount" style="display:none">'+pieCount+'</div>'
        +'</div>';
    }



    // Group pies
    const groupPieSize = hasGroups ? makePie(groupEntriesSize, groupColorFn, v=>v, k=>k, fmtSize) : '';
    const groupPieCount = hasGroups ? makePie(groupEntriesCount, groupColorFn, v=>v, k=>k, v=>String(v)) : '';

    // Cat pies
    const catPieSize = makePie(catEntriesSize, catColorFn, v=>v, k=>k, fmtSize);
    const catPieCount = makePie(catEntriesCount, catColorFn, v=>v, k=>k, v=>String(v));

    // Provider pie (including "Aucun") — switchable taille/nombre
    const provColorFn=(k,i)=>provColors[i%provColors.length];
    const noneCount = items.filter(i=>!(i.providers&&i.providers.length)).length;
    const noneSize  = items.filter(i=>!(i.providers&&i.providers.length)).reduce((s,i)=>s+(i.size_b||0),0);
    const provCountEntries=[
      ...provEntries.map(([k,v])=>[k,v.count]),
      ...(noneCount>0 ? [['Aucun',noneCount]] : []),
    ];
    const byProvSize={};
    items.forEach(i=>(i.providers||[]).forEach(p=>{ if(p) byProvSize[p]=(byProvSize[p]||0)+(i.size_b||0); }));
    const provSizeEntries=[
      ...provEntries.map(([k])=>[k,byProvSize[k]||0]),
      ...(noneSize>0 ? [['Aucun',noneSize]] : []),
    ];
    const provColorFnWithNone=(k,i)=> k==='Aucun' ? '#555577' : provColors[i%provColors.length];
    const provPieHtml=provCountEntries.length
      ? switchablePie('prov',t('stats.providers'), provSizeEntries, provCountEntries, provColorFnWithNone)
      : '<p style="font-size:12px;color:var(--muted)">'+t('stats.no_provider_data')+'</p>';

    // Cross tables
    const crossGroupRows = Object.entries(provByGroup).sort((a,b)=>Object.values(b[1]).reduce((s,v)=>s+v,0)-Object.values(a[1]).reduce((s,v)=>s+v,0));
    const crossCatRows = Object.entries(provByCat).sort((a,b)=>Object.values(b[1]).reduce((s,v)=>s+v,0)-Object.values(a[1]).reduce((s,v)=>s+v,0));

      // ── GLOBAL ENCART (always uses allItems, ignores filters) ──────────
      const globalMovies  = allItems.filter(i=>i.type==='movie').length;
      const globalSeries  = allItems.filter(i=>i.type==='tv').length;
      const globalBytes   = allItems.reduce((s,i)=>s+(i.size_b||0),0);

      // Per-category counts from allItems
      const globalByCat = {};
      allItems.forEach(i=>{ globalByCat[i.category]=(globalByCat[i.category]||0)+1; });
      const catBarEntries = Object.entries(globalByCat).sort((a,b)=>b[1]-a[1]);
      const catBarMax = catBarEntries[0]?.[1]||1;

      function makeHBar(label, count, total, color) {
        const pct = Math.round(count/total*100);
        const w   = Math.round(count/total*100);
        return '<div style="margin-bottom:8px">'          +'<div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px">'            +'<span style="color:var(--text);font-weight:500">'+escH(label)+'</span>'            +'<span style="color:var(--muted)">'+count+' <span style="font-size:10px">('+pct+'%)</span></span>'          +'</div>'          +'<div style="height:6px;background:var(--bg);border-radius:3px;overflow:hidden">'            +'<div style="height:100%;width:'+w+'%;background:'+color+';border-radius:3px;transition:width .4s"></div>'          +'</div>'          +'</div>';
      }

      const catBars = catBarEntries.map(([cat,cnt],idx)=>
        makeHBar(cat, cnt, allItems.length, PALETTE[idx%PALETTE.length])
      ).join('');

      const globalEncart = '<div class="stats-block">'
        + '<div class="stats-block-title">'+t('stats.global_library')+'</div>'
        + '<div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:16px">'
          + '<div class="stat-row"><div class="stat-row-label">'+t('stats.movies')+'</div><div class="stat-row-val">'+globalMovies+'</div></div>'
          + '<div class="stat-row"><div class="stat-row-label">'+t('stats.series')+'</div><div class="stat-row-val">'+globalSeries+'</div></div>'
          + '<div class="stat-row"><div class="stat-row-label">'+t('stats.total')+'</div><div class="stat-row-val">'+allItems.length+'</div></div>'
          + '<div class="stat-row"><div class="stat-row-label">'+t('stats.disk')+'</div><div class="stat-row-val">'+fmtSize(globalBytes)+'</div></div>'
        + '</div>'
        + catBars
        + '</div>';

      // Year / decade stats from allItems
      // Year / decade stats from filtered items
      const byYear={}, byDecade={};
      items.forEach(i=>{
        const y=parseInt(i.year);
        if(!y||y<1880||y>2100) return;
        byYear[y]=(byYear[y]||0)+1;
        const d=Math.floor(y/10)*10;
        byDecade[d]=(byDecade[d]||0)+1;
      });

      function makeBarChart(data, labelFn, color) {
        const entries=Object.entries(data).sort((a,b)=>a[0]-b[0]);
        if(!entries.length) return '<p style="font-size:12px;color:var(--muted)">'+t('stats.not_enough_data')+'</p>';
        const maxV=Math.max(...entries.map(([,v])=>v));
        const W=800,H=120,PB=24,PT=8,PL=36,PR=8;
        const iW=W-PL-PR, iH=H-PT-PB, n=entries.length;
        const bw=Math.max(2,Math.floor(iW/n)-2);
        const bars=entries.map(([k,v],idx)=>{
          const bh=Math.round(v/maxV*iH);
          const x=PL+idx*(iW/n)+(iW/n-bw)/2;
          const y=PT+iH-bh;
          const showLbl=n<=30||idx%Math.ceil(n/20)===0||idx===n-1;
          return '<rect x="'+x.toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+bw+'" height="'+bh+'" fill="'+color+'" rx="2" opacity=".85"><title>'+labelFn(k)+' : '+v+'</title></rect>'            +(showLbl?'<text x="'+(x+bw/2).toFixed(1)+'" y="'+(H-6)+'" text-anchor="middle" font-size="8" fill="var(--muted)">'+labelFn(k)+'</text>':'');
        }).join('');
        // Y axis labels
        let yax='';
        for(let s=0;s<=3;s++){
          const yv=PT+iH-s/3*iH;
          yax+='<text x="'+(PL-3)+'" y="'+(yv+3).toFixed(1)+'" text-anchor="end" font-size="8" fill="var(--muted)">'+Math.round(maxV*s/3)+'</text>';
          yax+='<line x1="'+PL+'" y1="'+yv.toFixed(1)+'" x2="'+(W-PR)+'" y2="'+yv.toFixed(1)+'" stroke="var(--border)" stroke-width="0.5"/>';
        }
        return '<svg class="curve-svg" viewBox="0 0 '+W+' '+H+'" xmlns="http://www.w3.org/2000/svg">'+yax+bars+'</svg>';
      }

      const yearChart   = makeBarChart(byYear,   k=>k,           'var(--accent)');
      const decadeChart = makeBarChart(byDecade, k=>k+'s',       '#4ecdc4');


      const yearDecadeHtml = '<div class="stats-block">'
        + '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border)">'
          + '<div class="stats-block-title" style="margin:0;padding:0;border:none">'+t('stats.release_years')+'</div>'
          + '<div class="pie-switch">'
            + '<button class="pie-switch-btn active" id="yearBtnYear" onclick="switchYearView(this,\'year\')">'+t('stats.years')+'</button>'
            + '<button class="pie-switch-btn" id="yearBtnDecade" onclick="switchYearView(this,\'decade\')">'+t('stats.decades')+'</button>'
          + '</div>'
        + '</div>'
        + '<div id="yearViewYear">'+yearChart+'</div>'
        + '<div id="yearViewDecade" style="display:none">'+decadeChart+'</div>'
        + '</div>';






    return ''
      // 1. Pie charts
      +'<div class="stats-row">'
        +(hasGroups ? switchablePie('grp',t('stats.groups'), groupEntriesSize, groupEntriesCount, groupColorFn) : '')
        +switchablePie('cat',t('stats.categories'), catEntriesSize, catEntriesCount, catColorFn)
        +(resEntriesSize.length ? switchablePie('res',t('stats.resolution'), resEntriesSize, resEntriesCount, resColorFn) : '')
        +(codecEntriesSize.length ? switchablePie('codec',t('stats.codec'), codecEntriesSize, codecEntriesCount, codecColorFn) : '')
        +(audioCodecEntriesSize.length ? switchablePie('audioCodec',t('stats.audio_codec_chart_title'), audioCodecEntriesSize, audioCodecEntriesCount, audioCodecColorFn) : '')
        +provPieHtml
      +'</div>'
      // 2. Années / décennies
      +'<div style="margin-bottom:0">'+yearDecadeHtml+'</div>'
      // 3. Courbes d'évolution
      +'<div class="stats-block"><div class="stats-block-title">'+t('stats.monthly_evolution')+'</div>'+curveHtml+'</div>';
  }

  // ── ACCENT COLOR ─────────────────────────────────────
  const _DEFAULT_ACCENT = '#7c6aff';
  function _hexToRgba(hex, a) {
    const r=parseInt(hex.slice(1,3),16), g=parseInt(hex.slice(3,5),16), b=parseInt(hex.slice(5,7),16);
    return `rgba(${r},${g},${b},${a})`;
  }
  function applyAccent(color) {
    const r = document.documentElement;
    r.style.setProperty('--accent', color);
    r.style.setProperty('--accent-08', _hexToRgba(color, 0.08));
    r.style.setProperty('--accent-20', _hexToRgba(color, 0.20));
    r.style.setProperty('--accent-40', _hexToRgba(color, 0.40));
    const el = document.getElementById('cfgAccentColor');
    if (el && el.value !== color) el.value = color;
  }
  function resetAccent() {
    const el = document.getElementById('cfgAccentColor');
    if (el) el.value = _DEFAULT_ACCENT;
  }

  function toggleTheme() {
    const html = document.documentElement;
    const isLight = html.getAttribute('data-theme') === 'light';
    const newTheme = isLight ? 'dark' : 'light';
    html.setAttribute('data-theme', newTheme);
    const icon = document.getElementById('themeIcon');
    if (icon) {
      if (newTheme === 'dark') {
        icon.innerHTML = '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>';
      } else {
        icon.innerHTML = '<path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>';
      }
    }
    // Persist to config.json and update in-memory appConfig
    appConfig.ui = appConfig.ui || {};
    appConfig.ui.theme = newTheme;
    saveConfig({ ui: { theme: newTheme } }).catch(() => {
      // Revert on failure
      html.setAttribute('data-theme', isLight ? 'light' : 'dark');
      appConfig.ui.theme = isLight ? 'light' : 'dark';
    });
  }

  // ── STATS MODAL ──────────────────────────────────────
  function openStats() {
    document.getElementById('statsModal').classList.add('open');
    renderStatsModal();
  }
  function closeStats() {
    document.getElementById('statsModal').classList.remove('open');
  }
  function closeStatsIfBackdrop(e) {
    if (e.target === document.getElementById('statsModal')) closeStats();
  }
  document.addEventListener('keydown', e => { if(e.key==='Escape') closeStats(); });

  function renderStatsModal() {
    const el = document.getElementById('statsModalContent');
    el.innerHTML = buildStatsHTML();
  }

  function buildStatsHTML() {
    let html = '';

    // ── Section 1: Répartition par groupe ──
    const byGroup = {};
    allItems.forEach(i => {
      const g = i.group || 'Autres';
      if (!byGroup[g]) byGroup[g] = {count:0, size:0};
      byGroup[g].count++; byGroup[g].size += i.size_b||0;
    });
    const groupEntries = Object.entries(byGroup).sort((a,b)=>b[1].size-a[1].size);
    const maxGSize = groupEntries[0]?.[1].size || 1;
    html += '<div class="modal-section"><div class="modal-section-title">'+t('stats.by_group')+'</div>';
    html += '<div class="hbar-list">';
    groupEntries.forEach(([g,d],i) => {
      const col = groupColorMap[g] || PALETTE[i%PALETTE.length];
      const pct = (d.size/maxGSize*100).toFixed(1);
      html += '<div class="hbar-item">'
        +'<div class="hbar-label" title="'+escH(g)+'">'+escH(g)+'</div>'
        +'<div class="hbar-track"><div class="hbar-fill" style="width:'+pct+'%;background:'+col+'"></div></div>'
        +'<div class="hbar-val">'+fmtSize(d.size)+'<br><span style="font-size:10px;color:var(--muted)">'+(d.count>1?t('stats.items_count_pl',{n:d.count}):t('stats.items_count',{n:d.count}))+'</span></div>'
        +'</div>';
    });
    html += '</div></div>';

    // ── Section 2: Répartition par catégorie ──
    const byCat = {};
    allItems.forEach(i => {
      if (!byCat[i.category]) byCat[i.category] = {count:0, size:0, group: i.group||'Autres'};
      byCat[i.category].count++; byCat[i.category].size += i.size_b||0;
    });
    const catEntries = Object.entries(byCat).sort((a,b)=>b[1].size-a[1].size);
    const maxCSize = catEntries[0]?.[1].size || 1;
    html += '<div class="modal-section"><div class="modal-section-title">'+t('stats.by_category')+'</div>';
    html += '<div class="hbar-list">';
    catEntries.forEach(([c,d],i) => {
      const col = catColorMap[c] || PALETTE[i%PALETTE.length];
      const pct = (d.size/maxCSize*100).toFixed(1);
      html += '<div class="hbar-item">'
        +'<div class="hbar-label" title="'+escH(c)+'">'+escH(c)+'</div>'
        +'<div class="hbar-track"><div class="hbar-fill" style="width:'+pct+'%;background:'+col+'"></div></div>'
        +'<div class="hbar-val">'+fmtSize(d.size)+'<br><span style="font-size:10px;color:var(--muted)">'+(d.count>1?t('stats.items_count_pl',{n:d.count}):t('stats.items_count',{n:d.count}))+'</span></div>'
        +'</div>';
    });
    html += '</div></div>';

    // ── Section 3: Providers globaux (visibles seulement) ──
    const byProv = {};
    allItems.forEach(i => (i.providers||[]).forEach(p => {
      const name=_pname(p); if (!name || !_provVisible(name)) return;
      if (!byProv[name]) byProv[name] = {count:0, logo:_plogo(p)};
      byProv[name].count++;
      if (!byProv[name].logo) byProv[name].logo = _plogo(p);
    }));
    const provEntries = Object.entries(byProv).sort((a,b)=>b[1].count-a[1].count);
    if (provEntries.length) {
      const maxPC = provEntries[0][1].count || 1;
      html += '<div class="modal-section"><div class="modal-section-title">'+t('stats.streaming_availability')+'</div>';
      html += '<div class="hbar-list">';
      provEntries.forEach(([name,d]) => {
        const pct = (d.count/maxPC*100).toFixed(1);
        const logo = d.logo ? '<img src="'+escH(d.logo)+'" style="width:16px;height:16px;border-radius:3px;vertical-align:middle;margin-right:5px" alt=""/>' : '';
        html += '<div class="hbar-item">'
          +'<div class="hbar-label">'+logo+escH(name)+'</div>'
          +'<div class="hbar-track"><div class="hbar-fill" style="width:'+pct+'%;background:var(--accent)"></div></div>'
          +'<div class="hbar-val">'+(d.count>1?t('stats.items_count_pl',{n:d.count}):t('stats.items_count',{n:d.count}))+'</div>'
          +'</div>';
      });
      html += '</div></div>';

      // ── Section 4: Providers par groupe ──
      html += '<div class="modal-section"><div class="modal-section-title">'+t('stats.streaming_by_group')+'</div>';
      html += '<div class="stats-grid">';
      groupEntries.forEach(([g]) => {
        const gItems = allItems.filter(i=>(i.group||'Autres')===g);
        const gProv = {};
        const gProvMap = {};
        gItems.forEach(i=>(i.providers||[]).forEach(p=>{
          const n=_pname(p); if(!n||!_provVisible(n)) return;
          if(!gProvMap[n]) gProvMap[n]={count:0, logo:_plogo(p)};
          gProvMap[n].count++;
          if(!gProvMap[n].logo) gProvMap[n].logo=_plogo(p);
        }));
        const gProvEntries = Object.entries(gProvMap).sort((a,b)=>b[1].count-a[1].count);
        if (!gProvEntries.length) return;
        const col = groupColorMap[g] || '#888';
        html += '<div class="stat-row" style="flex-direction:column;align-items:flex-start;gap:6px">'
          +'<div style="display:flex;align-items:center;gap:6px"><div class="stat-dot" style="background:'+col+'"></div>'
          +'<span style="font-family:Syne,sans-serif;font-weight:700;font-size:13px">'+escH(g)+'</span></div>'
          +'<div style="width:100%;display:flex;flex-direction:column;gap:3px">';
        gProvEntries.forEach(([pname, d]) => {
          const cnt = d.count;
          const logo = d.logo ? '<img src="'+escH(d.logo)+'" style="width:14px;height:14px;border-radius:2px;vertical-align:middle;margin-right:4px" alt=""/>' : '';
          html += '<div style="display:flex;justify-content:space-between;font-size:12px">'
            +'<span style="color:var(--muted)">'+logo+escH(pname)+'</span>'
            +'<span style="color:var(--text);font-weight:500">'+cnt+'</span>'
            +'</div>';
        });
        html += '</div></div>';
      });
      html += '</div></div>';
    }

    // ── Section 5: Évolution mensuelle ──
    const byMonth = {};
    allItems.forEach(i => {
      if (!i.added_at) return;
      const d = new Date(i.added_at);
      const key = d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0');
      byMonth[key] = (byMonth[key]||0)+1;
    });
    const monthEntries = Object.entries(byMonth).sort((a,b)=>a[0]<b[0]?-1:1);
    if (monthEntries.length > 1) {
      const W=860, H=140, PL=50, PR=20, PT=15, PB=35;
      const iW=W-PL-PR, iH=H-PT-PB;
      const counts=monthEntries.map(e=>e[1]);
      const maxC=Math.max(...counts)||1;
      const minC=0;
      const n=monthEntries.length;
      const xStep=iW/(n-1);

      const pts=monthEntries.map((_,i)=>{
        const x=PL+i*xStep;
        const y=PT+iH-(counts[i]-minC)/(maxC-minC)*iH;
        return [x,y];
      });

      // Build SVG
      const pathD='M'+pts.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' L');
      // Area fill
      const areaD=pathD+' L'+pts[pts.length-1][0].toFixed(1)+','+(PT+iH)+' L'+PL+','+(PT+iH)+' Z';

      // X axis labels (every 2nd month if many)
      const step = n>12 ? Math.ceil(n/8) : 1;
      const MOIS=['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc'];
      let xLabels='', yLabels='', vLines='';
      monthEntries.forEach(([key],i)=>{
        if (i%step===0 || i===n-1) {
          const x=PL+i*xStep;
          const [yr,mo]=key.split('-');
          const label=MOIS[parseInt(mo)-1]+(n>14?' '+yr.slice(2):'');
          xLabels+='<text x="'+x.toFixed(0)+'" y="'+(H-6)+'" text-anchor="middle" font-size="10" fill="var(--muted)">'+label+'</text>';
          vLines+='<line x1="'+x.toFixed(0)+'" y1="'+PT+'" x2="'+x.toFixed(0)+'" y2="'+(PT+iH)+'" stroke="var(--border)" stroke-width="1" stroke-dasharray="3,3"/>';
        }
      });
      // Y labels
      for (let t=0; t<=4; t++) {
        const v=Math.round(maxC*t/4);
        const y=PT+iH-iH*t/4;
        yLabels+='<text x="'+(PL-6)+'" y="'+(y+4).toFixed(0)+'" text-anchor="end" font-size="10" fill="var(--muted)">'+v+'</text>';
        vLines+='<line x1="'+PL+'" y1="'+y.toFixed(0)+'" x2="'+(PL+iW)+'" y2="'+y.toFixed(0)+'" stroke="var(--border)" stroke-width="1" stroke-dasharray="3,3"/>';
      }
      // Dots
      const dots=pts.map(([x,y],i)=>'<circle cx="'+x.toFixed(1)+'" cy="'+y.toFixed(1)+'" r="3" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"><title>'+monthEntries[i][0]+': '+counts[i]+' ajouts</title></circle>').join('');

      const svgContent='<defs><linearGradient id="lineGrad" x1="0" y1="0" x2="0" y2="1">'
        +'<stop offset="0%" stop-color="var(--accent)" stop-opacity=".25"/>'
        +'<stop offset="100%" stop-color="var(--accent)" stop-opacity="0"/>'
        +'</linearGradient></defs>'
        +vLines
        +'<path d="'+areaD+'" fill="url(#lineGrad)"/>'
        +'<path d="'+pathD+'" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        +dots+xLabels+yLabels;

      const totalAdded=counts.reduce((s,v)=>s+v,0);
      const avgPerMonth=(totalAdded/n).toFixed(1);
      html += '<div class="modal-section"><div class="modal-section-title">'+t('stats.monthly_evolution')+'</div>';
      html += '<div style="display:flex;gap:16px;margin-bottom:10px;flex-wrap:wrap">'
        +'<div class="stat-row"><div class="stat-row-label">'+t('stats.total_indexed')+'</div><div class="stat-row-val">'+totalAdded+'</div></div>'
        +'<div class="stat-row"><div class="stat-row-label">'+t('stats.avg_per_month')+'</div><div class="stat-row-val">'+avgPerMonth+'</div></div>'
        +'<div class="stat-row"><div class="stat-row-label">'+t('stats.period')+'</div><div class="stat-row-val" style="font-size:12px">'+monthEntries[0][0]+' → '+monthEntries[n-1][0]+'</div></div>'
        +'</div>';
      html += '<div class="chart-wrap"><svg class="chart-svg" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid meet">'+svgContent+'</svg></div>';
      html += '</div>';
    }

    return html;
  }

  function switchYearView(btn, view) {
    const yr = document.getElementById('yearViewYear');
    const dc = document.getElementById('yearViewDecade');
    if (yr) yr.style.display = view==='year'   ? '' : 'none';
    if (dc) dc.style.display = view==='decade' ? '' : 'none';
    const by = document.getElementById('yearBtnYear');
    const bd = document.getElementById('yearBtnDecade');
    if (by) by.classList.toggle('active', view==='year');
    if (bd) bd.classList.toggle('active', view==='decade');
  }

  function statSwitchPie(el) {
    const id = el.dataset.pie, unit = el.dataset.unit;
    document.getElementById(id+'PieSize').style.display  = unit==='size'  ? '' : 'none';
    document.getElementById(id+'PieCount').style.display = unit==='count' ? '' : 'none';
    document.getElementById(id+'BtnSize').classList.toggle('active',  unit==='size');
    document.getElementById(id+'BtnCount').classList.toggle('active', unit==='count');
  }

  // ── SCAN ──────────────────────────────────────────────
  let _scanMode = 'default';
  let _pollTimer = null;
  let _logOffset = 0;

  const SCAN_MODE_LABELS = {
    default: 'Quick + Enrich',
    quick:   'Quick',
    enrich:  'Enrich',
    full:    'Full',
  };

  function selectScanMode(mode) {
    _scanMode = mode;
    document.getElementById('scanBtnLabel').textContent = SCAN_MODE_LABELS[mode] || 'Scanner';
    document.getElementById('scanDropdown').classList.remove('open');
  }

  function toggleScanDropdown(e) {
    e.stopPropagation();
    const dd = document.getElementById('scanDropdown');
    const wrap = document.getElementById('scanBtnWrap');
    document.querySelectorAll('.scan-dropdown').forEach(d => { if(d!==dd) d.classList.remove('open'); });
    if (!dd.classList.contains('open')) {
      const r = wrap.getBoundingClientRect();
      dd.style.bottom = (window.innerHeight - r.top + 6) + 'px';
      dd.style.top = 'auto';
      dd.style.left = r.left + 'px';
      dd.style.minWidth = r.width + 'px';
    }
    dd.classList.toggle('open');
  }
  document.addEventListener('click', () => {
    document.getElementById('scanDropdown')?.classList.remove('open');
  });

  function triggerScan() {
    const btn = document.getElementById('scanMainBtn');
    const arrow = document.getElementById('scanArrowBtn');
    btn.disabled = true; arrow.disabled = true;
    _logOffset = 0;
    openScanLog(_scanMode);

    fetch('/api/scan/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mode: _scanMode}),
    })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        appendScanLog('[Erreur] ' + data.error, 'log-err');
        setScanStatus('error');
        btn.disabled = false; arrow.disabled = false;
        return;
      }
      startPoll();
    })
    .catch(err => {
      appendScanLog('[Erreur réseau] ' + err, 'log-err');
      setScanStatus('error');
      btn.disabled = false; arrow.disabled = false;
    });
  }

  function startPoll() {
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTimer = setInterval(pollScanStatus, 1200);
  }

  function pollScanStatus() {
    fetch('/api/scan/status')
      .then(r => r.json())
      .then(data => {
        // Append new log lines
        const lines = data.log || [];
        const newLines = lines.slice(_logOffset);
        _logOffset = lines.length;
        newLines.forEach(l => {
          const cls = /error|erreur|exception/i.test(l) ? 'log-err'
                    : /terminé|done|✓/i.test(l)         ? 'log-ok'
                    : 'log-line';
          appendScanLog(l, cls);
        });
        setScanStatus(data.status);
        if (data.status !== 'running') {
          clearInterval(_pollTimer);
          _pollTimer = null;
          const btn = document.getElementById('scanMainBtn');
          const arrow = document.getElementById('scanArrowBtn');
          btn.disabled = false; arrow.disabled = false;
          // Reload library.json on success
          if (data.status === 'done') {
            setTimeout(() => loadLibrary(), 800);
            setTimeout(() => closeScanLog(), 5000);
          }
        }
      })
      .catch(() => {});
  }

  function openScanLog(mode) {
    const panel = document.getElementById('scanLogPanel');
    panel.classList.remove('viewer');
    document.getElementById('scanLogTitle').textContent = 'Scan — ' + (SCAN_MODE_LABELS[mode] || mode);
    document.getElementById('scanLogBody').innerHTML = '';
    setScanStatus('running');
    panel.classList.add('open');
  }

  function closeScanLog() {
    const panel = document.getElementById('scanLogPanel');
    panel.classList.remove('open');
    panel.classList.remove('viewer');
  }

  function openLogViewer() {
    const panel = document.getElementById('scanLogPanel');
    const body = document.getElementById('scanLogBody');
    document.getElementById('scanLogTitle').textContent = t('scan.log_title');
    body.innerHTML = '<div class="log-line" style="color:var(--muted)">'+t('scan.log_loading')+'</div>';
    setScanStatus('');
    panel.classList.add('viewer');
    panel.classList.add('open');
    fetch('/api/scan/log')
      .then(r => r.text())
      .then(txt => {
        body.innerHTML = '';
        txt.split('\n').forEach(line => {
          if (!line) return;
          const el = document.createElement('div');
          el.className = line.includes('[ERROR]') ? 'log-err'
                       : line.includes('[WARNING]') ? 'log-line'
                       : line.includes('✓') || line.includes('terminé') ? 'log-ok'
                       : 'log-line';
          el.textContent = line;
          body.appendChild(el);
        });
        body.scrollTop = body.scrollHeight;
      })
      .catch(() => { body.innerHTML = '<div class="log-err">'+t('scan.log_error')+'</div>'; });
  }

  function appendScanLog(line, cls) {
    const body = document.getElementById('scanLogBody');
    const el = document.createElement('div');
    el.className = cls || 'log-line';
    el.textContent = line;
    body.appendChild(el);
    body.scrollTop = body.scrollHeight;
  }

  function setScanStatus(status) {
    const dot = document.getElementById('scanStatusDot');
    dot.className = 'scan-status-dot ' + (status || '');
    const title = document.getElementById('scanLogTitle');
    const mode = SCAN_MODE_LABELS[_scanMode] || _scanMode;
    const suffix = status === 'running' ? t('scan.status_running')
                 : status === 'done'    ? t('scan.status_done')
                 : status === 'error'   ? t('scan.status_error')
                 : '';
    title.textContent = 'Scan — ' + mode + suffix;
  }

  // ── CURVE PERIOD SWITCH ──────────────────────────────
  let _buildCurveForPeriodGlobal = ()=>'';
  function setCurvePeriod(btn) {
    const controls = document.getElementById('curveControls');
    if (!controls) return;
    const period = btn.dataset.period;
    controls.querySelectorAll('.pie-switch-btn').forEach(b=>b.classList.toggle('active', b===btn));
    const charts = document.getElementById('curveCharts');
    if (charts) charts.innerHTML = _buildCurveForPeriodGlobal(period);
  }

  // ── MOBILE NAV ───────────────────────────────────────
  let currentMobileTab = 'library';

  function isMobile() { return window.innerWidth <= 768; }

  let mobileFiltersOpen = false;

  function toggleMobileFilters() {
    mobileFiltersOpen = !mobileFiltersOpen;
    const panel = document.getElementById('mobileFiltersPanel');
    const btn   = document.getElementById('mobileFilterBtn');
    if (panel) panel.style.display = mobileFiltersOpen ? 'block' : 'none';
    if (btn)   btn.style.color = mobileFiltersOpen ? 'var(--accent)' : '';
    if (mobileFiltersOpen) syncMobileFilters();
  }

  function closeMobileFilters() {
    mobileFiltersOpen = false;
    const panel = document.getElementById('mobileFiltersPanel');
    const btn   = document.getElementById('mobileFilterBtn');
    if (panel) panel.style.display = 'none';
    if (btn)   btn.style.color = '';
  }

  function switchMobileTab(tab) {
    currentMobileTab = tab;
    closeMobileFilters();
    // Update nav buttons
    ['library','stats'].forEach(t => {
      const btn = document.getElementById('mnav' + t.charAt(0).toUpperCase() + t.slice(1));
      if (btn) btn.classList.toggle('active', t === tab);
    });
    // Show/hide panels
    ['libraryPanel','statsPanel'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.remove('active');
    });
    const el = document.getElementById(tab + 'Panel');
    if (el) el.classList.add('active');
    currentTab = tab;
    const lc2 = document.getElementById('libraryControls');
    if (lc2) lc2.style.display = tab==='library' ? '' : 'none';
    if (tab === 'library') render();
    else if (tab === 'stats') renderStatsPanel();
  }

  function syncMobileFilters() {
    // Sync search input value
    const mSearch = document.getElementById('searchInputMobile');
    const dSearch = document.getElementById('searchInput');
    if (mSearch && dSearch && mSearch.value !== dSearch.value) mSearch.value = dSearch.value;
    // Mirror filter sections to mobile panel
    ['storageSection','providerSection','resolutionSection','codecSection','audioCodecSection'].forEach(id => {
      const src = document.getElementById(id);
      const dst = document.getElementById(id + 'Mobile');
      if (src && dst) dst.innerHTML = src.innerHTML;
    });
    // Sync stats bar
    const sbSrc = document.getElementById('statsBar');
    document.querySelectorAll('#mobileStatsBar').forEach(el => {
      if (sbSrc) el.innerHTML = sbSrc.innerHTML;
    });
    // Sync type pills
    ['#typeFilterMobile'].forEach(sel => {
      document.querySelectorAll(sel + ' .provider-pill').forEach(p => {
        const t = p.dataset.type || 'all';
        p.classList.toggle('active', activeType==='all' ? !p.dataset.type : t===activeType);
      });
    });
  }

  // Also mirror to mobile on every filter render
  const _origRenderStorageBar = renderStorageBar;

  // ── SETTINGS ─────────────────────────────────────────
    // serverConfig is populated from library.json in loadLibrary()

  function _field(id) { return document.getElementById(id); }
  function _ro(id, val) {
    const el = _field(id);
    if (!el) return;
    if (el.type === 'checkbox') { el.checked = val; el.disabled = true; }
    else if (el.tagName === 'SELECT') { el.value = val; el.disabled = true; }
    else { el.value = val; el.readOnly = true; }
  }
  function _rw(id, val) {
    const el = _field(id);
    if (!el) return;
    if (el.type === 'checkbox') { el.checked = val; el.disabled = false; }
    else if (el.tagName === 'SELECT') { el.value = val; el.disabled = false; }
    else { el.value = val; el.readOnly = false; }
  }

  function loadSettings() {
    if (!_field('cfgLibraryPath')) return;
    const sc = serverConfig;

    // Accent color — from appConfig (persisted in config.json)
    const accentEl = _field('cfgAccentColor');
    if (accentEl) {
      accentEl.value = appConfig.ui?.accent_color || _DEFAULT_ACCENT;
    }

    // enablePlot — from appConfig
    const epEl = _field('cfgEnablePlot');
    if (epEl) { epEl.checked = enablePlot; epEl.disabled = false; }

    // Library path — readonly, from serverConfig (set in library.json config block)
    _ro('cfgLibraryPath', sc.library_path || '');

    // Enable flags — editable, from appConfig
    _rw('cfgEnableMovies',  appConfig.enable_movies  ?? true);
    _rw('cfgEnableSeries',  appConfig.enable_series  ?? true);

    // Scan cron / log level / language — from appConfig.system (editable, stored in config.json)
    const sys = appConfig.system || {};
    _rw('cfgScanCron',  sys.scan_cron  || '0 3 * * *');
    _rw('cfgLogLevel',  sys.log_level  || 'INFO');
    _rw('cfgLanguage',  sys.language   || 'fr');
    updateCronHint();

    // Jellyseerr — editable from appConfig
    _rw('cfgEnableJellyseerr', appConfig.jellyseerr?.enabled ?? false);
    _rw('cfgJellyseerrUrl',    appConfig.jellyseerr?.url    || '');
    _rw('cfgJellyseerrKey',    '');   // never pre-fill the key
    toggleJsrFields();

    renderFoldersUI();
    renderProviderToggles();
  }

  function toggleJsrFields() {
    const enabled = document.getElementById('cfgEnableJellyseerr')?.checked;
    ['cfgJellyseerrUrl', 'cfgJellyseerrKey', 'cfgJsrTestBtn'].forEach(id => {
      const el = document.getElementById(id);
      if (el) { el.disabled = !enabled; el.style.opacity = enabled ? '' : '.45'; }
    });
  }

  function _hasEditableFields() {
    const ids = ['cfgScanCron','cfgJellyseerrUrl','cfgJellyseerrKey','cfgLogLevel','cfgLanguage',
                 'cfgEnableMovies','cfgEnableSeries','cfgEnableJellyseerr','cfgEnablePlot','cfgAccentColor','cfgCardHeight'];
    return ids.some(id => { const e = _field(id); return e && !e.readOnly && !e.disabled; });
  }

  function saveSettings() {
    // Sync enablePlot immediately (no server roundtrip for preview)
    const epEl = _field('cfgEnablePlot');
    if (epEl && !epEl.disabled) enablePlot = epEl.checked;
  }

  async function saveSettingsAndClose() {
    saveSettings();
    const get = id => {
      const e = _field(id);
      if (!e || e.readOnly || e.disabled) return null;
      return e.type === 'checkbox' ? e.checked : e.value;
    };

    // Build partial config from editable fields
    const partial = {};

    const ep = get('cfgEnablePlot');
    if (ep !== null) { partial.ui = partial.ui||{}; partial.ui.synopsis_on_hover = ep; }

    const accentEl = _field('cfgAccentColor');
    if (accentEl && !accentEl.readOnly) {
      partial.ui = partial.ui||{};
      partial.ui.accent_color = accentEl.value;
    }

    const em = get('cfgEnableMovies');
    if (em !== null) partial.enable_movies = em;

    const es = get('cfgEnableSeries');
    if (es !== null) partial.enable_series = es;

    const jEnabled = get('cfgEnableJellyseerr');
    const jUrl     = get('cfgJellyseerrUrl');
    const jKey     = get('cfgJellyseerrKey');
    if (jEnabled !== null || jUrl !== null || (jKey !== null && jKey !== '')) {
      partial.jellyseerr = partial.jellyseerr || {};
      if (jEnabled !== null)           partial.jellyseerr.enabled = jEnabled;
      if (jUrl     !== null)           partial.jellyseerr.url     = jUrl;
      if (jKey !== null && jKey !== '') partial.jellyseerr.apikey  = jKey;
    }

    // Gather folder type/visibility — always include current state
    const folderUpdates = gatherFolderEdits();
    if (folderUpdates) partial.folders = folderUpdates;

    // Gather provider visibility
    const provVis = gatherProviderVisibility();
    if (provVis !== undefined) partial.providers_visible = provVis;

    // Scan cron / log level / language → system block
    const cron = get('cfgScanCron');
    const logLevel = get('cfgLogLevel');
    const lang = get('cfgLanguage');
    if (cron !== null || logLevel !== null || lang !== null) {
      partial.system = partial.system || {};
      if (cron !== null)     partial.system.scan_cron = cron;
      if (logLevel !== null) partial.system.log_level = logLevel;
      if (lang !== null)     partial.system.language  = lang;
    }

    try {
      await saveConfig(partial);
      window.location.reload();
    } catch(e) {
      alert(t('settings.save_error', {msg: e.message}));
    }
  }

  // ── SETTINGS — FOLDERS ───────────────────────────────
  function onFolderTypeChange(sel) {
    const idx = parseInt(sel.dataset.folderIdx);
    const val = sel.value === 'null' ? null : sel.value;
    if (appConfig.folders[idx]) {
      appConfig.folders[idx].type = val;
      if (val && val !== 'ignore') appConfig.folders[idx].visible = true;
    }
    renderFoldersUI();
  }

  function renderFoldersUI() {
    const container = document.getElementById('cfgFoldersContainer');
    if (!container) return;
    const folders = appConfig.folders || [];
    if (!folders.length) {
      container.innerHTML = '<div class="settings-note">Aucun dossier détecté. Lancez un scan pour détecter les dossiers.</div>';
      return;
    }
    const unknownCount = folders.filter(f => !f.missing && (f.type === null || f.type === undefined)).length;
    let html = '';
    if (unknownCount > 0) {
      html += '<div class="settings-note" style="border-left:3px solid #f7b731;padding-left:10px;margin-bottom:10px">'
        + '⚠ ' + t('settings.library.folder_unconfigured', {n: unknownCount, s: unknownCount>1?'s':''}) + '</div>';
    }
    html += '<table style="width:100%;border-collapse:collapse;font-size:13px">'
      + '<thead><tr>'
        + '<th style="text-align:left;padding:4px 8px;color:var(--muted);font-weight:500">'+t('settings.library.folder_col_name')+'</th>'
        + '<th style="text-align:left;padding:4px 8px;color:var(--muted);font-weight:500">'+t('settings.library.folder_col_type')+'</th>'
        + '<th style="text-align:left;padding:4px 8px;color:var(--muted);font-weight:500">'+t('settings.library.folder_col_visible')+'</th>'
      + '</tr></thead><tbody>';
    folders.forEach((f, idx) => {
      const isMissing = !!f.missing;
      const typeOpts = [
        ['movie', t('settings.library.folder_types.movie')],
        ['tv', t('settings.library.folder_types.tv')],
        ['null', t('settings.library.folder_types.ignore')],
      ].map(([v, lbl]) =>
        '<option value="'+v+'"'+(String(f.type)===v?' selected':'')+'>'+lbl+'</option>'
      ).join('');
      html += '<tr style="border-top:1px solid var(--border)'+(isMissing?';opacity:0.5':'')+'">'
        + '<td style="padding:6px 8px;font-family:monospace;font-size:12px">'+escH(f.name)
          + (isMissing ? '<span style="display:inline;margin-left:6px;font-size:10px;color:#f97316;font-style:italic">'+t('settings.library.missing')+'</span>' : '')
          + '</td>'
        + '<td style="padding:6px 8px">'
          + (isMissing
            ? '<span style="color:var(--muted);font-size:12px">'+(f.type==='movie'?t('settings.library.folder_types.movie'):f.type==='tv'?t('settings.library.folder_types.tv'):'—')+'</span>'
            : '<select class="settings-input" style="padding:3px 6px;font-size:12px" data-folder-idx="'+idx+'" data-folder-key="type" onchange="onFolderTypeChange(this)">'
              + typeOpts + '</select>')
          + '</td>'
        + '<td style="padding:6px 8px">'
          + (!f.type || f.type === 'null' || isMissing
            ? '<span style="color:var(--muted);font-size:12px">—</span>'
            : '<label class="toggle-switch">'
              + '<input type="checkbox" data-folder-idx="'+idx+'" data-folder-key="visible"'
              + (f.visible !== false ? ' checked' : '')
              + '/><span class="toggle-switch-slider"></span></label>')
          + '</td>'
        + '</tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
  }

  function gatherFolderEdits() {
    const folders = JSON.parse(JSON.stringify(appConfig.folders || []));
    if (!folders.length) return null;
    // Always read current DOM state — appConfig.folders may have been mutated by
    // onFolderTypeChange() so we can't rely on a "changed" diff; always return full state.
    document.querySelectorAll('[data-folder-idx][data-folder-key]').forEach(el => {
      const idx = parseInt(el.dataset.folderIdx);
      const key = el.dataset.folderKey;
      if (!folders[idx]) return;
      if (el.type === 'checkbox') { folders[idx][key] = el.checked; }
      else { folders[idx][key] = el.value === 'null' ? null : el.value; }
    });
    return folders;
  }

  // ── SETTINGS — PROVIDER TOGGLES ──────────────────────
  function renderProviderToggles() {
    const container = document.getElementById('cfgProviderToggles');
    if (!container) return;
    const provs = [...new Set(allItems.flatMap(i=>(i.providers||[]).map(p=>p.name||p).filter(Boolean)))].sort();
    if (!provs.length) { container.innerHTML = '<div class="settings-note">Aucun provider disponible.</div>'; return; }
    let html = '';
    provs.forEach(prov => {
      const checked = _provVisible(prov);
      html += '<div class="settings-row" style="margin-bottom:6px">'
        + '<label class="settings-label">'+escH(prov)+'</label>'
        + '<label class="toggle-switch"><input type="checkbox" class="prov-visibility-toggle" data-prov="'+escH(prov)+'"'
        + (checked?' checked':'') + '/><span class="toggle-switch-slider"></span></label>'
        + '</div>';
    });
    container.innerHTML = html;
  }

  function gatherProviderVisibility() {
    const all = [...new Set(allItems.flatMap(i=>(i.providers||[]).map(p=>p.name||p).filter(Boolean)))].sort();
    const checked = [];
    document.querySelectorAll('.prov-visibility-toggle').forEach(el => {
      if (el.checked) checked.push(el.dataset.prov);
    });
    // [] = all visible (matches config.json schema); non-empty = whitelist
    if (checked.length === all.length) return [];
    return checked;
  }

  function _cronHint(cron) {
    if (!cron || typeof cron !== 'string') return '';
    const parts = cron.trim().split(/\s+/);
    if (parts.length !== 5) return 'Format invalide (5 champs requis)';
    const [min, hour, dom, month, dow] = parts;
    const days = ['dim','lun','mar','mer','jeu','ven','sam'];
    const months = ['jan','fév','mar','avr','mai','jun','jul','aoû','sep','oct','nov','déc'];
    const isAll = v => v === '*';
    const isNum = v => /^\d+$/.test(v);
    // Simple common patterns
    if (isAll(dom) && isAll(month) && isAll(dow)) {
      if (isAll(min) && isAll(hour)) return 'Chaque minute';
      if (isNum(min) && isNum(hour)) return 'Tous les jours à ' + hour.padStart(2,'0') + 'h' + min.padStart(2,'0');
      if (isAll(min) && isNum(hour)) return 'Toutes les heures, à ' + hour + 'h';
      if (isNum(min) && isAll(hour)) return 'Chaque heure, à .' + min.padStart(2,'0');
    }
    if (isNum(min) && isNum(hour) && isAll(dom) && isAll(month) && isNum(dow)) {
      return 'Chaque ' + (days[parseInt(dow)] || 'jour?') + ' à ' + hour.padStart(2,'0') + 'h' + min.padStart(2,'0');
    }
    if (isNum(min) && isNum(hour) && isNum(dom) && isAll(month) && isAll(dow)) {
      return 'Le ' + dom + ' de chaque mois à ' + hour.padStart(2,'0') + 'h' + min.padStart(2,'0');
    }
    if (isNum(min) && isNum(hour) && isNum(dom) && isNum(month) && isAll(dow)) {
      return 'Le ' + dom + ' ' + (months[parseInt(month)-1] || month) + ' à ' + hour.padStart(2,'0') + 'h' + min.padStart(2,'0');
    }
    if (min === '0' && hour === '*/2' && isAll(dom) && isAll(month) && isAll(dow)) return 'Toutes les 2 heures';
    const step = hour.match(/^\*\/(\d+)$/);
    if (step && isAll(dom) && isAll(month) && isAll(dow)) return 'Toutes les ' + step[1] + 'h';
    return ''; // Unknown pattern — no hint
  }

  function updateCronHint() {
    const el = _field('cfgScanCron');
    const hint = document.getElementById('cfgCronHint');
    if (!hint) return;
    hint.textContent = el ? _cronHint(el.value) : '';
  }

  function _hasMultipleTypes() {
    const folders = appConfig.folders || [];
    const hasMovies = folders.some(f => !f.missing && f.type === 'movie');
    const hasTv = folders.some(f => !f.missing && f.type === 'tv');
    return hasMovies && hasTv && (appConfig.enable_movies ?? true) && (appConfig.enable_series ?? true);
  }

  function _updateTypeFilterVisibility() {
    const show = _hasMultipleTypes();
    ['typeSection', 'mobileTypeSection'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = show ? '' : 'none';
    });
  }

  async function testJellyseerr() {
    const btn = document.getElementById('cfgJsrTestBtn');
    const res = document.getElementById('cfgJsrTestResult');
    if (!res) return;
    res.textContent = '…';
    res.style.color = 'var(--muted)';
    if (btn) btn.disabled = true;
    try {
      const r = await fetch('/api/jellyseerr/test');
      const data = await r.json();
      if (data.ok) {
        res.textContent = '✓'; res.style.color = '#34d399';
      } else {
        res.textContent = '✗'; res.style.color = '#f97316';
      }
    } catch(e) {
      res.textContent = '✗'; res.style.color = '#f97316';
    } finally {
      if (btn) btn.disabled = false;
      setTimeout(() => { if (res) res.textContent = ''; }, 3000);
    }
  }

  function switchStab(btn, tabId) {
    document.querySelectorAll('.stab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.stab-panel').forEach(p => p.style.display = 'none');
    document.getElementById(tabId).style.display = 'block';
  }

  function openSettings() {
    loadSettings();
    loadVersion();
    renderProviderToggles();
    document.getElementById('settingsOverlay').style.display = 'flex';
    const btn = document.getElementById('settingsSaveBtn');
    if (btn) btn.style.display = 'block'; // always show — config.json is always writable
  }

  function closeSettings() {
    document.getElementById('settingsOverlay').style.display = 'none';
  }

  function closeSettingsIfBackdrop(e) {
    if (e.target === document.getElementById('settingsOverlay')) closeSettings();
  }

  // ── LAYOUT TOGGLE ────────────────────────────────────
  

  


  function syncThemeIcons() {
    const isDark = document.documentElement.classList.contains('dark');
    const sunMoon = isDark
      ? '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>'
      : '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>';
    ['themeIcon','themeIconMobile'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = sunMoon;
    });
  }

  

  // ── PLOT TOOLTIP ─────────────────────────────────────
  let _tt = null;
  let _ttTimer;

  function showPlot(el, text) {
    if (!enablePlot || isMobile()) return;
    if (!_tt) _tt = document.getElementById('plotTooltip');
    if (!text || !_tt) return;
    clearTimeout(_ttTimer);
    _ttTimer = setTimeout(() => {
      _tt.textContent = text;
      _tt.classList.add('visible');
    }, 400);
    document.addEventListener('mousemove', _moveTT);
  }

  function hidePlot() {
    clearTimeout(_ttTimer);
    if (_tt) _tt.classList.remove('visible');
    document.removeEventListener('mousemove', _moveTT);
  }

  function _moveTT(e) {
    if (!_tt) return;
    const x = e.clientX + 14, y = e.clientY + 14;
    const maxX = window.innerWidth  - _tt.offsetWidth  - 10;
    const maxY = window.innerHeight - _tt.offsetHeight - 10;
    _tt.style.left = Math.min(x, maxX) + 'px';
    _tt.style.top  = Math.min(y, maxY) + 'px';
  }

  // ── KEYBOARD SHORTCUTS ──────────────────────────────
  // Close mobile filters on outside tap
  document.addEventListener('click', e => {
    if (!mobileFiltersOpen) return;
    const panel = document.getElementById('mobileFiltersPanel');
    const btn   = document.getElementById('mobileFilterBtn');
    if (panel && !panel.contains(e.target) && btn && !btn.contains(e.target)) {
      closeMobileFilters();
    }
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      const overlay = document.getElementById('settingsOverlay');
      if (overlay && overlay.style.display !== 'none') closeSettings();
    }
  });

  // ── SIDEBAR RESIZE ───────────────────────────────────
  (function(){
    const sidebar = document.getElementById('sidebar');
    const resizer = document.getElementById('sidebarResizer');
    let startX, startW;
    resizer.addEventListener('mousedown', function(e){
      startX = e.clientX;
      startW = sidebar.offsetWidth;
      resizer.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      function onMove(e){
        const w = Math.min(420, Math.max(200, startW + e.clientX - startX));
        sidebar.style.width = w + 'px';
      }
      function onUp(){
        resizer.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      }
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  })();

  // ── AUTH ─────────────────────────────────────────────
  async function checkAuth() {
    try {
      const r = await fetch('/api/auth');
      if (!r.ok) { initApp(); return; }
      const d = await r.json();
      if (!d.required) { initApp(); return; }
      if (sessionStorage.getItem('mediaAuth') === '1') { initApp(); return; }
      const ov = document.getElementById('authOverlay');
      if (ov) { ov.style.display = 'flex'; setTimeout(()=>document.getElementById('authInput')?.focus(), 50); }
    } catch(e) {
      initApp();
    }
  }

  async function submitAuth() {
    const input = document.getElementById('authInput');
    const btn   = document.getElementById('authBtn');
    const err   = document.getElementById('authError');
    if (!input) return;
    btn.disabled = true; btn.textContent = '…';
    try {
      const r = await fetch('/api/auth', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({password: input.value}),
      });
      const d = await r.json();
      if (d.ok) {
        sessionStorage.setItem('mediaAuth', '1');
        document.getElementById('authOverlay').style.display = 'none';
        initApp();
      } else {
        if (err) { err.style.display = 'block'; }
        input.value = ''; input.focus();
        btn.disabled = false; btn.textContent = t('auth.enter');
      }
    } catch(e) {
      btn.disabled = false; btn.textContent = 'Entrer';
    }
  }

  // ── ONBOARDING ───────────────────────────────────────
  let _onbStep = 0;
  let _onbJsr = { enabled: false, url: '', key: '' };
  let _onbLogSeen = 0;
  let _langTimer = null;
  let _onbLang = 'fr';
  let _onbTheme = 'dark';

  const _ONB_TEXTS = {
    fr: {
      title: 'Bienvenue dans MyMediaLibrary',
      desc: 'Visualisez et explorez votre bibliothèque de films et séries en un coup d\'œil. Repérez les fichiers encombrants, les codecs ou résolutions à remplacer, les contenus déjà disponibles sur vos plateformes de streaming, et suivez l\'évolution de votre collection.',
      start: 'Commencer →',
    },
    en: {
      title: 'Welcome to MyMediaLibrary',
      desc: 'Visualize and explore your movie and TV library at a glance. Spot large files, outdated codecs or resolutions, content already available on your streaming platforms, and track your collection\'s growth with detailed statistics.',
      start: 'Get started →',
    },
  };

  function _updateOnbLangDisplay(displayLang) {
    const txt = _ONB_TEXTS[displayLang] || _ONB_TEXTS.fr;
    const el = (id) => document.getElementById(id);
    if (el('onbWelcomeTitle')) el('onbWelcomeTitle').textContent = txt.title;
    if (el('onbWelcomeDesc'))  el('onbWelcomeDesc').textContent  = txt.desc;
    if (el('onbWelcomeStart')) el('onbWelcomeStart').textContent = txt.start;
    ['onbLangFr','onbLangEn'].forEach(id => {
      const btn = el(id);
      if (!btn) return;
      const isDisplayed = (id === 'onbLangFr' && displayLang === 'fr') || (id === 'onbLangEn' && displayLang === 'en');
      const isSelected  = _onbLang !== null && ((id === 'onbLangFr' && _onbLang === 'fr') || (id === 'onbLangEn' && _onbLang === 'en'));
      if (isSelected) {
        // Manual selection: filled background
        btn.style.background  = 'var(--accent)';
        btn.style.borderColor = 'var(--accent)';
        btn.style.color       = '#fff';
        btn.style.boxShadow   = '';
        btn.style.transform   = '';
      } else if (isDisplayed) {
        // Auto-highlight: border only, transparent background
        btn.style.background  = 'transparent';
        btn.style.borderColor = 'var(--accent)';
        btn.style.color       = 'var(--text)';
        btn.style.boxShadow   = '0 0 0 3px rgba(124,106,255,.15)';
        btn.style.transform   = 'scale(1.04)';
      } else {
        // Default
        btn.style.background  = 'var(--surface)';
        btn.style.borderColor = 'var(--border)';
        btn.style.color       = 'var(--muted)';
        btn.style.boxShadow   = '';
        btn.style.transform   = '';
      }
    });
  }

  function _startLangToggle() {
    // Visual-only: highlight current language; if none selected yet use CURRENT_LANG
    _updateOnbLangDisplay(_onbLang || CURRENT_LANG);
    clearInterval(_langTimer);
    let showing = CURRENT_LANG;
    _langTimer = setInterval(() => {
      // Only auto-toggle display while no manual selection made
      if (_onbLang !== null) { clearInterval(_langTimer); _langTimer = null; return; }
      showing = showing === 'fr' ? 'en' : 'fr';
      _updateOnbLangDisplay(showing);
    }, 3000);
  }

  async function selectOnbLang(lang) {
    clearInterval(_langTimer);
    _langTimer = null;
    _onbLang = lang;
    _updateOnbLangDisplay(lang);
    // Enable Commencer button now that a language was manually selected
    const btn = document.getElementById('onbCommencerBtn');
    if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.style.cursor = 'pointer'; }
    if (lang !== CURRENT_LANG) {
      await loadTranslations(lang);
      applyTranslations();
      // Re-update display after translations loaded (button text may have changed)
      _updateOnbLangDisplay(lang);
      const startSpan = document.getElementById('onbWelcomeStart');
      if (startSpan) startSpan.textContent = (_ONB_TEXTS[lang] || _ONB_TEXTS.fr).start;
    }
  }

  function toggleOnboardingTheme() {
    _onbTheme = _onbTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', _onbTheme);
  }

  function showOnboarding() {
    _onbStep = 0;
    _onbLang = null;
    _onbTheme = appConfig.ui?.theme || 'dark';
    _onbJsr = {
      enabled: appConfig.jellyseerr?.enabled ?? false,
      url:     appConfig.jellyseerr?.url     || '',
      key:     '',
    };
    _onbLogSeen = 0;
    // Prefetch both i18n files so lang switching is instant (browser caches them)
    ['fr', 'en'].forEach(l => fetch(`/i18n/${l}.json?_=`+Date.now()).catch(()=>{}));
    const ov = document.getElementById('onboardingOverlay');
    if (ov) { ov.style.display = 'flex'; _onbRender(); }
  }

  function _onbRender() {
    // Step indicator: hidden on step 0, 3 bars for steps 1-3
    const stepsEl = document.getElementById('onbSteps');
    if (stepsEl) {
      if (_onbStep === 0) {
        stepsEl.innerHTML = '';
      } else {
        stepsEl.innerHTML = [1,2,3].map(n =>
          '<div style="width:40px;height:4px;border-radius:2px;background:'+(n===_onbStep?'var(--accent)':'var(--border)')+'"></div>'
        ).join('');
      }
    }

    const panel = document.getElementById('onbPanel');
    if (!panel) return;
    if      (_onbStep === 0) { panel.innerHTML = _onbStep0HTML(); _startLangToggle(); }
    else if (_onbStep === 1) panel.innerHTML = _onbStep1HTML();
    else if (_onbStep === 2) panel.innerHTML = _onbStep2HTML();
    else                     panel.innerHTML = _onbStep3HTML();

    // Nav buttons
    const prev = document.getElementById('onbPrevBtn');
    const next = document.getElementById('onbNextBtn');
    const skip = document.getElementById('onbSkipBtn');
    // Step 0: hide all nav buttons (step has its own Commencer button)
    if (_onbStep === 0) {
      if (prev) prev.style.display = 'none';
      if (next) next.style.display = 'none';
      if (skip) skip.style.display = 'none';
      return;
    }
    if (prev) prev.style.display = _onbStep >= 1 ? '' : 'none';
    if (next) {
      next.style.display = '';
      if (_onbStep === 3) { next.textContent = t('nav.launch_scan'); next.onclick = onbLaunchScan; }
      else                { next.textContent = t('nav.next');        next.onclick = onbNext; }
      // Step 1: disable next until at least 1 folder has movie/tv type
      // Step 2: disable next until Jellyseerr test passes
      if (_onbStep === 1) { next.disabled = true; _onbValidateStep1(); }
      else if (_onbStep === 2) { next.disabled = true; }
      else next.disabled = false;
    }
    if (skip) {
      skip.textContent = t('nav.skip');
      skip.style.display = _onbStep === 2 ? '' : 'none';
      if (_onbStep === 2) _updateOnbSkipStyle(skip);
    }
  }

  function _onbStep0HTML() {
    const btnBase = 'padding:7px 18px;border-radius:8px;border:1px solid var(--border);cursor:pointer;font-size:13px;font-weight:600;font-family:\'Syne\',sans-serif;transition:all .15s';
    return '<div style="text-align:center;padding:20px 0 10px">'
      + '<div style="font-size:48px;margin-bottom:16px">🎬</div>'
      // Language selector
      + '<div style="display:flex;gap:10px;justify-content:center;margin-bottom:24px">'
        + '<button id="onbLangFr" onclick="selectOnbLang(\'fr\')" style="'+btnBase+';background:var(--accent);border-color:var(--accent);color:#fff">🇫🇷 Français</button>'
        + '<button id="onbLangEn" onclick="selectOnbLang(\'en\')" style="'+btnBase+';background:var(--surface);color:var(--muted)">🇬🇧 English</button>'
      + '</div>'
      // Auto-toggling content
      + '<div id="onbWelcomeTitle" style="font-family:\'Syne\',sans-serif;font-weight:800;font-size:22px;margin-bottom:10px">Bienvenue dans MyMediaLibrary</div>'
      + '<div id="onbWelcomeDesc" style="font-size:13px;color:var(--muted);max-width:420px;margin:0 auto 28px;line-height:1.7;text-align:left">'
      + 'Visualisez et explorez votre bibliothèque de films et séries en un coup d\'œil.'
      + '</div>'
      + '<button id="onbCommencerBtn" onclick="onbNext()" disabled style="padding:10px 28px;border-radius:10px;background:var(--accent);color:#fff;border:none;cursor:not-allowed;font-size:14px;font-weight:600;opacity:.35;transition:opacity .2s">'
        + '<span id="onbWelcomeStart">Commencer →</span>'
      + '</button>'
      + '</div>';
  }

  function _onbStep1HTML() {
    const folders = appConfig.folders || [];
    let html = '<div style="margin-bottom:16px">'
      + '<div style="font-family:\'Syne\',sans-serif;font-weight:700;font-size:18px;margin-bottom:4px">'+t('onboarding.step_folders_title')+'</div>'
      + '<div style="font-size:13px;color:var(--muted)">'+t('onboarding.step_folders_desc')+'</div>'
      + '</div>';
    if (!folders.length) {
      return html + '<div style="color:var(--muted);font-size:13px;text-align:center;padding:32px 0">'+t('onboarding.no_folders')+'</div>';
    }
    const unconfigured = folders.filter(f => !f.missing && !(f._onbType || f.type)).length;
    if (unconfigured > 0) {
      html += '<div style="font-size:12px;color:#f7b731;margin-bottom:10px">'
        + '⚠ ' + t('onboarding.unconfigured', {n: unconfigured, s: unconfigured>1?'s':''}) + '</div>';
    }
    html += '<div style="display:flex;flex-direction:column;gap:6px;max-height:280px;overflow-y:auto;padding-right:2px">';
    folders.forEach((f, idx) => {
      const isMissing = !!f.missing;
      const cur = f._onbType !== undefined ? f._onbType : (f.type || '');
      html += '<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:8px;border:1px solid var(--border);'+(isMissing?'opacity:.45':'')+'">'
        + '<span style="font-family:monospace;font-size:12px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+escH(f.name)+'">'+escH(f.name)+'</span>'
        + (isMissing
          ? '<span style="font-size:11px;color:#f97316">'+t('onboarding.folder_missing')+'</span>'
          : '<select class="'+(cur?'has-value':'')+'" style="padding:4px 8px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:12px" onchange="_onbFolderChange('+idx+',this.value);this.classList.toggle(\'has-value\',!!this.value)">'
            + '<option value="">'+t('onboarding.folder_choose')+'</option>'
            + '<option value="movie"'+(cur==='movie'?' selected':'')+'>'+t('onboarding.folder_movie')+'</option>'
            + '<option value="tv"'+(cur==='tv'?' selected':'')+'>'+t('onboarding.folder_tv')+'</option>'
            + '<option value="ignore"'+(cur==='ignore'?' selected':'')+'>'+t('onboarding.folder_ignore')+'</option>'
            + '</select>')
        + '</div>';
    });
    html += '</div>';
    return html;
  }

  function _onbValidateStep1() {
    const next = document.getElementById('onbNextBtn');
    if (!next) return;
    const hasMedia = (appConfig.folders || []).some(f =>
      !f.missing && ['movie', 'tv'].includes(f._onbType !== undefined ? f._onbType : (f.type || ''))
    );
    next.disabled = !hasMedia;
  }

  function _onbFolderChange(idx, val) {
    if (appConfig.folders[idx]) {
      appConfig.folders[idx]._onbType = val;
      if (val && val !== 'ignore') appConfig.folders[idx].visible = true;
    }
    _onbValidateStep1();
  }

  function _captureOnbJsr() {
    const enabled = document.getElementById('onbJsrEnabled')?.checked ?? _onbJsr.enabled;
    const url     = document.getElementById('onbJsrUrl')?.value ?? _onbJsr.url;
    const key     = document.getElementById('onbJsrKey')?.value ?? _onbJsr.key;
    _onbJsr = { enabled, url, key };
  }

  function _updateOnbSkipStyle(btn) {
    if (!btn) return;
    const enabled = document.getElementById('onbJsrEnabled')?.checked ?? _onbJsr.enabled;
    if (enabled) {
      // Jellyseerr on → Skip grayed (but clickable)
      btn.style.background  = 'transparent';
      btn.style.borderColor = 'var(--border)';
      btn.style.color       = 'var(--muted)';
    } else {
      // Jellyseerr off → Skip highlighted (violet)
      btn.style.background  = 'var(--accent)';
      btn.style.borderColor = 'var(--accent)';
      btn.style.color       = '#fff';
    }
  }

  function _onbJsrToggle() {
    const enabled = document.getElementById('onbJsrEnabled')?.checked;
    ['onbJsrUrl', 'onbJsrKey', 'onbJsrTestBtn'].forEach(id => {
      const el = document.getElementById(id);
      if (el) { el.disabled = !enabled; el.style.opacity = enabled ? '' : '.45'; }
    });
    // Update skip button style + reset next button (test no longer valid)
    _updateOnbSkipStyle(document.getElementById('onbSkipBtn'));
    const next = document.getElementById('onbNextBtn');
    if (next) next.disabled = true;
    // Clear previous test result
    const res = document.getElementById('onbJsrTestResult');
    if (res) { res.textContent = ''; }
  }

  function _onbStep2HTML() {
    const dis = _onbJsr.enabled ? '' : ' disabled';
    const disOp = _onbJsr.enabled ? '' : ';opacity:.45';
    return '<div style="margin-bottom:16px">'
      + '<div style="font-family:\'Syne\',sans-serif;font-weight:700;font-size:18px;margin-bottom:4px">'+t('onboarding.step_jsr_title')+'</div>'
      + '<div style="font-size:13px;color:var(--muted)">'+t('onboarding.step_jsr_desc')+'</div>'
      + '</div>'
      + '<div style="display:flex;flex-direction:column;gap:14px">'
      + '<div class="settings-row"><label class="settings-label">'+t('onboarding.jsr_enable')+'</label>'
        + '<label class="toggle-switch"><input type="checkbox" id="onbJsrEnabled"'+(_onbJsr.enabled?' checked':'')+' onchange="_onbJsrToggle()"/><span class="toggle-switch-slider"></span></label></div>'
      + '<div class="settings-row"><label class="settings-label">'+t('onboarding.jsr_url')+'</label>'
        + '<input type="url" id="onbJsrUrl" class="settings-input" placeholder="https://jellyseerr.domain.com" value="'+escH(_onbJsr.url)+'"'+dis+' style="'+disOp+'"/></div>'
      + '<div class="settings-row"><label class="settings-label">'+t('onboarding.jsr_apikey')+'</label>'
        + '<input type="password" id="onbJsrKey" class="settings-input" placeholder="API key" value="'+escH(_onbJsr.key)+'"'+dis+' style="'+disOp+'"/></div>'
      + '<div class="settings-row">'
        + '<button class="scan-btn" id="onbJsrTestBtn" onclick="onbTestJsr()"'+dis+' style="padding:5px 14px;font-size:12px'+disOp+'">'+t('onboarding.jsr_test')+'</button>'
        + '<span id="onbJsrTestResult" style="font-size:12px;margin-left:10px;color:var(--muted)"></span>'
      + '</div>'
      + '</div>';
  }

  function _onbStep3HTML() {
    const folders = appConfig.folders || [];
    const nMovies  = folders.filter(f => !f.missing && (f._onbType||f.type)==='movie').length;
    const nTv      = folders.filter(f => !f.missing && (f._onbType||f.type)==='tv').length;
    const nIgnored = folders.filter(f => !f.missing && ((f._onbType||f.type)==='ignore' || !(f._onbType||f.type))).length;
    const rows = [];
    if (nMovies)  rows.push('<b>'+nMovies+'</b> '+t(nMovies>1?'onboarding.summary_movies_pl':'onboarding.summary_movies',{n:nMovies}).replace(nMovies+' ',''));
    if (nTv)      rows.push('<b>'+nTv+'</b> '+t(nTv>1?'onboarding.summary_tv_pl':'onboarding.summary_tv',{n:nTv}).replace(nTv+' ',''));
    if (nIgnored) rows.push('<b>'+nIgnored+'</b> '+t(nIgnored>1?'onboarding.summary_ignored_pl':'onboarding.summary_ignored',{n:nIgnored}).replace(nIgnored+' ',''));
    return '<div style="margin-bottom:16px">'
      + '<div style="font-family:\'Syne\',sans-serif;font-weight:700;font-size:18px;margin-bottom:4px">'+t('onboarding.step_scan_title')+'</div>'
      + '<div style="font-size:13px;color:var(--muted)">'+t('onboarding.step_scan_desc')+'</div>'
      + '</div>'
      + '<div style="background:var(--bg);border-radius:10px;padding:16px 20px;font-size:13px;line-height:2">'
      + '<div>📁 '+(rows.length ? rows.join(', ') : '<span style="color:var(--muted)">'+t('onboarding.no_configured')+'</span>')+'</div>'
      + '<div>🔍 Jellyseerr : '+(_onbJsr.enabled&&_onbJsr.url ? '<span style="color:#34d399">'+t('onboarding.jsr_active')+' — '+escH(_onbJsr.url)+'</span>' : '<span style="color:var(--muted)">'+t('onboarding.jsr_inactive')+'</span>')+'</div>'
      + '</div>';
  }

  async function onbTestJsr() {
    const btn = document.getElementById('onbJsrTestBtn');
    const res = document.getElementById('onbJsrTestResult');
    if (!res) return;
    _captureOnbJsr();
    await saveConfig({ jellyseerr: { enabled: _onbJsr.enabled, url: _onbJsr.url, ...(_onbJsr.key ? {apikey: _onbJsr.key} : {}) } });
    res.textContent = '…'; res.style.color = 'var(--muted)';
    if (btn) btn.disabled = true;
    try {
      const r = await fetch('/api/jellyseerr/test');
      const d = await r.json();
      if (d.ok) {
        res.textContent = '✓ ' + t('onboarding.jsr_ok'); res.style.color = '#34d399';
        // Enable Next button — test passed
        const next = document.getElementById('onbNextBtn');
        if (next) next.disabled = false;
      } else {
        res.textContent = '✗ ' + (d.error || t('onboarding.jsr_fail')); res.style.color = '#f97316';
      }
    } catch(e) { res.textContent = '✗ ' + t('onboarding.jsr_fail'); res.style.color = '#f97316'; }
    finally { if (btn) btn.disabled = false; }
  }

  function onbNext() {
    if (_onbStep === 0) { clearInterval(_langTimer); _langTimer = null; }
    if (_onbStep === 2) _captureOnbJsr();
    if (_onbStep < 3) { _onbStep++; _onbRender(); }
  }

  function onbPrev() {
    if (_onbStep >= 1) { _onbStep--; _onbRender(); }
  }

  function onbSkip() {
    // Only shown on step 2 — Skip means disable Jellyseerr
    if (_onbStep === 2) {
      _captureOnbJsr();
      _onbJsr.enabled = false;
      _onbStep = 3; _onbRender();
    }
  }

  async function onbLaunchScan() {
    const btn = document.getElementById('onbNextBtn');
    if (btn) { btn.disabled = true; btn.textContent = t('onboarding.saving'); }

    // Build folder list: apply _onbType overrides, set visible accordingly
    const folders = (appConfig.folders || []).map(f => {
      const t = f._onbType !== undefined ? (f._onbType || null) : (f.type || null);
      const type = (t === 'ignore') ? null : t;
      const visible = !!type;
      const clean = Object.fromEntries(Object.entries(f).filter(([k]) => k !== '_onbType'));
      return {...clean, type, visible};
    });

    const partial = {
      folders,
      enable_movies: folders.some(f => f.type === 'movie'),
      enable_series: folders.some(f => f.type === 'tv'),
      jellyseerr: { enabled: _onbJsr.enabled, url: _onbJsr.url, ...(_onbJsr.key ? {apikey: _onbJsr.key} : {}) },
      system: { language: _onbLang },
      ui: { theme: _onbTheme },
    };

    try {
      await saveConfig(partial);
    } catch(e) {
      alert(t('settings.save_error', {msg: e.message}));
      if (btn) { btn.disabled = false; btn.textContent = t('nav.launch_scan'); }
      return;
    }

    const mode = (_onbJsr.enabled && _onbJsr.url) ? 'full' : 'quick';
    try {
      await fetch('/api/scan/start', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({mode})});
    } catch(e) {}

    // Switch to live scan log view
    const panel = document.getElementById('onbPanel');
    if (panel) panel.innerHTML = '<div style="padding:8px 0">'
      + '<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">'
        + '<div class="spinner" style="width:18px;height:18px;border-width:2px"></div>'
        + '<span style="font-family:\'Syne\',sans-serif;font-weight:700;font-size:16px">'+t('onboarding.scanning')+'</span>'
      + '</div>'
      + '<div id="onbLogBox" style="background:var(--bg);border-radius:8px;padding:10px 12px;font-size:11px;font-family:monospace;color:var(--muted);max-height:220px;overflow-y:auto;line-height:1.6;word-break:break-all"></div>'
      + '<div id="onbDoneBtn" style="display:none;margin-top:16px;text-align:center">'
        + '<button onclick="document.getElementById(\'onboardingOverlay\').style.display=\'none\';loadLibrary();" '
          + 'style="padding:10px 28px;border-radius:10px;background:var(--accent);color:#fff;border:none;cursor:pointer;font-size:14px;font-weight:600">'+t('onboarding.open_library')+'</button>'
      + '</div>'
      + '</div>';
    const stepsEl = document.getElementById('onbSteps');
    if (stepsEl) stepsEl.innerHTML = '';
    ['onbSkipBtn','onbPrevBtn','onbNextBtn'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });
    _onbLogSeen = 0;
    _onbPollScan();
  }

  async function _onbPollScan() {
    try {
      const r = await fetch('/api/scan/status');
      const d = await r.json();
      const logBox = document.getElementById('onbLogBox');
      if (logBox) {
        const lines = (d.log || []).slice(_onbLogSeen);
        if (lines.length) {
          _onbLogSeen += lines.length;
          lines.forEach(line => {
            const div = document.createElement('div');
            div.textContent = line;
            logBox.appendChild(div);
          });
          logBox.scrollTop = logBox.scrollHeight;
        }
      }
      if (d.status === 'done' || d.status === 'error') {
        const spinnerRow = document.querySelector('#onbPanel .spinner')?.parentElement;
        if (spinnerRow) spinnerRow.style.display = 'none';
        const doneBtn = document.getElementById('onbDoneBtn');
        if (doneBtn) doneBtn.style.display = '';
        return;
      }
    } catch(e) {}
    setTimeout(_onbPollScan, 1500);
  }

  function initApp() {
    loadLibrary();
  }

  checkAuth();

(function(){
      const btn=document.getElementById('backToTop');
      const _mc=document.querySelector('.main-content');
      const _mbtn=document.getElementById('mobileBackToTop');
      if(_mc)_mc.addEventListener('scroll',function(){
        btn.style.opacity=_mc.scrollTop>300?'1':'0';
        if(_mbtn) _mbtn.style.opacity=_mc.scrollTop>300?'1':'0';
      });
    })();


// Start
document.body.classList.add('layout-sidebar');
