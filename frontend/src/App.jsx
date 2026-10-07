import React from 'react';
import { HashRouter, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar.jsx';
import JobBar from './components/JobBar.jsx';
import { JobProvider } from './context/JobContext.jsx';
import Overview from './pages/Overview.jsx';
import Inventory from './pages/Inventory.jsx';
import Search from './pages/Search.jsx';
import UploadPage from './pages/Upload.jsx';
import { CATEGORIES } from './lib/categories.js';

export default function App() {
  return (
    <JobProvider>
      <HashRouter>
        <div className="shell">
          <Sidebar />
          <main className="main">
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/site-inventory" element={<Inventory category="site" title={CATEGORIES.site.label} hint={CATEGORIES.site.hint} />} />
              <Route path="/cell-inventory" element={<Inventory category="cell" title={CATEGORIES.cell.label} hint={CATEGORIES.cell.hint} />} />
              <Route path="/ip-inventory" element={<Inventory category="ip" title={CATEGORIES.ip.label} hint={CATEGORIES.ip.hint} />} />
              <Route path="/mme-inventory" element={<Inventory category="mme" title={CATEGORIES.mme.label} hint={CATEGORIES.mme.hint} />} />
              <Route path="/other-reports" element={<Inventory category="other" title={CATEGORIES.other.label} hint={CATEGORIES.other.hint} />} />
              <Route path="/search" element={<Search />} />
              <Route path="/upload" element={<UploadPage />} />
            </Routes>
          </main>
          <JobBar />
        </div>
      </HashRouter>
    </JobProvider>
  );
}
