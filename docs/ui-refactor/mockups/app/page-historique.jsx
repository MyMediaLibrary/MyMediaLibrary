// MyMediaLibrary — Bibliothèque

const MEDIA_TITLES = [
  ["[REC]", 2007, "Movies", "720p", 60, "Netflix"],
  ["[REC]²", 2009, "Movies", "720p", 60, "Netflix"],
  ["[REC]³ : Génesis", 2012, "Movies", "720p", 60, null],
  ["[REC]⁴ : Apocalypse", 2014, "Movies", "720p", 60, null],
  ["# Pire Soirée", 2017, "Movies", "1080p", 75, "Netflix"],
  ["#No_Filter", 2022, "Movies", "1080p", 66, null],
  ["10 Cloverfield Lane", 2016, "Movies", "4K", 87, "Netflix"],
  ["10 jours encore sans maman", 2023, "Movies", "1080p", 68, "Disney+"],
  ["10 jours sans maman", 2020, "Movies", "1080p", 70, null],
  ["10 Minutes Gone", 2019, "Movies", "1080p", 72, null],
  ["100 Millions !", 2025, "Movies", "1080p", 68, null],
  ["100% bio", 2020, "Movies", "1080p", 56, null],
  ["100% loup", 2020, "Animation", "1080p", 57, "Disney+"],
  ["11.22.63", 2016, "Tv", "1080p", 60, null],
  ["11.6", 2013, "Movies", "1080p", 70, null],
  ["12 heures", 2025, "Movies", "1080p", 75, "Netflix"],
  ["12 Monkeys", 2015, "Tv", "1080p", 60, null],
  ["127 Heures", 2010, "Movies", "1080p", 75, null],
  ["13", 2010, "Movies", "720p", 57, null],
  ["13 Exorcismes", 2022, "Movies", "1080p", 61, null],
  ["13 Jeux de mort", 2006, "Movies", "1080p", 72, null],
  ["13 Jours, 13 Nuits", 2025, "Movies", "1080p", 68, null],
  ["13 Minutes", 2021, "Movies", "1080p", 75, null],
  ["14 Jours pour aller mieux", 2024, "Movies", "1080p", 67, null],
  ["16 blocs", 2006, "Movies", "1080p", 75, "Netflix"],
  ["1899", 2022, "Tv", "1080p", 66, "Netflix"],
  ["1917", 2019, "Movies", "1080p", 72, null],
  ["1992 (2024)", 2024, "Tv", "1080p", 66, null],
  ["1BR : The Apartment", 2019, "Movies", "1080p", 72, null],
  ["2 Fast 2 Furious", 2003, "Movies", "4K", 90, null],
  ["20 Ans d'écart", 2013, "Movies", "1080p", 70, null],
  ["2012", 2009, "Movies", "1080p", 75, null],
  ["2036 Origine inconnue", 2018, "Movies", "1080p", 71, null],
  ["2067", 2020, "Movies", "1080p", 73, null],
  ["22 minutes", 2014, "Movies", "1080p", 70, null],
  ["24H Limit", 2017, "Movies", "1080p", 75, null],
];

function PageBibliotheque({ navigate, filters, filterCount, resetFilters }) {
  const ALL_COLUMNS = [
    { id: "title",    label: "Titre",       always: true },
    { id: "type",     label: "Type" },
    { id: "year",     label: "Année" },
    { id: "res",      label: "Résolution" },
    { id: "codec",    label: "Codec" },
    { id: "audio",    label: "Audio" },
    { id: "langue",   label: "Langue" },
    { id: "size",     label: "Taille" },
    { id: "score",    label: "Score" },
    { id: "provider", label: "Provider" },
    { id: "added",    label: "Ajouté le" },
  ];
  const [view, setView] = React.useState("grid");
  const [sort, setSort] = React.useState("title");
  const [cols, setCols] = React.useState(["title","type","year","res","score","provider"]);
  const [colMenu, setColMenu] = React.useState(false);

  const toggleCol = (id) => {
    setCols(arr => arr.includes(id) ? arr.filter(c => c !== id) : [...arr, id]);
  };

  // Map type folder labels: Movies → Films, Tv → Séries, Animation → Animation
  const typeToDossier = (t) => t === "Movies" ? "Movies" : t === "Tv" ? "Tv" : t === "Animation" ? "Animation" : t;
  const codecFor = (res, year) => res === "4K" ? "h265" : (year > 2018 ? "h265" : "h264");
  const audioFor = (type) => type === "Tv" ? "EAC3" : "AC3";
  const channelFor = (res) => res === "4K" ? "5.1" : (res === "1080p" ? "5.1" : "2.0");
  const langFor = (provider) => provider ? "Français" : "Anglais";

  const filtered = MEDIA_TITLES.filter(m => {
    const [title, year, type, res, score, provider] = m;
    // Disponibilité — all items are "disponibles" in mock; absents would be empty
    if (filters?.disponibilite === "absents") return false;
    // Type
    if (filters?.type === "films" && type !== "Movies" && type !== "Animation") return false;
    if (filters?.type === "series" && type !== "Tv") return false;
    // Dossier
    if (filters && !matchMulti(filters.dossier, typeToDossier(type))) return false;
    // Streaming
    if (filters && !matchMulti(filters.streaming, provider || "Aucun")) return false;
    // Langue audio (synthetic mapping)
    if (filters && !matchMulti(filters.langue, langFor(provider))) return false;
    // Score
    if (filters && !matchScore(filters, score)) return false;
    // Resolution
    if (filters && !matchMulti(filters.resolution, res)) return false;
    // Codec video
    if (filters && !matchMulti(filters.codecVideo, codecFor(res, year))) return false;
    // Codec audio
    if (filters && !matchMulti(filters.codecAudio, audioFor(type))) return false;
    // Channel audio
    if (filters && !matchMulti(filters.channelAudio, channelFor(res))) return false;
    return true;
  });

  return (
    <div data-screen-label="Bibliotheque">
      <div className="page-head">
        <div>
          <h2>Bibliothèque</h2>
          <div className="page-sub">{filtered.length.toLocaleString("fr-FR")} médias affichés sur 3 322</div>
        </div>
      </div>

      <div className="lib-toolbar">
        {filterCount > 0 && (
          <div className="lib-filters">
            <div className="filter-chip active" style={{cursor: "default"}}>
              <Icons.filter size={13}/>
              {filterCount} filtre{filterCount > 1 ? "s" : ""} actif{filterCount > 1 ? "s" : ""}
            </div>
            <div className="filter-chip" onClick={resetFilters}>
              <Icons.x size={13}/> Réinitialiser
            </div>
          </div>
        )}

        <div style={{flex: 1}}/>

        <select className="field sm" value={sort} onChange={e => setSort(e.target.value)} style={{minWidth: 140}}>
          <option value="title">Titre A→Z</option>
          <option value="year">Année</option>
          <option value="score">Score</option>
          <option value="size">Taille</option>
        </select>

        {view === "list" && (
          <div style={{position: "relative"}}>
            <button className="btn small" onClick={() => setColMenu(v => !v)}>
              <Icons.filter size={13}/> Colonnes ({cols.length})
              <Icons.chevronDown size={11}/>
            </button>
            {colMenu && <ColumnsMenu columns={ALL_COLUMNS} active={cols} onToggle={toggleCol} onClose={() => setColMenu(false)}/>}
          </div>
        )}

        <div className="btn-group">
          <div className={`seg ${view === "grid" ? "active" : ""}`} onClick={() => setView("grid")}>
            <Icons.grid size={13} style={{verticalAlign: "middle"}}/>
          </div>
          <div className={`seg ${view === "list" ? "active" : ""}`} onClick={() => setView("list")}>
            <Icons.list size={13} style={{verticalAlign: "middle"}}/>
          </div>
        </div>

        <button className="btn small"><Icons.download size={13}/> Export CSV</button>
      </div>

      {view === "grid" ? (
        <div className="media-grid">
          {filtered.map((m, i) => (
            <PosterCard key={i} media={{
              title: m[0], year: m[1], type: m[2], res: m[3], score: m[4], provider: m[5]
            }}/>
          ))}
        </div>
      ) : (
        <div className="card tight" style={{padding: 0, overflow: "hidden"}}>
          <table className="tbl">
            <thead><tr>
              {ALL_COLUMNS.filter(c => cols.includes(c.id)).map(c => <th key={c.id}>{c.label}</th>)}
            </tr></thead>
            <tbody>
              {filtered.map((m, i) => {
                const media = { title: m[0], year: m[1], type: m[2], res: m[3], score: m[4], provider: m[5] };
                // synthetic extra fields
                const codec  = m[3] === "4K" ? "H.265" : "H.264";
                const audio  = m[2] === "Tv" ? "Dolby Digital Plus" : "Dolby Digital";
                const langue = m[5] ? "MULTI" : "VF";
                const size   = `${(2 + ((i*173) % 28) + (m[3]==="4K"?20:0)).toFixed(1)} GB`;
                const added  = `2024-${String(1 + (i % 12)).padStart(2, "0")}-${String(1 + (i % 27)).padStart(2, "0")}`;
                const cells = {
                  title:    <span style={{fontWeight: 500}}>{media.title}</span>,
                  type:     <span className="pill">{media.type}</span>,
                  year:     <span className="mono muted">{media.year}</span>,
                  res:      <span className="mono">{media.res}</span>,
                  codec:    <span className="mono muted">{codec}</span>,
                  audio:    <span className="muted" style={{fontSize: 12.5}}>{audio}</span>,
                  langue:   <span className="mono">{langue}</span>,
                  size:     <span className="mono">{size}</span>,
                  score:    <span className={`pill ${media.score >= 80 ? "ok" : media.score >= 60 ? "warn" : "danger"}`}>{media.score}</span>,
                  provider: <span className="muted">{media.provider || "—"}</span>,
                  added:    <span className="mono muted" style={{fontSize: 12}}>{added}</span>,
                };
                return (
                  <tr key={i}>
                    {ALL_COLUMNS.filter(c => cols.includes(c.id)).map(c => <td key={c.id}>{cells[c.id]}</td>)}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ColumnsMenu({ columns, active, onToggle, onClose }) {
  React.useEffect(() => {
    const close = (e) => { if (!e.target.closest(".cols-menu")) onClose(); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [onClose]);
  return (
    <div className="cols-menu" style={{
      position: "absolute", top: "calc(100% + 6px)", right: 0,
      width: 220, padding: 6,
      background: "var(--panel)",
      border: "1px solid var(--border)",
      borderRadius: 10,
      boxShadow: "var(--shadow-lg)",
      zIndex: 100,
    }}>
      <div className="muted" style={{padding: "6px 10px", fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em"}}>
        Colonnes affichées
      </div>
      {columns.map(c => {
        const checked = active.includes(c.id);
        const disabled = c.always;
        return (
          <div key={c.id} onClick={() => { if (!disabled) onToggle(c.id); }} style={{
            padding: "7px 10px", borderRadius: 6, cursor: disabled ? "not-allowed" : "pointer",
            fontSize: 13,
            display: "flex", alignItems: "center", gap: 10,
            color: disabled ? "var(--muted)" : "var(--text)",
            opacity: disabled ? 0.7 : 1,
          }}
          onMouseEnter={e => { if (!disabled) e.currentTarget.style.background = "var(--hover)"; }}
          onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
            <span style={{
              width: 16, height: 16, borderRadius: 4,
              border: `1.5px solid ${checked ? "var(--accent)" : "var(--border-strong)"}`,
              background: checked ? "var(--accent)" : "transparent",
              color: "var(--on-accent)",
              display: "grid", placeItems: "center", flex: "none",
            }}>{checked && <Icons.check size={11} sw={3}/>}</span>
            <span>{c.label}</span>
            {disabled && <span className="muted" style={{marginLeft: "auto", fontSize: 10.5}}>requis</span>}
          </div>
        );
      })}
    </div>
  );
}

Object.assign(window, { PageBibliotheque });
