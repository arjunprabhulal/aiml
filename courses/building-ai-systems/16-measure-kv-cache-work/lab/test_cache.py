import math
import unittest
from cache import Cache, full, generate, step, workload_sweep, D
class CacheTests(unittest.TestCase):
    def test_each_cached_position_matches_full_causal_attention(self):
        tokens=[1,4,2,9,3];cache=Cache()
        for pos,token in enumerate(tokens):
            got=step(cache,token,pos);want=full(tokens[:pos+1])[-1]
            self.assertTrue(all(math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12) for a,b in zip(got,want)))
    def test_generated_sequence_is_identical(self):
        self.assertEqual(generate([1,2,3],8,True)['tokens'],generate([1,2,3],8,False)['tokens'])
    def test_causal_outputs_do_not_change_with_future_tokens(self):
        self.assertEqual(full([1,2]),full([1,2,3])[:2])
    def test_cache_reduces_counted_work(self):
        a=generate([1,2,3],8,False);b=generate([1,2,3],8,True)
        self.assertLess(b['projected_token_rows'],a['projected_token_rows'])
        self.assertLess(b['attention_score_cells'],a['attention_score_cells'])
    def test_wrong_position_rejected_without_mutation(self):
        c=Cache()
        with self.assertRaisesRegex(ValueError,'position'): step(c,1,2)
        self.assertEqual(c.tokens,[])
    def test_wrong_model_rejected(self):
        with self.assertRaisesRegex(ValueError,'model'): step(Cache(model_id='old'),1,0)
    def test_invalid_token_and_empty_prefix_rejected(self):
        with self.assertRaises(ValueError): step(Cache(),99,0)
        with self.assertRaises(ValueError): generate([],1,True)
    def test_workload_sweep_matches_the_executed_row_counts(self):
        for row in workload_sweep():
            p,n=row['prompt_tokens'],row['new_tokens']
            self.assertTrue(row['identical_tokens'])
            self.assertEqual(row['uncached_rows'],sum(range(p,p+n)))
            self.assertEqual(row['cached_rows'],p+n-1)
            self.assertEqual(row['retained_kv_floats'],2*D*(p+n-1))
if __name__ == '__main__': unittest.main()
