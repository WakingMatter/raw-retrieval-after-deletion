import json, re
EX = [(7240241, 's42:W:DIRECT:K018', 'cluster', 'c0082', 'Observability'), (7240241, 's04:S:DIRECT:K000', 'cluster', 'c0086', 'Dublin'),
      (7240242, 's26:P:DIRECT:K104', 'cluster', 'c0082', 'eu-central-1')]
o = []
for seed, pid, k, i, v in EX:
    R = f'runs/PILOT/stream-{seed}/A3n-F'
    ans = next(json.loads(l) for l in open(f'{R}/answers.jsonl') if json.loads(l)['probe_id'] == pid)
    txt = next(x for kk, ii, x in json.load(open(f'{R}/artifacts.json')) if kk == k and ii == i)
    m = re.search(re.escape(v), txt); s = txt[max(0, m.start() - 220): m.end() + 120]
    o.append(dict(seed=seed, probe=pid, q=ans['question'], A3n_answer=ans['answer'], residue_artifact=f'{k}:{i}', residue_excerpt=s))
json.dump(o, open('runs/PILOT/examples_task3.json', 'w'), indent=1)
for e in o: print(json.dumps(e, ensure_ascii=False)); print()
