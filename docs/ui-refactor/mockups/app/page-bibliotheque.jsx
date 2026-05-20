// MyMediaLibrary — Accueil (dashboard)

function PageAccueil({ navigate }) {
  const d = window.MML_DATA;
  const totalSize = d.folders.reduce((s, f) => s + f.size, 0);

  return (
    <div data-screen-label="Accueil">
      {/* Top stat row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 20 }}>
        <Stat
          label="Éléments"
          value={d.totals.elements.toLocaleString("fr-FR")}
          foot={<><Icons.trendUp size={12}/> +12 cette semaine</>}
          icon={<Icons.film/>}
          accent
        />
        <Stat
          label="Fichiers"
          value={d.totals.files.toLocaleString("fr-FR")}
          foot={<>{d.totals.folders} dossiers actifs</>}
          icon={<Icons.file/>}
        />
        <Stat
          label="Stockage"
          value={`${d.totals.diskTB.toFixed(1)} TB`}
          foot={<><Icons.warn size={12} style={{color: "var(--warn)"}}/> 99,2% utilisé</>}
          icon={<Icons.hardDrive/>}
        />
        <Stat
          label="Score moyen"
          value="68,5"
          icon={<Icons.award/>}
        />
      </div>

      {/* Aligned 3-col grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 20 }}>
        <div className="card">
          <div className="card-head">
            <div className="card-title">Croissance mensuelle</div>
            <span className="pill ok"><Icons.trendUp size={11}/> +5,4%</span>
          </div>
          <div className="row" style={{justifyContent: "space-between", alignItems: "baseline"}}>
            <div className="mono" style={{fontSize: 30, fontWeight: 600, letterSpacing: "-0.02em"}}>+1,7 TB</div>
            <span className="muted" style={{fontSize: 12}}>moy. 6 mois</span>
          </div>
          <div className="divider" style={{margin: "14px 0 12px"}}/>
          <div className="col gap-2">
            <KV2 k="Médias ajoutés / mois"     v="47"/>
            <KV2 k="Médias supprimés / mois"   v="12"/>
            <KV2 k="Taille moyenne d'un média" v="35,6 GB"/>
            <KV2 k="Score moyen — nouveaux"    v="74,2"/>
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <div className="card-title">Activité récente</div>
            <button className="btn ghost small">Tout voir</button>
          </div>
          <div>
            {d.activity.slice(0, 4).map((a, i) => {
              const I = Icons[a.icon] || Icons.bell;
              return (
                <div className="activity-row" key={i}>
                  <div className="activity-dot"><I/></div>
                  <div className="activity-text">
                    <div>{a.text}</div>
                    <div className="at-meta">{a.meta} · {a.t}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <div className="card-title-lg">Recommandations</div>
            <span className="pill accent">{d.recos.total.toLocaleString("fr-FR")}</span>
          </div>

          <div style={{display: "flex", flexDirection: "column", gap: 10}}>
            {[
              { k: "high",    label: "Priorité haute",     value: d.recos.high,    color: "var(--danger)" },
              { k: "quality", label: "Qualité technique",  value: d.recos.quality, color: "var(--chart-2)" },
              { k: "space",   label: "Gain de place",      value: d.recos.space,   color: "var(--warn)" },
              { k: "langues", label: "Langues manquantes", value: d.recos.langues, color: "var(--chart-4)" },
            ].map(r => (
              <div key={r.k} className="row gap-3" style={{justifyContent: "space-between", padding: "6px 0"}}>
                <div className="row gap-2">
                  <span style={{width: 6, height: 22, borderRadius: 3, background: r.color}}/>
                  <span style={{fontSize: 13, color: "var(--text-2)"}}>{r.label}</span>
                </div>
                <span className="mono" style={{fontSize: 14, fontWeight: 600}}>{r.value.toLocaleString("fr-FR")}</span>
              </div>
            ))}
          </div>

          <button className="btn" style={{width: "100%", justifyContent: "center", marginTop: 12}} onClick={() => navigate("recos")}>
            Tout voir <Icons.chevronRight size={13}/>
          </button>
        </div>

        <div className="card">
          <div className="card-head">
            <div className="card-title">Score de qualité</div>
            <span className="muted mono" style={{fontSize: 12}}>Moyen 68,5</span>
          </div>
          <BarList
            data={d.scoreBuckets}
            total={d.totals.elements}
            formatter={(v) => v.toLocaleString("fr-FR")}
          />
          <div className="divider" style={{margin: "14px 0 12px"}}/>
          <div className="row gap-3" style={{justifyContent: "space-between"}}>
            <div>
              <div style={{fontSize: 12, color: "var(--muted)"}}>Médias ≥ 80</div>
              <div className="mono" style={{fontSize: 18, fontWeight: 600, color: "var(--ok)"}}>319</div>
            </div>
            <div>
              <div style={{fontSize: 12, color: "var(--muted)"}}>Médias &lt; 40</div>
              <div className="mono" style={{fontSize: 18, fontWeight: 600, color: "var(--danger)"}}>27</div>
            </div>
            <div>
              <div style={{fontSize: 12, color: "var(--muted)"}}>Sans score</div>
              <div className="mono" style={{fontSize: 18, fontWeight: 600}}>0</div>
            </div>
          </div>
        </div>

        <DonutCard
          title="Composition"
          centerLabel="ÉLÉMENTS"
          centerValue={d.totals.elements.toLocaleString("fr-FR")}
          data={[
            { label: "Films", value: d.totals.movies, color: "var(--chart-1)" },
            { label: "Séries", value: d.totals.series, color: "var(--chart-3)" },
            { label: "Anime", value: d.totals.anime, color: "var(--chart-4)" },
          ]}
        />

        <DonutCard
          title="Médias par résolution"
          centerLabel="ENTRÉES"
          centerValue={d.resolutions.length}
          data={d.resolutions}
        />
      </div>

      {/* Derniers demandés (Seerr) */}
      <MediaCarousel
        title="Derniers demandés sur Seerr"
        subtitle="20 demandes les plus récentes"
        badge={<span className="pill accent"><Icons.sparkles size={11}/> Seerr</span>}
        items={SEERR_REQUESTS}
        onSeeAll={() => navigate("library")}
      />

      {/* Recently added */}
      <MediaCarousel
        title="Derniers médias ajoutés"
        subtitle="20 derniers médias détectés lors du scan"
        items={ADDED_MEDIA}
        onSeeAll={() => navigate("library")}
      />
    </div>
  );
}

function MediaCarousel({ title, subtitle, badge, items, onSeeAll }) {
  const scrollerRef = React.useRef(null);
  const scroll = (dir) => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollBy({ left: dir * (el.clientWidth * 0.8), behavior: "smooth" });
  };
  return (
    <div className="card" style={{marginBottom: 16}}>
      <div className="card-head">
        <div>
          <div className="row gap-2">
            <div className="card-title-lg">{title}</div>
            {badge}
          </div>
          <div className="muted" style={{fontSize: 12.5, marginTop: 2}}>{subtitle}</div>
        </div>
        <div className="row gap-1">
          <button className="icon-btn" onClick={() => scroll(-1)} title="Précédent">
            <Icon d="m15 6-6 6 6 6" size={16}/>
          </button>
          <button className="icon-btn" onClick={() => scroll(1)} title="Suivant">
            <Icons.chevronRight size={16}/>
          </button>
          {onSeeAll && <button className="btn ghost small" onClick={onSeeAll}>Tout voir</button>}
        </div>
      </div>
      <div ref={scrollerRef} className="mml-carousel" style={{
        display: "flex", gap: 14,
        overflowX: "auto",
        scrollSnapType: "x mandatory",
        paddingBottom: 2,
      }}>
        {items.map((m, i) => (
          <div key={i} style={{flex: "0 0 145px", scrollSnapAlign: "start"}}>
            <PosterCard media={m}/>
          </div>
        ))}
      </div>
    </div>
  );
}

const SEERR_REQUESTS = [
  { title: "The Last of Us S2",        year: 2025, type: "Tv",     res: "4K",    score: null, provider: null, status: "approved" },
  { title: "Mickey 17",                year: 2025, type: "Movies", res: "1080p", score: null, provider: null, status: "pending" },
  { title: "Andor S2",                 year: 2025, type: "Tv",     res: "4K",    score: null, provider: "Disney+", status: "approved" },
  { title: "Mission: Impossible 8",    year: 2025, type: "Movies", res: "4K",    score: null, provider: null, status: "available" },
  { title: "Squid Game S3",            year: 2025, type: "Tv",     res: "4K",    score: null, provider: "Netflix", status: "approved" },
  { title: "Wednesday S2",             year: 2025, type: "Tv",     res: "4K",    score: null, provider: "Netflix", status: "pending" },
  { title: "Captain America 4",        year: 2025, type: "Movies", res: "1080p", score: null, provider: null, status: "available" },
  { title: "Fallout S2",               year: 2025, type: "Tv",     res: "4K",    score: null, provider: null, status: "approved" },
  { title: "Thunderbolts",             year: 2025, type: "Movies", res: "1080p", score: null, provider: null, status: "pending" },
  { title: "Demon Slayer Final",       year: 2025, type: "Anime",  res: "1080p", score: null, provider: null, status: "approved" },
  { title: "Stranger Things S5",       year: 2025, type: "Tv",     res: "4K",    score: null, provider: "Netflix", status: "pending" },
  { title: "Avatar 3",                 year: 2025, type: "Movies", res: "4K",    score: null, provider: null, status: "approved" },
  { title: "Severance S3",             year: 2026, type: "Tv",     res: "4K",    score: null, provider: "Apple TV", status: "pending" },
  { title: "Jurassic World Rebirth",   year: 2025, type: "Movies", res: "4K",    score: null, provider: null, status: "approved" },
  { title: "The Mandalorian S4",       year: 2026, type: "Tv",     res: "4K",    score: null, provider: "Disney+", status: "approved" },
  { title: "Tron: Ares",               year: 2025, type: "Movies", res: "4K",    score: null, provider: null, status: "available" },
  { title: "The Witcher S4",           year: 2025, type: "Tv",     res: "4K",    score: null, provider: "Netflix", status: "declined" },
  { title: "Frieren S2",               year: 2026, type: "Anime",  res: "1080p", score: null, provider: null, status: "pending" },
  { title: "Zootopia 2",               year: 2025, type: "Movies", res: "4K",    score: null, provider: "Disney+", status: "approved" },
  { title: "House of the Dragon S3",   year: 2026, type: "Tv",     res: "4K",    score: null, provider: null, status: "pending" },
];

const ADDED_MEDIA = [
  { title: "Dune: Part Two",   year: 2024, type: "Movies", res: "4K",    score: 92, provider: "Netflix"  },
  { title: "Shogun",           year: 2024, type: "Tv",     res: "4K",    score: 89, provider: "Disney+"  },
  { title: "The Bear",         year: 2024, type: "Tv",     res: "1080p", score: 84, provider: "Disney+"  },
  { title: "Frieren",          year: 2023, type: "Anime",  res: "1080p", score: 86, provider: null },
  { title: "Oppenheimer",      year: 2023, type: "Movies", res: "4K",    score: 90, provider: "Netflix"  },
  { title: "Severance",        year: 2025, type: "Tv",     res: "4K",    score: 88, provider: "Apple TV" },
  { title: "Spider-Verse",     year: 2023, type: "Movies", res: "1080p", score: 81, provider: "Netflix"  },
  { title: "The Boys",         year: 2024, type: "Tv",     res: "1080p", score: 75, provider: null },
  { title: "Furiosa",          year: 2024, type: "Movies", res: "4K",    score: 87, provider: null },
  { title: "Penguin",          year: 2024, type: "Tv",     res: "4K",    score: 88, provider: null },
  { title: "Anora",            year: 2024, type: "Movies", res: "1080p", score: 85, provider: null },
  { title: "Arcane S2",        year: 2024, type: "Tv",     res: "4K",    score: 93, provider: "Netflix" },
  { title: "The Substance",    year: 2024, type: "Movies", res: "4K",    score: 84, provider: null },
  { title: "Civil War",        year: 2024, type: "Movies", res: "4K",    score: 79, provider: null },
  { title: "Fallout",          year: 2024, type: "Tv",     res: "4K",    score: 86, provider: null },
  { title: "Hazbin Hotel",     year: 2024, type: "Anime",  res: "1080p", score: 78, provider: null },
  { title: "True Detective S4",year: 2024, type: "Tv",     res: "4K",    score: 81, provider: null },
  { title: "The Holdovers",    year: 2023, type: "Movies", res: "1080p", score: 82, provider: null },
  { title: "Mr. Robot",        year: 2019, type: "Tv",     res: "1080p", score: 88, provider: null },
  { title: "Past Lives",       year: 2023, type: "Movies", res: "1080p", score: 83, provider: null },
];

function QuickLink({ icon, title, desc, onClick, accent }) {
  return (
    <div className="card" onClick={onClick} style={{cursor: "pointer", transition: "border-color .12s"}}
         onMouseEnter={e => e.currentTarget.style.borderColor = "var(--border-strong)"}
         onMouseLeave={e => e.currentTarget.style.borderColor = ""}>
      <div className="row gap-3">
        <div style={{
          width: 40, height: 40, borderRadius: 10,
          background: accent ? "var(--accent)" : "var(--accent-soft)",
          color: accent ? "var(--on-accent)" : "var(--accent)",
          display: "grid", placeItems: "center", flex: "none"
        }}>{icon}</div>
        <div style={{flex: 1}}>
          <div style={{fontSize: 14, fontWeight: 600}}>{title}</div>
          <div className="muted" style={{fontSize: 12.5}}>{desc}</div>
        </div>
        <Icons.chevronRight size={16} style={{color: "var(--muted)"}}/>
      </div>
    </div>
  );
}

function KV2({ k, v }) {
  return (
    <div className="row gap-3" style={{justifyContent: "space-between", fontSize: 13}}>
      <span className="text-2">{k}</span>
      <span className="mono" style={{fontWeight: 500}}>{v}</span>
    </div>
  );
}

function PosterCard({ media }) {
  const scoreClass = media.score >= 80 ? "" : media.score >= 60 ? "warn" : "danger";
  const providerColor = {
    "Netflix": "#e50914", "Disney+": "#0a3a8c", "Apple TV": "#222"
  }[media.provider];
  const statusLabel = {
    approved: "Approuvé",
    pending: "En attente",
    available: "Dispo.",
    declined: "Refusé",
  }[media.status];
  const statusColor = {
    approved: "var(--ok)",
    pending: "var(--warn)",
    available: "var(--accent)",
    declined: "var(--danger)",
  }[media.status];
  return (
    <div className="media-card">
      <div className="media-poster">
        <div className="poster-art"/>
        {media.provider && (
          <div className="provider-chip" style={{background: providerColor}}>
            {media.provider === "Disney+" ? "D+" : media.provider === "Apple TV" ? "TV" : "N"}
          </div>
        )}
        <div className="poster-overlay">
          <span className="res-chip">{media.res}</span>
          {media.status ? (
            <span className="score-chip" style={{background: statusColor}}>{statusLabel}</span>
          ) : media.score !== null && media.score !== undefined ? (
            <span className={`score-chip ${scoreClass}`}>{media.score}</span>
          ) : null}
        </div>
      </div>
      <div className="media-meta">
        <div className="title">{media.title}</div>
        <div className="sub">
          <span>{media.year}</span>
          <span>·</span>
          <span>{media.type}</span>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { PageAccueil, PosterCard });
