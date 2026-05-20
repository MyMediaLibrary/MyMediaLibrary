// MyMediaLibrary — Recommandations

function PageRecommandations({ navigate, filters, filterCount, resetFilters }) {
  const d = window.MML_DATA;
  const [prio, setPrio] = React.useState("all");
  const [recoType, setRecoType] = React.useState("all");

  const channelFromAudio = (audio) => audio?.includes("Plus") ? "5.1" : audio === "DTS" ? "7.1" : audio === "AAC" ? "2.0" : "5.1";
  const codecMap = (c) => c === "H.265" ? "h265" : c === "H.264" ? "h264" : c;
  const audioMap = (a) => a?.includes("Plus") ? "EAC3" : a === "Dolby Digital" ? "AC3" : a;
  const langMap = (l) => l === "VF" ? "Français" : l === "MULTI" ? "Français" : l === "VO" ? "Anglais" : l;

  const filtered = d.recoItems.filter(r => {
    if (prio !== "all" && r.prio !== prio) return false;
    if (recoType !== "all" && r.type !== recoType) return false;

    // Sidebar filters
    if (filters?.type === "films" && (r.title.includes("Saison") || r.type === "Séries")) return false;
    if (filters?.type === "series" && r.type !== "Séries") {/* don't strictly filter — recos cross types */}
    if (filters && !matchScore(filters, r.score)) return false;
    if (filters && !matchMulti(filters.resolution, r.res)) return false;
    if (filters && !matchMulti(filters.codecVideo, codecMap(r.codec))) return false;
    if (filters && !matchMulti(filters.codecAudio, audioMap(r.audio))) return false;
    if (filters && !matchMulti(filters.channelAudio, channelFromAudio(r.audio))) return false;
    if (filters && !matchMulti(filters.langue, langMap(r.lang))) return false;
    return true;
  });

  return (
    <div data-screen-label="Recommandations">
      <div className="page-head">
        <div>
          <h2>Recommandations</h2>
          <div className="page-sub">{d.recos.total.toLocaleString("fr-FR")} recommandations détectées sur votre médiathèque</div>
        </div>
        <div className="actions">
          <button className="btn"><Icons.download/> Export CSV</button>
        </div>
      </div>

      {/* KPI strip */}
      <div style={{display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 12, marginBottom: 18}}>
        <KpiTile label="TOTAL"   value={d.recos.total}   active={prio === "all" && recoType === "all"} onClick={() => { setPrio("all"); setRecoType("all"); }} color="var(--accent)"/>
        <KpiTile label="PRIO. HAUTE" value={d.recos.high}   active={prio === "high"}  onClick={() => setPrio("high")}   color="var(--danger)"/>
        <KpiTile label="QUALITÉ" value={d.recos.quality} active={recoType === "Qualité"} onClick={() => setRecoType("Qualité")} color="var(--chart-2)"/>
        <KpiTile label="ESPACE"  value={d.recos.space}   active={recoType === "Espace"}  onClick={() => setRecoType("Espace")} color="var(--warn)"/>
        <KpiTile label="SÉRIES"  value={d.recos.series}  active={recoType === "Séries"}  onClick={() => setRecoType("Séries")} color="var(--chart-3)"/>
        <KpiTile label="LANGUES" value={d.recos.langues} active={recoType === "Langues"} onClick={() => setRecoType("Langues")} color="var(--chart-4)"/>
      </div>

      {/* Filters */}
      <div className="card" style={{padding: 14, marginBottom: 14}}>
        <div className="row gap-4" style={{flexWrap: "wrap"}}>
          <div className="col gap-2">
            <div className="card-title">Priorité</div>
            <div className="lib-filters">
              {[["all","Toutes"],["high","Haute"],["med","Moyenne"],["low","Basse"]].map(([v,l]) => (
                <div key={v} className={`filter-chip ${prio === v ? "active" : ""}`} onClick={() => setPrio(v)}>{l}</div>
              ))}
            </div>
          </div>

          <div className="col gap-2" style={{flex: 1}}>
            <div className="card-title">Type de recommandation</div>
            <div className="lib-filters">
              {[["all","Tous"],["Qualité","Qualité"],["Espace","Espace"],["Langues","Langues"],["Séries","Séries"],["Données","Données"]].map(([v,l]) => (
                <div key={v} className={`filter-chip ${recoType === v ? "active" : ""}`} onClick={() => setRecoType(v)}>{l}</div>
              ))}
            </div>
          </div>

          <div className="col gap-2">
            <div className="card-title">Trier par</div>
            <select className="field sm" style={{minWidth: 140}}>
              <option>Priorité ↓</option>
              <option>Taille ↓</option>
              <option>Score ↑</option>
              <option>Titre A→Z</option>
            </select>
          </div>
        </div>
      </div>

      <div className="card tight" style={{padding: 0, overflow: "hidden"}}>
        <table className="tbl">
          <thead>
            <tr>
              <th style={{width: 90}}>Priorité</th>
              <th style={{width: 110}}>Type</th>
              <th>Média</th>
              <th>Recommandation</th>
              <th>Action</th>
              <th style={{width: 40}}></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r, i) => (
              <tr key={i}>
                <td><span className={`prio ${r.prio}`}>{r.prio === "high" ? "Haute" : r.prio === "med" ? "Moyenne" : "Basse"}</span></td>
                <td><span className="pill">{r.type}</span></td>
                <td>
                  <div style={{fontWeight: 500}}>{r.title} <span className="muted mono" style={{fontWeight: 400}}>({r.year})</span></div>
                  <div className="muted" style={{fontSize: 11.5, marginTop: 2}}>
                    <span className="mono">Score {r.score}</span>
                    <span style={{margin: "0 6px", color: "var(--border-strong)"}}>·</span>
                    <span className="mono">{r.size}</span>
                    <span style={{margin: "0 6px", color: "var(--border-strong)"}}>·</span>
                    <span className="mono">{r.res}</span>
                    <span style={{margin: "0 6px", color: "var(--border-strong)"}}>·</span>
                    <span>{r.codec}</span>
                    <span style={{margin: "0 6px", color: "var(--border-strong)"}}>·</span>
                    <span>{r.audio}</span>
                    <span style={{margin: "0 6px", color: "var(--border-strong)"}}>·</span>
                    <span>{r.lang}</span>
                  </div>
                </td>
                <td className="text-2">{r.reason}</td>
                <td className="muted" style={{fontSize: 12.5}}>{r.action}</td>
                <td>
                  <button className="icon-btn"><Icons.chevronRight/></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="muted" style={{fontSize: 12, marginTop: 14, textAlign: "center"}}>
        Affichage de {filtered.length} sur {d.recos.total.toLocaleString("fr-FR")} recommandations
      </div>
    </div>
  );
}

function KpiTile({ label, value, active, onClick, color }) {
  return (
    <div onClick={onClick} style={{
      background: active ? `color-mix(in oklch, ${color} 14%, var(--panel))` : "var(--panel)",
      border: `1px solid ${active ? color : "var(--border)"}`,
      borderRadius: 12,
      padding: "12px 14px",
      cursor: "pointer",
      transition: "background .12s, border-color .12s",
      position: "relative",
    }}>
      <div style={{fontSize: 10.5, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--muted)"}}>{label}</div>
      <div className="mono" style={{fontSize: 22, fontWeight: 600, color: active ? color : "var(--text)", marginTop: 4}}>
        {value.toLocaleString("fr-FR")}
      </div>
    </div>
  );
}

Object.assign(window, { PageRecommandations });
