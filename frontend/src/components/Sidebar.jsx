import React from 'react';
import { NavLink } from 'react-router-dom';

const LINKS = [
  { to: '/', label: 'Overview', icon: '◎', end: true },
  { to: '/site-inventory', label: 'Site Inventory', icon: '⌂' },
  { to: '/cell-inventory', label: 'Cell Inventory', icon: '▲' },
  { to: '/ip-inventory', label: 'IP Inventory', icon: '◇' },
  { to: '/mme-inventory', label: 'MME Inventory', icon: '⇄' },
  { to: '/other-reports', label: 'Other Reports', icon: '▤' },
  { to: '/search', label: 'Search', icon: '⌕' },
  { to: '/upload', label: 'Upload / Import', icon: '⇧' },
];

export default function Sidebar() {
  return (
    <nav className="sidebar">
      <div className="brandmark">
        <span className="brandglyph">N</span>
        <div>
          <strong>Network Inventory</strong>
          <small>Multi-vendor console</small>
        </div>
      </div>
      <ul>
        {LINKS.map((l) => (
          <li key={l.to}>
            <NavLink to={l.to} end={l.end} className={({ isActive }) => 'navlink' + (isActive ? ' active' : '')}>
              <span className="navicon">{l.icon}</span>
              {l.label}
            </NavLink>
          </li>
        ))}
      </ul>
      <div className="sidebarfoot">
        <span className="pulse" /> Live database link
      </div>
    </nav>
  );
}
