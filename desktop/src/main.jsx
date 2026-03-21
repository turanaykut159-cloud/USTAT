/**
 * ÜSTAT v5.7 Desktop — React entry point (Vite).
 *
 * v14.1: Global error handler + renderer log forwarding eklendi.
 */

import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/theme.css';

// ── v14.1: Renderer-side console override — logları main process'e ilet ──
// Orijinal console referansları
const _origError = console.error;
const _origWarn = console.warn;

console.error = (...args) => {
  _origError.apply(console, args);
  try {
    window.electronAPI?.logToMain?.('ERROR', args.map(a =>
      typeof a === 'string' ? a : (a?.stack || a?.message || JSON.stringify(a))
    ).join(' '));
  } catch { /* yoksay */ }
};

console.warn = (...args) => {
  _origWarn.apply(console, args);
  try {
    window.electronAPI?.logToMain?.('WARN', args.map(a =>
      typeof a === 'string' ? a : JSON.stringify(a)
    ).join(' '));
  } catch { /* yoksay */ }
};

// ── v14.1: Startup lifecycle log ────────────────────────────────
try {
  window.electronAPI?.logToMain?.('INFO', 'React app başlatılıyor (main.jsx)');
} catch { /* yoksay */ }

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// ── v14.1: Mount başarılı log ───────────────────────────────────
try {
  window.electronAPI?.logToMain?.('INFO', 'React app mount edildi');
} catch { /* yoksay */ }
