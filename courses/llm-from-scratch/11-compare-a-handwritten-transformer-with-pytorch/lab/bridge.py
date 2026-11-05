"""Compare the unchanged list transformer with CPU float64 PyTorch autograd."""
import argparse
import hashlib
import json
import math
import platform
import sys
from pathlib import Path
import torch
import torch.nn.functional as F
from torch.nn.attention import SDPBackend, sdpa_kernel
from vendor import model

HERE = Path(__file__).resolve().parent
ATOL, RTOL = 1e-10, 1e-8
CONFIG = {'vocab': 9, 'd': 4, 'hidden': 7, 'max_len': 8, 'seed': 31}
IDS, TARGETS = [1, 3, 1, 5, 2], [3, 1, 5, 2, 6]


def params():
    return model.init_params(**CONFIG)


def tensors(p):
    return {name: torch.tensor(value, dtype=torch.float64, device='cpu', requires_grad=True)
            for name, value in p.items()}


def inputs(p, ids, targets):
    vocab = len(p['tok_emb'])
    if (not ids or len(ids) > len(p['pos_emb']) or len(targets) != len(ids)
            or any(type(i) is not int or not 0 <= i < vocab for i in [*ids, *targets])):
        raise ValueError('require nonempty in-range integer IDs, matching targets and available positions')


def attention(q, k, v, path='explicit', *, causal=True, scale=None):
    scale = 1 / math.sqrt(q.shape[-1]) if scale is None else scale
    if path == 'explicit':
        scores = (q @ k.T) * scale
        if causal:
            allowed = torch.ones(q.shape[0], k.shape[0], dtype=torch.bool).tril()
            scores = scores.masked_fill(~allowed, float('-inf'))
        return scores.softmax(dim=-1) @ v
    if path != 'sdpa':
        raise ValueError('unknown attention path')
    # Shape: (batch=1, heads=1, positions, width). Force the documented math backend.
    with sdpa_kernel(backends=[SDPBackend.MATH]):
        mixed = F.scaled_dot_product_attention(q[None, None], k[None, None], v[None, None],
                                              dropout_p=0.0, is_causal=causal, scale=scale)
    return mixed[0, 0]


def forward(p, ids, targets, path='explicit', *, causal=True, scale=None, eps=model.EPS):
    inputs(p, ids, targets)
    x0 = p['tok_emb'][ids] + p['pos_emb'][:len(ids)]
    norm = lambda x, name: F.layer_norm(x, (CONFIG['d'],), p[name+'_g'], p[name+'_b'], eps=eps)
    h1 = norm(x0, 'ln1')
    q, k, v = (h1 @ p[name] for name in ('Wq', 'Wk', 'Wv'))
    x1 = x0 + attention(q, k, v, path, causal=causal, scale=scale) @ p['Wo']
    h2 = norm(x1, 'ln2')
    x2 = x1 + F.relu(h2 @ p['W1'] + p['b1']) @ p['W2'] + p['b2']
    logits = norm(x2, 'lnf') @ p['W_out'] + p['b_out']
    loss = F.cross_entropy(logits, torch.tensor(targets, dtype=torch.long), reduction='mean')
    return logits, loss


def difference(actual, expected):
    a = torch.as_tensor(actual, dtype=torch.float64).detach()
    b = torch.as_tensor(expected, dtype=torch.float64).detach()
    if a.shape != b.shape or not torch.isfinite(a).all() or not torch.isfinite(b).all():
        raise ValueError('comparison needs equal finite shapes')
    return {'max_abs_error': (a-b).abs().max().item(),
            'passed': bool(torch.allclose(a, b, atol=ATOL, rtol=RTOL))}


def compare(path, p=None):
    p = params() if p is None else p
    manual_logits, cache = model.forward(p, IDS)
    manual_loss, dlogits = model.loss_and_dlogits(manual_logits, TARGETS)
    manual_grads = model.backward(p, cache, dlogits)
    tensor_p = tensors(p)
    logits, loss = forward(tensor_p, IDS, TARGETS, path)
    loss.backward()
    gradients = {name: difference(tensor_p[name].grad, manual_grads[name]) for name in p}
    return {'logits': difference(logits, manual_logits), 'loss': difference(loss, manual_loss),
            'loss_value': loss.item(), 'parameter_gradients': gradients,
            'compared_gradient_elements': sum(t.numel() for t in tensor_p.values()),
            'nonzero_manual_gradient_tensors': sum(any(v != 0 for v in flatten(manual_grads[n])) for n in p),
            'passed': all(x['passed'] for x in gradients.values()) and
                      difference(logits, manual_logits)['passed'] and difference(loss, manual_loss)['passed']}


def flatten(value):
    if isinstance(value, list):
        return [n for child in value for n in flatten(child)]
    return [value]


def failures():
    p = tensors(params())
    reference, _ = forward(p, IDS, TARGETS)
    rows = {}
    for name, kwargs in [('no_causal_mask', {'causal':False}), ('unscaled_attention', {'scale':1.0}),
                         ('wrong_layernorm_epsilon', {'eps':0.1})]:
        changed, _ = forward(p, IDS, TARGETS, **kwargs)
        rows[name] = difference(changed, reference)
    refused = []
    for ids, targets in [([], []), ([1, 2], [2]), ([1, 9], [2, 3]), ([True], [1])]:
        try:
            forward(p, ids, targets)
        except ValueError as error:
            refused.append({'ids':ids, 'targets':targets, 'error':str(error)})
        else:
            raise AssertionError('invalid input accepted')
    return {'mismatch_probes':rows, 'refused_inputs':refused}


def record():
    runs = {path: compare(path) for path in ('explicit', 'sdpa')}
    probes = failures()
    assert all(run['passed'] for run in runs.values())
    assert all(not row['passed'] for row in probes['mismatch_probes'].values())
    files = ['bridge.py', 'vendor/model.py', 'test_bridge.py', 'requirements.txt']
    return {'execution_mode':'CPU float64 forward and full parameter-backward comparison; no training update',
            'command':['python','bridge.py','--record'], 'exit_status':0,
            'config':CONFIG, 'ids':IDS, 'targets':TARGETS, 'dtype':'float64', 'device':'cpu',
            'dropout_p':0.0, 'is_causal':True, 'attention_scale':1/math.sqrt(CONFIG['d']),
            'layernorm_eps':model.EPS, 'loss_reduction':'mean', 'sdpa_backend':'MATH',
            'tolerance':{'atol':ATOL,'rtol':RTOL}, 'comparisons':runs, 'failures':probes,
            'environment':{'python':platform.python_version(),'torch':torch.__version__,'platform':platform.platform()},
            'sources':{name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in files}}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--record',action='store_true');args=parser.parse_args()
    torch.set_num_threads(1)
    result=record()
    print('CPU float64; one head; five positions; dropout=0; causal scale=1/sqrt(4)')
    for path, row in result['comparisons'].items():
        print(f"{path}: logits max error={row['logits']['max_abs_error']:.3e}; loss error={row['loss']['max_abs_error']:.3e}; "
              f"gradient max error={max(x['max_abs_error'] for x in row['parameter_gradients'].values()):.3e}; "
              f"{len(row['parameter_gradients'])} tensors/{row['compared_gradient_elements']} elements; passed={row['passed']}")
    for name, probe in result['failures']['mismatch_probes'].items():
        print(f"{name}: logits max error={probe['max_abs_error']:.3e}; within tolerance={probe['passed']}")
    print('Invalid inputs refused:',len(result['failures']['refused_inputs']))
    if args.record:
        (HERE/'result.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')

if __name__=='__main__':main()
