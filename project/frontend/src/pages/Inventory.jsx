import React, { useEffect, useMemo, useState } from 'react';
import { api, fmtNum } from '../lib/api.js';
import { groupTabsByCategory, vendorTone } from '../lib/categories.js';
import DataTable from '../components/DataTable.jsx';

export default function Inventory({ category, title, hint }) {
  const [tabs, setTabs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    setLoading(true);
    api.tabs().then((all) => {
      const list = groupTabsByCategory(all)[category];
      setTabs(list);
      setSelected(list[0] || null);
    }).finally(() => setLoading(false));
  }, [category]);

  const totalRows = useMemo(() => tabs.reduce((s, t) => s + Number(t.count || 0), 0), [tabs]);

  return (
    <div className="page">
      <header className="pagehead">
        <div>
          <h1>{title}</h1>
          <p>{hint}</p>
        </div>
        <div className="pagehead-stat">
          <strong>{fmtNum(totalRows)}</strong>
          <span>records across {tabs.length} report{tabs.length === 1 ? '' : 's'}</span>
          <a className="btn ghost small export-btn" href={`/api/export/all?category=${category}`} download>
            ⇩ Export this category
          </a>
        </div>
      </header>

      {loading ? (
        <div className="empty">Loading reports…</div>
      ) : tabs.length === 0 ? (
        <div className="empty">No reports of this type have been imported yet.</div>
      ) : (
        <div className="inventory-body">
          <aside className="tablist">
            {tabs.map((t) => (
              <button
                key={t.vendor + t.report}
                className={'tabitem ' + (selected && selected.vendor === t.vendor && selected.report === t.report ? 'active' : '')}
                onClick={() => setSelected(t)}
              >
                <span className={'vendordot ' + vendorTone(t.vendor)} />
                <span className="tabitem-text">
                  <b>{t.vendor}</b>
                  <small>{t.report}</small>
                </span>
                <em>{fmtNum(t.count)}</em>
              </button>
            ))}
          </aside>
          <section className="tablepane">
            {selected && (
              <>
                <div className="tablepane-head">
                  <span className={'vendordot ' + vendorTone(selected.vendor)} />
                  <h2>{selected.vendor} · {selected.report}</h2>
                </div>
                <DataTable vendor={selected.vendor} report={selected.report} />
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
