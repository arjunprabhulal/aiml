"""Execute actual local objective updates and record their result and refusals."""
import argparse
import hashlib
import html
import json
import platform
from pathlib import Path
import torch
import updates as u


def record(stage):
    result=u.run_dpo() if stage=='dpo' else u.run_grpo()
    p=u.policy();reference=u.frozen(p)
    try:
        if stage=='dpo':u.dpo_loss(p,reference,[{'prompt':[1],'chosen':[2],'rejected':[2]}])
        else:u.advantages([0,float('nan')])
    except ValueError as error:result['refusal']=str(error)
    else:raise AssertionError('expected invalid objective input refusal')
    result['command']=['python','run.py',stage,'--record'];result['exit_status']=0
    result['environment']={'python':platform.python_version(),'torch':torch.__version__,'platform':platform.platform()}
    result['sources']={name:hashlib.sha256((u.HERE/name).read_bytes()).hexdigest() for name in ['updates.py','decoder.py','vendor/model.py','run.py','test_updates.py']}
    return result


def report(stage,result):
    summary={key:value for key,value in result.items() if key not in ['trace','loss_history','environment','sources']}
    if stage=='grpo':summary['first_group_samples']=result['trace'][0]['completions'];summary['first_group_rewards']=result['trace'][0]['rewards']
    rows=''.join('<tr><th>'+html.escape(key.replace('_',' '))+'</th><td><pre>'+html.escape(json.dumps(value,indent=2))+'</pre></td></tr>' for key,value in summary.items())
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Actual '+stage.upper()+' objective experiment</title><style>body{margin:0;padding:24px;color:#192136;background:white;font:18px system-ui}h1{font-size:28px}p{line-height:1.5;color:#596375}table{width:100%;border-collapse:collapse;table-layout:fixed}th,td{border:1px solid #dfe4ed;padding:14px;vertical-align:top;text-align:left}th{width:27%}pre{font:16px/1.5 monospace;margin:0;white-space:pre-wrap;overflow-wrap:anywhere}@media(max-width:600px){body{padding:14px}th,td{display:block;width:auto}th{background:#f5f7fb}}</style><h1>'+stage.upper()+': actual CPU objective experiment</h1><p>Tiny synthetic-vocabulary autoregressive model. Fresh local parameter updates; no pretrained-model alignment, GPU or semantic-quality claim. This summary links to the full raw trace in the lesson.</p><table>'+rows+'</table></html>'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['dpo','grpo']);parser.add_argument('--record',action='store_true');args=parser.parse_args();torch.set_num_threads(1)
    result=record(args.stage);text=json.dumps(result,indent=2,allow_nan=False)+'\n';print(text,end='')
    if args.record:
        (u.HERE/(args.stage+'-result.json')).write_text(text)
        (u.HERE/(args.stage+'-output.txt')).write_text(text)
        (u.HERE/(args.stage+'-report.html')).write_text(report(args.stage,result))
