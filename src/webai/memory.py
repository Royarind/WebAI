import json, sqlite3, time
from pathlib import Path

class Memory:
    """Local SQLite run history and domain-specific notes; no cloud sync."""
    def __init__(self, path='webai_memory.sqlite3'):
        self.path=str(path)
        parent=Path(self.path).parent
        if str(parent) not in ('','.'): parent.mkdir(parents=True,exist_ok=True)
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, created REAL, task TEXT, status TEXT, summary TEXT, artifacts TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, created REAL, domain TEXT, note TEXT, metadata TEXT)')
    def _connect(self): return sqlite3.connect(self.path)
    def add_run(self,task,status,summary,artifacts=None):
        with self._connect() as db:
            db.execute('INSERT INTO runs(created,task,status,summary,artifacts) VALUES(?,?,?,?,?)',(time.time(),task,status,summary,json.dumps(artifacts or [])))
    def add_note(self,domain,note,metadata=None):
        with self._connect() as db:
            db.execute('INSERT INTO notes(created,domain,note,metadata) VALUES(?,?,?,?)',(time.time(),domain,note,json.dumps(metadata or {})))
    def recent_runs(self,limit=10):
        with self._connect() as db: rows=db.execute('SELECT id,created,task,status,summary FROM runs ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [dict(id=r[0],created=r[1],task=r[2],status=r[3],summary=r[4]) for r in rows]
    def notes_for(self,domain,limit=5):
        with self._connect() as db: rows=db.execute('SELECT note,metadata FROM notes WHERE domain=? ORDER BY id DESC LIMIT ?', (domain,limit)).fetchall()
        return [{'note':r[0],'metadata':json.loads(r[1] or '{}')} for r in rows]
