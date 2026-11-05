import copy
import unittest
import torch
import experiment as e

torch.set_num_threads(1)

class ExperimentTests(unittest.TestCase):
    def test_signed_four_bit_packing_and_odd_lengths(self):
        weights=torch.tensor([[-7.,0.,7.]],dtype=torch.float64)
        artifact=e.quantize(weights,4)
        self.assertEqual(len(bytes.fromhex(artifact['payload_hex'])),2)
        torch.testing.assert_close(e.dequantize(artifact),weights,atol=0,rtol=0)

    def test_zero_row_and_error_bound_for_both_widths(self):
        for bits in [4,8]:
            weights=torch.tensor([[0.,0.,0.],[-0.7,0.1,0.9]],dtype=torch.float64)
            a=e.quantize(weights,bits);out=e.dequantize(a)
            bound=torch.tensor(a['scales'])[:,None]/2+1e-12
            self.assertTrue(((out-weights).abs()<=bound).all())

    def test_invalid_width_payload_and_scales_refused(self):
        with self.assertRaises(ValueError):e.quantize(torch.ones(2,2),3)
        for shape in [(0,2),(2,0)]:
            with self.assertRaises(ValueError):e.quantize(torch.empty(shape),4)
        a=e.quantize(torch.ones(2,2,dtype=torch.float64),4)
        for change in [{'payload_hex':''},{'scales':[0.,1.]},{'shape':[True,4]}]:
            with self.assertRaises(ValueError):e.dequantize({**a,**change})

    def test_batched_logits_match_individual_with_padding(self):
        p=e.parameters();sequences=[[1,3],[2,4,1,7]]
        batch=e.batched_logits(p,sequences)
        for i,ids in enumerate(sequences):
            logits,_=e.decoder.forward(p,ids,[0]*len(ids))
            torch.testing.assert_close(batch[i],logits[-1],atol=1e-10,rtol=1e-8)

    def test_schedule_preserves_outputs_and_admits_into_free_slot(self):
        r=e.batching_run();self.assertTrue(r['outputs_equal'])
        self.assertEqual(r['fixed']['logical_ticks'],6)
        self.assertEqual(r['continuous']['logical_ticks'],5)
        fixed=next(j for j in r['fixed']['jobs'] if j['id']=='c')
        continuous=next(j for j in r['continuous']['jobs'] if j['id']=='c')
        self.assertLess(continuous['admitted'],fixed['admitted'])

    def test_invalid_job_identity_capacity_and_context_refused(self):
        p=e.parameters();job={'id':'a','arrival':0,'prompt':[1],'tokens':2}
        for jobs,capacity in [([job],0),([job,job],2),([{**job,'tokens':0}],2),([{**job,'tokens':100}],2),([{**job,'prompt':[True]}],2)]:
            with self.assertRaises(ValueError):e.schedule(p,jobs,capacity=capacity)

    def test_idle_arrival_does_not_start_work_early(self):
        p=e.parameters();job={'id':'later','arrival':3,'prompt':[1],'tokens':1}
        r=e.schedule(p,[job]);self.assertEqual(r['jobs'][0]['admitted'],3);self.assertEqual(r['batch_forward_calls'],1)

if __name__=='__main__':unittest.main()
