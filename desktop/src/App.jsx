/**
 * ÜSTAT v5.3 Desktop — Ana uygulama bileşeni.
 *
 * HashRouter kullanılır (Electron file:// protokolü uyumu).
 * React Router v6 ile 5 sayfa yönlendirme.
 */

import React, { useState, useEffect } from 'react';
import { HashRouter, Routes, Route } from 'react-router-dom';
import TopBar from './components/TopBar';
import SideNav from './components/SideNav';
import LockScreen from './components/LockScreen';
import Dashboard from './components/Dashboard';
import TradeHistory from './components/TradeHistory';
import Performance from './components/Performance';
import RiskManagement from './components/RiskManagement';
import ManualTrade from './components/ManualTrade';
import HybridTrade from './components/HybridTrade';
import AutoTrading from './components/AutoTrading';
import Monitor from './components/Monitor';
import Settings from './components/Settings';
import ErrorBoundary from './components/ErrorBoundary';

export default function App() {
  const [isLocked, setIsLocked] = useState(true);

  // Sayfa yüklendiğinde localStorage'dan temayı uygula
  useEffect(() => {
    const saved = localStorage.getItem('ustat_theme');
    if (saved === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    }
  }, []);

  if (isLocked) {
    return <LockScreen onUnlock={() => setIsLocked(false)} />;
  }

  return (
    <HashRouter>
      <div className="app-container">
        <TopBar />
        <div className="app-body">
          <SideNav />
          <main className="app-content">
            <ErrorBoundary>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/manual" element={<ManualTrade />} />
                <Route path="/hybrid" element={<HybridTrade />} />
                <Route path="/auto" element={<AutoTrading />} />
                <Route path="/trades" element={<TradeHistory />} />
                <Route path="/performance" element={<Performance />} />
                <Route path="/risk" element={<RiskManagement />} />
                <Route path="/monitor" element={<Monitor />} />
                <Route path="/settings" element={<Settings />} />
              </Routes>
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </HashRouter>
  );
}
