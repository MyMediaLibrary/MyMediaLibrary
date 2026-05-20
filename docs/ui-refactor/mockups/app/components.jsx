// MyMediaLibrary — main app shell

const NAV = [
  { v: "accueil",   l: "Accueil",         icon: Icons.home },
  { v: "library",   l: "Bibliothèque",    icon: Icons.library },
  { v: "stats",     l: "Statistiques",    icon: Icons.stats },
  { v: "recos",     l: "Recommandations", icon: Icons.bulb },
  { v: "history",   l: "Historique des scans", icon: Icons.clock },
  { v: "settings",  l: "Paramètres",      icon: Icons.settings },
];

const DEFAULT_TWEAKS = /*EDITMODE-BEGIN*/{
  "theme": "dark",
  "accent": "#6ba4e8"
}/*EDITMODE-END*/;

function App() {
  const [tweaks, setTweak] = useTweaks(DEFAULT_TWEAKS);
  const [page, setPage] = React.useState("accueil");
  const [settingsSection, setSettingsSection] = React.useState("bibliotheque");
  const [scanning, setScanning] = React.useState(false);
  const [userMenu, setUserMenu] = React.useState(false);
  const [sidebarOpen, setSidebarOpen] = React.useState(false);
  const [filtersOpen, setFiltersOpen] = React.useState(() =>
    typeof window !== "undefined" ? window.innerWidth >= 768 : true
  );
  const { filters, patch: patchFilter, reset: resetFilters } = useFiltersState();
  const filtersAvailable = page === "library" || page === "stats" || page === "recos";
  const showFilters = filtersAvailable && filtersOpen;
  const filterCount = activeFilterCount(filters);

  const theme = tweaks.theme === "system"
    ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : tweaks.theme;

  React.useEffect(() => {
    document.documentElement.style.setProperty("--accent", tweaks.accent);
    document.body.className = `theme-${theme}`;
  }, [theme, tweaks.accent]);

  const navigate = (p, section) => {
    setPage(p);
    if (p === "settings" && section) setSettingsSection(section);
    // Auto-close drawers on mobile after navigation
    if (typeof window !== "undefined" && window.innerWidth <= 768) {
      setSidebarOpen(false);
      setFiltersOpen(false);
    }
  };

  const pageTitle = NAV.find(n => n.v === page)?.l || "Accueil";

  return (
    <div className={`app ${showFilters ? "has-filters" : ""} ${sidebarOpen ? "sidebar-open" : ""}`}>
      {/* Mobile backdrop */}
      {(sidebarOpen || showFilters) && (
        <div className="mobile-backdrop" onClick={() => { setSidebarOpen(false); setFiltersOpen(false); }}/>
      )}

      {/* Sidebar (icon-only / expandable) */}
      <aside className={`sidebar mini ${sidebarOpen ? "expanded" : ""}`}>
        <div className="brand mini">
          <div className="brand-mark">M</div>
          {sidebarOpen && (
            <div className="col" style={{minWidth: 0}}>
              <div className="brand-name">MyMediaLibrary</div>
            </div>
          )}
        </div>

        <div className="nav-section mini">
          {NAV.map(n => (
            <button key={n.v}
              className={`nav-item mini ${page === n.v ? "active" : ""}`}
              onClick={() => navigate(n.v)}
              data-tip={n.l}>
              <n.icon/>
              {sidebarOpen && <span className="nav-item-label">{n.l}</span>}
            </button>
          ))}
        </div>

        {filtersAvailable && (
          <div className="nav-section mini" style={{marginTop: 6, paddingTop: 10, borderTop: "1px solid var(--border)"}}>
            <button
              className={`nav-item mini filter-toggle ${filtersOpen ? "active" : ""}`}
              onClick={() => setFiltersOpen(o => !o)}
              data-tip={filtersOpen ? "Masquer les filtres" : "Afficher les filtres"}>
              <Icons.filter/>
              {sidebarOpen && <span className="nav-item-label">Filtres</span>}
              {filterCount > 0 && <span className="filter-toggle-badge">{filterCount}</span>}
            </button>
          </div>
        )}

        <div className="sidebar-foot mini">
          <button className={`nav-item mini scan-btn ${scanning ? "scanning" : ""}`}
            onClick={() => { setScanning(true); setTimeout(() => setScanning(false), 1800); }}
            data-tip={scanning ? "Scan en cours…" : "Lancer un scan · il y a 12 min"}>
            <Icons.scan/>
            {sidebarOpen && (
              <span className="nav-item-label">
                {scanning ? "Scan en cours…" : "Lancer un scan"}
                <span className="nav-item-sub">il y a 12 min</span>
              </span>
            )}
          </button>

          <button
            className="nav-item mini collapse-btn"
            onClick={() => setSidebarOpen(o => !o)}
            data-tip={sidebarOpen ? "Replier la sidebar" : "Déplier la sidebar"}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2"/>
              <line x1="9" y1="3" x2="9" y2="21"/>
              {sidebarOpen
                ? <polyline points="16 9 13 12 16 15"/>
                : <polyline points="14 9 17 12 14 15"/>}
            </svg>
            {sidebarOpen && <span className="nav-item-label">Replier</span>}
          </button>
        </div>
      </aside>

      {showFilters && <FiltersRail filters={filters} patch={patchFilter} reset={resetFilters}/>}

      {/* Main */}
      <main className="main">
        <header className="topbar">
          <button className="icon-btn topbar-burger"
            onClick={() => setSidebarOpen(o => !o)}
            title="Menu">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="3" y1="6" x2="21" y2="6"/>
              <line x1="3" y1="12" x2="21" y2="12"/>
              <line x1="3" y1="18" x2="21" y2="18"/>
            </svg>
          </button>
          <div className="col">
            <h1>{pageTitle}</h1>
          </div>
          <div style={{flex: 1}}/>
          <div className="search">
            <Icons.search size={14}/>
            <input placeholder="Rechercher un film, une série…"/>
            <span className="kbd">⌘K</span>
          </div>
          <button className="icon-btn topbar-search-btn" title="Rechercher">
            <Icons.search size={16}/>
          </button>
          {filtersAvailable && (
            <button className="icon-btn topbar-filter-btn"
              onClick={() => setFiltersOpen(o => !o)} title="Filtres">
              <Icons.filter size={16}/>
              {filterCount > 0 && <span className="filter-toggle-badge">{filterCount}</span>}
            </button>
          )}
          <button className="icon-btn" title="Basculer le thème"
            onClick={() => setTweak({ theme: theme === "dark" ? "light" : "dark" })}>
            {theme === "dark" ? <Icons.sun/> : <Icons.moon/>}
          </button>
          <div className="col" style={{position: "relative"}}>
            <div className="row gap-2 user-menu-trigger"
              onClick={() => setUserMenu(v => !v)}
              style={{padding: "4px 4px 4px 10px", borderRadius: 8, background: "var(--panel-2)", border: `1px solid ${userMenu ? "var(--accent)" : "var(--border)"}`, cursor: "pointer"}}>
              <span style={{fontSize: 12.5, color: "var(--text-2)", fontWeight: 500}}>admin</span>
              <div style={{width: 26, height: 26, borderRadius: "50%", background: "linear-gradient(135deg, var(--accent), color-mix(in oklch, var(--accent) 50%, #b56be8))", display: "grid", placeItems: "center", color: "var(--on-accent)", fontSize: 11, fontWeight: 700}}>A</div>
              <Icons.chevronDown size={13} style={{color: "var(--muted)", transform: userMenu ? "rotate(180deg)" : "rotate(0deg)", transition: "transform .15s"}}/>
            </div>
            {userMenu && <UserMenu onClose={() => setUserMenu(false)} onNavigate={(p) => { setUserMenu(false); navigate(p); }}/>}
          </div>
        </header>

        <div className="scroll">
          {page === "accueil"  && <PageAccueil navigate={navigate}/>}
          {page === "library"  && <PageBibliotheque navigate={navigate} filters={filters} filterCount={filterCount} resetFilters={resetFilters}/>}
          {page === "stats"    && <PageStatistiques navigate={navigate} filters={filters} filterCount={filterCount} resetFilters={resetFilters}/>}
          {page === "recos"    && <PageRecommandations navigate={navigate} filters={filters} filterCount={filterCount} resetFilters={resetFilters}/>}
          {page === "history"  && <PageHistorique navigate={navigate}/>}
          {page === "settings" && <PageParametres
              section={settingsSection} setSection={setSettingsSection}
              theme={tweaks.theme} setTheme={(t) => setTweak({ theme: t })}
              accent={tweaks.accent} setAccent={(a) => setTweak({ accent: a })}
              navigate={navigate}/>}
        </div>
      </main>

      <TweaksPanel title="Tweaks">
        <TweakSection title="Apparence">
          <TweakRadio label="Thème" value={tweaks.theme} onChange={(v) => setTweak({ theme: v })}
            options={[{ value: "light", label: "Clair" }, { value: "dark", label: "Sombre" }]}/>
          <TweakColor label="Accent" value={tweaks.accent} onChange={(v) => setTweak({ accent: v })}
            options={["#6ba4e8", "#7a7af0", "#4cc086", "#e8a44a", "#e87aa4", "#9c6bd9", "#4ec1c9", "#ed7a6b"]}/>
        </TweakSection>
        <TweakSection title="Navigation">
          <TweakSelect label="Aller à" value={page} onChange={setPage}
            options={NAV.map(n => ({ value: n.v, label: n.l }))}/>
        </TweakSection>
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);

function UserMenu({ onClose, onNavigate }) {
  React.useEffect(() => {
    const close = (e) => {
      if (!e.target.closest(".user-menu-pop") && !e.target.closest(".user-menu-trigger")) onClose();
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [onClose]);

  return (
    <div className="user-menu-pop" style={{
      position: "absolute", top: "calc(100% + 8px)", right: 0,
      minWidth: 240, padding: 6,
      background: "var(--panel)",
      border: "1px solid var(--border)",
      borderRadius: 10,
      boxShadow: "var(--shadow-lg)",
      zIndex: 100,
    }}>
      <div style={{padding: "10px 12px 8px"}}>
        <div style={{fontSize: 13, fontWeight: 600}}>admin</div>
        <div className="muted" style={{fontSize: 11.5}}>admin@magicgg.fr</div>
        <div className="muted" style={{fontSize: 11.5, marginTop: 4}}>
          <span className="health"><span className="dot"/> Session active</span>
        </div>
      </div>
      <div className="divider"/>
      <MenuItem icon={<Icons.user/>}     label="Mon compte"  onClick={() => onNavigate("settings", "compte")}/>
      <div className="divider" style={{margin: "4px 0"}}/>
      <MenuItem icon={<Icons.logout/>} label="Déconnexion" danger onClick={() => {
        onClose();
        alert("Déconnexion (mock)");
      }}/>
    </div>
  );
}

function MenuItem({ icon, label, onClick, danger, badge }) {
  return (
    <div onClick={onClick} style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "8px 12px",
      borderRadius: 7,
      cursor: "pointer",
      fontSize: 13,
      color: danger ? "var(--danger)" : "var(--text-2)",
      fontWeight: 500,
    }}
    onMouseEnter={e => e.currentTarget.style.background = "var(--hover)"}
    onMouseLeave={e => e.currentTarget.style.background = ""}>
      <span style={{display: "grid", placeItems: "center", width: 16, height: 16}}>{icon}</span>
      <span>{label}</span>
      {badge && <span style={{marginLeft: "auto", fontSize: 11, padding: "1px 7px", background: "var(--accent)", color: "var(--on-accent)", borderRadius: 999, fontWeight: 600}}>{badge}</span>}
    </div>
  );
}
