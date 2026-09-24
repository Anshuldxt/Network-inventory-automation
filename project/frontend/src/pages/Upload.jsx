import React, { useEffect, useRef, useState } from 'react';
import { api, fmtNum } from '../lib/api.js';
import { useJob } from '../context/JobContext.jsx';

export default function UploadPage() {
  const { upload, runFolderImport, job } = useJob();
  const fileRef = useRef(null);
  const busy = job && !['COMPLETED', 'FAILED', 'CANCELLED'].includes(job.job?.status);
  const [history, setHistory] = useState(null);
  const [historyError, setHistoryError] = useState('');

  const loadHistory = () => {
    api.imports().then(setHistory).catch((e) => setHistoryError(e.message));
  };

  useEffect(() => { loadHistory(); }, []);
  // Refresh the history list whenever a job finishes, so a just-completed import
  // shows up without the user having to reload the page.
  const lastStatus = job?.job?.status;
  useEffect(() => {
    if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(lastStatus)) loadHistory();
  }, [lastStatus]);

  return (
    <div className="page">
      <header className="pagehead">
        <div>
          <h1>Upload / Import</h1>
          <p>Bring a new Huawei, Ericsson or ZTE report into the database. Progress stays visible from any page while it runs.</p>
        </div>
      </header>

      <div className="uploadgrid">
        <div className="uploadcard">
          <h3>Upload a report</h3>
          <p>CSV, XLSX or a ZIP of reports. Vendor and report type are detected automatically from the file/sheet names.</p>
          <input
            ref={fileRef}
            type="file"
            hidden
            accept=".csv,.xlsx,.xlsm,.zip"
            onChange={(e) => { const f = e.target.files[0]; if (f) upload(f); e.target.value = ''; }}
          />
          <button className="btn primary" disabled={busy} onClick={() => fileRef.current?.click()}>
            {busy ? 'Import in progress…' : 'Choose file to upload'}
          </button>
        </div>

        <div className="uploadcard">
          <h3>Import from input folder</h3>
          <p>Process everything already sitting in the server's configured input directory — useful for a batch drop or a scheduled sync.</p>
          <button className="btn ghost" disabled={busy} onClick={runFolderImport}>
            {busy ? 'Import in progress…' : 'Run folder import'}
          </button>
        </div>
      </div>

      <div className="uploadnote">
        <h4>Import rules currently in effect</h4>
        <ul>
          <li>Only these exact file names are imported — anything else is ignored automatically:</li>
          <li style={{ marginLeft: 8 }}><code>Report_GSM_combine</code>, <code>Report_LTE_combine</code>, <code>Report_LTE S1_combine</code>, <code>Report_Ne_Report_combine</code>, <code>Report_NR_combine</code>, <code>Report_UMTS_combine</code>, <code>DEVIP_combine_OTHERS</code>, <code>VLAN_combine_OTHERS</code> (Huawei)</li>
          <li style={{ marginLeft: 8 }}><code>NetworkDumpAuditReport_YYYYMMDD</code>, <code>Network Cell Status Output_YYYYMMDD</code> (Ericsson)</li>
          <li style={{ marginLeft: 8 }}><code>ZTE_NETWORK_INVENTORY_DUMP</code>, <code>ZTE_2G_GSM_COMBINED</code>, <code>ZTE_3G_UMTS_COMBINED</code>, <code>ZTE_4G_LTE_COMBINED</code>, <code>ZTE_5G_NR_COMBINED</code></li>
          <li>A date suffix, an extra numeric suffix, or being bundled inside a ZIP doesn't matter — matching is by name, not exact file.</li>
        </ul>
      </div>

      <div className="uploadnote historypane">
        <h4>Import history</h4>
        {historyError && <div className="notice error">{historyError}</div>}
        {!history ? (
          <div className="empty">Loading…</div>
        ) : history.length === 0 ? (
          <div className="empty">No imports yet.</div>
        ) : (
          <div className="datatable-scroll history-scroll">
            <table className="datatable">
              <thead>
                <tr>
                  <th>File</th><th>Status</th><th>Rows</th><th>Imported at</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h, i) => (
                  <tr key={i}>
                    <td>{h.file_name}</td>
                    <td><span className={'statuspill ' + String(h.status).toLowerCase()}>{h.status}</span></td>
                    <td>{fmtNum(h.rows_imported)}</td>
                    <td>{new Date(h.imported_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
