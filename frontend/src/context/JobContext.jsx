import React, { createContext, useCallback, useContext, useRef, useState } from 'react';
import { api } from '../lib/api.js';

const TERMINAL = new Set(['COMPLETED', 'FAILED', 'CANCELLED']);
const Ctx = createContext(null);

export function JobProvider({ children, onSettled }) {
  const [job, setJob] = useState(null);       // full /api/jobs/:id payload
  const [visible, setVisible] = useState(false);
  const pollRef = useRef(null);

  const stopPolling = useCallback(() => {
    clearInterval(pollRef.current);
    pollRef.current = null;
  }, []);

  const watchJob = useCallback((id) => {
    stopPolling();
    setVisible(true);
    const tick = () => {
      api.job(id).then((data) => {
        setJob(data);
        if (TERMINAL.has(data.job.status)) {
          stopPolling();
          onSettled && onSettled(data.job.status);
        }
      }).catch((e) => setJob((j) => ({ ...(j || { job: {} }), error: e.message })));
    };
    tick();
    pollRef.current = setInterval(tick, 1000);
  }, [stopPolling, onSettled]);

  const upload = useCallback((file) => {
    const form = new FormData();
    form.append('file', file);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload');
    setVisible(true);
    setJob({
      job: { status: 'UPLOADING', file_name: file.name, bytes_total: file.size, bytes_received: 0, message: 'Uploading file…' },
      items: [], upload_percent: 0, processing_percent: 0, reports_done: 0, reports_total: 0,
    });
    xhr.upload.onprogress = (ev) => {
      if (!ev.lengthComputable) return;
      setJob((j) => ({
        ...j,
        job: { ...(j?.job || {}), status: 'UPLOADING', file_name: file.name, bytes_total: ev.total, bytes_received: ev.loaded },
        upload_percent: Math.round((ev.loaded * 100) / ev.total),
      }));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const data = JSON.parse(xhr.responseText);
        watchJob(data.job_id);
      } else {
        setJob((j) => ({ ...j, job: { ...(j?.job || {}), status: 'FAILED', message: `Upload failed (${xhr.status})` } }));
      }
    };
    xhr.onerror = () => setJob((j) => ({ ...j, job: { ...(j?.job || {}), status: 'FAILED', message: 'Upload failed — connection error' } }));
    xhr.send(form);
  }, [watchJob]);

  const runFolderImport = useCallback(() => {
    setVisible(true);
    setJob({ job: { status: 'QUEUED', file_name: 'Input folder', message: 'Queued' }, items: [], upload_percent: 100, processing_percent: 0, reports_done: 0, reports_total: 0 });
    api.runFolderImport().then((data) => watchJob(data.job_id)).catch((e) =>
      setJob((j) => ({ ...j, job: { ...(j?.job || {}), status: 'FAILED', message: e.message } }))
    );
  }, [watchJob]);

  const dismiss = useCallback(() => { stopPolling(); setVisible(false); }, [stopPolling]);

  const cancel = useCallback(() => {
    const id = job?.job?.id;
    if (!id) return;
    setJob((j) => ({ ...j, job: { ...(j?.job || {}), status: 'CANCELLING', message: 'Cancelling…' } }));
    api.cancelJob(id).catch(() => {});
  }, [job]);

  return (
    <Ctx.Provider value={{ job, visible, upload, runFolderImport, dismiss, cancel }}>
      {children}
    </Ctx.Provider>
  );
}

export const useJob = () => useContext(Ctx);
