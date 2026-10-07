const API = '/api';

async function get(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}

export const api = {
  summary: () => get('/summary'),
  tabs: () => get('/tabs'),
  report: (vendor, report, offset = 0, limit = 100) =>
    get(`/report/${encodeURIComponent(vendor)}/${encodeURIComponent(report)}?offset=${offset}&limit=${limit}`),
  search: (q, limit = 500) => get(`/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  searchBulk: (sitesText, file) => {
    const form = new FormData();
    form.append('sites', sitesText || '');
    if (file) form.append('file', file);
    return fetch(API + '/search/bulk', { method: 'POST', body: form }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Request failed (${r.status})`);
      return r.json();
    });
  },
  searchBulkExportBlob: (sitesText, file) => {
    const form = new FormData();
    form.append('sites', sitesText || '');
    if (file) form.append('file', file);
    return fetch(API + '/search/bulk/export', { method: 'POST', body: form }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Request failed (${r.status})`);
      return r.blob();
    });
  },
  job: (id) => get(`/jobs/${id}`),
  runFolderImport: () => fetch(API + '/import', { method: 'POST' }).then((r) => r.json()),
  cancelJob: (id) => fetch(API + `/jobs/${id}/cancel`, { method: 'POST' }).then((r) => r.json()),
  imports: (limit = 100) => get(`/imports?limit=${limit}`),
};

export const fmtBytes = (n) => {
  if (!n) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0, x = Number(n);
  while (x >= 1024 && i < u.length - 1) { x /= 1024; i++; }
  return `${x.toFixed(i ? 1 : 0)} ${u[i]}`;
};

export const fmtNum = (n) => Number(n || 0).toLocaleString('en-IN');
