"""Verbatim Module 6 lexical symbols, without importing unused vector SDKs."""
import re
import sqlite3
from version_documents import validate_snapshot

PAYLOAD_KEYS=('chunk_id','source_id','version','url','text')

def version_filter(policy):
    if policy is None or policy=={}:return None
    if not isinstance(policy,dict) or set(policy)!={'version'}:raise ValueError('unsupported_filter')
    operator=policy['version']
    if not isinstance(operator,dict) or set(operator)!={'$eq'}:raise ValueError('unsupported_filter_operator')
    version=operator['$eq']
    if not isinstance(version,str) or re.fullmatch(r'[0-9]+\.[0-9]+',version) is None:raise ValueError('invalid_filter_version')
    return version


def rows_from_snapshot(snapshot):
    validate_snapshot(snapshot)
    rows=[];seen=set()
    for source in snapshot['documents']:
        if not isinstance(source.get('version'),str) or re.fullmatch(r'[0-9]+\.[0-9]+',source['version']) is None:raise ValueError('invalid_source_version')
        for chunk in source['chunks']:
            if chunk['chunk_id'] in seen:raise ValueError('duplicate_chunk_id')
            seen.add(chunk['chunk_id'])
            rows.append({'chunk_id':chunk['chunk_id'],'source_id':source['source_id'],'version':source['version'],'url':source['url'],'text':chunk['text']})
    return rows


def positive_int(value, name):
    if type(value) is not int or not 1<=value<=100:
        raise ValueError('invalid_'+name)


def question_terms(query):
    if not isinstance(query,str) or not query.strip() or len(query)>512:
        raise ValueError('invalid_query')
    tokens=re.findall(r'[a-z0-9]+',query.lower())
    if not tokens or len(tokens)>32 or any(len(token)>64 for token in tokens):
        raise ValueError('invalid_query')
    return list(dict.fromkeys(tokens))


class QuestionLexicalRetriever:
    def __init__(self,snapshot):
        self.rows=rows_from_snapshot(snapshot)
        self.db=sqlite3.connect(':memory:')
        try:
            self.db.execute('CREATE VIRTUAL TABLE passages USING fts5(chunk_id UNINDEXED,source_id UNINDEXED,version UNINDEXED,url UNINDEXED,text, tokenize="unicode61")')
            self.db.executemany('INSERT INTO passages VALUES(?,?,?,?,?)',[(r['chunk_id'],r['source_id'],r['version'],r['url'],r['text']) for r in self.rows])
        except Exception:
            self.db.close();raise
    def search(self,query,k=3,policy=None):
        positive_int(k,'candidate_budget')
        version=version_filter(policy)
        terms=question_terms(query)
        expression=' OR '.join('"'+term+'"' for term in terms)
        sql='SELECT chunk_id,source_id,version,url,text,bm25(passages) FROM passages WHERE passages MATCH ?'
        params=[expression]
        if version is not None:
            sql+=' AND version=?';params.append(version)
        sql+=' ORDER BY bm25(passages),chunk_id LIMIT ?';params.append(k)
        return [dict(zip((*PAYLOAD_KEYS,'native_score'),row)) for row in self.db.execute(sql,params)]
    def close(self):self.db.close()

