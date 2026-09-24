import React from 'react';
import { fmtBytes } from '../lib/api.js';
import { useJob } from '../context/JobContext.jsx';

export default function JobBar() {
  const { job, visible, dismiss, cancel } = useJob();
  if (!visible || !job) return null;
  const j = job.job || {};
  const items = job.items || [];
  const overall = j.status === 'COMPLETED' ? 100 : Math.round((Number(job.upload_percent || 0) * 0.35) + (Number(job.processing_percent || 0) * 0.65));
  const done = ['COMPLETED', 'FAILED', 'CANCELLED'].includes(j.status);
  const cancellable = j.id && !done && j.status !== 'CANCELLING';

  return (
    <div className={'jobbar ' + String(j.status || '').toLowerCase()}>
      <div className="jobbar-row">
        <div className="jobbar-title">
          <span className={'jobdot ' + String(j.status || '').toLowerCase()} />
          <div>
            <strong>{j.file_name || 'Input folder'}</strong>
            <small>{j.message || j.status}</small>
          </div>
        </div>
        <div className="jobbar-meta">
          {j.bytes_total ? <span>{fmtBytes(j.bytes_received)} / {fmtBytes(j.bytes_total)}</span> : null}
          <span>{job.reports_done || 0}/{job.reports_total || 0} reports</span>
          <b>{overall}%</b>
          {cancellable && <button className="jobbar-cancel" onClick={cancel}>Stop import</button>}
          {done && <button className="jobbar-close" onClick={dismiss} aria-label="Dismiss">✕</button>}
        </div>
      </div>
      <div className="jobbar-track"><i style={{ width: `${overall}%` }} /></div>
      {items.length > 0 && (
        <div className="jobbar-items">
          {items.slice(-6).map((it, i) => (
            <span key={i} className={'jobchip ' + String(it.status).toLowerCase()}>
              {it.vendor} · {it.report}{it.source_sheet ? ` · ${it.source_sheet}` : ''} — {it.rows_imported || 0} rows
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
