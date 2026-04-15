/**
 * MyMediaLibrary — Core Module (MMLCore)
 *
 * Shared helpers and constants used across app.js and stats.js.
 * Exposed as window.MMLCore to make cross-module dependencies explicit.
 *
 * Scope: pure formatters + shared constants only.
 * Do NOT add stateful or UI-specific logic here.
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

})(typeof self !== 'undefined' ? self : this);
