// MyMediaLibrary — Historique des scans

const SCAN_HISTORY = [
  {
    id: 281, date: "2026-05-20T09:30:00", trigger: "Auto",   status: "ok",
    duration: 142, added: 12, removed: 4, updated: 38, errors: 0, recos: 47,
    sizeStart: 39.6, sizeEnd: 39.7,
    steps: [
      { name: "Indexation des fichiers", duration: 22, ok: true, detail: "24 854 fichiers scannés" },
      { name: "Analyse ffprobe",         duration: 86, ok: true, detail: "12 nouveaux médias analysés" },
      { name: "Métadonnées TMDB",        duration: 14, ok: true, detail: "12 fiches mises à jour" },
      { name: "Calcul du score",         duration: 8,  ok: true, detail: "3 322 médias évalués" },
      { name: "Génération des recos",    duration: 12, ok: true, detail: "47 recommandations" },
    ],
  },
  {
    id: 280, date: "2026-05-19T04:00:00", trigger: "Cron",   status: "ok",
    duration: 138, added: 0,  removed: 0,  updated: 12, errors: 0, recos: 3,
    sizeStart: 39.6, sizeEnd: 39.6,
    steps: [
      { name: "Indexation des fichiers", duration: 21, ok: true, detail: "24 850 fichiers scannés" },
      { name: "Analyse ffprobe",         duration: 84, ok: true, detail: "0 nouveau média" },
      { name: "Métadonnées TMDB",        duration: 13, ok: true, detail: "0 fiches" },
      { name: "Calcul du score",         duration: 8,  ok: true, detail: "3 310 médias" },
      { name: "Génération des recos",    duration: 12, ok: true, detail: "3 recommandations" },
    ],
  },
  {
    id: 279, date: "2026-05-18T04:00:00", trigger: "Cron",   status: "warning",
    duration: 156, added: 18, removed: 2,  updated: 41, errors: 3, recos: 22,
    sizeStart: 39.5, sizeEnd: 39.6,
    steps: [
      { name: "Indexation des fichiers", duration: 24, ok: true,  detail: "24 836 fichiers" },
      { name: "Analyse ffprobe",         duration: 92, ok: false, detail: "3 fichiers corrompus — voir log" },
      { name: "Métadonnées TMDB",        duration: 16, ok: true,  detail: "18 fiches mises à jour" },
      { name: "Calcul du score",         duration: 9,  ok: true,  detail: "3 292 médias" },
      { name: "Génération des recos",    duration: 15, ok: true,  detail: "22 recommandations" },
    ],
  },
  {
    id: 278, date: "2026-05-17T04:00:00", trigger: "Cron",   status: "ok",
    duration: 134, added: 4,  removed: 1,  updated: 9,  errors: 0, recos: 6,
    sizeStart: 39.5, sizeEnd: 39.5,
    steps: [
      { name: "Indexation des fichiers", duration: 20, ok: true, detail: "24 820 fichiers" },
      { name: "Analyse ffprobe",         duration: 82, ok: true, detail: "4 nouveaux médias" },
      { name: "Métadonnées TMDB",        duration: 13, ok: true, detail: "4 fiches" },
      { name: "Calcul du score",         duration: 8,  ok: true, detail: "3 274 médias" },
      { name: "Génération des recos",    duration: 11, ok: true, detail: "6 recommandations" },
    ],
  },
  {
    id: 277, date: "2026-05-16T15:22:00", trigger: "Manuel", status: "ok",
    duration: 128, added: 0,  removed: 0,  updated: 4,  errors: 0, recos: 0,
    sizeStart: 39.5, sizeEnd: 39.5,
    steps: [
      { name: "Indexation des fichiers", duration: 19, ok: true, detail: "24 816 fichiers" },
      { name: "Analyse ffprobe",         duration: 78, ok: true, detail: "0 nouveau" },
      { name: "Métadonnées TMDB",        duration: 12, ok: true, detail: "0 fiches" },
      { name: "Calcul du score",         duration: 8,  ok: true, detail: "3 270 médias" },
      { name: "Génération des recos",    duration: 11, ok: true, detail: "0 recommandations" },
    ],
  },
  {
    id: 276, date: "2026-05-16T04:00:00", trigger: "Cron",   status: "error",
    duration: 38,  added: 0, removed: 0, updated: 0, errors: 1, recos: 0,
    sizeStart: 39.5, sizeEnd: 39.5,
    steps: [
      { name: "Indexation des fichiers", duration: 4, ok: false, detail: "Lecture impossible — disque inaccessible" },
      { name: "Analyse ffprobe",         duration: 0, ok: false, detail: "Annulé (pré-requis échoué)" },
    ],
  },
  {
    id: 275, date: "2026-05-15T04:00:00", trigger: "Cron",   status: "ok",
    duration: 132, added: 6, removed: 0, updated: 14, errors: 0, recos: 8,
    sizeStart: 39.4, sizeEnd: 39.5,
    steps: [
      { name: "Indexation des fichiers", duration: 21, ok: true, detail: "24 810 fichiers" },
      { name: "Analyse ffprobe",         duration: 82, ok: true, detail: "6 nouveaux médias" },
      { name: "Métadonnées TMDB",        duration: 13, ok: true, detail: "6 fiches" },
      { name: "Calcul du score",         duration: 8,  ok: true, detail: "3 270 médias" },
      { name: "Génération des recos",    duration: 8,  ok: true, detail: "8 recommandations" },
    ],
  },
  {
    id: 274, date: "2026-05-14T04:00:00", trigger: "Cron",   status: "ok",
    duration: 129, added: 2, removed: 0, updated: 8, errors: 0, recos: 4,
    sizeStart: 39.4, sizeEnd: 39.4,
    steps: [
      { name: "Indexation des fichiers", duration: 20, ok: true, detail: "24 804 fichiers" },
      { name: "Analyse ffprobe",         duration: 81, ok: true, detail: "2 nouveaux médias" },
      { name: "Métadonnées TMDB",        duration: 12, ok: true, detail: "2 fiches" },
      { name: "Calcul du score",         duration: 8,  ok: true, detail: "3 264 médias" },
      { name: "Génération des recos",    duration: 8,  ok: true, detail: "4 recommandations" },
    ],
  },
  {
    id: 273, date: "2026-05-13T04:00:00", trigger: "Cron",   status: "ok",
    duration: 131, added: 9, removed: 3, updated: 22, errors: 0, recos: 12,
    sizeStart: 39.3, sizeEnd: 39.4,
    steps: [
      { name: "Indexation des fichiers", duration: 21, ok: true, detail: "24 798 fichiers" },
      { name: "Analyse ffprobe",         duration: 82, ok: true, detail: "9 nouveaux médias" },
      { name: "Métadonnées TMDB",        duration: 14, ok: true, detail: "9 fiches" },
      { name: "Calcul du score",         duration: 7,  ok: true, detail: "3 262 médias" },
      { name: "Génération des recos",    duration: 7,  ok: true, detail: "12 recommandations" },
    ],
  },
  {
    id: 272, date: "2026-05-12T04:00:00", trigger: "Cron",   status: "ok",
    duration: 130, added: 0, removed: 0, updated: 5, errors: 0, recos: 1,
    sizeStart: 39.3, sizeEnd: 39.3,
    steps: [
      { name: "Indexation des fichiers", duration: 20, ok: true, detail: "24 792 fichiers" },
      { name: "Analyse ffprobe",         duration: 80, ok: true, detail: "0 nouveau" },
      { name: "Métadonnées TMDB",        duration: 13, ok: true, detail: "0 fiches" },
      { name: "Calcul du score",         duration: 8,  ok: true, detail: "3 256 médias" },
      { name: "Génération des recos",    duration: 9,  ok: true, detail: "1 recommandation" },
    ],
  },
];

function fmtDuration(s) {
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}m ${r}s` : `${r}s`;
}

function fmtDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" })
       + " · " + d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

function PageHistorique({ navigate }) {
  const [expanded, setExpanded] = React.useState(281);
  const [trigger, setTrigger] = React.useState("all");
  const [status, setStatus] = React.useState("all");

  const filtered = SCAN_HISTORY.filter(s => {
    if (trigger !== "all" && s.trigger !== trigger) return false;
    if (status !== "all" && s.status !== status) return false;
    return true;
  });

  const avgDuration = Math.round(SCAN_HISTORY.reduce((s, h) => s + h.duration, 0) / SCAN_HISTORY.length);
  const successRate = Math.round((SCAN_HISTORY.filter(h => h.status === "ok").length / SCAN_HISTORY.length) * 100);
  const totalAdded   = SCAN_HISTORY.reduce((s, h) => s + h.added, 0);
  const totalErrors  = SCAN_HISTORY.reduce((s, h) => s + h.errors, 0);

  return (
    <div data-screen-label="Historique">
      <div className="page-head">
        <div>
          <h2>Historique des scans</h2>
          <div className="page-sub">{SCAN_HISTORY.length} scans sur les 30 derniers jours · planifiés tous les jours à 04h00</div>
        </div>
        <div className="actions">
          <button className="btn"><Icons.download/> Export CSV</button>
          <button className="btn primary"><Icons.scan/> Lancer un scan</button>
        </div>
      </div>

      {/* KPI */}
      <div style={{display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 20}}>
        <Stat label="Scans (30j)"  value={SCAN_HISTORY.length} foot={<>{SCAN_HISTORY.filter(h => h.trigger === "Cron").length} planifiés · {SCAN_HISTORY.filter(h => h.trigger === "Manuel").length} manuels</>}        icon={<Icons.scan/>} accent/>
        <Stat label="Durée moyenne" value={fmtDuration(avgDuration)} foot={<>Min {fmtDuration(Math.min(...SCAN_HISTORY.map(h=>h.duration)))} · Max {fmtDuration(Math.max(...SCAN_HISTORY.map(h=>h.duration)))}</>} icon={<Icons.clock/>}/>
        <Stat label="Taux de succès" value={`${successRate}%`} foot={<>{SCAN_HISTORY.filter(h=>h.status === "ok").length} OK · {SCAN_HISTORY.filter(h=>h.status === "error").length} erreur(s)</>} icon={<Icons.check/>}/>
        <Stat label="Médias ajoutés" value={totalAdded} foot={<>{totalErrors} erreurs détectées</>} icon={<Icons.plus/>}/>
      </div>

      {/* Filters */}
      <div className="lib-toolbar" style={{marginBottom: 14}}>
        <div className="lib-filters">
          <span className="muted" style={{fontSize: 12, marginRight: 4}}>Déclencheur :</span>
          {[["all","Tous"],["Cron","Cron"],["Auto","Auto"],["Manuel","Manuel"]].map(([v,l]) => (
            <div key={v} className={`filter-chip ${trigger === v ? "active" : ""}`} onClick={() => setTrigger(v)}>{l}</div>
          ))}
        </div>
        <div className="lib-filters">
          <span className="muted" style={{fontSize: 12, marginRight: 4}}>Statut :</span>
          {[["all","Tous"],["ok","OK"],["warning","Avertissement"],["error","Erreur"]].map(([v,l]) => (
            <div key={v} className={`filter-chip ${status === v ? "active" : ""}`} onClick={() => setStatus(v)}>{l}</div>
          ))}
        </div>
        <div style={{flex: 1}}/>
        <div className="muted" style={{fontSize: 12.5}}>{filtered.length} scan(s) affiché(s)</div>
      </div>

      <div className="card tight" style={{padding: 0, overflow: "hidden"}}>
        <table className="tbl">
          <thead>
            <tr>
              <th style={{width: 30}}></th>
              <th style={{width: 70}}>#</th>
              <th style={{width: 170}}>Date</th>
              <th style={{width: 100}}>Déclencheur</th>
              <th style={{width: 100}}>Statut</th>
              <th style={{width: 90}}>Durée</th>
              <th style={{width: 80}}>+ Ajoutés</th>
              <th style={{width: 90}}>− Supprimés</th>
              <th style={{width: 90}}>Modifiés</th>
              <th style={{width: 80}}>Erreurs</th>
              <th>Recos</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((h, i) => {
              const isOpen = expanded === h.id;
              const sCls = h.status === "ok" ? "ok" : h.status === "warning" ? "warn" : "danger";
              return (
                <React.Fragment key={h.id}>
                  <tr onClick={() => setExpanded(isOpen ? null : h.id)} style={{cursor: "pointer"}}>
                    <td>
                      <Icons.chevronRight size={14} style={{
                        color: "var(--muted)",
                        transform: isOpen ? "rotate(90deg)" : "rotate(0deg)",
                        transition: "transform .15s"
                      }}/>
                    </td>
                    <td className="mono muted">#{h.id}</td>
                    <td className="mono">{fmtDate(h.date)}</td>
                    <td><span className="pill">{h.trigger}</span></td>
                    <td>
                      <span className={`pill ${sCls}`}>
                        {h.status === "ok"      && <><Icons.check size={11}/> Succès</>}
                        {h.status === "warning" && <><Icons.warn size={11}/> Avert.</>}
                        {h.status === "error"   && <><Icons.x size={11}/> Erreur</>}
                      </span>
                    </td>
                    <td className="mono">{fmtDuration(h.duration)}</td>
                    <td className="mono" style={{color: h.added > 0 ? "var(--ok)" : "var(--muted)"}}>{h.added > 0 ? `+${h.added}` : "0"}</td>
                    <td className="mono" style={{color: h.removed > 0 ? "var(--danger)" : "var(--muted)"}}>{h.removed > 0 ? `−${h.removed}` : "0"}</td>
                    <td className="mono muted">{h.updated}</td>
                    <td className="mono" style={{color: h.errors > 0 ? "var(--danger)" : "var(--muted)"}}>{h.errors}</td>
                    <td className="mono muted">{h.recos}</td>
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={11} style={{padding: 0, background: "var(--panel-2)"}}>
                        <ScanDetail h={h}/>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ScanDetail({ h }) {
  return (
    <div style={{padding: "20px 24px"}}>
      <div style={{display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 24}}>
        <div>
          <div className="card-title" style={{marginBottom: 12}}>Étapes ({h.steps.length})</div>
          <div className="col gap-1">
            {h.steps.map((step, i) => {
              const pct = h.duration > 0 ? (step.duration / h.duration) * 100 : 0;
              return (
                <div key={i} style={{padding: "10px 0", borderBottom: i === h.steps.length-1 ? 0 : "1px solid var(--border-soft)"}}>
                  <div className="row" style={{justifyContent: "space-between", marginBottom: 6}}>
                    <div className="row gap-2">
                      {step.ok ? (
                        <span style={{width: 18, height: 18, borderRadius: "50%", background: "color-mix(in oklch, var(--ok) 18%, transparent)", color: "var(--ok)", display: "grid", placeItems: "center"}}>
                          <Icons.check size={11}/>
                        </span>
                      ) : (
                        <span style={{width: 18, height: 18, borderRadius: "50%", background: "color-mix(in oklch, var(--danger) 18%, transparent)", color: "var(--danger)", display: "grid", placeItems: "center"}}>
                          <Icons.x size={11}/>
                        </span>
                      )}
                      <span style={{fontSize: 13, fontWeight: 500}}>{step.name}</span>
                    </div>
                    <span className="mono muted" style={{fontSize: 12}}>{fmtDuration(step.duration)}</span>
                  </div>
                  <div style={{height: 4, background: "var(--panel-3)", borderRadius: 999, overflow: "hidden", marginBottom: 6}}>
                    <div style={{width: `${pct}%`, height: "100%", background: step.ok ? "var(--accent)" : "var(--danger)"}}/>
                  </div>
                  <div className="muted" style={{fontSize: 12, paddingLeft: 26}}>{step.detail}</div>
                </div>
              );
            })}
          </div>
        </div>

        <div>
          <div className="card-title" style={{marginBottom: 12}}>Résumé</div>
          <div style={{background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 10, padding: 14}}>
            <div className="col gap-2">
              <KV k="Identifiant"      v={<span className="mono">#{h.id}</span>}/>
              <KV k="Date"             v={<span className="mono">{fmtDate(h.date)}</span>}/>
              <KV k="Durée totale"     v={<span className="mono">{fmtDuration(h.duration)}</span>}/>
              <KV k="Déclencheur"      v={h.trigger}/>
              <KV k="Médias ajoutés"   v={<span className="mono" style={{color: "var(--ok)"}}>+{h.added}</span>}/>
              <KV k="Médias supprimés" v={<span className="mono" style={{color: h.removed > 0 ? "var(--danger)" : "var(--muted)"}}>−{h.removed}</span>}/>
              <KV k="Médias modifiés"  v={<span className="mono">{h.updated}</span>}/>
              <KV k="Erreurs"          v={<span className="mono" style={{color: h.errors > 0 ? "var(--danger)" : "var(--muted)"}}>{h.errors}</span>}/>
              <KV k="Recos générées"   v={<span className="mono">{h.recos}</span>}/>
              <div className="divider" style={{margin: "4px 0"}}/>
              <KV k="Stockage avant"   v={<span className="mono">{h.sizeStart.toFixed(1)} TB</span>}/>
              <KV k="Stockage après"   v={<span className="mono">{h.sizeEnd.toFixed(1)} TB</span>}/>
              <KV k="Variation"        v={<span className="mono" style={{color: (h.sizeEnd - h.sizeStart) > 0 ? "var(--warn)" : "var(--muted)"}}>
                {(h.sizeEnd - h.sizeStart) >= 0 ? "+" : ""}{(h.sizeEnd - h.sizeStart).toFixed(2)} TB
              </span>}/>
            </div>
          </div>

          <div className="row gap-2" style={{marginTop: 12}}>
            <button className="btn small"><Icons.log size={13}/> Voir le log brut</button>
            <button className="btn small"><Icons.refresh size={13}/> Relancer ce scan</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function KV({ k, v }) {
  return (
    <div className="row" style={{justifyContent: "space-between", fontSize: 12.5}}>
      <span className="muted">{k}</span>
      <span>{v}</span>
    </div>
  );
}

Object.assign(window, { PageHistorique });
