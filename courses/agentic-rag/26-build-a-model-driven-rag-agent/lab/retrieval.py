"""Multi-term lexical search; keep the preceding lab's receipt-bound reads."""
import copy
import re
from tools import DocumentationTools, ToolError
from version_documents import canonical_hash


class RetrievalTools(DocumentationTools):
    def search(self, query, k=2, version='3.12'):
        self.available()
        if not isinstance(query, str) or not query.strip() or len(query) > 512:
            raise ToolError('invalid_query')
        if type(k) is not int or not 1 <= k <= 4:
            raise ToolError('invalid_k')
        if not isinstance(version, str) or re.fullmatch(r'[0-9]+\.[0-9]+', version) is None:
            raise ToolError('invalid_version')
        terms = sorted(set(re.findall(r'[a-z0-9]+', query.lower())))
        if not terms or len(terms) > 64:
            raise ToolError('invalid_query')
        # Literal OR terms, never caller-supplied FTS syntax. Version filtering
        # precedes LIMIT. This is lexical retrieval, not vector/hybrid search.
        expression = ' OR '.join('"' + term + '"' for term in terms)
        ranked = self.index.connection.execute(
            'SELECT chunk_id,bm25(passages) AS score FROM passages '
            'WHERE passages MATCH ? AND version=? ORDER BY score,chunk_id LIMIT ?',
            (expression, version, k)).fetchall()
        request = dict(corpus_id=self.corpus_id, query=' '.join(terms), version=version, k=k)
        request_id = canonical_hash(request)
        handles = []
        for rank, row in enumerate(ranked, 1):
            source = self.rows[row['chunk_id']]
            handle = dict(corpus_id=self.corpus_id, search_request_id=request_id,
                          **{key: value for key, value in source.items() if key not in ('text', 'url')},
                          native_score=row['score'], rank=rank)
            handle['read_token'] = canonical_hash(handle)
            handles.append(handle)
        result = dict(request, search_request_id=request_id, results=handles)
        self.receipts[request_id] = copy.deepcopy(result)
        return copy.deepcopy(result)
