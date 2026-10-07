import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, fmtNum } from '../lib/api.js';
import { CATEGORIES, categoryOf, groupTabsByCategory, vendorTone } from '../lib/categories.js';

export default function Overview() {
  const [summary, setSummary] = useState({ records: 0, files: 0, tabs: 0 });
  const [tabs, setTabs] = useState([]);

  useEffect(() => {
    api.summary().then(setSummary).catch(() => {});
    api.tabs().then(setTabs).catch(() => {});
  }, []);

  const grouped = useMemo(() => groupTabsByCategory(tabs), [tabs]);
  const byVendor = useMemo(() => {
    const m = {};
    for (const t of tabs) m[t.vendor] = (m[t.vendor] || 0) + Number(t.count || 0);
    return Object.entries(m).sort((a, b) => b[1] - a[1]);
  }, [tabs]);

  // Vendor × category matrix — Site (NE) / Cell / IP / MME / Other counts per vendor.
  const matrix = useMemo(() => {
    const m = {};
    for (const t of tabs) {
      m[t.vendor] = m[t.vendor] || { site: 0, cell: 0, ip: 0, mme: 0, other: 0 };
      m[t.vendor][categoryOf(t.report)] += Number(t.count || 0);
    }
    return Object.entries(m).sort((a, b) => byVendor.findIndex(([v]) => v === a[0]) - byVendor.findIndex(([v]) => v === b[0]));
  }, [tabs, byVendor]);

  return (
    <div className="page">
      <section className="hero">
        <div className="hero-sweep" aria-hidden="true" />
        <div className="hero-text">
          <span className="eyebrowless">Multi-vendor network inventory</span>
          <h1>Huawei, Ericsson and ZTE — one console.</h1>
          <p>Every vendor keeps its own tables under the hood. Up here, it's just site, cell and IP inventory — searchable end to end.</p>
        </div>
        <div className="hero-stat">
          <strong>{fmtNum(summary.records)}</strong>
          <span>records on file</span>
        </div>
      </section>

      <div className="exportrow">
        <a className="btn primary" href="/api/export/all" download>
          ⇩ Export full inventory (Excel — every vendor, every report)
        </a>
      </div>

      <section className="statrow">
        <div className="statcard"><span>Imported files</span><strong>{fmtNum(summary.files)}</strong></div>
        <div className="statcard"><span>Report tables</span><strong>{fmtNum(summary.tabs)}</strong></div>
        <div className="statcard"><span>Vendors online</span><strong>{byVendor.length}</strong></div>
      </section>

      <section className="catgrid">
        {['site', 'cell', 'ip', 'mme', 'other'].map((key) => {
          const meta = CATEGORIES[key];
          const list = grouped[key] || [];
          const count = list.reduce((s, t) => s + Number(t.count || 0), 0);
          const path = key === 'other' ? '/other-reports' : `/${key}-inventory`;
          return (
            <Link to={path} key={key} className="catcard">
              <div className="catcard-top">
                <h3>{meta.label}</h3>
                <span>{list.length} report{list.length === 1 ? '' : 's'}</span>
              </div>
              <strong>{fmtNum(count)}</strong>
              <p>{meta.hint}</p>
            </Link>
          );
        })}
      </section>

      <section className="vendorstrip">
        <h2>By vendor</h2>
        <div className="vendorbars">
          {byVendor.map(([vendor, count]) => {
            const max = byVendor[0][1] || 1;
            return (
              <div className="vendorbar" key={vendor}>
                <div className="vendorbar-label">
                  <span className={'vendordot ' + vendorTone(vendor)} />
                  {vendor}
                  <b>{fmtNum(count)}</b>
                </div>
                <div className="vendorbar-track"><i style={{ width: `${(count / max) * 100}%` }} className={vendorTone(vendor)} /></div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="vendorstrip">
        <h2>Vendor × inventory type</h2>
        <div className="tablepane matrixpane">
          <table className="datatable matrixtable">
            <thead>
              <tr>
                <th>Vendor</th>
                <th>Site Inventory</th>
                <th>Cell Inventory</th>
                <th>IP Inventory</th>
                <th>MME Inventory</th>
                <th>Other</th>
                <th>Total</th>
              </tr>
            </thead>
            <tbody>
              {matrix.map(([vendor, c]) => (
                <tr key={vendor}>
                  <td><span className={'vendordot ' + vendorTone(vendor)} /> {vendor}</td>
                  <td>{fmtNum(c.site)}</td>
                  <td>{fmtNum(c.cell)}</td>
                  <td>{fmtNum(c.ip)}</td>
                  <td>{fmtNum(c.mme)}</td>
                  <td>{fmtNum(c.other)}</td>
                  <td><b>{fmtNum(c.site + c.cell + c.ip + c.mme + c.other)}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
