/**
 * ÜSTAT v5.0 Desktop — Ana uygulama bileşeni.
 *
 * HashRouter kullanılır (Electron file:// protokolü uyumu).
 * React Router v6 ile 5 sayfa yönlendirme.
 */

import React, { useState } from 'react';
import { HashRouter, Routes, Route } from 'react-router-dom';
import TopBar from './components/TopBar';
import SideNav from './components/SideNav';
import LockScreen from './components/LockScreen';
import Dashboard from './components/Dashboard';
import TradeHistory from './components/TradeHistory';
import OpenPositions from './components/OpenPositions';
import Performance from './components/Performance';
import RiskManagement from './components/RiskManagement';
import Settings from './components/Settings';

export default function App() {
  const [isLocked, setIsLocked] = useState(true);

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
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/trades" element={<TradeHistory />} />
              <Route path="/positions" element={<OpenPositions />} />
              <Route path="/performance" element={<Performance />} />
              <Route path="/risk" element={<RiskManagement />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </main>
        </div>
      </div>
    </HashRouter>
  );
}
