"""Actual SQLite lexical + LangChain saved-vector retrieval, fused by rank."""
import math
import re
import sqlite3
from vector_retriever import VectorRetriever, rows_from_snapshot, version_filter

PAYLOAD_KEYS=('chunk_id','source_id','version','url','text')

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

def reciprocal_rank_fusion(lexical,vector,k=2,rank_constant=60):
    positive_int(k,'k')
    if type(rank_constant) is not int or rank_constant<=0 or rank_constant>1000000:
        raise ValueError('invalid_rank_constant')
    merged={}
    for branch,rows,score_key in [('lexical',lexical,'native_score'),('vector',vector,'score')]:
        if not isinstance(rows,list) or len(rows)>100:raise ValueError('invalid_candidates')
        seen=set()
        for rank,row in enumerate(rows,1):
            if not isinstance(row,dict) or any(not isinstance(row.get(key),str) or not row[key] for key in PAYLOAD_KEYS):
                raise ValueError('invalid_candidate_payload')
            key=row['chunk_id']
            if key in seen:raise ValueError('duplicate_branch_chunk_id')
            seen.add(key)
            score=row.get(score_key)
            try:
                valid_score=type(score) in (int,float) and math.isfinite(score)
            except OverflowError:
                valid_score=False
            if not valid_score:raise ValueError('invalid_native_score')
            payload={key:row[key] for key in PAYLOAD_KEYS}
            if key not in merged:
                merged[key]={**payload,'lexical_score':None,'vector_score':None,'lexical_rank':None,'vector_rank':None,'lexical_contribution':0.0,'vector_contribution':0.0,'fused_score':0.0}
            elif any(merged[key][field]!=payload[field] for field in PAYLOAD_KEYS):
                raise ValueError('inconsistent_chunk_payload')
            merged[key][branch+'_score']=score
            merged[key][branch+'_rank']=rank
            merged[key][branch+'_contribution']=1.0/(rank_constant+rank)
    for row in merged.values():
        row['fused_score']=math.fsum([row['lexical_contribution'],row['vector_contribution']])
    return sorted(merged.values(),key=lambda row:(-row['fused_score'],row['chunk_id']))[:k]

class HybridRetriever:
    def __init__(self,snapshot,embeddings):
        self.vector=VectorRetriever(snapshot,embeddings)
        self.lexical=QuestionLexicalRetriever(snapshot)
    def close(self):self.lexical.close()
    def search(self,query,k=2,candidate_budget=3,rank_constant=60,policy=None):
        positive_int(k,'k');positive_int(candidate_budget,'candidate_budget')
        if candidate_budget<k:raise ValueError('candidate_budget_below_k')
        if type(rank_constant) is not int or not 1<=rank_constant<=1000000:raise ValueError('invalid_rank_constant')
        terms=question_terms(query);version_filter(policy)
        lexical=self.lexical.search(query,k=candidate_budget,policy=policy)
        # Original full question: no substitution with the lexical tokens.
        vector=self.vector.search(query,k=candidate_budget,policy=policy)
        return {'query':query,'lexical_query_terms':terms,'lexical':lexical,'vector':vector,
                'results':reciprocal_rank_fusion(lexical,vector,k,rank_constant)}
