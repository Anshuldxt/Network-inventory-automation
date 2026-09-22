import csv, json, os, re, sqlite3, sys, tempfile, zipfile, threading, queue, shutil
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import openpyxl
except ImportError:
    openpyxl = None

APP_TITLE = 'Multi-Vendor Network Inventory'
REPORTS = [
    'Huawei - NE', 'Huawei - 2G', 'Huawei - 3G', 'Huawei - 4G', 'Huawei - 5G',
    'Huawei - IP', 'Huawei - VLAN', 'Huawei - S1',
    'ZTE - NE', 'ZTE - 2G', 'ZTE - 3G', 'ZTE - 4G', 'ZTE - 5G',
    'Ericsson - Network Dump Audit', 'Ericsson - 2G', 'Ericsson - TCU',
    'Ericsson - 3G', 'Ericsson - 4G FDD', 'Ericsson - 4G TDD', 'Ericsson - 5G'
]


def app_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def one_drive_root():
    candidates = []
    for key in ('OneDriveCommercial', 'OneDrive'):
        value = os.environ.get(key)
        if value:
            candidates.append(Path(value))
    home = Path.home()
    candidates.extend([p for p in home.glob('OneDrive*') if p.is_dir()])
    for p in candidates:
        if p.exists():
            return p
    return None


def read_config():
    p = app_dir() / 'app_config.json'
    if p.exists():
        try:
            return json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            pass
    root = one_drive_root()
    default_input = str(root / 'Input') if root else ''
    return {'input_folder': default_input, 'db_path': str(app_dir() / 'inventory.sqlite3')}


def write_config(cfg):
    (app_dir() / 'app_config.json').write_text(json.dumps(cfg, indent=2), encoding='utf-8')


def clean(v):
    if v is None:
        return ''
    return str(v).replace('\ufeff', '').strip()


def header_key(v):
    return re.sub(r'[^a-z0-9]+', '', clean(v).lower())


def row_text(headers, values):
    vals = []
    for h, v in zip(headers, values):
        if clean(v):
            vals.append(clean(h) + ' ' + clean(v))
    return ' '.join(vals)


def classify_csv(name):
    n = name.lower()
    if 'report_ne' in n or 'network_inventory' in n:
        return 'Huawei - NE'
    if 'gsm' in n:
        return 'Huawei - 2G'
    if 'umts' in n:
        return 'Huawei - 3G'
    if 'lte s1' in n or 's1' in n:
        return 'Huawei - S1'
    if 'report_lte' in n:
        return 'Huawei - 4G'
    if 'report_nr' in n or '_nr' in n:
        return 'Huawei - 5G'
    if 'devip' in n:
        return 'Huawei - IP'
    if 'vlan' in n:
        return 'Huawei - VLAN'
    return None


def zte_sheet_report(filename, sheet):
    s = sheet.lower()
    f = filename.lower()
    if 'network_inventory' in f or sheet.lower() in ('nodedata', 'ip'):
        return 'ZTE - NE'
    if s == 'gsm' or '2g' in f:
        return 'ZTE - 2G'
    if s == 'umts' or '3g' in f:
        return 'ZTE - 3G'
    if s in ('nr', 'nr_cell_summary') or '5g' in f:
        return 'ZTE - 5G'
    if 'lte' in f or s.startswith('lte_'):
        return 'ZTE - 4G'
    return None


def ericsson_sheet_report(filename, sheet):
    s = sheet.lower()
    f = filename.lower()
    if 'networkdumpauditreport' in f and s == 'network dump audit':
        return 'Ericsson - Network Dump Audit'
    if 'networkdumpauditreport' in f and s == '2g':
        return 'Ericsson - 2G'
    if 'networkdumpauditreport' in f and s == 'tcu':
        return 'Ericsson - TCU'
    if 'networkdumpauditreport' in f and s == 'termpoint_data':
        return None
    if 'network cell status output' in f:
        if s == 'utrancell': return 'Ericsson - 3G'
        if s == 'eutrancellfdd': return 'Ericsson - 4G FDD'
        if s == 'eutrancelltdd': return 'Ericsson - 4G TDD'
        if s == 'nrcelldu': return 'Ericsson - 5G'
        return None
    return None


def infer_report(path, sheet=None):
    name = Path(path).name
    if sheet is not None:
        r = zte_sheet_report(name, sheet)
        if r: return r
        r = ericsson_sheet_report(name, sheet)
        if r: return r
    return classify_csv(name)


class Store:
    def __init__(self, path):
        self.path = path
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.execute('PRAGMA journal_mode=WAL')
        self.con.execute('PRAGMA synchronous=NORMAL')
        self.con.executescript('''
        CREATE TABLE IF NOT EXISTS rows (
          id INTEGER PRIMARY KEY, vendor TEXT, report TEXT, source TEXT,
          headers TEXT NOT NULL, values_json TEXT NOT NULL, search_text TEXT NOT NULL,
          imported_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_rows_report ON rows(report);
        CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(search_text, content='rows', content_rowid='id');
        CREATE TABLE IF NOT EXISTS imports (source TEXT PRIMARY KEY, row_count INTEGER, imported_at TEXT);
        ''')
        self.con.commit()

    def begin_source(self, source):
        self.con.execute('DELETE FROM rows WHERE source=?', (source,))
        self.con.execute('DELETE FROM search_index WHERE rowid NOT IN (SELECT id FROM rows)')

    def insert_batch(self, records):
        if not records: return
        self.con.executemany(
            'INSERT INTO rows(vendor,report,source,headers,values_json,search_text,imported_at) VALUES (?,?,?,?,?,?,?)',
            records)
        ids = self.con.execute('SELECT id FROM rows ORDER BY id DESC LIMIT ?', (len(records),)).fetchall()
        # IDs are returned in reverse insertion order; index with the corresponding records by lookup below.
        # Contentless FTS is populated explicitly from inserted ids using a safe lastrowid range.
        first = ids[-1][0]
        self.con.executemany('INSERT INTO search_index(rowid,search_text) VALUES (?,?)',
                             [(first + i, r[5]) for i, r in enumerate(records)])

    def finish_source(self, source, count):
        self.con.execute('INSERT OR REPLACE INTO imports VALUES (?,?,?)',
                         (source, count, datetime.now().isoformat(timespec='seconds')))
        self.con.commit()

    def report_counts(self):
        return dict(self.con.execute('SELECT report, COUNT(*) FROM rows GROUP BY report').fetchall())

    def search(self, terms, reports=None, limit=5000):
        terms = [clean(x) for x in terms if clean(x)]
        if not terms: return []
        reports = reports or REPORTS
        # FTS prefix queries keep common searches responsive.
        q = ' OR '.join('"' + re.sub(r'[^\w.-]', ' ', t).strip().replace(' ', '" OR "') + '*"' for t in terms)
        try:
            sql = '''SELECT r.id,r.vendor,r.report,r.source,r.headers,r.values_json
                     FROM search_index s JOIN rows r ON r.id=s.rowid
                     WHERE search_index MATCH ? AND r.report IN (%s) LIMIT ?''' % ','.join('?' * len(reports))
            return self.con.execute(sql, [q] + list(reports) + [limit]).fetchall()
        except sqlite3.Error:
            like = '%' + terms[0].lower() + '%'
            sql = '''SELECT id,vendor,report,source,headers,values_json FROM rows
                     WHERE lower(search_text) LIKE ? AND report IN (%s) LIMIT ?''' % ','.join('?' * len(reports))
            return self.con.execute(sql, [like] + list(reports) + [limit]).fetchall()

    def close(self):
        self.con.close()


def records_from_csv(path, report):
    encs = ('utf-8-sig', 'cp1252', 'latin1')
    last = None
    for enc in encs:
        try:
            with open(path, 'r', encoding=enc, errors='replace', newline='') as f:
                reader = csv.reader(f)
                headers = [clean(x) or 'Column_%d' % (i + 1) for i, x in enumerate(next(reader, []))]
                for row in reader:
                    row = list(row) + [''] * (len(headers) - len(row))
                    row = row[:len(headers)]
                    if not any(clean(v) for v in row):
                        continue
                    if row and clean(row[0]).lower() == clean(headers[0]).lower():
                        continue
                    if report == 'Huawei - NE' and len(row) > 3 and clean(row[2]).upper() == 'OSS' and clean(row[3]).upper() == 'OSS':
                        continue
                    yield headers, row
            return
        except Exception as e:
            last = e
    if last: raise last


def records_from_xlsx(path, sheet, report):
    if openpyxl is None:
        raise RuntimeError('openpyxl is required for Excel imports')
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet]
    it = ws.iter_rows(values_only=True)
    headers = [clean(x) or 'Column_%d' % (i + 1) for i, x in enumerate(next(it, ()))]
    for row in it:
        vals = list(row) + [''] * (len(headers) - len(row))
        yield headers, vals[:len(headers)]
    wb.close()


def vendor_for(report):
    return report.split(' - ', 1)[0]


def import_one(store, path, report, sheet=None, progress=None):
    source = Path(path).name + (('::' + sheet) if sheet else '')
    store.begin_source(source)
    batch, count = [], 0
    iterator = records_from_xlsx(path, sheet, report) if sheet else records_from_csv(path, report)
    for headers, values in iterator:
        vals = [clean(v) for v in values]
        text = row_text(headers, vals)
        record = (vendor_for(report), report, source, json.dumps(headers, ensure_ascii=False),
                  json.dumps(vals, ensure_ascii=False), text, datetime.now().isoformat(timespec='seconds'))
        batch.append(record); count += 1
        if len(batch) >= 1000:
            store.insert_batch(batch); batch.clear()
            if progress: progress(count, source)
    store.insert_batch(batch)
    store.finish_source(source, count)
    return count


def import_path(store, path, selected, progress=None):
    path = Path(path)
    total = 0
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as z:
            members = [m for m in z.infolist() if not m.is_dir() and not Path(m.filename).name.startswith('__MACOSX')]
            with tempfile.TemporaryDirectory() as td:
                for m in members:
                    ext = Path(m.filename).suffix.lower()
                    if ext not in ('.csv', '.xlsx', '.xlsm'): continue
                    target = Path(td) / Path(m.filename).name
                    with z.open(m) as src, open(target, 'wb') as dst: shutil.copyfileobj(src, dst)
                    total += import_path(store, target, selected, progress)
        return total
    ext = path.suffix.lower()
    if ext == '.csv':
        r = infer_report(path)
        if r in selected:
            return import_one(store, path, r, progress=progress)
        return 0
    if ext in ('.xlsx', '.xlsm'):
        if openpyxl is None: raise RuntimeError('Install openpyxl first')
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in wb.sheetnames:
                r = infer_report(path, sheet)
                if r in selected:
                    total += import_one(store, path, r, sheet=sheet, progress=progress)
        finally:
            wb.close()
        return total
    return 0


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry('1320x820'); self.minsize(1000, 650)
        self.cfg = read_config(); write_config(self.cfg)
        self.store = Store(self.cfg.get('db_path') or str(app_dir() / 'inventory.sqlite3'))
        self.selected_reports = {r: tk.BooleanVar(value=True) for r in REPORTS}
        self.results_by_report = {}
        self._build_style(); self._build_ui(); self.refresh_counts()

    def _build_style(self):
        style = ttk.Style(self)
        try: style.theme_use('clam')
        except Exception: pass
        style.configure('App.TFrame', background='#f4f7fb')
        style.configure('Header.TFrame', background='#102a43')
        style.configure('Header.TLabel', background='#102a43', foreground='white', font=('Segoe UI', 18, 'bold'))
        style.configure('Sub.TLabel', background='#102a43', foreground='#c9d8e8', font=('Segoe UI', 9))
        style.configure('Card.TFrame', background='white', relief='flat')
        style.configure('CardTitle.TLabel', background='white', foreground='#627d98', font=('Segoe UI', 9))
        style.configure('CardValue.TLabel', background='white', foreground='#102a43', font=('Segoe UI', 18, 'bold'))
        style.configure('Accent.TButton', background='#147d92', foreground='white', padding=8)
        style.configure('Treeview', rowheight=25, font=('Segoe UI', 9))
        style.configure('Treeview.Heading', font=('Segoe UI', 9, 'bold'))

    def _build_ui(self):
        self.configure(background='#f4f7fb')
        header = ttk.Frame(self, style='Header.TFrame', padding=(22, 15)); header.pack(fill='x')
        ttk.Label(header, text='Multi-Vendor Network Inventory', style='Header.TLabel').pack(side='left')
        ttk.Label(header, text='Huawei  •  Ericsson  •  ZTE', style='Sub.TLabel').pack(side='left', padx=18, pady=8)
        self.status = ttk.Label(header, text='Ready', style='Sub.TLabel'); self.status.pack(side='right')

        controls = ttk.Frame(self, style='App.TFrame', padding=14); controls.pack(fill='x')
        ttk.Button(controls, text='Import Folder', command=self.import_folder).pack(side='left', padx=3)
        ttk.Button(controls, text='Import ZIP', command=self.import_zip).pack(side='left', padx=3)
        ttk.Button(controls, text='Sync Now', command=self.sync_now).pack(side='left', padx=3)
        ttk.Button(controls, text='Input Folder', command=self.choose_input).pack(side='left', padx=3)
        ttk.Button(controls, text='Export CSV', command=self.export_results).pack(side='left', padx=3)
        ttk.Button(controls, text='Export Excel', command=self.export_excel).pack(side='left', padx=3)
        self.path_lbl = ttk.Label(controls, text=self.cfg.get('input_folder') or 'Input folder not set', foreground='#486581')
        self.path_lbl.pack(side='right', padx=5)

        cards = ttk.Frame(self, style='App.TFrame', padding=(14, 0)); cards.pack(fill='x')
        self.card_vars = {}
        for key, label in [('Huawei','Huawei'),('Ericsson','Ericsson'),('ZTE','ZTE'),('Total','Total rows')]:
            card = ttk.Frame(cards, style='Card.TFrame', padding=12); card.pack(side='left', fill='x', expand=True, padx=4)
            ttk.Label(card, text=label, style='CardTitle.TLabel').pack(anchor='w')
            v = tk.StringVar(value='0'); self.card_vars[key] = v
            ttk.Label(card, textvariable=v, style='CardValue.TLabel').pack(anchor='w')

        search = ttk.Frame(self, style='App.TFrame', padding=14); search.pack(fill='x')
        ttk.Label(search, text='Global search:', font=('Segoe UI', 10, 'bold')).pack(side='left')
        self.query = tk.StringVar(); entry = ttk.Entry(search, textvariable=self.query, width=55, font=('Segoe UI', 11)); entry.pack(side='left', padx=10)
        entry.bind('<Return>', lambda e: self.do_search())
        ttk.Button(search, text='Search all reports', style='Accent.TButton', command=self.do_search).pack(side='left')
        ttk.Button(search, text='Clear', command=self.clear_search).pack(side='left', padx=6)

        body = ttk.Panedwindow(self, orient='horizontal'); body.pack(fill='both', expand=True, padx=14, pady=(0,14))
        left = ttk.Frame(body, style='Card.TFrame', padding=8); right = ttk.Frame(body, style='Card.TFrame', padding=8)
        body.add(left, weight=1); body.add(right, weight=5)
        ttk.Label(left, text='Matching reports', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(0,6))
        self.matches = ttk.Treeview(left, columns=('report','count'), show='headings', selectmode='browse')
        self.matches.heading('report', text='Report tab'); self.matches.heading('count', text='Matches')
        self.matches.column('report', width=190); self.matches.column('count', width=70, anchor='center')
        self.matches.pack(fill='both', expand=True); self.matches.bind('<<TreeviewSelect>>', self.open_match)
        ttk.Label(right, text='Report tabs', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(0,6))
        self.notebook = ttk.Notebook(right); self.notebook.pack(fill='both', expand=True)
        self.report_views = {}
        for report in REPORTS:
            frame = ttk.Frame(self.notebook)
            self.notebook.add(frame, text=report)
            tree = ttk.Treeview(frame, show='headings')
            y = ttk.Scrollbar(frame, orient='vertical', command=tree.yview); y.pack(side='right', fill='y')
            x = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview); x.pack(side='bottom', fill='x')
            tree.pack(fill='both', expand=True); tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
            self.report_views[report] = tree

    def set_status(self, text): self.status.config(text=text); self.update_idletasks()
    def choose_input(self):
        p = filedialog.askdirectory(title='Select OneDrive/SharePoint-synced Input folder')
        if p:
            self.cfg['input_folder'] = p; write_config(self.cfg); self.path_lbl.config(text=p); self.set_status('Input folder saved')
    def import_folder(self):
        p = filedialog.askdirectory(title='Select folder containing reports')
        if p: self.start_import(Path(p))
    def import_zip(self):
        p = filedialog.askopenfilename(filetypes=[('ZIP files','*.zip')])
        if p: self.start_import(Path(p))
    def start_import(self, path):
        def work():
            try:
                self.set_status('Importing...')
                n = import_path(self.store, path, set(REPORTS), progress=lambda c,s: self.after(0, self.set_status, 'Importing %s (%s rows)' % (s,c)))
                self.after(0, self.refresh_counts); self.after(0, self.set_status, 'Imported %s rows' % n)
            except Exception as e:
                self.after(0, messagebox.showerror, 'Import error', str(e)); self.after(0, self.set_status, 'Import failed')
        threading.Thread(target=work, daemon=True).start()
    def sync_now(self):
        p = self.cfg.get('input_folder')
        if not p or not Path(p).exists():
            self.choose_input(); p = self.cfg.get('input_folder')
        if not p or not Path(p).exists():
            return
        def work():
            try:
                from auto_sync import sync_once
                ac = json.loads((app_dir() / 'auto_sync_config.json').read_text(encoding='utf-8'))
                cfg = read_config()
                if not ac.get('input_folder'): ac['input_folder'] = cfg.get('input_folder', '')
                saved = sync_once({**cfg, **ac})
                self.after(0, self.set_status, 'Downloaded %d attachment(s); importing...' % len(saved))
            except Exception as e:
                self.after(0, self.set_status, 'Outlook sync skipped: %s' % e)
            self.after(0, self.start_import, Path(p))
        threading.Thread(target=work, daemon=True).start()
    def refresh_counts(self):
        counts = self.store.report_counts(); h=e=z=0
        for r,c in counts.items():
            if r.startswith('Huawei'): h+=c
            elif r.startswith('Ericsson'): e+=c
            elif r.startswith('ZTE'): z+=c
        self.card_vars['Huawei'].set('{:,}'.format(h)); self.card_vars['Ericsson'].set('{:,}'.format(e)); self.card_vars['ZTE'].set('{:,}'.format(z)); self.card_vars['Total'].set('{:,}'.format(h+e+z))
    def do_search(self):
        raw = self.query.get()
        terms = [x for x in re.split(r'[\n,;\t]+', raw) if clean(x)]
        if not terms: return
        self.set_status('Searching...')
        def work():
            rows = self.store.search(terms, REPORTS, limit=12000)
            grouped = {}
            for row in rows: grouped.setdefault(row[2], []).append(row)
            self.results_by_report = grouped
            self.after(0, self.show_matches, grouped); self.after(0, self.set_status, '%s matching rows' % len(rows))
        threading.Thread(target=work, daemon=True).start()
    def show_matches(self, grouped):
        for x in self.matches.get_children(): self.matches.delete(x)
        for r in REPORTS:
            if r in grouped: self.matches.insert('', 'end', iid=r, values=(r, len(grouped[r])))
        if self.matches.get_children(): self.matches.selection_set(self.matches.get_children()[0]); self.open_match()
    def open_match(self, event=None):
        sel = self.matches.selection();
        if not sel: return
        r = sel[0]; rows = self.results_by_report.get(r, [])
        if not rows: return
        tree = self.report_views[r]
        headers = json.loads(rows[0][4]); tree.configure(columns=headers)
        for c in tree['columns']:
            tree.heading(c, text=c); tree.column(c, width=125, minwidth=80, anchor='w')
        for x in tree.get_children(): tree.delete(x)
        for row in rows[:1000]: tree.insert('', 'end', values=json.loads(row[5]))
        try: self.notebook.select(self.report_views[r].master)
        except Exception: pass
    def export_excel(self):
        if not self.results_by_report:
            messagebox.showinfo('Export', 'Search first.')
            return
        if openpyxl is None:
            messagebox.showerror('Export error', 'Install openpyxl first.')
            return
        p = filedialog.asksaveasfilename(defaultextension='.xlsx', filetypes=[('Excel workbook','*.xlsx')])
        if not p: return
        try:
            wb = openpyxl.Workbook(); wb.remove(wb.active)
            for report, rows in self.results_by_report.items():
                if not rows: continue
                ws = wb.create_sheet(report[:31])
                headers = json.loads(rows[0][4]); ws.append(headers)
                for row in rows: ws.append(json.loads(row[5]))
                ws.freeze_panes = 'A2'; ws.auto_filter.ref = ws.dimensions
            wb.save(p); messagebox.showinfo('Export', 'Excel export complete.')
        except Exception as e:
            messagebox.showerror('Export error', str(e))

    def _fit_columns(self): pass
    def clear_search(self):
        self.query.set('')
        for x in self.matches.get_children(): self.matches.delete(x)
        for tree in self.report_views.values():
            for x in tree.get_children(): tree.delete(x)
        self.set_status('Ready')
    def export_results(self):
        if not self.results_by_report: messagebox.showinfo('Export', 'Search first.'); return
        p = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV','*.csv')])
        if not p: return
        try:
            with open(p, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                for report, rows in self.results_by_report.items():
                    if not rows: continue
                    w.writerow([report]); headers=json.loads(rows[0][4]); w.writerow(headers)
                    for row in rows: w.writerow(json.loads(row[5]))
            messagebox.showinfo('Export', 'Exported search results.')
        except Exception as e: messagebox.showerror('Export error', str(e))

if __name__ == '__main__':
    if '--sync-and-import' in sys.argv:
        try:
            from auto_sync import sync_once
            ac = json.loads((app_dir() / 'auto_sync_config.json').read_text(encoding='utf-8'))
            if not ac.get('input_folder'): ac['input_folder'] = read_config().get('input_folder', '')
            sync_once({**read_config(), **ac})
        except Exception as e:
            print('Outlook sync:', e)
        cfg = read_config(); st = Store(cfg.get('db_path') or str(app_dir() / 'inventory.sqlite3'))
        folder = cfg.get('input_folder') or json.loads((app_dir() / 'auto_sync_config.json').read_text(encoding='utf-8')).get('input_folder', '')
        if folder and Path(folder).exists():
            print('Importing', folder)
            print('Imported rows:', import_path(st, Path(folder), set(REPORTS)))
        st.close()
    else:
        app = App(); app.mainloop()
