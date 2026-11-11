"""Isolated real-API corpus server; never touches the user's document library."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
server.STORAGE=Path(__file__).resolve().parent/'corpus'/'http-store'
server.STORAGE.mkdir(exist_ok=True)
server.CONTENT_INDEX.clear();server.JOBS.clear()
# Index previously uploaded test documents when a run is resumed.
import json,hashlib
for meta in server.STORAGE.glob('*.json'):
 if meta.name.endswith(('.analysis.json','.layout.json')):continue
 data=json.loads(meta.read_text(encoding='utf8'));raw=server.STORAGE/meta.stem
 if raw.exists():server.CONTENT_INDEX[(hashlib.sha256(raw.read_bytes()).hexdigest(),data['extension'])]=meta.stem
print('Isolated corpus API http://127.0.0.1:18766',flush=True)
server.ThreadingHTTPServer(('127.0.0.1',18766),server.Handler).serve_forever()
