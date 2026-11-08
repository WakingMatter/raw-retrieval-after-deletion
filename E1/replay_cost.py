"""E1 zero-call cost-frontier replay (lazy A6 / eager A6-eager / delete-on-touch A3+DoT, with A3n, A6m, RS context).
READ-ONLY over saved per-instance stats.json / log.json / residue_bytes.json of DONE instances. No model calls.
Run from research/: python3 -B E1/replay_cost.py > E1/replay_cost.out
'logical' = every call the arm issued (memo hits included; this is what a cold run would pay).
'real' = memo:false. Latency is reported only over real ok calls (memo-hit latency is a replay of the original)."""
import json, collections, statistics
from pathlib import Path
R = Path(__file__).resolve().parents[1]  # release root
RUNS = [('PILOT2', R / 'pilot-v1.2/runs/PILOT2'), ('PILOT3-GROK-FULL', R / 'pilot-v1.3/runs/PILOT3-GROK-FULL'),
        ('PILOT3-ASTRA', R / 'pilot-v1.3/runs/PILOT3-ASTRA')]
def p95(xs): xs = sorted(xs); return xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))] if xs else None
def fmt(x, d=0): return '-' if x is None else (f'{x:,.{d}f}')
for label, run in RUNS:
    insts = collections.defaultdict(list)
    for d in sorted(run.glob('stream-*/*')):
        if d.is_dir() and (d / 'DONE').exists() and (d / 'stats.json').exists(): insts[d.name].append(d)
    print(f'\n## {label}  ({run.relative_to(R)})')
    print('| instance | streams | logical calls | real calls | synth calls | forget-phase calls | tokens in+out (logical) | per stream | answers | tokens/answer | real-call latency mean / p95 s | probe-answer calls |')
    print('|---|---|---|---|---|---|---|---|---|---|---|---|')
    fg = {}
    for inst in sorted(insts):
        C = []; ans = 0
        for d in insts[inst]:
            C += json.load(open(d / 'stats.json'))['calls']
            ans += sum(1 for _ in open(d / 'answers.jsonl'))
        tok = sum((c.get('in') or 0) + (c.get('out') or 0) for c in C)
        real = [c for c in C if not c.get('memo')]
        lat = [c['latency'] for c in real if c.get('ok') and c.get('latency') is not None]
        syn = sum(c['role'] == 'synth' for c in C)
        fgc = [c for c in C if str(c.get('phase', '')).startswith('forget')]
        pa = sum(c['role'] == 'answer' and c.get('phase') == 'probe' for c in C)
        n = len(insts[inst])
        print(f'| {inst} | {n} | {len(C):,} | {len(real):,} | {syn} | {len(fgc)} ({sum((c.get("in") or 0)+(c.get("out") or 0) for c in fgc):,} tok) | {tok:,} | {tok/n:,.0f} | {ans} | {tok/ans:,.0f} | '
              f'{fmt(statistics.mean(lat) if lat else None,1)} / {fmt(p95(lat),1)} (n {len(lat)}) | {pa} |')
        # forget-time work from log.json
        F = collections.Counter(); walls = []
        rec = collections.Counter()
        for d in insts[inst]:
            lg = json.load(open(d / 'log.json'))
            for f in lg.get('forget') or []:
                walls.append(f.get('wall_s') or 0)
                for k in ('units_deleted',): F[k] += f.get(k) or 0
                for k in ('writebacks_deleted', 'caches_invalidated', 'eager_recomputed', 'notes_deleted', 'notes_redacted',
                          'clusters_rebuilt', 'clusters_dropped', 'cluster_fail', 'redact_failed'):
                    if k in f: F[k] += len(f[k])
                if 'kc1a_subtraction_equals_rebuild' in f: F['kc1a_true'] += bool(f['kc1a_subtraction_equals_rebuild']); F['kc1a_n'] += 1
                F['forgets'] += 1
            st = json.load(open(d / 'stats.json'))
            for r in st.get('recompute') or []: rec[str(r.get('phase')).split('_')[0]] += 1
            res = json.load(open(d / 'residue_bytes.json'))
            F['canary_bytes'] += sum(v for m in res.values() for v in (m.values() if isinstance(m, dict) else []))
        fg[inst] = (F, walls, rec)
    print('\nforget-time work and deletion bookkeeping (sum over streams; wall_s = time inside arm.forget):')
    print('| instance | forgets | wall_s total | wall_s median | units deleted | caches invalidated | eager recomputed | notes deleted | notes redacted | clusters rebuilt / dropped / failed | kc1a ok | recomputes by phase | canary bytes in store files |')
    print('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    for inst, (F, walls, rec) in sorted(fg.items()):
        if not F['forgets'] and not rec and not F['canary_bytes']:
            kc = '-'
        print(f"| {inst} | {F['forgets']} | {sum(walls):.2f} | {statistics.median(walls) if walls else 0:.3f} | {F['units_deleted']} | {F['caches_invalidated']} | {F['eager_recomputed']} | "
              f"{F['notes_deleted']} | {F['notes_redacted']} | {F['clusters_rebuilt']} / {F['clusters_dropped']} / {F['cluster_fail']} | "
              f"{str(F['kc1a_true'])+'/'+str(F['kc1a_n']) if F['kc1a_n'] else '-'} | {dict(rec) or '-'} | {F['canary_bytes']} |")
    # lazy vs eager: fate of eager recomputes
    eg = [k for k in insts if k.startswith('A6-eager')]
    for inst in eg:
        wasted = total = ee = 0
        for d in insts[inst]:
            recs = json.load(open(d / 'stats.json'))['recompute']
            for i, r in enumerate(recs):
                if r.get('phase') != 'forget_eager': continue
                total += 1
                later = [x for x in recs[i + 1:] if x['node'] == r['node']]
                if later: wasted += 1          # replaced by a later recompute of the same node -> not the probe-time cache
                if later and later[0].get('phase') == 'forget_eager': ee += 1
        print(f'\n{inst}: eager recomputes {total}; of these, the same node was recomputed again later (eager result superseded '
              f'i.e. eager result did not survive to probe time): {wasted} (next recompute was itself another eager one: {ee})')
