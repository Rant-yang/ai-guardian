"""Local source locators, separate from exported/redacted action history.

Only routing identities are stored; never prompts, tool arguments or credentials.
Expiry uses wall time so a service restart does not invalidate live sessions.
"""
import json
import sqlite3
import threading
import time


class LocatorStore:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS locators (kind TEXT, event TEXT, value TEXT, expires REAL, PRIMARY KEY(kind,event))')
        self.db.commit()

    def put(self, kind, event, value):
        with self.lock, self.db:
            self.db.execute('DELETE FROM locators WHERE expires <= ?', (time.time(),))
            self.db.execute('INSERT OR IGNORE INTO locators VALUES (?,?,?,?)',
                            (kind, event, json.dumps(value), time.time()+86400))
            self.db.execute('DELETE FROM locators WHERE kind=? AND event NOT IN '
                            '(SELECT event FROM locators WHERE kind=? ORDER BY expires DESC LIMIT 2000)', (kind,kind))

    def get(self, kind, event):
        with self.lock:
            row = self.db.execute('SELECT value,expires FROM locators WHERE kind=? AND event=? AND expires>?',
                                  (kind,event,time.time())).fetchone()
        if not row:return None
        try:return json.loads(row[0]), row[1]-time.time()
        except (ValueError,TypeError):return None

    def forget(self, event_ids):
        with self.lock, self.db:
            self.db.executemany('DELETE FROM locators WHERE event=?', ((identity,) for identity in event_ids))

    def close(self):
        with self.lock:self.db.close()
