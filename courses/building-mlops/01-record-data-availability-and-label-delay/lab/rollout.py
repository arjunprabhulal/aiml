"""Transactional local routing state and explicit compatible rollback."""
import hashlib
from pathlib import Path
import sqlite3
import workflow as w
import serving
import release


class Routing:
    def __init__(self,path):
        self.db=sqlite3.connect(path)
        self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE IF NOT EXISTS releases (generation INTEGER PRIMARY KEY,stable TEXT NOT NULL,candidate TEXT NOT NULL,percent INTEGER NOT NULL,reason TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS head (singleton INTEGER PRIMARY KEY CHECK(singleton=1), generation INTEGER NOT NULL)')
        self.db.commit()

    def close(self):self.db.close()

    def current(self):
        row=self.db.execute('SELECT r.* FROM releases r JOIN head h ON r.generation=h.generation').fetchone()
        if row is None:raise ValueError('no routing release selected')
        return dict(row)

    def stage(self,stable,candidate,percent,expected_generation,reason='stage'):
        if type(percent) is not int or not 0<=percent<=100:raise ValueError('percent must be an integer from 0 to 100')
        for path in [stable,candidate]:
            _,_,decision=release.load_bundle(path)
            if not decision['passed']:raise ValueError('gate failure prevents routing')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT generation FROM head WHERE singleton=1').fetchone()
            old=row[0] if row else 0
            if expected_generation!=old:raise ValueError('routing changed; reload before editing')
            generation=old+1
            self.db.execute('INSERT INTO releases VALUES (?,?,?,?,?)',(generation,str(Path(stable).resolve()),str(Path(candidate).resolve()),percent,reason))
            self.db.execute('INSERT INTO head VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET generation=excluded.generation',(generation,))
            self.db.commit();return self.current()
        except Exception:self.db.rollback();raise

    def predict(self,value):
        # Invalid requests cannot influence routing or create prediction records.
        value=serving.request(value);state=self.current()
        bucket=int(hashlib.sha256(value['id'].encode()).hexdigest()[:8],16)%100
        chosen=state['candidate'] if bucket<state['percent'] else state['stable']
        result=serving.Predictor(chosen).predict(value)
        return dict(result,generation=state['generation'],route='candidate' if bucket<state['percent'] else 'stable',bucket=bucket)

    def rollback(self,target_generation,expected_generation):
        row=self.db.execute('SELECT * FROM releases WHERE generation=?',(target_generation,)).fetchone()
        if row is None:raise ValueError('unknown rollback generation')
        # Revalidate target bytes and code compatibility before changing the head.
        return self.stage(row['stable'],row['candidate'],row['percent'],expected_generation,'rollback to '+str(target_generation))
