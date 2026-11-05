"""Native SQLite FTS5 BM25 over a validated local documentation snapshot."""
from collections import Counter
import math
import re
import sqlite3
from version_documents import validate_snapshot

class LexicalIndex:
    def __init__(self, snapshot):
        validate_snapshot(snapshot)
        self.connection = sqlite3.connect(':memory:')
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("CREATE VIRTUAL TABLE passages USING fts5(text,chunk_id UNINDEXED,source_id UNINDEXED,version UNINDEXED,url UNINDEXED, tokenize='unicode61')")
            for document in snapshot['documents']:
                for chunk in document['chunks']:
                    self.connection.execute('INSERT INTO passages(text,chunk_id,source_id,version,url) VALUES(?,?,?,?,?)', (chunk['text'],chunk['chunk_id'],document['source_id'],document['version'],document['url']))
            self.connection.execute("CREATE VIRTUAL TABLE vocabulary USING fts5vocab(passages,'instance')")
            self.connection.execute("CREATE VIRTUAL TABLE terms USING fts5vocab(passages,'row')")
        except sqlite3.OperationalError:
            self.connection.close()
            raise
        self.snapshot_id=snapshot['snapshot_id']
    def close(self):
        self.connection.close()
    def indexed_terms(self):
        return [dict(row) for row in self.connection.execute('SELECT term,doc AS document_frequency,cnt AS occurrences FROM terms ORDER BY term')]
    def search(self, query, limit=10):
        if not isinstance(query,str) or not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=100:
            raise ValueError('invalid_query')
        query=query.strip().lower()
        if not query:
            return {'query':query,'status':'empty_query','results':[]}
        # Bounded literal words; spaces and underscores separate terms, never operators.
        if len(query)>256 or not re.fullmatch(r'[a-z0-9_ ]+',query):
            raise ValueError('invalid_query')
        tokens=list(dict.fromkeys(re.findall(r'[a-z0-9]+',query)))
        if not tokens or len(tokens)>16 or any(len(term)>64 for term in tokens):
            raise ValueError('invalid_query')
        if len(tokens)>1:
            return self._search_terms(query,tokens,limit)
        query=tokens[0]
        lengths={row['rowid']:0 for row in self.connection.execute('SELECT rowid FROM passages')}
        frequencies=Counter()
        for row in self.connection.execute('SELECT term,doc FROM vocabulary'):
            lengths[row['doc']]+=1
            if row['term']==query:frequencies[row['doc']]+=1
        count=len(lengths);average=sum(lengths.values())/count if count else 0
        df=len(frequencies)
        idf=max(math.log((count-df+0.5)/(df+0.5)),1e-6) if count else 0
        rows=self.connection.execute('SELECT rowid,text,chunk_id,source_id,version,url,bm25(passages) AS native_score FROM passages WHERE passages MATCH ? ORDER BY native_score ASC,chunk_id ASC LIMIT ?',('"'+query+'"',limit)).fetchall()
        results=[]
        for row in rows:
            tf=frequencies[row['rowid']];length=lengths[row['rowid']]
            length_factor=1-0.75+0.75*length/average
            saturation=tf*(1.2+1)/(tf+1.2*length_factor)
            results.append({key:row[key] for key in ('chunk_id','source_id','version','url','text','native_score')} | {'term_frequency':tf,'document_length':length,'average_document_length':average,'document_frequency':df,'idf':idf,'length_factor':length_factor,'saturation':saturation,'explained_score':-idf*saturation})
        return {'query':query,'status':'ok' if results else 'no_match','results':results}

    def _search_terms(self, query, tokens, limit):
        expression=' OR '.join('"'+term+'"' for term in tokens)
        rows=self.connection.execute(
            'SELECT text,chunk_id,source_id,version,url,bm25(passages) AS native_score FROM passages WHERE passages MATCH ? ORDER BY native_score ASC,chunk_id ASC LIMIT ?',
            (expression,limit)).fetchall()
        # Single-term diagnostic fields are intentionally absent for a multi-term score.
        return {'query':query,'status':'ok' if rows else 'no_match','results':[dict(row) for row in rows]}
