// MyMediaLibrary — shared icons & primitives
// Loaded as Babel script. Exports to window.

const Icon = ({ d, size = 16, sw = 1.8, fill = "none", style }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke="currentColor" strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" style={style}>
    {typeof d === "string" ? <path d={d} /> : d}
  </svg>
);

const Icons = {
  home: (p) => <Icon {...p} d="M3 11.5L12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1v-8.5z" />,
  library: (p) => <Icon {...p} d={<><rect x="3" y="3" width="7" height="18" rx="1.5"/><rect x="13" y="3" width="7" height="11" rx="1.5"/><path d="M13 17h7"/><path d="M13 21h7"/></>} />,
  stats: (p) => <Icon {...p} d={<><path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-8"/><path d="M22 20H2"/></>} />,
  bulb: (p) => <Icon {...p} d={<><path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7c.8.6 1.3 1.4 1.4 2.3h5.2c.1-.9.6-1.7 1.4-2.3A7 7 0 0 0 12 2z"/></>} />,
  settings: (p) => <Icon {...p} d={<><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .4 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.4 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.4l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .4-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.4-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.4h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1c0 .7.4 1.3 1 1.5a1.7 1.7 0 0 0 1.9-.4l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.4 1.9v0c.2.6.8 1 1.5 1H21a2 2 0 1 1 0 4h-.1c-.7 0-1.3.4-1.5 1z"/></>} />,
  search: (p) => <Icon {...p} d={<><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></>} />,
  scan: (p) => <Icon {...p} d={<><path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7 12h10"/></>} />,
  sun: (p) => <Icon {...p} d={<><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m4.93 19.07 1.41-1.41"/><path d="m17.66 6.34 1.41-1.41"/></>} />,
  moon: (p) => <Icon {...p} d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />,
  film: (p) => <Icon {...p} d={<><rect x="2" y="3" width="20" height="18" rx="2"/><path d="M7 3v18"/><path d="M17 3v18"/><path d="M2 8h5"/><path d="M2 16h5"/><path d="M17 8h5"/><path d="M17 16h5"/><path d="M7 12h10"/></>} />,
  tv: (p) => <Icon {...p} d={<><rect x="2" y="6" width="20" height="13" rx="2"/><path d="M8 21h8"/><path d="m7 6 5-4 5 4"/></>} />,
  folder: (p) => <Icon {...p} d="M3 7a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />,
  hardDrive: (p) => <Icon {...p} d={<><path d="M22 12H2"/><path d="m5.5 5 13 0a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"/><path d="M6 16h.01"/><path d="M10 16h.01"/></>} />,
  file: (p) => <Icon {...p} d={<><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></>} />,
  trendUp: (p) => <Icon {...p} d={<><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></>} />,
  trendDown: (p) => <Icon {...p} d={<><polyline points="22 17 13.5 8.5 8.5 13.5 2 7"/><polyline points="16 17 22 17 22 11"/></>} />,
  chevronRight: (p) => <Icon {...p} d="m9 6 6 6-6 6" />,
  chevronDown: (p) => <Icon {...p} d="m6 9 6 6 6-6" />,
  download: (p) => <Icon {...p} d={<><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></>} />,
  refresh: (p) => <Icon {...p} d={<><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/></>} />,
  bell: (p) => <Icon {...p} d={<><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></>} />,
  clock: (p) => <Icon {...p} d={<><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/></>} />,
  warn: (p) => <Icon {...p} d={<><path d="M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></>} />,
  check: (p) => <Icon {...p} d="m5 12 5 5 10-10" />,
  x: (p) => <Icon {...p} d={<><path d="M18 6 6 18"/><path d="m6 6 12 12"/></>} />,
  plus: (p) => <Icon {...p} d={<><path d="M12 5v14"/><path d="M5 12h14"/></>} />,
  filter: (p) => <Icon {...p} d="M22 3H2l8 9.5V19l4 2v-8.5L22 3z" />,
  grid: (p) => <Icon {...p} d={<><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/></>} />,
  list: (p) => <Icon {...p} d={<><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></>} />,
  logout: (p) => <Icon {...p} d={<><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></>} />,
  globe: (p) => <Icon {...p} d={<><circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18z"/></>} />,
  link: (p) => <Icon {...p} d={<><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></>} />,
  shield: (p) => <Icon {...p} d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />,
  sparkles: (p) => <Icon {...p} d={<><path d="m12 3-1.9 5.1L5 10l5.1 1.9L12 17l1.9-5.1L19 10l-5.1-1.9z"/><path d="M5 3v4"/><path d="M19 17v4"/><path d="M3 5h4"/><path d="M17 19h4"/></>} />,
  zap: (p) => <Icon {...p} d="m13 2-9 12h7l-1 8 9-12h-7l1-8z" />,
  trash: (p) => <Icon {...p} d={<><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></>} />,
  user: (p) => <Icon {...p} d={<><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>} />,
  log: (p) => <Icon {...p} d={<><path d="M4 4h16v16H4z"/><path d="M8 9h8M8 13h8M8 17h5"/></>} />,
  key: (p) => <Icon {...p} d={<><circle cx="7" cy="14" r="4"/><path d="m10 11 11-11"/><path d="m17 4 3 3"/><path d="m14 7 3 3"/></>} />,
  language: (p) => <Icon {...p} d={<><path d="M5 8h14"/><path d="M9 4v4"/><path d="M3 16c4-3 6-3 6-7"/><path d="m7 11 5 5"/><path d="M14 22h7l-3.5-9z"/><path d="M15 19h5"/></>} />,
  flame: (p) => <Icon {...p} d="M8.5 14.5A2.5 2.5 0 0 0 11 17c2 0 4-2 4-4.5C15 9 12 7 12 4c-2 2-5 5-5 8.5a5 5 0 0 0 5 5 5 5 0 0 0 5-5C17 9 14 7 14 4" />,
  database: (p) => <Icon {...p} d={<><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 11v6c0 1.7 4 3 9 3s9-1.3 9-3v-6"/></>} />,
  award: (p) => <Icon {...p} d={<><circle cx="12" cy="9" r="6"/><polyline points="8.5 13.5 6 22 12 18 18 22 15.5 13.5"/></>} />,
  filmReel: (p) => <Icon {...p} d={<><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="19" r="1.5"/><circle cx="5" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/></>} />,
};

// Donut chart (SVG)
function Donut({ data, size = 140, thickness = 18, total, centerLabel, centerValue }) {
  const sum = total || data.reduce((s, d) => s + d.value, 0);
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  let offset = 0;
  const segs = data.map((d, i) => {
    const frac = sum > 0 ? d.value / sum : 0;
    const len = c * frac;
    const seg = (
      <circle key={i}
        cx={size/2} cy={size/2} r={r}
        fill="none"
        stroke={d.color}
        strokeWidth={thickness}
        strokeDasharray={`${len} ${c - len}`}
        strokeDashoffset={-offset}
        strokeLinecap="butt"
        transform={`rotate(-90 ${size/2} ${size/2})`}
      />
    );
    offset += len;
    return seg;
  });
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="var(--panel-3)" strokeWidth={thickness} />
      {segs}
      {centerValue !== undefined && (
        <>
          <text x={size/2} y={size/2 - 4} textAnchor="middle" fill="var(--text)" fontSize="20" fontWeight="600" fontFamily="var(--font-mono)">{centerValue}</text>
          <text x={size/2} y={size/2 + 14} textAnchor="middle" fill="var(--muted)" fontSize="10" letterSpacing="0.08em">{centerLabel}</text>
        </>
      )}
    </svg>
  );
}

function DonutCard({ title, data, centerLabel, centerValue, action }) {
  const sum = data.reduce((s, d) => s + d.value, 0);
  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">{title}</div>
        {action}
      </div>
      <div className="donut-wrap">
        <Donut data={data} centerLabel={centerLabel} centerValue={centerValue ?? sum} />
        <div className="donut-legend">
          {data.map((d, i) => (
            <div className="dl-row" key={i}>
              <div className="dl-label"><span className="dl-dot" style={{background: d.color}}></span>{d.label}</div>
              <div className="dl-value">{d.display ?? d.value.toLocaleString("fr-FR")}</div>
              <div className="dl-pct">{sum > 0 ? ((d.value / sum) * 100).toFixed(1) : 0}%</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function BarList({ data, formatter = (v)=>v.toLocaleString("fr-FR"), max, total }) {
  const sum = total ?? data.reduce((s, d) => s + d.value, 0);
  const m = max ?? (total ? total : Math.max(...data.map(d=>d.value), 1));
  return (
    <div>
      {data.map((d, i) => (
        <div className="bar-row" key={i}>
          <div className="bar-label">{d.label}</div>
          <div className="bar-track"><div className="bar-fill" style={{width: `${(d.value/m)*100}%`, background: d.color || "var(--accent)"}}></div></div>
          <div className="bar-value">{formatter(d.value, d)}</div>
        </div>
      ))}
    </div>
  );
}

function Toggle({ value, onChange }) {
  return <div className={`toggle ${value ? "on" : ""}`} onClick={() => onChange(!value)} role="switch" aria-checked={value}/>;
}

function Tabs({ items, value, onChange }) {
  return (
    <div className="tabs">
      {items.map(it => (
        <div key={it.value} className={`tab ${value === it.value ? "active" : ""}`} onClick={() => onChange(it.value)}>
          {it.icon} {it.label}
        </div>
      ))}
    </div>
  );
}

function Stat({ label, value, icon, foot, accent, trend }) {
  return (
    <div className={`stat ${accent ? "accent" : ""}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {foot && <div className="stat-foot">{foot}</div>}
      {icon && <div className="stat-icon">{icon}</div>}
      {trend && (
        <div className="trend">
          {trend.map((v, i) => <span key={i} className={v > 0.7 ? "high" : ""} style={{height: `${Math.max(8, v*100)}%`}}/>)}
        </div>
      )}
    </div>
  );
}

Object.assign(window, { Icon, Icons, Donut, DonutCard, BarList, Toggle, Tabs, Stat });
