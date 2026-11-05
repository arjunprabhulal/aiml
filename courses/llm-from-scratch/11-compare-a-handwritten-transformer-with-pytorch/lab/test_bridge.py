import hashlib
import json
import unittest
import torch
import bridge as b

class BridgeTests(unittest.TestCase):
    def test_saved_run_still_matches_implementation_sources(self):
        record=json.loads((b.HERE/'result.json').read_text())
        for name, expected in record['sources'].items():
            self.assertEqual(hashlib.sha256((b.HERE/name).read_bytes()).hexdigest(),expected)
        self.assertTrue(all(row['passed'] for row in record['comparisons'].values()))
    def test_explicit_outputs_loss_and_all_gradients(self):
        r=b.compare('explicit');self.assertTrue(r['passed'])
        self.assertEqual(len(r['parameter_gradients']),len(b.params()))
        self.assertEqual(r['nonzero_manual_gradient_tensors'],len(b.params()))
    def test_sdpa_outputs_loss_and_all_gradients(self):
        self.assertTrue(b.compare('sdpa')['passed'])
    def test_repeated_token_embedding_accumulates_gradient(self):
        p=b.tensors(b.params());_,loss=b.forward(p,b.IDS,b.TARGETS);loss.backward()
        self.assertGreater(p['tok_emb'].grad[1].abs().max().item(),0)
        self.assertTrue(b.compare('sdpa')['parameter_gradients']['tok_emb']['passed'])
    def test_unused_embedding_rows_and_positions_have_zero_gradient(self):
        p=b.tensors(b.params());_,loss=b.forward(p,b.IDS,b.TARGETS);loss.backward()
        self.assertEqual(p['tok_emb'].grad[8].abs().max().item(),0)
        self.assertEqual(p['pos_emb'].grad[len(b.IDS):].abs().max().item(),0)
    def test_no_causal_mask_changes_outputs(self):
        self.assertFalse(b.failures()['mismatch_probes']['no_causal_mask']['passed'])
    def test_missing_scale_changes_outputs(self):
        self.assertFalse(b.failures()['mismatch_probes']['unscaled_attention']['passed'])
    def test_wrong_layernorm_epsilon_changes_outputs(self):
        self.assertFalse(b.failures()['mismatch_probes']['wrong_layernorm_epsilon']['passed'])
    def test_invalid_ids_and_target_lengths_refused(self):
        self.assertEqual(len(b.failures()['refused_inputs']),4)
    def test_causal_future_token_cannot_change_earlier_logits(self):
        for path in ('explicit','sdpa'):
            p=b.tensors(b.params());a,_=b.forward(p,b.IDS,b.TARGETS,path)
            ids=b.IDS[:-1]+[7];c,_=b.forward(p,ids,b.TARGETS,path)
            self.assertTrue(torch.equal(a[:-1],c[:-1]));self.assertFalse(torch.equal(a[-1],c[-1]))
    def test_bad_comparison_shapes_and_nonfinite_values_refused(self):
        for a,c in [([1],[1,2]),([float('nan')],[1])]:
            with self.assertRaises(ValueError):b.difference(a,c)
    def test_unknown_attention_path_refused(self):
        with self.assertRaises(ValueError):b.forward(b.tensors(b.params()),b.IDS,b.TARGETS,'unknown')

if __name__=='__main__':unittest.main()
