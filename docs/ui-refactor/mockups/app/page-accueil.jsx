// MyMediaLibrary — Filters rail
// A contextual second sidebar with shared filters for Library / Stats / Recos pages.

const FILTER_OPTIONS = {
  dossier: [
    ["Tv", 990], ["Movies", 482], ["Anime", 118], ["Spectacles", 64],
    ["Animation", 33], ["Anime Movies", 32], ["Tv Not In Sonarr", 1],
  ],
  genre: [
    ["Drama", 1284], ["Comedy", 912], ["Action", 705], ["Thriller", 488],
    ["Documentary", 312], ["Sci-Fi", 287], ["Horror", 196], ["Romance", 174],
    ["Animation", 158], ["Crime", 142],
  ],
  streaming: [
    ["Netflix", 842], ["Prime Video", 612], ["Disney+", 421], ["Apple TV+", 188],
    ["Canal+", 156], ["Max", 92], ["Paramount+", 67], ["Aucun", 944],
  ],
  langue: [
    ["Français", 2812], ["Anglais", 2104], ["Japonais", 218], ["Espagnol", 187],
    ["Allemand", 124], ["Italien", 96], ["Coréen", 47],
  ],
  resolution: [
    ["1080p", 2345], ["720p", 615], ["4K", 351], ["SD", 14], ["Inconnu", 1],
  ],
  codecVideo: [
    ["h264", 2188], ["h265", 1003], ["HEVC", 412], ["VP9", 18], ["Inconnu", 5],
  ],
  codecAudio: [
    ["AAC", 1612], ["EAC3", 824], ["AC3", 612], ["DTS", 188], ["FLAC", 86], ["MP3", 12],
  ],
  channelAudio: [
    ["5.1", 1820], ["2.0", 1294], ["7.1", 184], ["Mono", 12],
  ],
};

const DEFAULT_FILTERS = {
  disponibilite: "disponibles",       // disponibles | absents | tous
  type:          "tous",              // tous | films | series
  dossier:       { mode: "include", selected: [] },
  genre:         { mode: "include", selected: [] },
  streaming:     { mode: "include", selected: [] },
  langue:        { mode: "include", selected: [] },
  scoreRange:    [0, 100],
  scoreIncludeNone: true,
  resolution:    { mode: "include", selected: [] },
  codecVideo:    { mode: "include", selected: [] },
  codecAudio:    { mode: "include", selected: [] },
  channelAudio:  { mode: "include", selected: [] },
};

function useFiltersState() {
  const [filters, setFilters] = React.useState(DEFAULT_FILTERS);
  const patch = React.useCallback((k, v) => setFilters(f => ({...f, [k]: v})), []);
  const reset = React.useCallback(() => setFilters(DEFAULT_FILTERS), []);
  return { filters, patch, reset };
}

function FiltersRail({ filters, patch, reset }) {
  const [techOpen, setTechOpen] = React.useState(false);

  return (
    <aside className="filters-rail">
      <div className="filters-scroll">
        <button className="filter-reset" onClick={reset}>
          <Icons.refresh size={12}/> Réinitialiser les filtres
        </button>

        <FilterGroup label="Disponibilité">
          <Seg value={filters.disponibilite} onChange={v => patch("disponibilite", v)}
            options={[
              ["disponibles", "Disponibles"],
              ["absents",     "Absents"],
              ["tous",        "Tous"],
            ]}/>
        </FilterGroup>

        <FilterGroup label="Type">
          <Seg value={filters.type} onChange={v => patch("type", v)}
            options={[
              ["tous",   "Tous"],
              ["films",  "Films"],
              ["series", "Séries"],
            ]}/>
        </FilterGroup>

        <FilterGroup label="Par dossier">
          <MultiDropdown value={filters.dossier} onChange={v => patch("dossier", v)}
            options={FILTER_OPTIONS.dossier} title="Par dossier"/>
        </FilterGroup>

        <FilterGroup label="Genre">
          <MultiDropdown value={filters.genre} onChange={v => patch("genre", v)}
            options={FILTER_OPTIONS.genre} title="Genre"/>
        </FilterGroup>

        <FilterGroup label="Streaming (FR)">
          <MultiDropdown value={filters.streaming} onChange={v => patch("streaming", v)}
            options={FILTER_OPTIONS.streaming} title="Streaming (FR)"/>
        </FilterGroup>

        <FilterGroup label="Langue audio">
          <MultiDropdown value={filters.langue} onChange={v => patch("langue", v)}
            options={FILTER_OPTIONS.langue} title="Langue audio"/>
        </FilterGroup>

        <FilterGroup label="Score">
          <ScoreRange value={filters.scoreRange} onChange={v => patch("scoreRange", v)}/>
          <label className="filter-check" style={{marginTop: 10}}>
            <input type="checkbox" checked={filters.scoreIncludeNone}
              onChange={e => patch("scoreIncludeNone", e.target.checked)}/>
            <span>Inclure les éléments sans score</span>
          </label>
        </FilterGroup>

        <div className={`tech-block ${techOpen ? "open" : ""}`}>
          <button className="tech-head" onClick={() => setTechOpen(o => !o)}>
            <span>Qualité technique</span>
            <Icons.chevronDown size={13}
              style={{transform: techOpen ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform .15s"}}/>
          </button>
          {techOpen && (
            <div className="tech-body">
              <FilterGroup label="Résolution" tight>
                <MultiDropdown value={filters.resolution} onChange={v => patch("resolution", v)}
                  options={FILTER_OPTIONS.resolution} title="Résolution"/>
              </FilterGroup>
              <FilterGroup label="Codec vidéo" tight>
                <MultiDropdown value={filters.codecVideo} onChange={v => patch("codecVideo", v)}
                  options={FILTER_OPTIONS.codecVideo} title="Codec vidéo"/>
              </FilterGroup>
              <FilterGroup label="Codec audio" tight>
                <MultiDropdown value={filters.codecAudio} onChange={v => patch("codecAudio", v)}
                  options={FILTER_OPTIONS.codecAudio} title="Codec audio"/>
              </FilterGroup>
              <FilterGroup label="Channel audio" tight>
                <MultiDropdown value={filters.channelAudio} onChange={v => patch("channelAudio", v)}
                  options={FILTER_OPTIONS.channelAudio} title="Channel audio"/>
              </FilterGroup>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}

function FilterGroup({ label, children, tight }) {
  return (
    <div className={`filter-group ${tight ? "tight" : ""}`}>
      <div className="filter-label">{label}</div>
      {children}
    </div>
  );
}

function Seg({ value, onChange, options }) {
  return (
    <div className="filter-seg">
      {options.map(([v, l]) => (
        <button key={v} className={`seg-pill ${value === v ? "active" : ""}`} onClick={() => onChange(v)}>
          {l}
        </button>
      ))}
    </div>
  );
}

function MultiDropdown({ value, onChange, options, title }) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);

  React.useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const selected = value.selected || [];
  const mode = value.mode || "include";
  const summary = selected.length === 0
    ? "Tous"
    : selected.length === 1
      ? selected[0]
      : `${selected.length} sélectionné${selected.length > 1 ? "s" : ""}`;

  const allSelected = options.length > 0 && selected.length === options.length;

  const toggleOne = (label) => {
    const has = selected.includes(label);
    const next = has ? selected.filter(s => s !== label) : [...selected, label];
    onChange({ mode, selected: next });
  };
  const toggleAll = () => {
    onChange({ mode, selected: allSelected ? [] : options.map(o => o[0]) });
  };
  const toggleMode = () => {
    onChange({ mode: mode === "include" ? "exclude" : "include", selected });
  };

  return (
    <div className="md-wrap" ref={ref}>
      <button className={`md-trigger ${open ? "open" : ""} ${selected.length > 0 ? "filled" : ""}`}
        onClick={() => setOpen(o => !o)}>
        <span className={`md-value ${mode === "exclude" && selected.length > 0 ? "exc" : ""}`}>
          {mode === "exclude" && selected.length > 0 && <span className="md-mode-tag">Exclure</span>}
          {summary}
        </span>
        <Icons.chevronDown size={12}
          style={{transform: open ? "rotate(180deg)" : "rotate(0deg)", transition: "transform .15s", color: "var(--muted)"}}/>
      </button>
      {open && (
        <div className="md-pop">
          <div className="md-pop-head">
            <label className="filter-check md-all">
              <input type="checkbox" checked={allSelected} onChange={toggleAll}/>
              <span>Tout sélectionner</span>
            </label>
            <button className={`md-mode ${mode === "exclude" ? "exclude" : ""}`} onClick={toggleMode}>
              {mode === "include" ? "Inclure" : "Exclure"}
            </button>
          </div>
          <div className="md-pop-list">
            {options.map(([label, count]) => (
              <label key={label} className="filter-check md-item">
                <input type="checkbox" checked={selected.includes(label)} onChange={() => toggleOne(label)}/>
                <span className="md-item-label">{label}</span>
                <span className="md-item-count">({count.toLocaleString("fr-FR")})</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ScoreRange({ value, onChange }) {
  const [lo, hi] = value;
  const trackRef = React.useRef(null);

  const onDrag = (which) => (e) => {
    e.preventDefault();
    const track = trackRef.current;
    if (!track) return;
    const move = (ev) => {
      const r = track.getBoundingClientRect();
      const pct = Math.max(0, Math.min(100, Math.round(((ev.clientX - r.left) / r.width) * 100)));
      if (which === "lo") onChange([Math.min(pct, hi), hi]);
      else                onChange([lo, Math.max(pct, lo)]);
    };
    const up = () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  };

  return (
    <div className="score-range">
      <div className="sr-track" ref={trackRef}>
        <div className="sr-grad"/>
        <div className="sr-mask" style={{left: 0, width: `${lo}%`}}/>
        <div className="sr-mask" style={{right: 0, width: `${100 - hi}%`}}/>
        <div className="sr-thumb" style={{left: `${lo}%`}} onMouseDown={onDrag("lo")}/>
        <div className="sr-thumb" style={{left: `${hi}%`}} onMouseDown={onDrag("hi")}/>
      </div>
      <div className="sr-readout mono">{lo}–{hi}</div>
    </div>
  );
}

Object.assign(window, { FiltersRail, useFiltersState, DEFAULT_FILTERS, matchMulti, matchScore, activeFilterCount });

// ----------- match helpers -------------
function matchMulti(filter, value) {
  if (!filter || !filter.selected || filter.selected.length === 0) return true;
  const included = filter.selected.includes(value);
  return filter.mode === "exclude" ? !included : included;
}

function matchScore(filters, score) {
  if (score == null) return !!filters.scoreIncludeNone;
  return score >= filters.scoreRange[0] && score <= filters.scoreRange[1];
}

function activeFilterCount(f) {
  let n = 0;
  if (f.disponibilite !== "disponibles") n++;
  if (f.type !== "tous") n++;
  for (const k of ["dossier","genre","streaming","langue","resolution","codecVideo","codecAudio","channelAudio"]) {
    if (f[k]?.selected?.length) n++;
  }
  if (f.scoreRange[0] !== 0 || f.scoreRange[1] !== 100) n++;
  if (!f.scoreIncludeNone) n++;
  return n;
}
