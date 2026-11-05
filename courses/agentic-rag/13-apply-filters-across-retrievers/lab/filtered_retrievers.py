"""One version equality policy applied before either retriever selects top-k."""
import re
import sqlite3
from vector_retriever import rows_from_snapshot, version_filter


class LexicalRetriever:
    def __init__(self,snapshot):
        self.rows=rows_from_snapshot(snapshot)
        self.db=sqlite3.connect(':memory:')
        self.db.execute('CREATE VIRTUAL TABLE passages USING fts5(chunk_id UNINDEXED,source_id UNINDEXED,version UNINDEXED,url UNINDEXED,text, tokenize="unicode61")')
        self.db.executemany('INSERT INTO passages VALUES (?,?,?,?,?)',[(r['chunk_id'],r['source_id'],r['version'],r['url'],r['text']) for r in self.rows])

    def search(self,query,k=2,policy=None):
        if type(k) is not int or k<1:raise ValueError('invalid_k')
        version=version_filter(policy)
        if not isinstance(query,str) or re.fullmatch(r'[A-Za-z0-9]{1,64}',query) is None:raise ValueError('invalid_lexical_query')
        sql='SELECT chunk_id,source_id,version,url,text,bm25(passages) FROM passages WHERE passages MATCH ?'
        params=['"'+query+'"']
        if version is not None:
            sql+=' AND version=?';params.append(version)
        sql+=' ORDER BY bm25(passages),chunk_id LIMIT ?';params.append(k)
        return [dict(zip(('chunk_id','source_id','version','url','text','native_score'),row)) for row in self.db.execute(sql,params)]

    def close(self):self.db.close()


def candidates(rows,policy):
    version=version_filter(policy)
    return sorted(r['chunk_id'] for r in rows if version is None or r['version']==version)
