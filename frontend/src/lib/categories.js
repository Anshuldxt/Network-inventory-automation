// Every physical report table belongs to a vendor + report code (e.g. Huawei/NE,
// ZTE/4G, Ericsson/TCU). The backend keeps vendors separate on purpose (see README),
// but operators think in terms of *what kind of inventory* they're looking at, not
// which vendor produced it. This file infers that grouping from the report code so
// the UI can offer "Site / Cell / IP" tabs that span all three vendors at once.

export const CATEGORIES = {
  site: { key: 'site', label: 'Site Inventory', short: 'Site', hint: 'NE / node-level records' },
  cell: { key: 'cell', label: 'Cell Inventory', short: 'Cell', hint: '2G–5G cell and radio records' },
  ip: { key: 'ip', label: 'IP Inventory', short: 'IP', hint: 'IP, VLAN and DEVIP transport records' },
  mme: { key: 'mme', label: 'MME Inventory', short: 'MME', hint: 'S1/MME signalling link records' },
  other: { key: 'other', label: 'Other Reports', short: 'Other', hint: 'Anything not yet classified' },
};

export function categoryOf(report) {
  const r = String(report || '').toLowerCase();
  if (/\bs1\b/.test(r) || /mme/.test(r)) return 'mme';
  if (/\bip\b/.test(r) || /devip/.test(r) || /vlan/.test(r)) return 'ip';
  if (/2g|3g|4g|5g|gsm|umts|lte|nr\b|fdd|tdd|tcu|cell/.test(r)) return 'cell';
  // "NE" for Huawei/ZTE, and Ericsson's node-level dump report — all node/site records.
  if (/\bne\b/.test(r) || /network dump audit/.test(r) || /network_dump_audit/.test(r)) return 'site';
  return 'other';
}

export function groupTabsByCategory(tabs) {
  const groups = { site: [], cell: [], ip: [], mme: [], other: [] };
  for (const t of tabs) groups[categoryOf(t.report)].push(t);
  for (const k of Object.keys(groups)) {
    groups[k].sort((a, b) => (a.vendor + a.report).localeCompare(b.vendor + b.report));
  }
  return groups;
}

// Stable colour tag per vendor, independent of light/dark content.
export function vendorTone(vendor) {
  const v = String(vendor || '').toLowerCase();
  if (v === 'huawei') return 'huawei';
  if (v === 'ericsson') return 'ericsson';
  if (v === 'zte') return 'zte';
  return 'other';
}
