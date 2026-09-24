import os,time,logging
from .importer import import_folder
from .db import init_db
logging.basicConfig(level=logging.INFO)
interval=int(os.getenv('SYNC_INTERVAL_SECONDS','3600'))
init_db()
while True:
    try: logging.info('input scan: %s', import_folder())
    except Exception: logging.exception('input scan failed')
    time.sleep(interval)
