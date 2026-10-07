import React, { useEffect, useState } from 'react';
import { api, fmtNum } from '../lib/api.js';

const PAGE = 100;

export default function DataTable({ vendor, report }) {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    setRows([]); setOffset(0); setTotal(0); setError(''); setLoading(true);
    api.report(vendor, report, 0, PAGE)
      .then((data) => { setRows(data.results); setTotal(data.total); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [vendor, report]);

  const loadMore = () => {
    const next = offset + PAGE;
    setLoading(true);
    api.report(vendor, report, next, PAGE)
      .then((data) => { setRows((r) => [...r, ...data.results]); setOffset(next); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  if (error) return <div className="empty error">Couldn't load this report — {error}</div>;
  if (!loading && rows.length === 0) return <div className="empty">No rows in this report yet.</div>;

  // Source headers come straight from the imported file's own header row —
  // we just take the key order of the first record.
  const headers = rows.length ? Object.keys(rows[0].row_data || {}) : [];

  return (
    <div className="datatable-wrap">
      <div className="datatable-scroll">
        <table className="datatable">
          <thead>
            <tr>
              <th className="col-src">Source</th>
              {headers.map((h) => <th key={h}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="col-src"><code>{r.source_sheet || r.source_file}</code></td>
                {headers.map((h) => <td key={h}>{r.row_data?.[h] ?? ''}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="datatable-foot">
        <span>{fmtNum(rows.length)} of {fmtNum(total)} rows</span>
        {rows.length < total && (
          <button className="btn ghost" onClick={loadMore} disabled={loading}>
            {loading ? 'Loading…' : `Load ${Math.min(PAGE, total - rows.length)} more`}
          </button>
        )}
      </div>
    </div>
  );
}
