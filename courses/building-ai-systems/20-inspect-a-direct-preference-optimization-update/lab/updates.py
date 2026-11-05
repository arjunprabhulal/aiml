"""DPO and online group-relative updates on a tiny synthetic-vocabulary LM.

This is an objective/mechanism experiment, not pretrained-model alignment.
"""
import copy
import json
import math
from pathlib import Path
import torch
import torch.nn.functional as F
import decoder

HERE = Path(__file__).resolve().parent
PAIRS = [{'prompt': [1, 3], 'chosen': [6, 2], 'rejected': [4, 2]},
         {'prompt': [2, 5], 'chosen': [6, 2], 'rejected': [7, 2]}]


def policy():
    return decoder.tensors(decoder.params())


def frozen(parameters):
    return {key: value.detach().clone() for key, value in parameters.items()}


def token_logps(parameters, prompt, completion):
    if not isinstance(prompt, list) or not isinstance(completion, list) or not prompt or not completion:
        raise ValueError('prompt and completion must be nonempty')
    ids = prompt + completion[:-1]
    decoder.inputs(parameters, ids, [0] * len(ids))
    decoder.inputs(parameters, completion, [0] * len(completion))
    logits, _ = decoder.forward(parameters, ids, [0] * len(ids))
    selected = logits[len(prompt)-1:].log_softmax(-1)
    return selected.gather(1, torch.tensor(completion).unsqueeze(1)).squeeze(1)


def dpo_loss(parameters, reference, pairs, beta=0.3):
    if not math.isfinite(beta) or beta <= 0 or not pairs:
        raise ValueError('positive beta and preference pairs required')
    losses = []
    for pair in pairs:
        if not isinstance(pair, dict) or set(pair) != {'prompt', 'chosen', 'rejected'} or pair['chosen'] == pair['rejected']:
            raise ValueError('distinct chosen and rejected completions required')
        prompt, chosen, rejected = (pair[key] for key in ('prompt', 'chosen', 'rejected'))
        margin = token_logps(parameters, prompt, chosen).sum() - token_logps(parameters, prompt, rejected).sum()
        with torch.no_grad():
            ref_margin = token_logps(reference, prompt, chosen).sum() - token_logps(reference, prompt, rejected).sum()
        losses.append(-F.logsigmoid(beta * (margin - ref_margin)))
    return torch.stack(losses).mean()


def sample(parameters, prompt, count, length, generator):
    if type(count) is not int or count < 2 or type(length) is not int or length < 1:
        raise ValueError('group size >=2 and positive completion length required')
    completions = []
    with torch.no_grad():
        for _ in range(count):
            generated = []
            for _ in range(length):
                ids = prompt + generated
                decoder.inputs(parameters, ids, [0] * len(ids))
                logits, _ = decoder.forward(parameters, ids, [0] * len(ids))
                token = torch.multinomial(logits[-1].softmax(-1), 1, generator=generator).item()
                generated.append(token)
            completions.append(generated)
    return completions


def advantages(rewards):
    values = torch.tensor(rewards, dtype=torch.float64)
    if values.ndim != 1 or len(values) < 2 or not torch.isfinite(values).all():
        raise ValueError('finite reward group with at least two members required')
    std = values.std(unbiased=False)
    if std.item() == 0:
        return torch.zeros_like(values)
    return (values - values.mean()) / (std + 1e-8)


def grpo_loss(parameters, reference, old_logps, prompt, completions, rewards, clip=0.2, beta=0.04):
    if not 0 < clip < 1 or not math.isfinite(beta) or beta < 0:
        raise ValueError('clip in (0,1) and nonnegative finite KL coefficient required')
    if not (len(completions) == len(rewards) == len(old_logps)) or len({len(c) for c in completions}) != 1:
        raise ValueError('aligned equal-length completion group required')
    if any(not isinstance(old, torch.Tensor) or old.shape != (len(completion),) or not torch.isfinite(old).all() for old, completion in zip(old_logps, completions)):
        raise ValueError('old-policy token log-probabilities must align with completions')
    advantage = advantages(rewards)
    losses = []
    for i, completion in enumerate(completions):
        current = token_logps(parameters, prompt, completion)
        ratio = (current - old_logps[i].detach()).exp()
        with torch.no_grad():
            ref = token_logps(reference, prompt, completion)
        delta = ref - current
        kl = delta.exp() - delta - 1
        surrogate = torch.minimum(ratio * advantage[i], ratio.clamp(1-clip, 1+clip) * advantage[i])
        losses.append((-surrogate + beta * kl).mean())
    return torch.stack(losses).mean()


def run_dpo():
    parameters = policy(); reference = frozen(parameters)
    optimizer = torch.optim.SGD(parameters.values(), lr=0.1)
    before = dpo_loss(parameters, reference, PAIRS).item()
    history = []
    for _ in range(30):
        optimizer.zero_grad();loss = dpo_loss(parameters, reference, PAIRS)
        loss.backward();optimizer.step();history.append(loss.item())
    after = dpo_loss(parameters, reference, PAIRS).item()
    return {'mode': 'fresh CPU parameter updates on a tiny synthetic-vocabulary language model',
            'method': 'DPO sigmoid loss; frozen reference; completion log-probability sums',
            'pairs': PAIRS, 'beta': 0.3, 'steps': len(history), 'learning_rate': 0.1,
            'loss_before': before, 'loss_after': after, 'loss_history': history,
            'reference_has_gradients': any(t.grad is not None for t in reference.values()),
            'scope': 'Authored token preferences, not human annotation or pretrained-model alignment.'}


def run_grpo():
    parameters = policy(); reference = frozen(parameters)
    optimizer = torch.optim.SGD(parameters.values(), lr=0.02)
    generator = torch.Generator().manual_seed(47)
    prompt = [1, 3]; trace = []
    def desired_probability():
        with torch.no_grad():
            logits, _ = decoder.forward(parameters, prompt, [0] * len(prompt))
            return logits[-1].softmax(-1)[6].item()
    before = desired_probability()
    for step in range(8):
        completions = sample(parameters, prompt, 16, 2, generator)
        # Authored syntactic reward: first generated token equals token 6.
        rewards = [float(completion[0] == 6) for completion in completions]
        old = [token_logps(parameters, prompt, completion).detach() for completion in completions]
        a = advantages(rewards)
        losses = []
        for _ in range(2):
            optimizer.zero_grad();loss = grpo_loss(parameters, reference, old, prompt, completions, rewards)
            loss.backward();optimizer.step();losses.append(loss.item())
        trace.append({'step': step, 'completions': completions, 'rewards': rewards,
                      'advantages': a.tolist(), 'losses': losses, 'zero_variance': bool(a.eq(0).all())})
    return {'mode': 'fresh online CPU sampling and parameter updates on a tiny synthetic-vocabulary LM',
            'method': 'fixed-length token-level clipped group-relative objective with sampled KL penalty',
            'prompt': prompt, 'seed': 47, 'group_size': 16, 'completion_length': 2,
            'groups': len(trace), 'inner_updates': 2, 'clip': 0.2, 'kl_beta': 0.04,
            'reward': '1 if the first generated token equals 6; otherwise 0',
            'desired_token_probability_before': before, 'desired_token_probability_after': desired_probability(),
            'sampled_completions': sum(len(group['completions']) for group in trace), 'trace': trace,
            'scope': 'No semantic quality, human preference, reasoning or held-out capability claim.'}
