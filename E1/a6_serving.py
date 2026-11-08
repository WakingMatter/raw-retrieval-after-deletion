"""E1 / A6 summary-serving audit. READ-ONLY over saved runs; no model calls, no pilot imports, no network.
Run from research/: python3 -B E1/a6_serving.py > E1/a6_serving.out
local_tokens/item_cost copied verbatim from pilot-v1.3/eng-pin/arms/adapters.py:56-72 and
pilot-v1.3/pilot/common.py:56-57 (SAFETY=1.15, SEP='\\n\\n' at eng-pin/arms/common.py:35-36)."""
import json, glob, math, re, ast, collections, statistics
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]  # release root
_PIECE = re.compile(r"[A-Za-z]+|\d|[^\sA-Za-z\d]")
def local_tokens(text):
    if not text: return 0
    n = 0
    for m in _PIECE.finditer(text):
        s = m.group(0); n += max(1, math.ceil(len(s) / 4)) if s[0].isalpha() else 1
    return max(n, math.ceil(len(text.encode('utf-8')) / 4))
def item_cost(text): return local_tokens(text + '\n\n') * 1.15
B = 2000; CAP = B / 5   # RUN-META B=2000; header cap arms.py:171
RUNS = [('P2', 'pilot-v1.2/runs/PILOT2', 'pilot-v1.2/runs/_calls/memo'),
        ('P3', 'pilot-v1.3/runs/PILOT3-GROK-FULL', 'pilot-v1.3/runs/_calls/memo')]
def kind_of(pid):
    return pid.split(':')[-1] if pid.startswith('mix:') else pid.split(':')[2]
def cls_of(pid):
    return 'MIX' if pid.startswith('mix:') else pid.split(':')[1]

print('# A6 summary-serving audit (saved traces only)')
for label, run, memo in RUNS:
    print(f'\n## {label} {run}')
    # 1. served-summary counts by instance x probe kind (terminal probes)
    for inst in ['A6-F', 'A6-C', 'A6-eager-F', 'A6m-F', 'A6m-C']:
        cnt = collections.defaultdict(collections.Counter); nsum = collections.Counter()
        for p in sorted((ROOT / run).glob(f'stream-*/{inst}/answers.jsonl')):
            for raw in p.open():
                r = json.loads(raw); k = kind_of(r['probe_id'])
                s = [x for x in r.get('served', []) if x.startswith('summary:')]
                cnt[k]['n'] += 1; cnt[k]['summary'] += bool(s); nsum[len(s)] += 1
        tot = sum(cnt.values(), collections.Counter())
        print(f'{inst} terminal probes n={tot["n"]} with_summary={tot["summary"]} '
              f'summaries_per_probe={dict(sorted(nsum.items()))}')
        print('   by kind: ' + '; '.join(f'{k} {c["summary"]}/{c["n"]}' for k, c in sorted(cnt.items())))
    # 2. warm reads (pre-forget) summary exposure
    w = collections.Counter()
    for p in sorted((ROOT / run).glob('stream-*/A6-F/log.json')):
        for x in json.load(open(p))['warm']:
            w['n'] += 1; w['summary'] += any(s.startswith('summary:') for s in x.get('served') or [])
    print(f'A6-F warm reads n={w["n"]} with_summary={w["summary"]}')
    # 3. every A6 (code-edge) synth output in the call log: header item cost vs cap B/5
    costs, words, seen = [], [], set()
    for line in open(ROOT / run / 'calls.jsonl'):
        d = json.loads(line)
        if d.get('role') != 'synth' or str(d.get('ok')) != 'True': continue
        ctx = d.get('ctx'); ctx = ctx if isinstance(ctx, dict) else ast.literal_eval(ctx or '{}')
        if ctx.get('arm') not in ('A6', 'A6-eager'): continue
        if d['key'] in seen: continue
        seen.add(d['key'])
        mp = ROOT / memo / f"{d['key']}.json"
        if not mp.exists(): continue
        t = json.load(open(mp)).get('text', '').strip()
        n = ctx.get('node', 0)
        costs.append(item_cost(f'[summary:n{n:02d}] {t}')); words.append(len(t.split()))
    fits = sum(c <= CAP for c in costs)
    print(f'distinct ok A6/A6-eager synth outputs with memo text: {len(costs)}; header item_cost <= {CAP:.0f} (fits alone): {fits} '
          f'({fits/len(costs):.3f}); cost median {statistics.median(costs):.0f} p10 {sorted(costs)[len(costs)//10]:.0f} '
          f'p90 {sorted(costs)[9*len(costs)//10]:.0f}; words median {statistics.median(words):.0f}, >120 words: {sum(x>120 for x in words)}')
    # 4. served summaries: confirm each one fits and look up its text cost where recoverable
    # 5. A6-F vs A6-eager-F terminal answer-prompt identity (same probe, same seed)
    keys = collections.defaultdict(dict)
    for line in open(ROOT / run / 'calls.jsonl'):
        d = json.loads(line)
        if d.get('role') != 'answer' or str(d.get('ok')) != 'True': continue
        ctx = d.get('ctx'); ctx = ctx if isinstance(ctx, dict) else ast.literal_eval(ctx or '{}')
        if ctx.get('phase') != 'probe' or ctx.get('world') != 'F': continue
        keys[(ctx.get('seed'), ctx.get('probe'))][ctx.get('arm')] = d['key']
    for a, b in [('A6', 'A6-eager'), ('A6', 'A6m'), ('A6', 'RS')]:
        pairs = [v for v in keys.values() if a in v and b in v]
        same = sum(v[a] == v[b] for v in pairs)
        print(f'F terminal answer prompts byte-identical (memo key equal) {a} vs {b}: {same}/{len(pairs)}')
