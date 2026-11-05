import copy
import math
import unittest
import torch
import updates as u

torch.set_num_threads(1)

class PreferenceTests(unittest.TestCase):
    def test_equal_policy_reference_starts_at_log_two(self):
        p = u.policy();r = u.frozen(p)
        self.assertAlmostEqual(u.dpo_loss(p, r, u.PAIRS).item(), math.log(2), places=12)

    def test_dpo_updates_reduce_loss_without_reference_gradients(self):
        result = u.run_dpo()
        self.assertLess(result['loss_after'], result['loss_before'])
        self.assertFalse(result['reference_has_gradients'])

    def test_dpo_gradient_increases_chosen_relative_margin(self):
        p=u.policy();r=u.frozen(p);pair=u.PAIRS[0]
        def margin():
            return (u.token_logps(p,pair['prompt'],pair['chosen']).sum()-u.token_logps(p,pair['prompt'],pair['rejected']).sum()).item()
        before=margin();optimizer=torch.optim.SGD(p.values(),lr=0.01)
        u.dpo_loss(p,r,[pair]).backward();optimizer.step()
        self.assertGreater(margin(),before)

    def test_grpo_clipping_and_gradient_isolation(self):
        p=u.policy();r={key:value.detach().clone().requires_grad_() for key,value in p.items()}
        completions=[[1,2],[2,3]]
        old=[(u.token_logps(p,[1],c).detach()-math.log(2)).requires_grad_() for c in completions]
        loss=u.grpo_loss(p,r,old,[1],completions,[0,1],beta=0)
        self.assertAlmostEqual(loss.item(),0.4/(1+2e-8),places=10)
        loss.backward()
        self.assertTrue(all(value.grad is None for value in r.values()))
        self.assertTrue(all(value.grad is None for value in old))

    def test_identical_pairs_and_invalid_beta_refused(self):
        p=u.policy();r=u.frozen(p);pair=copy.deepcopy(u.PAIRS[0]);pair['rejected']=pair['chosen']
        for pairs,beta in [([pair],0.3),(u.PAIRS,0),(u.PAIRS,float('nan')),([],0.3)]:
            with self.assertRaises(ValueError):u.dpo_loss(p,r,pairs,beta)

    def test_completion_scoring_excludes_prompt_positions(self):
        p=u.policy();pair=u.PAIRS[0]
        values=u.token_logps(p,pair['prompt'],pair['chosen'])
        self.assertEqual(len(values),len(pair['chosen']))
        ids=pair['prompt']+pair['chosen'][:-1]
        logits,_=u.decoder.forward(p,ids,[0]*len(ids))
        self.assertAlmostEqual(values[0].item(),logits[len(pair['prompt'])-1].log_softmax(-1)[pair['chosen'][0]].item())

    def test_group_advantages_center_and_handle_zero_variance(self):
        a=u.advantages([0,0,1,0]);self.assertAlmostEqual(a.sum().item(),0,places=12)
        self.assertTrue(u.advantages([1,1,1]).eq(0).all())
        with self.assertRaises(ValueError):u.advantages([0,float('nan')])

    def test_sampling_uses_policy_and_preserves_fixed_lengths(self):
        p=u.policy();g=torch.Generator().manual_seed(47)
        completions=u.sample(p,[1,3],16,2,g)
        self.assertEqual(len(completions),16)
        self.assertTrue(all(len(c)==2 and all(0<=i<9 for i in c) for c in completions))
        with self.assertRaises(ValueError):u.sample(p,[1],1,2,g)

    def test_grpo_alignment_and_invalid_clipping_refused(self):
        p=u.policy();r=u.frozen(p);c=[[1,2],[2,3]];old=[u.token_logps(p,[1],x).detach() for x in c]
        for rewards,clip in [([1],0.2),([0,1],0),([0,1],1)]:
            with self.assertRaises(ValueError):u.grpo_loss(p,r,old,[1],c,rewards,clip=clip)

    def test_online_rewards_correspond_to_actual_generated_tokens(self):
        result=u.run_grpo()
        self.assertEqual(result['sampled_completions'],128)
        for group in result['trace']:
            self.assertEqual(group['rewards'],[float(c[0]==6) for c in group['completions']])
            self.assertTrue(all(math.isfinite(value) for value in group['losses']))

if __name__=='__main__':unittest.main()
