/* MyMediaLibrary — refonte
   Theming via CSS variables on .theme-light / .theme-dark
   Accent is injected as --accent via inline style on root.
*/

:root {
  --r-sm: 6px;
  --r: 10px;
  --r-lg: 14px;
  --r-xl: 20px;

  --sp-1: 4px;
  --sp-2: 8px;
  --sp-3: 12px;
  --sp-4: 16px;
  --sp-5: 20px;
  --sp-6: 24px;
  --sp-8: 32px;
  --sp-10: 40px;

  --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.04);
  --shadow:    0 2px 8px rgba(15, 23, 42, 0.06), 0 1px 2px rgba(15,23,42,0.04);
  --shadow-lg: 0 12px 32px rgba(15, 23, 42, 0.12), 0 2px 6px rgba(15,23,42,0.06);

  --font-sans: "Helvetica Neue", Helvetica, "Segoe UI", Arial, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.theme-light {
  --bg:           #f5f6f9;
  --bg-grad:      radial-gradient(1200px 600px at 80% -10%, rgba(107,164,232,0.10), transparent 60%),
                  radial-gradient(900px 500px at -10% 110%, rgba(107,164,232,0.06), transparent 60%),
                  #f5f6f9;
  --panel:        #ffffff;
  --panel-2:      #fafbfd;
  --panel-3:      #f3f5f9;
  --hover:        #f0f3f8;
  --border:       #e3e6ee;
  --border-soft:  #ecedf2;
  --border-strong:#cfd4e0;
  --text:         #131722;
  --text-2:       #404656;
  --muted:        #8089a0;
  --muted-2:      #aab2c5;
  --accent-soft:  color-mix(in oklch, var(--accent) 14%, var(--panel));
  --accent-hover: color-mix(in oklch, var(--accent) 90%, black);
  --on-accent:    #ffffff;
  --danger:       #e44848;
  --warn:         #e89234;
  --ok:           #36a36a;
  --chart-1:      var(--accent);
  --chart-2:      #8a76e3;
  --chart-3:      #ee8a6a;
  --chart-4:      #4ec1a4;
  --chart-5:      #e8b441;
  --chart-6:      #d05b8a;
  --chart-7:      #6e7a90;
}

.theme-dark {
  --bg:           #0f1117;
  --bg-grad:      radial-gradient(1200px 600px at 85% -15%, color-mix(in oklch, var(--accent) 18%, transparent), transparent 60%),
                  radial-gradient(900px 500px at -10% 110%, color-mix(in oklch, var(--accent) 8%, transparent), transparent 60%),
                  #0f1117;
  --panel:        #171a23;
  --panel-2:      #1b1f2a;
  --panel-3:      #20242f;
  --hover:        #1f2330;
  --border:       #262b38;
  --border-soft:  #1f2330;
  --border-strong:#363c4d;
  --text:         #eef0f6;
  --text-2:       #b9c0d0;
  --muted:        #7a8197;
  --muted-2:      #5c6378;
  --accent-soft:  color-mix(in oklch, var(--accent) 18%, var(--panel));
  --accent-hover: color-mix(in oklch, var(--accent) 88%, white);
  --on-accent:    #0b1019;
  --danger:       #ef6464;
  --warn:         #f0a352;
  --ok:           #4cc086;
  --chart-1:      var(--accent);
  --chart-2:      #9886ef;
  --chart-3:      #f29c7c;
  --chart-4:      #5dd6b8;
  --chart-5:      #f4c25b;
  --chart-6:      #e07ca4;
  --chart-7:      #8c95ac;
}

* { box-sizing: border-box; }
html, body, #root { height: 100%; margin: 0; }
body {
  font-family: var(--font-sans);
  color: var(--text);
  background: var(--bg-grad);
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

/* utility */
.mono { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.muted { color: var(--muted); }
.text-2 { color: var(--text-2); }
.row { display: flex; align-items: center; }
.col { display: flex; flex-direction: column; }
.gap-1 { gap: 4px; } .gap-2 { gap: 8px; } .gap-3 { gap: 12px; }
.gap-4 { gap: 16px; } .gap-5 { gap: 20px; } .gap-6 { gap: 24px; }
.spread { display: flex; align-items: center; justify-content: space-between; }
.divider { height: 1px; background: var(--border); width: 100%; }
.pill { display:inline-flex; align-items:center; gap:6px; padding: 3px 9px; border-radius: 999px; font-size: 11px; line-height: 1.4; background: var(--panel-3); color: var(--text-2); border: 1px solid var(--border-soft); font-weight: 500; }
.pill.accent { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
.pill.warn { background: color-mix(in oklch, var(--warn) 16%, var(--panel)); color: var(--warn); border-color: transparent; }
.pill.danger { background: color-mix(in oklch, var(--danger) 16%, var(--panel)); color: var(--danger); border-color: transparent; }
.pill.ok { background: color-mix(in oklch, var(--ok) 16%, var(--panel)); color: var(--ok); border-color: transparent; }

/* ---------- Layout ---------- */
.app {
  display: grid;
  grid-template-columns: 56px 1fr;
  height: 100vh;
  overflow: hidden;
}
.app.has-filters { grid-template-columns: 56px 280px 1fr; }
.app.sidebar-open { grid-template-columns: 220px 1fr; }
.app.sidebar-open.has-filters { grid-template-columns: 220px 280px 1fr; }

/* ---------- Mini sidebar (icon rail) ---------- */
.sidebar.mini {
  background: var(--panel);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
  padding: 10px 8px 10px;
  position: relative;
  z-index: 3;
  align-items: center;
  gap: 6px;
  transition: padding .15s;
}
.sidebar.mini.expanded { padding: 12px 10px 12px; align-items: stretch; }

.brand.mini {
  display: flex; align-items: center; gap: 10px;
  padding: 4px 0 10px;
  width: 100%;
  position: relative;
  justify-content: center;
}
.sidebar.mini.expanded .brand.mini { justify-content: flex-start; padding-left: 4px; }

.nav-section.mini {
  display: flex; flex-direction: column;
  gap: 4px;
  width: 100%;
}
.nav-item.mini {
  position: relative;
  width: 40px; height: 40px;
  border-radius: 9px;
  display: grid; place-items: center;
  margin: 0 auto;
  background: transparent;
  border: none;
  color: var(--text-2);
  cursor: pointer;
  transition: background .12s, color .12s;
  font-family: inherit;
}
.sidebar.mini.expanded .nav-item.mini {
  width: 100%;
  height: 36px;
  display: flex; align-items: center;
  gap: 10px;
  padding: 0 10px;
  justify-content: flex-start;
  margin: 0;
}
.nav-item.mini:hover { background: var(--hover); color: var(--text); }
.nav-item.mini.active { background: var(--accent-soft); color: var(--accent); }
.nav-item.mini svg { width: 18px; height: 18px; flex: none; }
.nav-item-label {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: flex; flex-direction: column; gap: 1px;
  text-align: left;
}
.nav-item-label .nav-item-sub {
  font-size: 10.5px;
  color: var(--muted);
  font-weight: 400;
}
.nav-item.mini.active .nav-item-label { font-weight: 600; }

/* tooltip only when sidebar is collapsed */
.nav-item.mini[data-tip]::after {
  content: attr(data-tip);
  position: absolute;
  left: calc(100% + 10px);
  top: 50%;
  transform: translateY(-50%);
  background: var(--panel-3);
  color: var(--text);
  border: 1px solid var(--border);
  padding: 5px 9px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity .12s;
  box-shadow: var(--shadow-lg);
  z-index: 200;
}
.nav-item.mini:hover[data-tip]::after { opacity: 1; }
.sidebar.mini.expanded .nav-item.mini[data-tip]::after { display: none; }

.nav-item.mini.filter-toggle .filter-toggle-badge {
  position: absolute;
  top: 4px; right: 4px;
  min-width: 16px; height: 16px;
  background: var(--accent);
  color: var(--on-accent);
  font-size: 9.5px;
  font-weight: 700;
  border-radius: 999px;
  display: grid; place-items: center;
  padding: 0 4px;
  border: 1.5px solid var(--panel);
}
.sidebar.mini.expanded .nav-item.mini.filter-toggle .filter-toggle-badge {
  position: static;
  margin-left: auto;
  border: none;
}
.sidebar-foot.mini { margin-top: auto; padding-top: 8px; width: 100%; display: flex; flex-direction: column; gap: 4px; }
.sidebar-foot.mini .nav-item.mini.scan-btn { color: var(--accent); background: var(--accent-soft); }
.sidebar-foot.mini .nav-item.mini.scan-btn.scanning svg { animation: spin 1.2s linear infinite; }
.nav-item.mini.collapse-btn { color: var(--muted); }
.nav-item.mini.collapse-btn:hover { color: var(--text); background: var(--hover); }
.nav-item.mini.collapse-btn svg { width: 17px; height: 17px; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ---------- Filters rail ---------- */
.filters-rail {
  background: var(--panel);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
  position: relative;
  z-index: 1;
  overflow: hidden;
}
.filters-scroll {
  overflow: auto;
  padding: 14px 14px 24px;
  display: flex; flex-direction: column; gap: 14px;
}
.filter-reset {
  display: inline-flex; align-items: center; gap: 6px;
  align-self: flex-start;
  background: var(--panel-2);
  border: 1px solid var(--border);
  color: var(--text-2);
  font-size: 12px;
  padding: 7px 10px;
  border-radius: 8px;
  cursor: pointer;
}
.filter-reset:hover { background: var(--hover); color: var(--text); }
.filter-reset svg { color: var(--muted); }

.filter-group { display: flex; flex-direction: column; gap: 8px; }
.filter-group.tight { gap: 6px; }
.filter-label {
  font-size: 10.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  font-weight: 600;
}

/* segmented control (Disponibilité / Type) */
.filter-seg {
  display: flex; gap: 4px;
  background: var(--panel-3);
  padding: 3px;
  border-radius: 9px;
  border: 1px solid var(--border);
  width: 100%;
  overflow: hidden;
}
.seg-pill {
  flex: 1 1 0;
  min-width: 0;
  background: transparent;
  border: none;
  color: var(--text-2);
  font-size: 11.5px;
  font-weight: 500;
  padding: 6px 6px;
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.seg-pill:hover { color: var(--text); }
.seg-pill.active {
  background: var(--accent);
  color: var(--on-accent);
  box-shadow: 0 1px 2px rgba(0,0,0,0.15);
}

/* multi-select dropdown */
.md-wrap { position: relative; }
.md-trigger {
  width: 100%;
  display: flex; align-items: center; justify-content: space-between;
  gap: 8px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  color: var(--text);
  font-size: 12.5px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
}
.md-trigger:hover { border-color: var(--border-strong, var(--border)); background: var(--hover); }
.md-trigger.open { border-color: var(--accent); }
.md-trigger.filled .md-value { color: var(--text); font-weight: 500; }
.md-value {
  flex: 1;
  display: inline-flex; align-items: center; gap: 6px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  color: var(--text-2);
}
.md-value.exc { color: var(--danger); }
.md-mode-tag {
  display: inline-block;
  font-size: 9.5px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 1px 5px;
  border-radius: 4px;
  background: color-mix(in oklch, var(--danger) 18%, transparent);
  color: var(--danger);
}
.md-pop {
  position: absolute;
  top: calc(100% + 4px);
  left: 0; right: 0;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: var(--shadow-lg, 0 12px 32px rgba(0,0,0,0.35));
  z-index: 50;
  padding: 6px;
  display: flex; flex-direction: column;
  gap: 4px;
  max-height: 320px;
}
.md-pop-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: 8px;
  padding: 4px 6px 6px;
  border-bottom: 1px solid var(--border);
}
.md-all { font-weight: 500; }
.md-mode {
  background: var(--panel-2);
  border: 1px solid var(--border);
  color: var(--text-2);
  font-size: 11px;
  font-weight: 600;
  padding: 4px 9px;
  border-radius: 6px;
  cursor: pointer;
}
.md-mode:hover { background: var(--hover); color: var(--text); }
.md-mode.exclude {
  background: color-mix(in oklch, var(--danger) 18%, transparent);
  border-color: color-mix(in oklch, var(--danger) 30%, transparent);
  color: var(--danger);
}
.md-pop-list {
  display: flex; flex-direction: column;
  overflow: auto;
  padding: 2px 0;
}
.md-item { padding: 5px 6px; border-radius: 5px; }
.md-item:hover { background: var(--hover); }
.md-item-label { flex: 1; color: var(--text-2); }
.md-item-count {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 11px;
}

/* checkbox row */
.filter-check {
  display: flex; align-items: center; gap: 8px;
  font-size: 12.5px; color: var(--text-2);
  cursor: pointer;
  user-select: none;
}
.filter-check input[type="checkbox"] {
  appearance: none;
  width: 14px; height: 14px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-3);
  display: grid; place-items: center;
  cursor: pointer;
  flex: none;
}
.filter-check input[type="checkbox"]:checked {
  background: var(--accent);
  border-color: var(--accent);
}
.filter-check input[type="checkbox"]:checked::after {
  content: "";
  width: 8px; height: 4px;
  border-left: 1.5px solid var(--on-accent);
  border-bottom: 1.5px solid var(--on-accent);
  transform: rotate(-45deg) translate(1px, -1px);
}

/* score range */
.score-range { display: flex; flex-direction: column; gap: 6px; }
.sr-track {
  position: relative;
  height: 8px;
  border-radius: 999px;
  overflow: visible;
}
.sr-grad {
  position: absolute; inset: 0;
  background: linear-gradient(90deg, #e35b5b 0%, #e8a44a 35%, #e8d445 55%, #6fc46a 80%, #36a36a 100%);
  border-radius: 999px;
}
.sr-mask {
  position: absolute; top: 0; bottom: 0;
  background: var(--panel-3);
  border-radius: 999px;
  opacity: 0.85;
}
.sr-thumb {
  position: absolute; top: 50%;
  width: 14px; height: 14px;
  background: var(--text);
  border: 2px solid var(--panel);
  border-radius: 50%;
  transform: translate(-50%, -50%);
  cursor: ew-resize;
  box-shadow: 0 1px 4px rgba(0,0,0,0.3);
}
.sr-readout {
  font-size: 11px;
  color: var(--muted);
  align-self: flex-end;
}

/* technique collapsible */
.tech-block {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 10px;
}
.tech-head {
  width: 100%;
  display: flex; align-items: center; justify-content: space-between;
  background: transparent;
  border: none;
  color: var(--text);
  font-size: 12.5px;
  font-weight: 500;
  padding: 10px 12px;
  cursor: pointer;
}
.tech-head:hover { color: var(--text); }
.tech-head svg { color: var(--muted); }
.tech-body {
  padding: 4px 10px 12px;
  display: flex; flex-direction: column; gap: 10px;
  border-top: 1px solid var(--border);
}

/* ---------- Sidebar ---------- */
.sidebar {
  background: var(--panel);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
  padding: 18px 14px 14px;
  position: relative;
  z-index: 2;
}
.brand {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 8px 18px;
}
.brand-mark {
  width: 30px; height: 30px; border-radius: 8px;
  background: linear-gradient(135deg, var(--accent), color-mix(in oklch, var(--accent) 60%, #6a4cb8));
  display: grid; place-items: center; color: var(--on-accent);
  font-weight: 700; font-size: 13px;
  box-shadow: 0 4px 12px color-mix(in oklch, var(--accent) 30%, transparent);
}
.brand-name { font-weight: 600; font-size: 14.5px; letter-spacing: -0.01em; }
.brand-sub { font-size: 11px; color: var(--muted); }

.nav-section { margin-top: 6px; }
.nav-label { font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted-2); padding: 10px 10px 6px; }
.nav-item {
  display: flex; align-items: center; gap: 11px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer; user-select: none;
  color: var(--text-2);
  font-weight: 500;
  font-size: 13.5px;
  transition: background .15s, color .15s;
  position: relative;
}
.nav-item:hover { background: var(--hover); color: var(--text); }
.nav-item.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}
.nav-item.active::before {
  content: "";
  position: absolute; left: -14px; top: 8px; bottom: 8px; width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--accent);
}
.nav-item svg { width: 17px; height: 17px; flex: none; }
.nav-item .nav-badge { margin-left: auto; font-size: 11px; padding: 1px 7px; background: var(--panel-3); border-radius: 999px; color: var(--muted); }
.nav-item.active .nav-badge { background: color-mix(in oklch, var(--accent) 20%, transparent); color: var(--accent); }

.sidebar-foot { margin-top: auto; padding-top: 12px; border-top: 1px solid var(--border); }
.scan-card {
  background: linear-gradient(135deg, color-mix(in oklch, var(--accent) 12%, var(--panel-2)), var(--panel-2));
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px;
  display: flex; flex-direction: column; gap: 8px;
}
.scan-card-head { display:flex; align-items:center; gap:8px; font-size: 12px; color: var(--text-2); }
.scan-status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 4px color-mix(in oklch, var(--ok) 20%, transparent); }
.scan-time { font-size: 11px; color: var(--muted); }
.scan-row { display:flex; gap: 8px; }

/* ---------- Main ---------- */
.main {
  display: flex; flex-direction: column;
  overflow: hidden;
  min-width: 0;
}
.topbar {
  height: 60px;
  display: flex; align-items: center; gap: 14px;
  padding: 0 24px;
  border-bottom: 1px solid var(--border);
  background: color-mix(in oklch, var(--panel) 70%, transparent);
  backdrop-filter: blur(10px);
  flex: none;
  position: relative;
  z-index: 1;
}
.topbar h1 { font-size: 17px; font-weight: 600; letter-spacing: -0.01em; margin: 0; }
.topbar .crumb-sub { font-size: 12px; color: var(--muted); margin-top: 1px; }

.search {
  display: flex; align-items: center; gap: 8px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 7px 12px;
  min-width: 280px;
  font-size: 13px;
  color: var(--text-2);
  flex: 1;
  max-width: 480px;
}
.search input { flex: 1; background: transparent; border: 0; outline: 0; color: var(--text); font-family: inherit; font-size: 13px; }
.search input::placeholder { color: var(--muted-2); }
.search .kbd { font-family: var(--font-mono); font-size: 10.5px; color: var(--muted); background: var(--panel-3); padding: 2px 6px; border-radius: 4px; border: 1px solid var(--border); }

.scroll {
  overflow: auto;
  padding: 24px 28px 80px;
  flex: 1;
}

/* ---------- Buttons ---------- */
.btn {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 7px 14px;
  border-radius: 8px;
  font: inherit;
  font-weight: 500;
  font-size: 13px;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text);
  cursor: pointer;
  transition: background .12s, border-color .12s, transform .04s;
}
.btn:hover { background: var(--hover); border-color: var(--border-strong); }
.btn:active { transform: translateY(0.5px); }
.btn.ghost { background: transparent; border-color: transparent; color: var(--text-2); }
.btn.ghost:hover { background: var(--hover); color: var(--text); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.btn.primary:hover { background: var(--accent-hover); border-color: var(--accent-hover); }
.btn.small { padding: 4px 10px; font-size: 12px; }
.btn.icon { padding: 7px; }
.btn.icon svg { width: 16px; height: 16px; }
.btn.danger { color: var(--danger); }
.btn-group { display:inline-flex; background: var(--panel-2); border: 1px solid var(--border); border-radius: 9px; padding: 3px; gap: 2px; }
.btn-group .seg { padding: 5px 12px; border-radius: 6px; font-size: 12.5px; color: var(--text-2); cursor: pointer; font-weight: 500; }
.btn-group .seg:hover { color: var(--text); }
.btn-group .seg.active { background: var(--panel); color: var(--text); box-shadow: var(--shadow-sm); }
.theme-dark .btn-group .seg.active { background: var(--panel-3); }

.icon-btn {
  width: 32px; height: 32px;
  border-radius: 8px;
  display: grid; place-items: center;
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-2);
  cursor: pointer;
}
.icon-btn:hover { background: var(--hover); color: var(--text); }
.icon-btn svg { width: 16px; height: 16px; }

/* ---------- Cards ---------- */
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px;
}
.card.tight { padding: 14px; }
.card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; gap: 12px; }
.card-title { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
.card-title-lg { font-size: 15px; font-weight: 600; letter-spacing: -0.005em; color: var(--text); text-transform: none; }

/* ---------- Stat ---------- */
.stat {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px 18px;
  display: flex; flex-direction: column; gap: 4px;
  position: relative; overflow: hidden;
}
.stat .stat-label { font-size: 11.5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
.stat .stat-value { font-size: 26px; font-weight: 600; letter-spacing: -0.02em; font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.stat .stat-foot { font-size: 11.5px; color: var(--muted); display: flex; align-items: center; gap: 6px; margin-top: 4px; }
.stat .stat-icon {
  position: absolute; top: 14px; right: 14px;
  width: 32px; height: 32px; border-radius: 8px;
  display: grid; place-items: center;
  background: var(--accent-soft); color: var(--accent);
}
.stat .stat-icon svg { width: 17px; height: 17px; }
.stat.accent .stat-value { color: var(--accent); }

/* Trend mini bar */
.trend { display:flex; align-items:flex-end; gap:2px; height: 24px; margin-top: 6px; }
.trend span { flex:1; background: color-mix(in oklch, var(--accent) 30%, var(--panel-3)); border-radius: 2px; }
.trend span.high { background: var(--accent); }

/* ---------- Donut / chart ---------- */
.donut-wrap { display: flex; gap: 20px; align-items: center; }
.donut-legend { display:flex; flex-direction: column; gap: 6px; flex: 1; }
.donut-legend .dl-row { display: grid; grid-template-columns: 1fr auto auto; gap: 12px; align-items: center; font-size: 12.5px; padding: 3px 0; }
.donut-legend .dl-label { color: var(--text-2); display:flex; align-items:center; gap: 8px; }
.donut-legend .dl-dot { width: 8px; height: 8px; border-radius: 50%; }
.donut-legend .dl-value { color: var(--text); font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.donut-legend .dl-pct { color: var(--muted); font-family: var(--font-mono); font-size: 11.5px; min-width: 42px; text-align: right; }

.bar-row { display: grid; grid-template-columns: 80px 1fr 80px; gap: 12px; align-items: center; font-size: 12.5px; padding: 4px 0; }
.bar-row .bar-value { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-row .bar-label { color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-row .bar-track { background: var(--panel-3); border-radius: 999px; height: 7px; overflow: hidden; }
.bar-row .bar-fill { height: 100%; border-radius: 999px; }
.bar-row .bar-value { color: var(--muted); font-family: var(--font-mono); font-size: 11.5px; text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* ---------- Page Header ---------- */
.page-head { display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 22px; gap: 16px; flex-wrap: wrap; }
.page-head h2 { font-size: 24px; margin: 0; letter-spacing: -0.02em; font-weight: 600; }
.page-head .page-sub { color: var(--muted); margin-top: 4px; font-size: 13.5px; }
.page-head .actions { display: flex; gap: 8px; }

/* ---------- Library ---------- */
.lib-toolbar { display: flex; gap: 12px; align-items: center; margin-bottom: 18px; flex-wrap: wrap; }
.lib-filters { display:flex; gap: 8px; flex-wrap: wrap; }
.filter-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 11px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-2);
  font-size: 12.5px; font-weight: 500;
  cursor: pointer;
}
.filter-chip:hover { background: var(--hover); color: var(--text); }
.filter-chip.active { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
.filter-chip svg { width: 13px; height: 13px; }

.media-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 18px;
}
.media-card {
  display: flex; flex-direction: column; gap: 8px;
  cursor: pointer;
  transition: transform .15s;
}
.media-card:hover { transform: translateY(-2px); }
.media-poster {
  aspect-ratio: 2/3;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--panel-3), var(--panel-2));
  border: 1px solid var(--border);
  position: relative;
  overflow: hidden;
  display: grid; place-items: center;
  color: var(--muted-2);
}
.media-poster .poster-art {
  position: absolute; inset: 0;
  background:
    repeating-linear-gradient(135deg, color-mix(in oklch, var(--accent) 18%, transparent) 0 6px, transparent 6px 24px),
    linear-gradient(180deg, var(--panel-2), var(--panel-3));
}
.media-poster .poster-overlay {
  position: absolute; inset: auto 0 0 0; padding: 8px;
  background: linear-gradient(180deg, transparent, rgba(0,0,0,0.55));
  display: flex; justify-content: space-between; align-items: flex-end;
}
.media-poster .score-chip {
  background: var(--ok); color: #fff;
  padding: 2px 6px; border-radius: 5px;
  font-size: 11px; font-weight: 600; font-family: var(--font-mono);
}
.media-poster .score-chip.warn { background: var(--warn); }
.media-poster .score-chip.danger { background: var(--danger); }
.media-poster .res-chip { background: rgba(0,0,0,0.55); color: #fff; padding: 2px 6px; border-radius: 5px; font-size: 11px; font-weight: 500; font-family: var(--font-mono); backdrop-filter: blur(4px); }
.media-poster .provider-chip { position: absolute; top: 8px; left: 8px; padding: 2px 6px; border-radius: 5px; font-size: 10px; font-weight: 700; color: #fff; background: rgba(0,0,0,0.6); backdrop-filter: blur(4px); }
.media-meta .title { font-size: 13.5px; font-weight: 500; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.media-meta .sub { font-size: 11.5px; color: var(--muted); display:flex; gap: 6px; margin-top: 2px; }

/* ---------- Recommendations table ---------- */
.tbl {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
}
.tbl thead th {
  text-align: left;
  font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted);
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0;
  background: var(--panel);
  z-index: 1;
}
.tbl tbody td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-soft);
  font-size: 13px;
  vertical-align: middle;
}
.tbl tbody tr:hover td { background: var(--hover); }
.tbl tbody tr:last-child td { border-bottom: 0; }

/* ---------- Settings ---------- */
.settings {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 28px;
  align-items: start;
}
.settings-nav { position: sticky; top: 0; display: flex; flex-direction: column; gap: 2px; }
.settings-nav .sn-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 12px;
  border-radius: 8px;
  font-size: 13.5px;
  color: var(--text-2);
  cursor: pointer;
  font-weight: 500;
}
.settings-nav .sn-item:hover { background: var(--hover); color: var(--text); }
.settings-nav .sn-item.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.settings-nav .sn-item svg { width: 16px; height: 16px; flex: none; }

.setting-block { padding: 18px 0; border-bottom: 1px solid var(--border-soft); }
.setting-block:last-child { border-bottom: 0; }
.setting-row { display: grid; grid-template-columns: 1fr auto; gap: 18px; align-items: center; }
.setting-row .desc { font-size: 12.5px; color: var(--muted); margin-top: 4px; }
.setting-row .label { font-size: 14px; font-weight: 500; color: var(--text); }

/* Toggle */
.toggle {
  width: 36px; height: 21px; border-radius: 999px;
  background: var(--border-strong);
  position: relative; cursor: pointer;
  transition: background .15s;
  flex: none;
}
.toggle::after {
  content: ""; position: absolute; top: 2px; left: 2px;
  width: 17px; height: 17px; border-radius: 50%;
  background: #fff;
  transition: transform .18s ease, background .15s;
  box-shadow: 0 1px 2px rgba(0,0,0,0.25);
}
.toggle.on { background: var(--accent); }
.toggle.on::after { transform: translateX(15px); }

.field {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 7px 11px;
  font: inherit; font-size: 13px;
  color: var(--text);
  outline: none;
  min-width: 200px;
}
.field:focus { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in oklch, var(--accent) 20%, transparent); }
.field.mono { font-family: var(--font-mono); font-size: 12.5px; }
.field.sm { padding: 4px 8px; font-size: 12px; min-width: 60px; }

.swatch-row { display:flex; gap: 8px; }
.swatch {
  width: 28px; height: 28px; border-radius: 8px;
  cursor: pointer;
  border: 2px solid transparent;
  transition: transform .1s;
}
.swatch:hover { transform: scale(1.08); }
.swatch.active { border-color: var(--text); box-shadow: 0 0 0 3px color-mix(in oklch, var(--accent) 20%, transparent); }

/* segmented tabs */
.tabs {
  display:inline-flex; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 3px;
}
.tab {
  padding: 6px 14px;
  border-radius: 7px;
  font-size: 13px;
  color: var(--text-2);
  cursor: pointer;
  font-weight: 500;
  display: flex; align-items: center; gap: 6px;
}
.tab:hover { color: var(--text); }
.tab.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }

/* Storage bar */
.storage-bar {
  height: 28px; border-radius: 8px;
  display: flex; overflow: hidden;
  background: var(--panel-3);
  border: 1px solid var(--border);
}
.storage-bar .seg-fill { display: flex; align-items: center; padding: 0 8px; font-size: 11px; color: #fff; font-family: var(--font-mono); font-weight: 600; min-width: 16px; }

/* health badge */
.health {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 3px 9px; border-radius: 999px;
  font-size: 11.5px; font-weight: 600;
  background: color-mix(in oklch, var(--ok) 16%, var(--panel));
  color: var(--ok);
}
.health .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

/* Empty state */
.empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 40px 20px;
  color: var(--muted);
  text-align: center;
}

/* recos table priority badge */
.prio { display:inline-flex; align-items:center; padding: 3px 9px; border-radius: 6px; font-size: 11px; font-weight: 600; }
.prio.high   { background: color-mix(in oklch, var(--danger) 16%, var(--panel)); color: var(--danger); }
.prio.med    { background: color-mix(in oklch, var(--warn) 16%, var(--panel)); color: var(--warn); }
.prio.low    { background: color-mix(in oklch, var(--ok) 16%, var(--panel)); color: var(--ok); }

/* Recent activity */
.activity-row { display:flex; gap: 12px; align-items: flex-start; padding: 10px 0; border-bottom: 1px solid var(--border-soft); }
.activity-row:last-child { border-bottom: 0; }
.activity-row:first-child { padding-top: 0; }
.activity-dot {
  width: 28px; height: 28px; border-radius: 50%;
  background: var(--accent-soft); color: var(--accent);
  display: grid; place-items: center; flex: none;
}
.activity-dot svg { width: 14px; height: 14px; }
.activity-text { flex: 1; font-size: 13px; }
.activity-text .at-meta { font-size: 11.5px; color: var(--muted); margin-top: 2px; }

/* Loading shimmer (decorative) */
@keyframes shimmer { from { background-position: -200px 0; } to { background-position: 200px 0; } }

/* Carousel — hide scrollbar */
.mml-carousel { scrollbar-width: none; -ms-overflow-style: none; }
.mml-carousel::-webkit-scrollbar { display: none; width: 0; height: 0; }

/* ---------- Mobile backdrop & helpers ---------- */
.mobile-backdrop {
  display: none;
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.5);
  backdrop-filter: blur(2px);
  z-index: 50;
}

.topbar-burger, .topbar-search-btn, .topbar-filter-btn { display: none; position: relative; }
.topbar-filter-btn .filter-toggle-badge {
  position: absolute;
  top: 2px; right: 2px;
  min-width: 14px; height: 14px;
  background: var(--accent);
  color: var(--on-accent);
  font-size: 9px;
  font-weight: 700;
  border-radius: 999px;
  display: grid; place-items: center;
  padding: 0 3px;
  border: 1.5px solid var(--panel);
}

/* responsive */
@media (max-width: 1080px) {
  .stat .stat-icon { width: 28px; height: 28px; }
  .lib-toolbar { gap: 8px; }
}

@media (max-width: 768px) {
  .app, .app.has-filters, .app.sidebar-open, .app.sidebar-open.has-filters {
    grid-template-columns: 1fr !important;
  }

  /* Sidebar becomes a left drawer */
  .sidebar.mini {
    position: fixed;
    top: 0; left: 0; bottom: 0;
    width: 240px;
    transform: translateX(-100%);
    transition: transform .22s cubic-bezier(.4,.0,.2,1);
    z-index: 60;
    padding: 12px 10px;
    align-items: stretch;
    box-shadow: 6px 0 24px rgba(0,0,0,0.25);
  }
  .sidebar.mini.expanded { transform: translateX(0); }
  .sidebar.mini .brand.mini { justify-content: flex-start; padding-left: 4px; }
  .sidebar.mini .nav-item.mini {
    width: 100%;
    height: 38px;
    display: flex; align-items: center;
    gap: 10px;
    padding: 0 10px;
    justify-content: flex-start;
    margin: 0;
  }
  .sidebar.mini .nav-item-label { display: inline-flex; }
  .sidebar.mini .nav-item.mini[data-tip]::after { display: none !important; }
  .sidebar.mini .nav-item.mini.filter-toggle .filter-toggle-badge {
    position: static; margin-left: auto; border: none;
  }
  .sidebar.mini .collapse-btn { display: none; }

  /* Filter rail becomes right drawer */
  .filters-rail {
    position: fixed;
    top: 0; right: 0; bottom: 0;
    width: 88vw; max-width: 340px;
    z-index: 60;
    box-shadow: -6px 0 24px rgba(0,0,0,0.25);
    border-right: none;
    border-left: 1px solid var(--border);
  }

  .mobile-backdrop { display: block; }

  /* Topbar */
  .topbar-burger,
  .topbar-search-btn,
  .topbar-filter-btn { display: grid; }
  .topbar .search { display: none; }
  .topbar { padding: 0 10px; height: 54px; gap: 4px; }
  .topbar h1 { font-size: 15px; }
  .user-menu-trigger > span:first-child { display: none; }

  /* Content */
  .scroll { padding: 14px 14px 60px; }
  .page-head { flex-direction: column; align-items: flex-start; gap: 10px; }
  .page-head .actions { width: 100%; flex-wrap: wrap; }
  .page-head h2 { font-size: 22px; }
  .lib-toolbar { flex-wrap: wrap; gap: 8px; }

  /* KPI / multi-col grids → single or 2-col */
  [style*="grid-template-columns: repeat(4, 1fr)"],
  [style*="gridTemplateColumns: \"repeat(4, 1fr)\""] {
    grid-template-columns: repeat(2, 1fr) !important;
  }
  [style*="grid-template-columns: repeat(6, 1fr)"],
  [style*="gridTemplateColumns: \"repeat(6, 1fr)\""] {
    grid-template-columns: repeat(2, 1fr) !important;
  }
  [style*="grid-template-columns: repeat(3, 1fr)"] {
    grid-template-columns: 1fr !important;
  }
  [style*="grid-template-columns: 1.1fr 1fr"],
  [style*="grid-template-columns: 1.4fr 1fr"],
  [style*="grid-template-columns: 1fr 1fr"],
  [style*="grid-template-columns: 2fr 1fr"],
  [style*="grid-template-columns: 1fr 2fr"],
  [style*="gridTemplateColumns: \"1fr 1fr\""],
  [style*="gridTemplateColumns: \"1.1fr 1fr\""],
  [style*="gridTemplateColumns: \"1.4fr 1fr\""] {
    grid-template-columns: 1fr !important;
  }

  .media-grid { grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 12px; }
  .card { padding: 14px; border-radius: 10px; }

  /* Tables: horizontal scroll */
  .card.tight { overflow-x: auto; }
  .tbl { min-width: 560px; }

  /* Tabs scrollable */
  .tabs { overflow-x: auto; white-space: nowrap; max-width: 100%; }

  /* Settings: stack nav above content, nav becomes horizontal scrollable */
  .settings {
    grid-template-columns: 1fr !important;
    gap: 12px;
  }
  .settings-nav {
    position: static !important;
    flex-direction: row !important;
    overflow-x: auto;
    padding-bottom: 4px;
    gap: 6px !important;
    margin: 0 -14px;
    padding-left: 14px; padding-right: 14px;
    -ms-overflow-style: none; scrollbar-width: none;
  }
  .settings-nav::-webkit-scrollbar { display: none; }
  .settings-nav .sn-item {
    flex: 0 0 auto;
    padding: 8px 14px !important;
    white-space: nowrap;
  }

  /* KPI tiles on recos / accueil — make them more compact */
  .stat { padding: 12px 14px; }
  .stat .stat-value { font-size: 20px; }
  .stat .stat-label { font-size: 10.5px; }

  /* Page sub spacing */
  .page-sub { font-size: 12px; }
}
