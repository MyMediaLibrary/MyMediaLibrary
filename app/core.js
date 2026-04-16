/**
 * MyMediaLibrary — Core Module (MMLCore + MMLConstants + MMLState)
 *
 * Shared helpers, constants and state used across app.js and stats.js.
 * Exposed as window.MML* to make cross-module dependencies explicit.
 *
 * Scope: pure formatters, shared constants, global load state.
 * Do NOT add stateful UI logic or business logic here.
 */

(function (root) {
  'use strict';

  const PALETTE = [
    '#7c6aff', '#ff6a6a', '#4ecdc4', '#f7b731', '#a78bfa',
    '#f97316', '#34d399', '#60a5fa', '#f472b6', '#facc15',
    '#2dd4bf', '#c084fc', '#fb923c', '#86efac', '#93c5fd'
  ];

  function fmtSize(b) {
    if (!b) return '0 B';
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return b.toFixed(1) + ' ' + u[i];
  }

  function escH(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/\r?\n/g, ' ');
  }

  root.MMLCore = { PALETTE, fmtSize, escH };

  root.MMLState = {
    isLoading: false,
    isLoaded:  false,
    hasError:  false,
    items:     []
  };

  // ── Shared constants ──────────────────────────────────────────────────────
  root.MMLConstants = {
    // Provider sentinel values (shared by app.js and app.logic.js)
    PROVIDER_OTHERS_KEY:     '__others__',
    PROVIDER_NONE_KEY:       '__none__',
    PROVIDER_OTHERS_ALIASES: ['autres', 'others', 'other'],

    CHARTS: {
      // Color palettes for chart series
      COLORS: {
        CODEC:       ['#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6'],
        AUDIO_CODEC: ['#06b6d4', '#f97316', '#a3e635', '#e879f9', '#fb7185', '#34d399', '#fbbf24'],
        AUDIO_LANG:  ['#38bdf8', '#fb923c', '#4ade80', '#f472b6', '#a78bfa', '#fbbf24', '#34d399', '#60a5fa', '#f87171', '#2dd4bf'],
        RESOLUTION:  { '4K': '#a855f7', '1080p': '#22c55e', '720p': '#3b82f6', 'SD': '#78716c' },
        PROVIDER:    ['#7c6aff', '#ff6a6a', '#4ecdc4', '#f7b731', '#a78bfa', '#f97316', '#34d399', '#60a5fa', '#f472b6'],
        // Quality score colors: index 0 = level 1 (worst) … index 4 = level 5 (best)
        QUALITY:     ['#ef4444', '#f97316', '#eab308', '#84cc16', '#22c55e']
      },

      // Canonical display order for resolution labels
      RESOLUTION_ORDER: ['4K', '1080p', '720p', 'SD'],

      // Default active state for chart toggles
      DEFAULTS: {
        PIE_MODE:        'size',   // 'size' | 'count'
        TIMELINE_PERIOD: '12m',   // 'all' | '12m' | '30d'
        YEAR_MODE:       'years'  // 'years' | 'decades'
      }
    }
  };

})(typeof self !== 'undefined' ? self : this);

// ── Auth token injection ──────────────────────────────────────────────────────
// Attach X-Auth-Token to all same-origin fetch calls when a session token is
// stored. Covers both /api/ endpoints and static protected resources
// (/library.json) gated by nginx auth_request.
// On 401, clear stale auth state and show the login overlay.
(function () {
  var _orig = window.fetch;
  window.fetch = function (url, opts) {
    opts = opts ? Object.assign({}, opts) : {};
    if (typeof url === 'string' && url.startsWith('/')) {
      var token = sessionStorage.getItem('mediaToken');
      if (token) {
        opts.headers = Object.assign({'X-Auth-Token': token}, opts.headers || {});
      }
    }
    return _orig.call(window, url, opts).then(function (resp) {
      if (resp.status === 401 && typeof url === 'string' && url.startsWith('/')
          && url !== '/api/auth') {
        sessionStorage.removeItem('mediaAuth');
        sessionStorage.removeItem('mediaToken');
        var ov = document.getElementById('authOverlay');
        if (ov) { ov.style.display = 'flex'; }
      }
      return resp;
    });
  };
})();
