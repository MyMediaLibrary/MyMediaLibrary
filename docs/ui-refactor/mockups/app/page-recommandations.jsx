// MyMediaLibrary — Paramètres (page dédiée)

function PageParametres({ section, setSection, theme, setTheme, accent, setAccent, navigate }) {
  const sections = [
    { v: "bibliotheque", l: "Bibliothèque", icon: <Icons.library/> },
    { v: "config",       l: "Configuration", icon: <Icons.settings/> },
    { v: "score",        l: "Score qualité", icon: <Icons.award/> },
    { v: "connexions",   l: "Connexions", icon: <Icons.link/> },
    { v: "fournisseurs", l: "Fournisseurs streaming", icon: <Icons.tv/> },
    { v: "apparence",    l: "Apparence", icon: <Icons.sparkles/> },
    { v: "systeme",      l: "Système", icon: <Icons.shield/> },
    { v: "compte",       l: "Compte", icon: <Icons.user/> },
  ];

  return (
    <div data-screen-label="Parametres">
      <div className="page-head">
        <div>
          <h2>Paramètres</h2>
          <div className="page-sub">Configuration de l'application et de la médiathèque</div>
        </div>
        <div className="actions">
          <button className="btn ghost">Annuler</button>
          <button className="btn primary">Enregistrer les modifications</button>
        </div>
      </div>

      <div className="settings">
        <aside className="settings-nav">
          {sections.map(s => (
            <div key={s.v} className={`sn-item ${section === s.v ? "active" : ""}`} onClick={() => setSection(s.v)}>
              {s.icon}<span>{s.l}</span>
            </div>
          ))}
        </aside>

        <div className="card" style={{padding: 24, minHeight: 600}}>
          {section === "bibliotheque" && <SBibliotheque/>}
          {section === "config" && <SConfig/>}
          {section === "score" && <SScore/>}
          {section === "connexions" && <SConnexions/>}
          {section === "fournisseurs" && <SFournisseurs/>}
          {section === "apparence" && <SApparence theme={theme} setTheme={setTheme} accent={accent} setAccent={setAccent}/>}
          {section === "systeme" && <SSysteme/>}
          {section === "compte" && <SCompte/>}
        </div>
      </div>
    </div>
  );
}

function SectionHeader({ title, desc }) {
  return (
    <div style={{marginBottom: 20}}>
      <div style={{fontSize: 18, fontWeight: 600, letterSpacing: "-0.01em"}}>{title}</div>
      {desc && <div className="muted" style={{fontSize: 13, marginTop: 4}}>{desc}</div>}
    </div>
  );
}

function SettingRow({ label, desc, children }) {
  return (
    <div className="setting-block">
      <div className="setting-row">
        <div>
          <div className="label">{label}</div>
          {desc && <div className="desc">{desc}</div>}
        </div>
        <div>{children}</div>
      </div>
    </div>
  );
}

function SBibliotheque() {
  const d = window.MML_DATA;
  const [films, setFilms] = React.useState(true);
  const [series, setSeries] = React.useState(true);
  const [folders, setFolders] = React.useState(d.detectedFolders);

  return (
    <div>
      <SectionHeader title="Bibliothèque" desc="Choisissez les contenus visibles et les dossiers à scanner."/>

      <SettingRow label="Afficher les Films" desc="Inclure le contenu de type Film dans l'application">
        <Toggle value={films} onChange={setFilms}/>
      </SettingRow>
      <SettingRow label="Afficher les Séries" desc="Inclure le contenu de type Série">
        <Toggle value={series} onChange={setSeries}/>
      </SettingRow>

      <div className="setting-block">
        <div className="row" style={{justifyContent: "space-between", marginBottom: 12}}>
          <div>
            <div className="label">Dossiers détectés</div>
            <div className="desc">10 dossiers • <span style={{color: "var(--warn)"}}>4 non configurés</span></div>
          </div>
          <button className="btn small"><Icons.refresh size={13}/> Rescanner</button>
        </div>

        <div style={{
          border: "1px solid var(--border)",
          borderRadius: 10,
          overflow: "hidden",
          background: "var(--panel-2)"
        }}>
          {folders.map((f, i) => (
            <div key={i} className="row" style={{
              padding: "10px 14px",
              borderBottom: i === folders.length - 1 ? "none" : "1px solid var(--border-soft)",
              justifyContent: "space-between",
              gap: 12,
            }}>
              <div className="row gap-2">
                <Icons.folder size={15} style={{color: "var(--muted)"}}/>
                <span className="mono" style={{fontSize: 13}}>{f.name}</span>
                {f.type === "Ignorer" && f.name !== "books" && f.name !== "comics" && f.name !== "mangas" && f.name !== "special" && (
                  <span className="pill warn" style={{marginLeft: 4}}>Non configuré</span>
                )}
              </div>
              <div className="row gap-3">
                <select className="field sm" value={f.type} onChange={e => {
                  const next = [...folders]; next[i] = {...f, type: e.target.value, active: e.target.value !== "Ignorer"}; setFolders(next);
                }}>
                  <option>Films</option>
                  <option>Séries</option>
                  <option>Animation</option>
                  <option>Spectacles</option>
                  <option>Ignorer</option>
                </select>
                <Toggle value={f.active} onChange={(v) => {
                  const next = [...folders]; next[i] = {...f, active: v}; setFolders(next);
                }}/>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SConfig() {
  const [a, setA] = React.useState(false);
  const [b, setB] = React.useState(true);
  const [c, setC] = React.useState(true);
  const [d, setD] = React.useState(true);
  return (
    <div>
      <SectionHeader title="Configuration" desc="Comportements et fonctionnalités de l'application."/>
      <SettingRow label="Synopsis au survol" desc="Affiche le synopsis lors du survol d'une tuile">
        <Toggle value={a} onChange={setA}/>
      </SettingRow>
      <SettingRow label="Analyse technique ffprobe" desc="Enrichit la bibliothèque avec les données techniques extraites par ffprobe">
        <Toggle value={b} onChange={setB}/>
      </SettingRow>
      <SettingRow label="Activer le score de qualité" desc="Quand désactivé, le score n'est plus calculé au scan et disparaît des tris/filtres/stats">
        <Toggle value={c} onChange={setC}/>
      </SettingRow>
      <SettingRow label="Activer les recommandations" desc="Nécessite le score qualité">
        <Toggle value={d} onChange={setD}/>
      </SettingRow>
      <SettingRow label="Niveau de notifications" desc="Fréquence des alertes dans l'application">
        <select className="field"><option>Important uniquement</option><option>Tout</option><option>Aucun</option></select>
      </SettingRow>
    </div>
  );
}

function SScore() {
  const [weights, setWeights] = React.useState({ Vidéo: 50, Audio: 20, Langues: 15, Taille: 15 });
  const [open, setOpen] = React.useState("Vidéo");
  const total = Object.values(weights).reduce((s, v) => s + v, 0);

  return (
    <div>
      <SectionHeader title="Score qualité" desc="Définissez le calcul du score de qualité des médias."/>

      <div className="setting-block">
        <div className="label" style={{marginBottom: 4}}>Poids des composantes</div>
        <div className="desc" style={{marginBottom: 14}}>Importance relative de chaque composante dans le score final.</div>
        <div style={{display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12}}>
          {Object.entries(weights).map(([k, v]) => (
            <Weight key={k} label={k} value={v} active={open === k}
              onChange={(nv) => setWeights(w => ({...w, [k]: nv}))}
              onClick={() => setOpen(open === k ? null : k)}/>
          ))}
        </div>
        <div className="row" style={{justifyContent: "space-between", marginTop: 14, padding: "10px 14px",
          background: total === 100 ? "color-mix(in oklch, var(--ok) 12%, var(--panel))" : "color-mix(in oklch, var(--warn) 12%, var(--panel))",
          borderRadius: 10,
          border: `1px dashed color-mix(in oklch, ${total === 100 ? "var(--ok)" : "var(--warn)"} 30%, transparent)`
        }}>
          <div className="row gap-2" style={{color: total === 100 ? "var(--ok)" : "var(--warn)", fontWeight: 600, fontSize: 13}}>
            {total === 100 ? <><Icons.check size={14}/> Configuration valide</> : <><Icons.warn size={14}/> Le total doit être égal à 100</>}
          </div>
          <div className="mono" style={{fontSize: 13}}>Total: {total}</div>
        </div>
      </div>

      <div className="col gap-2" style={{marginTop: 18}}>
        <Collapsible
          open={open === "Vidéo"} onToggle={() => setOpen(open === "Vidéo" ? null : "Vidéo")}
          icon={<Icons.film/>} title="Vidéo" subtitle={`Poids: ${weights["Vidéo"]}%`}
          weight={weights["Vidéo"]}>
          <ScoreSubBlock title="Résolution" desc="Score attribué selon la résolution détectée">
            <div className="row gap-3" style={{flexWrap: "wrap"}}>
              <PointField label="2160p (4K)" v="25"/>
              <PointField label="1080p" v="20"/>
              <PointField label="720p"  v="10"/>
              <PointField label="SD"    v="5"/>
              <PointField label="Inconnu" v="8" muted/>
            </div>
          </ScoreSubBlock>

          <ScoreSubBlock title="Codec vidéo" desc="Bonus selon le codec utilisé">
            <div className="row gap-3" style={{flexWrap: "wrap"}}>
              <PointField label="H.265 (HEVC)" v="15"/>
              <PointField label="AV1"   v="20"/>
              <PointField label="H.264" v="10"/>
              <PointField label="MPEG-4" v="2"/>
              <PointField label="Inconnu" v="5" muted/>
            </div>
          </ScoreSubBlock>

          <ScoreSubBlock title="HDR" desc="Bonus pour les flux HDR" last>
            <div className="row gap-3" style={{flexWrap: "wrap"}}>
              <PointField label="SDR"          v="0"/>
              <PointField label="HDR10"        v="8"/>
              <PointField label="HDR10+"       v="10"/>
              <PointField label="Dolby Vision" v="12"/>
            </div>
          </ScoreSubBlock>
        </Collapsible>

        <Collapsible
          open={open === "Audio"} onToggle={() => setOpen(open === "Audio" ? null : "Audio")}
          icon={<Icons.bell/>} title="Audio" subtitle={`Poids: ${weights["Audio"]}%`}
          weight={weights["Audio"]}>
          <ScoreSubBlock title="Codec audio" desc="Bonus selon le codec audio">
            <div className="row gap-3" style={{flexWrap: "wrap"}}>
              <PointField label="Dolby TrueHD"     v="20"/>
              <PointField label="Dolby Digital Plus" v="15"/>
              <PointField label="DTS"              v="12"/>
              <PointField label="Dolby Digital"    v="10"/>
              <PointField label="AAC"              v="6"/>
              <PointField label="MP3"              v="2"/>
            </div>
          </ScoreSubBlock>

          <ScoreSubBlock title="Channels" desc="Bonus selon la configuration multicanal" last>
            <div className="row gap-3" style={{flexWrap: "wrap"}}>
              <PointField label="Mono (1.0)" v="0"/>
              <PointField label="Stéréo (2.0)" v="5"/>
              <PointField label="5.1"        v="12"/>
              <PointField label="7.1"        v="15"/>
              <PointField label="Atmos"      v="18"/>
            </div>
          </ScoreSubBlock>
        </Collapsible>

        <Collapsible
          open={open === "Langues"} onToggle={() => setOpen(open === "Langues" ? null : "Langues")}
          icon={<Icons.language/>} title="Langues" subtitle={`Poids: ${weights["Langues"]}%`}
          weight={weights["Langues"]}>
          <ScoreSubBlock title="Pistes audio" desc="Bonus selon les pistes disponibles">
            <div className="row gap-3" style={{flexWrap: "wrap"}}>
              <PointField label="MULTI (VF+VO)" v="20"/>
              <PointField label="VF seule"     v="12"/>
              <PointField label="VO seule"     v="8"/>
              <PointField label="Inconnue"     v="0" muted/>
            </div>
          </ScoreSubBlock>

          <ScoreSubBlock title="Sous-titres" desc="Bonus si des sous-titres FR sont détectés" last>
            <div className="row gap-3" style={{flexWrap: "wrap"}}>
              <PointField label="Sous-titres FR"  v="6"/>
              <PointField label="Sous-titres VO"  v="3"/>
              <PointField label="Forcés / SDH"   v="2"/>
            </div>
          </ScoreSubBlock>
        </Collapsible>

        <Collapsible
          open={open === "Taille"} onToggle={() => setOpen(open === "Taille" ? null : "Taille")}
          icon={<Icons.hardDrive/>} title="Taille" subtitle={`Poids: ${weights["Taille"]}%`}
          weight={weights["Taille"]}>
          <ScoreSubBlock title="Bitrate vidéo" desc="Cible : bitrate optimal selon la résolution. Les fichiers trop lourds ou trop légers sont pénalisés.">
            <div style={{display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12}}>
              <RangeField label="2160p — min / max (Mb/s)" min="20" max="80"/>
              <RangeField label="1080p — min / max (Mb/s)" min="6"  max="25"/>
              <RangeField label="720p — min / max (Mb/s)"  min="2"  max="10"/>
              <RangeField label="SD — min / max (Mb/s)"    min="0.5" max="3"/>
            </div>
          </ScoreSubBlock>

          <ScoreSubBlock title="Pénalités" desc="Score retiré pour les fichiers hors-cible" last>
            <div className="row gap-3" style={{flexWrap: "wrap"}}>
              <PointField label="Trop lourd (>2× max)"  v="-15"/>
              <PointField label="Légèrement lourd (1.5×)" v="-5"/>
              <PointField label="Trop léger (<½ min)"   v="-10"/>
            </div>
          </ScoreSubBlock>
        </Collapsible>
      </div>
    </div>
  );
}

function Weight({ label, value, onChange, active, onClick }) {
  return (
    <div onClick={onClick} style={{
      background: active ? "color-mix(in oklch, var(--accent) 8%, var(--panel-2))" : "var(--panel-2)",
      border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`,
      borderRadius: 10, padding: 12,
      cursor: "pointer",
      transition: "background .12s, border-color .12s",
    }}>
      <div className="row" style={{justifyContent: "space-between", marginBottom: 8}}>
        <span style={{fontSize: 13, color: "var(--text-2)", fontWeight: 500}}>{label}</span>
        <div className="row gap-1" onClick={e => e.stopPropagation()}>
          <input className="field sm mono" type="number" value={value}
            onChange={(e) => onChange(Math.max(0, Math.min(100, parseInt(e.target.value) || 0)))}
            style={{textAlign: "right", width: 56, minWidth: 0}}/>
          <span className="muted" style={{fontSize: 12}}>%</span>
        </div>
      </div>
      <div style={{height: 6, background: "var(--panel-3)", borderRadius: 999, overflow: "hidden"}}>
        <div style={{width: `${value}%`, height: "100%", background: "var(--accent)", transition: "width .15s"}}/>
      </div>
    </div>
  );
}

function Collapsible({ open, onToggle, icon, title, subtitle, weight, children }) {
  return (
    <div style={{
      background: "var(--panel-2)",
      border: "1px solid var(--border)",
      borderRadius: 12,
      overflow: "hidden",
    }}>
      <div onClick={onToggle} style={{
        padding: "14px 16px",
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}>
        <div style={{
          width: 32, height: 32, borderRadius: 8,
          background: "var(--accent-soft)", color: "var(--accent)",
          display: "grid", placeItems: "center", flex: "none"
        }}>{icon}</div>
        <div style={{flex: 1}}>
          <div style={{fontSize: 14, fontWeight: 600}}>{title}</div>
          <div className="muted" style={{fontSize: 12, marginTop: 2}}>{subtitle}</div>
        </div>
        {weight !== undefined && (
          <div style={{minWidth: 80, height: 6, background: "var(--panel-3)", borderRadius: 999, overflow: "hidden"}}>
            <div style={{width: `${weight}%`, height: "100%", background: "var(--accent)"}}/>
          </div>
        )}
        <Icons.chevronDown size={16} style={{
          color: "var(--muted)",
          transform: open ? "rotate(180deg)" : "rotate(0deg)",
          transition: "transform .15s"
        }}/>
      </div>
      {open && (
        <div style={{padding: "4px 16px 16px", borderTop: "1px solid var(--border)"}}>
          {children}
        </div>
      )}
    </div>
  );
}

function ScoreSubBlock({ title, desc, children, last }) {
  return (
    <div style={{
      padding: "14px 0",
      borderBottom: last ? 0 : "1px solid var(--border-soft)",
    }}>
      <div className="row" style={{justifyContent: "space-between", marginBottom: 10, gap: 12, flexWrap: "wrap"}}>
        <div>
          <div style={{fontSize: 13, fontWeight: 500}}>{title}</div>
          {desc && <div className="muted" style={{fontSize: 12, marginTop: 2}}>{desc}</div>}
        </div>
      </div>
      {children}
    </div>
  );
}

function PointField({ label, v, muted }) {
  const sign = String(v).startsWith("-") ? "var(--danger)" : "var(--text)";
  return (
    <div className="col" style={{alignItems: "center", minWidth: 88}}>
      <div className="muted" style={{fontSize: 10.5, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", textAlign: "center", whiteSpace: "nowrap"}}>{label}</div>
      <input className={`field sm mono`} defaultValue={v} style={{width: 70, textAlign: "center", marginTop: 6, color: muted ? "var(--muted)" : sign}}/>
    </div>
  );
}

function RangeField({ label, min, max }) {
  return (
    <div style={{background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8, padding: 10}}>
      <div className="muted" style={{fontSize: 11.5, marginBottom: 8}}>{label}</div>
      <div className="row gap-2">
        <input className="field sm mono" defaultValue={min} style={{width: 70, textAlign: "right"}}/>
        <span className="muted" style={{fontSize: 12}}>→</span>
        <input className="field sm mono" defaultValue={max} style={{width: 70, textAlign: "right"}}/>
      </div>
    </div>
  );
}

function ResField({ label, v }) {
  return (
    <div className="col" style={{alignItems: "center"}}>
      <div className="muted" style={{fontSize: 10.5, fontWeight: 600}}>{label}</div>
      <input className="field sm mono" defaultValue={v} style={{width: 56, textAlign: "center", marginTop: 4}}/>
    </div>
  );
}

const CONNECTION_TYPES = [
  { id: "seerr",    name: "Seerr",    cat: "Requêtes",       auth: "apikey",  hint: "Demande automatique des médias manquants" },
  { id: "overseerr",name: "Overseerr",cat: "Requêtes",       auth: "apikey",  hint: "Demande automatique des médias manquants" },
  { id: "jellyseerr",name:"Jellyseerr",cat:"Requêtes",       auth: "apikey",  hint: "Demande automatique des médias manquants" },
  { id: "tmdb",     name: "TMDB",     cat: "Métadonnées",    auth: "apikey",  hint: "Affiches, synopsis et genres" },
  { id: "tvdb",     name: "TheTVDB",  cat: "Métadonnées",    auth: "apikey",  hint: "Métadonnées des séries" },
  { id: "sonarr",   name: "Sonarr",   cat: "Téléchargement", auth: "apikey",  hint: "Gestionnaire de séries TV" },
  { id: "radarr",   name: "Radarr",   cat: "Téléchargement", auth: "apikey",  hint: "Gestionnaire de films" },
  { id: "lidarr",   name: "Lidarr",   cat: "Téléchargement", auth: "apikey",  hint: "Gestionnaire de musique" },
  { id: "bazarr",   name: "Bazarr",   cat: "Sous-titres",    auth: "apikey",  hint: "Sous-titres automatiques" },
  { id: "prowlarr", name: "Prowlarr", cat: "Indexeurs",      auth: "apikey",  hint: "Gestionnaire d'indexeurs" },
  { id: "plex",     name: "Plex",     cat: "Lecteur",        auth: "token",   hint: "Serveur de médias Plex" },
  { id: "jellyfin", name: "Jellyfin", cat: "Lecteur",        auth: "apikey",  hint: "Serveur de médias open-source" },
  { id: "emby",     name: "Emby",     cat: "Lecteur",        auth: "apikey",  hint: "Serveur de médias Emby" },
  { id: "kavita",   name: "Kavita",   cat: "Lecteur",        auth: "userpass",hint: "Mangas, comics et livres" },
];

function SConnexions() {
  // Empty by default
  const [connections, setConnections] = React.useState([]);
  const [editing, setEditing] = React.useState(null);
  const [picker, setPicker] = React.useState(false);

  const setOne = (id, patch) => setConnections(arr => arr.map(c => c.id === id ? {...c, ...patch} : c));
  const remove = (id) => setConnections(arr => arr.filter(c => c.id !== id));

  const addConnection = (type) => {
    const newConn = {
      id: `${type.id}-${Date.now()}`,
      typeId: type.id,
      name: type.name,
      cat: type.cat,
      auth: type.auth,
      url: "",
      enabled: true,
      status: "pending",
      lastSync: "—",
    };
    setConnections(arr => [...arr, newConn]);
    setPicker(false);
    setEditing(newConn.id);
  };

  return (
    <div>
      <SectionHeader title="Connexions" desc="Intégrations avec les services externes — *arr, lecteurs, sous-titres, indexeurs."/>

      <div className="row gap-3" style={{marginBottom: 16, flexWrap: "wrap"}}>
        <div className="row gap-2">
          {connections.length > 0 ? (
            <>
              <span className="health"><span className="dot"/> {connections.filter(c => c.enabled && c.status === "ok").length} actif(s)</span>
              <span className="pill">{connections.length} au total</span>
            </>
          ) : (
            <span className="muted" style={{fontSize: 13}}>Aucune connexion configurée</span>
          )}
        </div>
        <div style={{flex: 1}}/>
        <button className="btn primary" onClick={() => setPicker(true)}><Icons.plus size={13}/> Ajouter une connexion</button>
      </div>

      {connections.length === 0 ? (
        <div className="card" style={{padding: 56, textAlign: "center"}}>
          <div style={{
            width: 56, height: 56, margin: "0 auto 14px",
            borderRadius: 14, background: "var(--accent-soft)", color: "var(--accent)",
            display: "grid", placeItems: "center",
          }}>
            <Icons.link size={26}/>
          </div>
          <div style={{fontSize: 16, fontWeight: 600, marginBottom: 6}}>Aucune connexion</div>
          <div className="muted" style={{fontSize: 13, maxWidth: 380, margin: "0 auto 16px"}}>
            Ajoutez une connexion vers un service externe (Sonarr, Radarr, Plex, Jellyfin, Seerr…) pour enrichir votre médiathèque.
          </div>
          <button className="btn primary" onClick={() => setPicker(true)}><Icons.plus size={13}/> Ajouter une connexion</button>
        </div>
      ) : (
        <div className="card tight" style={{padding: 0, overflow: "hidden"}}>
          <table className="tbl">
            <thead>
              <tr>
                <th style={{width: 50}}>État</th>
                <th>Service</th>
                <th style={{width: 140}}>Catégorie</th>
                <th>URL</th>
                <th style={{width: 130}}>Statut</th>
                <th style={{width: 110}}>Dernière sync</th>
                <th style={{width: 110}}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {connections.map(it => {
                const isEditing = editing === it.id;
                return (
                  <React.Fragment key={it.id}>
                    <tr>
                      <td><Toggle value={it.enabled} onChange={(v) => setOne(it.id, { enabled: v, status: v ? (it.url ? "ok" : "pending") : "disconnected" })}/></td>
                      <td>
                        <div className="row gap-3">
                          <div style={{
                            width: 30, height: 30, borderRadius: 7,
                            background: it.enabled ? "var(--accent-soft)" : "var(--panel-3)",
                            color: it.enabled ? "var(--accent)" : "var(--muted)",
                            display: "grid", placeItems: "center",
                            fontWeight: 700, fontSize: 13,
                            flex: "none",
                          }}>{it.name[0]}</div>
                          <div style={{fontWeight: 500}}>{it.name}</div>
                        </div>
                      </td>
                      <td><span className="pill">{it.cat}</span></td>
                      <td className="mono muted" style={{fontSize: 12, maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"}}>
                        {it.url || <span style={{color: "var(--muted-2)"}}>—</span>}
                      </td>
                      <td>
                        {it.status === "ok"           && <span className="pill ok"><Icons.check size={11}/> Connecté</span>}
                        {it.status === "pending"      && <span className="pill warn">À configurer</span>}
                        {it.status === "disconnected" && <span className="pill">Inactif</span>}
                        {it.status === "error"        && <span className="pill danger">Erreur</span>}
                      </td>
                      <td className="muted mono" style={{fontSize: 12}}>{it.lastSync}</td>
                      <td>
                        <div className="row gap-1">
                          <button className="icon-btn" title="Configurer" onClick={() => setEditing(isEditing ? null : it.id)}>
                            <Icons.settings size={14}/>
                          </button>
                          <button className="icon-btn" title="Tester"><Icons.refresh size={14}/></button>
                          <button className="icon-btn" title="Supprimer" onClick={() => remove(it.id)} style={{color: "var(--danger)"}}>
                            <Icons.trash size={14}/>
                          </button>
                        </div>
                      </td>
                    </tr>
                    {isEditing && (
                      <tr>
                        <td colSpan={7} style={{padding: 0, background: "var(--panel-2)"}}>
                          <IntegrationForm it={it} onChange={(p) => setOne(it.id, p)} onClose={() => setEditing(null)}/>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {picker && <ConnectionPicker onPick={addConnection} onClose={() => setPicker(false)}
        existing={connections.map(c => c.typeId)}/>}
    </div>
  );
}

function ConnectionPicker({ onPick, onClose, existing }) {
  const [query, setQuery] = React.useState("");
  const [cat, setCat] = React.useState("all");
  const cats = ["all", ...Array.from(new Set(CONNECTION_TYPES.map(t => t.cat)))];
  const filtered = CONNECTION_TYPES.filter(t => {
    if (cat !== "all" && t.cat !== cat) return false;
    if (query && !(t.name + " " + t.cat).toLowerCase().includes(query.toLowerCase())) return false;
    return true;
  });

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0,
      background: "rgba(0,0,0,0.5)",
      backdropFilter: "blur(4px)",
      display: "grid", placeItems: "center",
      zIndex: 200,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: "min(640px, 90vw)",
        maxHeight: "80vh",
        background: "var(--panel)",
        border: "1px solid var(--border)",
        borderRadius: 14,
        boxShadow: "var(--shadow-lg)",
        display: "flex", flexDirection: "column",
        overflow: "hidden",
      }}>
        <div style={{padding: "16px 20px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between"}}>
          <div>
            <div style={{fontSize: 16, fontWeight: 600}}>Ajouter une connexion</div>
            <div className="muted" style={{fontSize: 12, marginTop: 2}}>Choisissez un service à connecter</div>
          </div>
          <button className="icon-btn" onClick={onClose}><Icons.x size={14}/></button>
        </div>
        <div style={{padding: "12px 20px", borderBottom: "1px solid var(--border-soft)", display: "flex", gap: 10, flexWrap: "wrap"}}>
          <div className="search" style={{minWidth: 200, flex: 1}}>
            <Icons.search size={14}/>
            <input placeholder="Rechercher…" value={query} onChange={e => setQuery(e.target.value)} autoFocus/>
          </div>
          <div className="lib-filters">
            {cats.map(c => (
              <div key={c} className={`filter-chip ${cat === c ? "active" : ""}`} onClick={() => setCat(c)}>
                {c === "all" ? "Tous" : c}
              </div>
            ))}
          </div>
        </div>
        <div style={{padding: 12, overflow: "auto", flex: 1, display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8}}>
          {filtered.map(t => (
            <div key={t.id} onClick={() => onPick(t)} style={{
              padding: "12px 14px",
              borderRadius: 10,
              cursor: "pointer",
              display: "flex", alignItems: "center", gap: 12,
              border: "1px solid var(--border)",
              background: "var(--panel-2)",
              transition: "border-color .12s, background .12s",
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.background = "color-mix(in oklch, var(--accent) 6%, var(--panel-2))"; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = ""; e.currentTarget.style.background = ""; }}>
              <div style={{
                width: 36, height: 36, borderRadius: 8,
                background: "var(--accent-soft)", color: "var(--accent)",
                display: "grid", placeItems: "center", fontWeight: 700, fontSize: 14, flex: "none",
              }}>{t.name[0]}</div>
              <div style={{flex: 1, minWidth: 0}}>
                <div className="row gap-2">
                  <span style={{fontWeight: 600, fontSize: 13.5}}>{t.name}</span>
                  <span className="pill">{t.cat}</span>
                </div>
                <div className="muted" style={{fontSize: 11.5, marginTop: 2}}>{t.hint}</div>
              </div>
            </div>
          ))}
          {filtered.length === 0 && (
            <div className="empty" style={{gridColumn: "1 / -1"}}>Aucun service ne correspond.</div>
          )}
        </div>
      </div>
    </div>
  );
}

function IntegrationForm({ it, onChange, onClose }) {
  const [testing, setTesting] = React.useState(false);
  const [testResult, setTestResult] = React.useState(null);
  return (
    <div style={{padding: "16px 24px"}}>
      <div className="row" style={{justifyContent: "space-between", marginBottom: 12}}>
        <div className="card-title">Configuration · {it.name}</div>
        <button className="icon-btn" onClick={onClose}><Icons.x size={14}/></button>
      </div>
      <div style={{display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12}}>
        <div className="col gap-1" style={{gridColumn: "1 / -1"}}>
          <div className="muted" style={{fontSize: 11.5}}>URL du service</div>
          <input className="field" value={it.url} placeholder={`https://${it.typeId}.exemple.fr/`} onChange={e => onChange({ url: e.target.value })}/>
        </div>
        {it.auth === "apikey" && (
          <div className="col gap-1" style={{gridColumn: "1 / -1"}}>
            <div className="muted" style={{fontSize: 11.5}}>Clé API</div>
            <input className="field" type="password" placeholder="Coller la clé API"/>
          </div>
        )}
        {it.auth === "token" && (
          <div className="col gap-1" style={{gridColumn: "1 / -1"}}>
            <div className="muted" style={{fontSize: 11.5}}>Token X-Plex</div>
            <input className="field" type="password" placeholder="Coller le token Plex"/>
          </div>
        )}
        {it.auth === "userpass" && (
          <>
            <div className="col gap-1">
              <div className="muted" style={{fontSize: 11.5}}>Identifiant</div>
              <input className="field" placeholder="admin"/>
            </div>
            <div className="col gap-1">
              <div className="muted" style={{fontSize: 11.5}}>Mot de passe</div>
              <input className="field" type="password"/>
            </div>
          </>
        )}
      </div>
      <div className="row gap-2">
        <button className="btn primary small" onClick={() => {
          setTesting(true); setTestResult(null);
          setTimeout(() => { setTesting(false); setTestResult("ok"); onChange({ status: "ok", lastSync: "à l'instant" }); }, 900);
        }}>
          {testing ? "Test en cours…" : "Tester la connexion"}
        </button>
        <button className="btn small">Enregistrer</button>
        {testResult === "ok" && <span className="pill ok"><Icons.check size={11}/> Connexion établie</span>}
      </div>
    </div>
  );
}

function SFournisseurs() {
  const initialProviders = [
    { id: "netflix",       name: "Netflix",            group: "Netflix",      enabled: true },
    { id: "netflixads",    name: "Netflix with ads",   group: "Netflix",      enabled: true },
    { id: "disneyplus",    name: "Disney+",            group: "Disney+",      enabled: true },
    { id: "disneyplusads", name: "Disney+ with ads",   group: "Disney+",      enabled: false },
    { id: "primevideo",    name: "Prime Video",        group: "Prime Video",  enabled: true },
    { id: "primevideoads", name: "Prime Video with ads", group: "Prime Video", enabled: false },
    { id: "appletv",       name: "Apple TV+",          group: "Apple TV+",    enabled: true },
    { id: "max",           name: "Max",                group: "Max",          enabled: true },
    { id: "maxads",        name: "Max with ads",       group: "Max",          enabled: false },
    { id: "paramountplus", name: "Paramount+",         group: "Paramount+",   enabled: false },
    { id: "canalplus",     name: "Canal+",             group: "Canal+",       enabled: false },
    { id: "ocs",           name: "OCS",                group: "Autres",       enabled: false },
    { id: "crunchyroll",   name: "Crunchyroll",        group: "Crunchyroll",  enabled: true },
    { id: "adn",           name: "ADN",                group: "Autres",       enabled: false },
    { id: "hidive",        name: "HIDIVE",             group: "Autres",       enabled: false },
    { id: "mubi",          name: "Mubi",               group: "Autres",       enabled: false },
    { id: "francetv",      name: "France.tv",          group: "Autres",       enabled: false },
    { id: "tf1plus",       name: "TF1+",               group: "Autres",       enabled: false },
  ];
  const [providers, setProviders] = React.useState(initialProviders);
  const [extraGroups, setExtraGroups] = React.useState([]); // custom groups created via UI
  const [query, setQuery] = React.useState("");
  const [editingGroup, setEditingGroup] = React.useState(null);
  const [assignFor, setAssignFor] = React.useState(null); // provider id being assigned to a group

  const setOne = (id, patch) => setProviders(arr => arr.map(p => p.id === id ? {...p, ...patch} : p));
  const setGroupEnabled = (group, val) => setProviders(arr => arr.map(p => p.group === group ? {...p, enabled: val} : p));
  const setAll = (val) => setProviders(arr => arr.map(p => ({...p, enabled: val})));

  const filtered = providers.filter(p => !query || (p.name + " " + p.group).toLowerCase().includes(query.toLowerCase()));

  // Build group list — keep stable order: "Autres" last
  const allGroupsRaw = Array.from(new Set([...providers.map(p => p.group), ...extraGroups]));
  const allGroups = [...allGroupsRaw.filter(g => g !== "Autres").sort(), "Autres"].filter(g => allGroupsRaw.includes(g));
  const visibleGroups = allGroups.filter(g => filtered.some(p => p.group === g));

  const enabledCount = providers.filter(p => p.enabled).length;

  const renameGroup = (oldName, newName) => {
    const n = newName.trim();
    if (!n || n === oldName) { setEditingGroup(null); return; }
    setProviders(arr => arr.map(p => p.group === oldName ? {...p, group: n} : p));
    setExtraGroups(arr => arr.filter(g => g !== oldName));
    setEditingGroup(null);
  };

  const createGroup = () => {
    const name = prompt("Nom du nouveau regroupement :");
    if (name && name.trim()) {
      const n = name.trim();
      if (!allGroups.includes(n)) setExtraGroups(g => [...g, n]);
    }
  };

  return (
    <div>
      <SectionHeader title="Fournisseurs streaming" desc="Activez les fournisseurs visibles dans la bibliothèque et organisez-les par regroupement."/>

      <div className="row gap-3" style={{marginBottom: 16, flexWrap: "wrap"}}>
        <div className="row gap-2">
          <span className="health"><span className="dot"/> {enabledCount} actif(s)</span>
          <span className="pill">{providers.length - enabledCount} masqué(s)</span>
          <span className="pill">{allGroups.length} regroupement(s)</span>
        </div>
        <div style={{flex: 1}}/>
        <div className="search" style={{minWidth: 200, flex: 0}}>
          <Icons.search size={14}/>
          <input placeholder="Rechercher un fournisseur…" value={query} onChange={e => setQuery(e.target.value)}/>
        </div>
        <button className="btn small" onClick={createGroup}><Icons.plus size={13}/> Nouveau groupe</button>
        <button className="btn small" onClick={() => setAll(true)}>Tout activer</button>
        <button className="btn small" onClick={() => setAll(false)}>Tout désactiver</button>
      </div>

      <div className="col gap-3">
        {visibleGroups.map(group => {
          const items = filtered.filter(p => p.group === group);
          const isOthers = group === "Autres";
          const allOn = items.length > 0 && items.every(p => p.enabled);
          const someOn = items.some(p => p.enabled);
          return (
            <div key={group} style={{background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden"}}>
              <div style={{padding: "12px 16px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10}}>
                <div className="row gap-3">
                  <div style={{
                    width: 30, height: 30, borderRadius: 7,
                    background: isOthers ? "var(--panel-3)" : (allOn ? "var(--accent)" : someOn ? "var(--accent-soft)" : "var(--panel-3)"),
                    color:      isOthers ? "var(--muted)" : (allOn ? "var(--on-accent)" : someOn ? "var(--accent)" : "var(--muted)"),
                    display: "grid", placeItems: "center", fontSize: 12, fontWeight: 700,
                  }}>{group[0]}</div>
                  <div>
                    <div className="row gap-2">
                      <span style={{fontWeight: 600, fontSize: 14}}>{group}</span>
                      {isOthers && <span className="pill">par défaut</span>}
                      {items.length > 1 && !isOthers && <span className="pill">{items.length} variantes</span>}
                    </div>
                    <div className="muted" style={{fontSize: 11.5, marginTop: 2}}>
                      {items.filter(p => p.enabled).length} sur {items.length} actifs
                    </div>
                  </div>
                </div>
                <div className="row gap-3">
                  {!isOthers && (
                    <button className="btn small ghost" onClick={() => setEditingGroup(editingGroup === group ? null : group)}>
                      {editingGroup === group ? "Fermer" : "Renommer"}
                    </button>
                  )}
                  <Toggle value={allOn} onChange={(v) => setGroupEnabled(group, v)}/>
                </div>
              </div>
              {editingGroup === group && (
                <div style={{padding: "12px 16px", background: "var(--panel)", borderBottom: "1px solid var(--border-soft)"}}>
                  <div className="row gap-3" style={{alignItems: "center"}}>
                    <div className="muted" style={{fontSize: 12, minWidth: 140}}>Nom du regroupement</div>
                    <input className="field" defaultValue={group} style={{flex: 1, minWidth: 0}}
                      autoFocus
                      onKeyDown={(e) => { if (e.key === "Enter") renameGroup(group, e.target.value); if (e.key === "Escape") setEditingGroup(null); }}
                      onBlur={(e) => renameGroup(group, e.target.value)}/>
                    <div className="muted" style={{fontSize: 11.5}}>Entrée pour valider</div>
                  </div>
                </div>
              )}
              <div>
                {items.map((p, idx) => (
                  <div key={p.id} className="row" style={{
                    padding: "10px 16px",
                    borderBottom: idx === items.length - 1 ? 0 : "1px solid var(--border-soft)",
                    justifyContent: "space-between", gap: 10,
                    position: "relative",
                  }}>
                    <div className="row gap-2" style={{flex: 1, minWidth: 0}}>
                      <span style={{
                        width: 6, height: 6, borderRadius: "50%",
                        background: p.enabled ? "var(--ok)" : "var(--border-strong)",
                        flex: "none",
                      }}/>
                      <span style={{fontSize: 13, fontWeight: 500}}>{p.name}</span>
                      {p.name !== p.group && !isOthers && <span className="pill">variante</span>}
                    </div>
                    <div className="row gap-2">
                      <div style={{position: "relative"}}>
                        <button className="btn small ghost" data-assign-trigger={p.id}
                          onClick={(e) => setAssignFor(assignFor === p.id ? null : p.id)}
                          title="Changer de regroupement">
                          <Icons.folder size={12}/> {p.group}
                          <Icons.chevronDown size={11}/>
                        </button>
                      </div>
                      <Toggle value={p.enabled} onChange={(v) => setOne(p.id, { enabled: v })}/>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
        {visibleGroups.length === 0 && <div className="empty">Aucun fournisseur ne correspond.</div>}
      </div>

      {assignFor && (() => {
        const p = providers.find(x => x.id === assignFor);
        if (!p) return null;
        return (
          <AssignPopover
            triggerSelector={`[data-assign-trigger="${assignFor}"]`}
            provider={p}
            allGroups={allGroups}
            onPick={(g) => { setOne(p.id, { group: g }); setAssignFor(null); }}
            onNewGroup={() => {
              const name = prompt("Nom du nouveau regroupement :");
              if (name && name.trim()) {
                setOne(p.id, { group: name.trim() });
                setAssignFor(null);
              }
            }}
            onClose={() => setAssignFor(null)}/>
        );
      })()}
    </div>
  );
}

function AssignPopover({ provider, allGroups, onPick, onNewGroup, onClose, triggerSelector }) {
  const [pos, setPos] = React.useState(null);

  React.useLayoutEffect(() => {
    const trigger = document.querySelector(triggerSelector);
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const popWidth = 240;
    const popHeight = Math.min(320, 60 + allGroups.length * 32);
    let top = rect.bottom + 6;
    let left = rect.right - popWidth;
    // flip up if overflow bottom
    if (top + popHeight > window.innerHeight - 12) top = Math.max(12, rect.top - popHeight - 6);
    // clamp left
    if (left < 12) left = 12;
    setPos({ top, left, width: popWidth });
  }, [triggerSelector, allGroups.length]);

  React.useEffect(() => {
    const close = (e) => {
      if (!e.target.closest(".assign-pop") && !e.target.closest(triggerSelector)) onClose();
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [onClose, triggerSelector]);

  if (!pos) return null;

  return (
    <div className="assign-pop" style={{
      position: "fixed",
      top: pos.top, left: pos.left,
      width: pos.width, maxHeight: 320, overflow: "auto",
      background: "var(--panel)",
      border: "1px solid var(--border)",
      borderRadius: 10,
      boxShadow: "var(--shadow-lg)",
      padding: 6,
      zIndex: 1000,
    }}>
      <div className="muted" style={{padding: "6px 10px", fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em"}}>
        Assigner à un groupe
      </div>
      {allGroups.map(g => (
        <div key={g} onClick={() => onPick(g)} style={{
          padding: "7px 10px", borderRadius: 6, cursor: "pointer", fontSize: 13,
          display: "flex", alignItems: "center", justifyContent: "space-between",
          background: provider.group === g ? "var(--accent-soft)" : "transparent",
          color: provider.group === g ? "var(--accent)" : "var(--text-2)",
          fontWeight: provider.group === g ? 600 : 500,
        }}
        onMouseEnter={e => { if (provider.group !== g) e.currentTarget.style.background = "var(--hover)"; }}
        onMouseLeave={e => { if (provider.group !== g) e.currentTarget.style.background = "transparent"; }}>
          <span>{g}</span>
          {provider.group === g && <Icons.check size={13}/>}
        </div>
      ))}
      <div className="divider" style={{margin: "4px 0"}}/>
      <div onClick={onNewGroup} style={{
        padding: "7px 10px", borderRadius: 6, cursor: "pointer", fontSize: 13,
        display: "flex", alignItems: "center", gap: 8, color: "var(--accent)", fontWeight: 500,
      }}
      onMouseEnter={e => e.currentTarget.style.background = "var(--hover)"}
      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
        <Icons.plus size={13}/> Nouveau regroupement…
      </div>
    </div>
  );
}

function SApparence({ theme, setTheme, accent, setAccent }) {
  const accents = [
    { name: "Bleu doux",   v: "#6ba4e8" },
    { name: "Indigo",      v: "#7a7af0" },
    { name: "Émeraude",    v: "#4cc086" },
    { name: "Ambre",       v: "#e8a44a" },
    { name: "Rose",        v: "#e87aa4" },
    { name: "Violet",      v: "#9c6bd9" },
    { name: "Cyan",        v: "#4ec1c9" },
    { name: "Corail",      v: "#ed7a6b" },
  ];
  return (
    <div>
      <SectionHeader title="Apparence" desc="Personnalisez le thème et les couleurs de l'application."/>

      <SettingRow label="Thème" desc="Choisissez l'apparence claire ou sombre">
        <div className="btn-group">
          <div className={`seg ${theme === "light" ? "active" : ""}`} onClick={() => setTheme("light")}>
            <Icons.sun size={13} style={{verticalAlign: "middle", marginRight: 4}}/> Clair
          </div>
          <div className={`seg ${theme === "dark" ? "active" : ""}`} onClick={() => setTheme("dark")}>
            <Icons.moon size={13} style={{verticalAlign: "middle", marginRight: 4}}/> Sombre
          </div>
          <div className={`seg ${theme === "system" ? "active" : ""}`} onClick={() => setTheme("system")}>Système</div>
        </div>
      </SettingRow>

      <div className="setting-block">
        <div className="setting-row">
          <div>
            <div className="label">Couleur d'accent</div>
            <div className="desc">Utilisée pour les boutons, liens et états actifs</div>
          </div>
          <div className="row gap-3" style={{alignItems: "center"}}>
            <div className="swatch-row">
              {accents.map(s => (
                <div key={s.v} className={`swatch ${accent === s.v ? "active" : ""}`}
                     style={{background: s.v}} onClick={() => setAccent(s.v)} title={s.name}/>
              ))}
            </div>
            <div style={{width: 1, height: 24, background: "var(--border)"}}/>
            <label className="row gap-2" style={{cursor: "pointer"}}>
              <input type="color" value={accent} onChange={e => setAccent(e.target.value)} style={{width: 28, height: 28, border: 0, padding: 0, borderRadius: 8, cursor: "pointer", background: "transparent"}}/>
              <span className="mono" style={{fontSize: 12.5, color: "var(--text-2)"}}>{accent.toUpperCase()}</span>
            </label>
          </div>
        </div>
      </div>

      <SettingRow label="Langue" desc="Langue de l'interface">
        <select className="field"><option>🇫🇷 Français</option><option>🇬🇧 English</option></select>
      </SettingRow>
    </div>
  );
}

function SSysteme() {
  return (
    <div>
      <SectionHeader title="Système" desc="Tâches automatiques, journalisation et maintenance."/>

      <SettingRow label="Scan automatique (cron)" desc="Tous les jours à 04h00">
        <input className="field mono" defaultValue="0 4 * * *" style={{width: 140}}/>
      </SettingRow>

      <SettingRow label="Niveau de log" desc={<>Logs accessibles sur l'hôte : <span className="mono">./data/scanner.log</span></>}>
        <select className="field"><option>DEBUG</option><option>INFO</option><option>WARNING</option><option>ERROR</option></select>
      </SettingRow>

      <SettingRow label="Conservation des sauvegardes" desc="Nombre de jours avant suppression automatique">
        <input className="field sm mono" defaultValue="30" style={{width: 70, textAlign: "right"}}/>
      </SettingRow>

      <SettingRow label="Zone dangereuse" desc="Actions irréversibles sur l'instance">
        <button className="btn danger"><Icons.trash size={13}/> Réinitialiser la base</button>
      </SettingRow>
    </div>
  );
}

function SCompte() {
  const [auth, setAuth] = React.useState(true);
  return (
    <div>
      <SectionHeader title="Compte" desc="Informations de connexion et sécurité."/>
      <SettingRow label="Nom d'utilisateur" desc="Visible dans la barre supérieure">
        <input className="field" defaultValue="admin"/>
      </SettingRow>
      <SettingRow label="Email" desc="Utilisé pour les notifications">
        <input className="field" defaultValue="admin@magicgg.fr"/>
      </SettingRow>
      <SettingRow label="Session active depuis" desc="Connexion via mot de passe">
        <span className="muted mono" style={{fontSize: 13}}>20 mai 2026 — 09:42</span>
      </SettingRow>

      <div className="setting-block">
        <div className="label" style={{marginBottom: 4}}>Authentification</div>
        <div className="desc" style={{marginBottom: 12}}>Sécurisez l'accès à votre médiathèque</div>

        <SettingRow label="Authentification par mot de passe" desc="Demande un mot de passe à la connexion">
          <Toggle value={auth} onChange={setAuth}/>
        </SettingRow>

        {auth && (
          <div style={{background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 10, padding: 16}}>
            <div className="col gap-3">
              <div className="row gap-3" style={{alignItems: "center"}}>
                <div className="muted" style={{fontSize: 12, minWidth: 140}}>Nouveau mot de passe</div>
                <input type="password" className="field" style={{flex: 1, minWidth: 0}}/>
              </div>
              <div className="row gap-3" style={{alignItems: "center"}}>
                <div className="muted" style={{fontSize: 12, minWidth: 140}}>Confirmation</div>
                <input type="password" className="field" style={{flex: 1, minWidth: 0}}/>
              </div>
              <ul className="muted" style={{fontSize: 12, margin: "6px 0 0 20px", padding: 0}}>
                <li>25 caractères minimum</li>
                <li>Au moins 2 lettres minuscules</li>
                <li>Au moins 2 lettres majuscules</li>
                <li>Au moins 2 chiffres</li>
              </ul>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { PageParametres });
