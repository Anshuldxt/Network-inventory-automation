import os,time,logging
from .importer import import_folder
from .db import init_db
logging.basicConfig(level=logging.INFO)
interval=int(os.getenv('SYNC_INTERVAL_SECONDS','3600'))

# Same reasoning as backend/app/main.py's startup handler: on a host reboot,
# Postgres may still be recovering when this process starts. Retry instead of
# crashing on the first attempt.
for attempt in range(1, 31):
    try:
        init_db()
        break
    except Exception as exc:
        if attempt == 30:
            raise
        logging.info("database not ready yet (attempt %s/30): %s", attempt, exc)
        time.sleep(2)

while True:
    try: logging.info('input scan: %s', import_folder())
    except Exception: logging.exception('input scan failed')
    time.sleep(interval)
