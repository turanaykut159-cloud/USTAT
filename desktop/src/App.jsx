/**
 * ÜSTAT v6.0 Desktop — Ana uygulama bileşeni.
 *
 * HashRouter kullanılır (Electron file:// protokolü uyumu).
 * React Router v6 ile 5 sayfa yönlendirme.
 */

import React, { useState, useEffect } from 'react';
import { HashRouter, Routes, Route, useLocation } from 'react-router-dom';
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
import ErrorTracker from './components/ErrorTracker';
import Nabiz from './components/Nabiz';
import Settings from './components/Settings';
import UstatBrain from './components/UstatBrain';
import ErrorBoundary from './components/ErrorBoundary';

/** Her route'u ayri ErrorBoundary ile sarar — bir sayfa cokerse diger sayfalar etkilenmez. */
function RouteBoundary({ label, children }) {
  const { pathname } = useLocation();
  return (
    <ErrorBoundary resetKey={pathname} label={label}>
      {children}
    </ErrorBoundary>
  );
}

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
    <ErrorBoundary label="App">
    <HashRouter>
      <div className="app-container">
        <TopBar />
        <div className="app-body">
          <SideNav />
          <main className="app-content">
            <Routes>
              <Route path="/" element={<RouteBoundary label="Dashboard"><Dashboard /></RouteBoundary>} />
              <Route path="/manual" element={<RouteBoundary label="Manuel"><ManualTrade /></RouteBoundary>} />
              <Route path="/hybrid" element={<RouteBoundary label="Hibrit"><HybridTrade /></RouteBoundary>} />
              <Route path="/auto" element={<RouteBoundary label="Oto"><AutoTrading /></RouteBoundary>} />
              <Route path="/trades" element={<RouteBoundary label="Islem Gecmisi"><TradeHistory /></RouteBoundary>} />
              <Route path="/performance" element={<RouteBoundary label="Performans"><Performance /></RouteBoundary>} />
              <Route path="/ustat" element={<RouteBoundary label="Üstat"><UstatBrain /></RouteBoundary>} />
              <Route path="/risk" element={<RouteBoundary label="Risk"><RiskManagement /></RouteBoundary>} />
              <Route path="/monitor" element={<RouteBoundary label="Monitor"><Monitor /></RouteBoundary>} />
              <Route path="/errors" element={<RouteBoundary label="Hata Takip"><ErrorTracker /></RouteBoundary>} />
              <Route path="/nabiz" element={<RouteBoundary label="NABIZ"><Nabiz /></RouteBoundary>} />
              <Route path="/settings" element={<RouteBoundary label="Ayarlar"><Settings /></RouteBoundary>} />
            </Routes>
          </main>
        </div>
      </div>
    </HashRouter>
    </ErrorBoundary>
  );
}
