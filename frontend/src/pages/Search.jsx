import React, { useRef, useState } from 'react';
import { api, fmtNum } from '../lib/api.js';
import { vendorTone } from '../lib/categories.js';

const GROUP_PREVIEW = 60;

export default function Search() {
  const [mode, setMode] = useState('single'); // 'single' | 'bulk'

  // single-site search state
  const [q, setQ] = useState('');

  // bulk search state
  const [sitesText, setSitesText] = useState('');
  const [bulkFile, setBulkFile] = useState(null);
  const fileRef = useRef(null);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState('');
  const [scope, setScope] = useState(null); // {vendor, report} filter chip, or null = all

  const runSingle = (query) => {
    if (!query.trim()) return;
    setLoading(true); setError(''); setScope(null);
    api.search(query).then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false));
  };

  const runBulk = () => {
    if (!sitesText.trim() && !bulkFile) return;
    setLoading(true); setError(''); setScope(null);
    api.searchBulk(sitesText, bulkFile)
      .then((d) => setData({ ...d, query: `${d.query_terms.length} site(s)` }))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  const downloadBlob = (blob, filename) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  };

  const exportSingle = () => { window.location.href = `/api/search/export?q=${encodeURIComponent(data.query)}`; };
  const exportBulk = () => {
    setExporting(true);
    api.searchBulkExportBlob(sitesText, bulkFile)
      .then((blob) => downloadBlob(blob, `bulk_search_${data.query_terms.length}_sites.xlsx`))
      .catch((e) => setError(e.message))
      .finally(() => setExporting(false));
  };

  // Group the flat result list back into per-report buckets, same as the tabs
  // they were uploaded under, so each renders as a real table with the source's
  // own column headers — not a generic key/value dump.
  const groups = {};
  for (const r of data?.results || []) {
    const k = r.vendor + '|' + r.report;
    (groups[k] = groups[k] || []).push(r);
  }
  const groupList = (data?.tabs || [])
    .map((t) => ({ ...t, rows: groups[t.vendor + '|' + t.report] || [] }))
    .filter((g) => !scope || (g.vendor === scope.vendor && g.report === scope.report));

  return (
    <div className="page">
      <header className="pagehead">
        <div>
          <h1>Search</h1>
          <p>Looks across every vendor and every report table in one pass.</p>
        </div>
      </header>

      <div className="modeswitch">
        <button className={mode === 'single' ? 'active' : ''} onClick={() => { setMode('single'); setData(null); }}>Single search</button>
        <button className={mode === 'bulk' ? 'active' : ''} onClick={() => { setMode('bulk'); setData(null); }}>Bulk search (multiple sites)</button>
      </div>

      {mode === 'single' ? (
        <form className="searchbar-big" onSubmit={(e) => { e.preventDefault(); runSingle(q); }}>
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search NE name, cell, IP address, OSS ID…"
          />
          <button className="btn primary" type="submit" disabled={loading}>{loading ? 'Searching…' : 'Search'}</button>
        </form>
      ) : (
        <div className="bulkbox">
          <div className="bulkbox-col">
            <label>Paste site names (one per line, or comma-separated)</label>
            <textarea
              rows={6}
              value={sitesText}
              onChange={(e) => setSitesText(e.target.value)}
              placeholder={'SITE001\nSITE002\nSITE003'}
            />
          </div>
          <div className="bulkbox-col">
            <label>…and/or upload a CSV / XLSX list of sites</label>
            <input
              ref={fileRef}
              type="file"
              hidden
              accept=".csv,.xlsx,.xlsm"
              onChange={(e) => setBulkFile(e.target.files[0] || null)}
            />
            <button type="button" className="btn ghost" onClick={() => fileRef.current?.click()}>
              {bulkFile ? bulkFile.name : 'Choose file'}
            </button>
            {bulkFile && <button type="button" className="btn ghost small" onClick={() => setBulkFile(null)}>Remove file</button>}
            <p className="bulkhint">First row is treated as a header and skipped. Up to 300 sites at once.</p>
            <button className="btn primary" onClick={runBulk} disabled={loading}>{loading ? 'Searching…' : 'Search all sites'}</button>
          </div>
        </div>
      )}

      {error && <div className="notice error">{error}</div>}

      {data && (
        <>
          <div className="search-summary">
            <strong>{fmtNum(data.total)}</strong> match{data.total === 1 ? '' : 'es'} for “{data.query}”
            {data.total > 0 && (
              mode === 'single'
                ? <button className="btn ghost small export-btn" onClick={exportSingle}>⇩ Export to Excel (one sheet per report)</button>
                : <button className="btn ghost small export-btn" onClick={exportBulk} disabled={exporting}>{exporting ? 'Preparing…' : '⇩ Export to Excel (one sheet per report)'}</button>
            )}
          </div>

          {mode === 'bulk' && data.unmatched_terms && data.unmatched_terms.length > 0 && (
            <div className="notice">
              <b>{data.unmatched_terms.length}</b> of {data.query_terms.length} pasted site name(s) had no match: {data.unmatched_terms.slice(0, 20).join(', ')}
              {data.unmatched_terms.length > 20 ? '…' : ''}
            </div>
          )}

          {data.tabs.length > 0 && (
            <div className="matchchips">
              <button className={'matchchip ' + (!scope ? 'active' : '')} onClick={() => setScope(null)}>
                All reports <em>{fmtNum(data.total)}</em>
              </button>
              {data.tabs.map((t, i) => (
                <button
                  key={i}
                  className={'matchchip ' + (scope && scope.vendor === t.vendor && scope.report === t.report ? 'active' : '')}
                  onClick={() => setScope({ vendor: t.vendor, report: t.report })}
                >
                  <span className={'vendordot ' + vendorTone(t.vendor)} />
                  {t.vendor} · {t.report} <em>{fmtNum(t.count)}</em>
                </button>
              ))}
            </div>
          )}

          <div className="resultgroups">
            {groupList.map((g) => (
              <ReportResultTable key={g.vendor + g.report} group={g} preview={!scope} />
            ))}
            {groupList.length === 0 && !loading && <div className="empty">No matching rows.</div>}
          </div>
        </>
      )}
    </div>
  );
}

function ReportResultTable({ group, preview }) {
  const rows = group.rows;
  if (rows.length === 0) return null;
  const headers = Object.keys(rows[0].row_data || {});
  const shown = preview ? rows.slice(0, GROUP_PREVIEW) : rows;

  return (
    <div className="tablepane resultgroup">
      <div className="tablepane-head">
        <span className={'vendordot ' + vendorTone(group.vendor)} />
        <h2>{group.vendor} · {group.report}</h2>
        <span className="resultgroup-count">{fmtNum(group.count)} match{group.count === 1 ? '' : 'es'}</span>
      </div>
      <div className="datatable-scroll">
        <table className="datatable">
          <thead>
            <tr>
              <th className="col-src">Source</th>
              {headers.map((h) => <th key={h}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id}>
                <td className="col-src"><code>{r.source_sheet || r.source_file}</code></td>
                {headers.map((h) => <td key={h}>{r.row_data?.[h] ?? ''}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {preview && rows.length > GROUP_PREVIEW && (
        <div className="datatable-foot">
          <span>Showing {fmtNum(GROUP_PREVIEW)} of {fmtNum(rows.length)} fetched matches</span>
        </div>
      )}
    </div>
  );
}
