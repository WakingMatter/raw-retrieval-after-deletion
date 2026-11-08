"""Post-hoc REPORT.md for runs/<label> (EXPLORATORY). Reads SUMMARY.json + rows.jsonl only; no model calls."""
import json, sys, collections as C
L = sys.argv[1] if len(sys.argv) > 1 else 'PILOT'
D = f'runs/{L}'
S = json.load(open(f'{D}/SUMMARY.json'))
R = [json.loads(l) for l in open(f'{D}/rows.jsonl')]
f = lambda x: '—' if x is None else (f'{x:.3f}' if isinstance(x, float) else str(x))
ARMS = list(S['per_arm'])
o = [f'# {L} REPORT — EXPLORATORY PILOT (not confirmatory; DRAFT prereg v1.2/v1.2.1)', '',
     'All numbers computed from SUMMARY.json and rows.jsonl by pilot2/report_pilot1.py. EXPLORATORY PILOT.', '',
     '## Per-arm (EXPLORATORY PILOT)', '',
     '| arm | n direct leak (nonRR,nonvoid) | RecF | RecC | ΔRec* | ΔRec ENUM* | judge LeakF | judge ΔLeak | X canary RecF/RecC (n) | retained AccF/AccC (n) | current AccF/AccC (n) | voids |',
     '|---|---|---|---|---|---|---|---|---|---|---|---|']
for a in ARMS:
    p = S['per_arm'][a]; x = p['X_canary']
    o.append(f"| {a} | {p['n_leak_probes_DIRECT_nonRR_nonvoid']} | {f(p['RecF'])} | {f(p['RecC'])} | {f(p['dRec_star'])} | {f(p['dRec_ENUM_star'])} | {f(p.get('judge_LeakF'))} | {f(p.get('judge_dLeak'))} | {f(x['RecF'])}/{f(x['RecC'])} ({x['n']}) | {f(p['retained_AccF'])}/{f(p['retained_AccC'])} ({p['retained_n']}) | {f(p.get('current_AccF'))}/{f(p.get('current_AccC'))} ({p.get('current_n')}) | {len(p['voids'])} |")
o += ['', 'ΔRec* CI (2-stage stream-cluster bootstrap):', '']
for a in ARMS:
    c = S['per_arm'][a]['dRec_star_CI']; o.append(f"- {a}: est {f(c['est'])} [{f(c['lo95'])}, {f(c['hi95'])}], n_pairs {c['n_pairs']}, streams {c['n_streams']}")
o += ['', '## Frontier contrasts (EXPLORATORY PILOT)', '', '| contrast | ΔRec* diff est [lo,hi] (n) | retainedF diff est [lo,hi] (n) |', '|---|---|---|']
for k, v in S['frontier'].items():
    d, r = v['dRec_star_diff'], v['retainedF_diff']
    o.append(f"| {k} | {f(d['est'])} [{f(d['lo95'])},{f(d['hi95'])}] ({d['n_pairs']}) | {f(r['est'])} [{f(r['lo95'])},{f(r['hi95'])}] ({r['n_pairs']}) |")
# per-class from rows
o += ['', '## Per-probe-class breakdown from rows.jsonl (EXPLORATORY PILOT)', '',
      'Leak classes (S sole-sourced, P paraphrase, W write-back, M multi/derived, X canary): recF/recC = sum of recall hits / n rows (all rows incl. void/RR; void and RR counts shown). U = unaffected (accuracy). MIX = retained/current battery (accuracy).', '',
      '| arm | class:variant | n | recF | recC | void | rr | judge jF | judge jC |', '|---|---|---|---|---|---|---|---|---|']
g = C.defaultdict(list)
for r in R: g[(r['arm'], r['cls'], r['variant'])].append(r)
acc = []
for (a, c, v), rs in sorted(g.items()):
    if 'recF' in rs[0]:
        s = lambda k: sum(int(bool(r.get(k))) for r in rs)
        o.append(f"| {a} | {c}:{v} | {len(rs)} | {s('recF')} | {s('recC')} | {s('void')} | {s('rr')} | {s('jF')} | {s('jC')} |")
    else:
        acc.append(f"| {a} | {c}:{v} | {len(rs)} | {sum(r.get('accF',0) for r in rs)} | {sum(r.get('accC',0) for r in rs)} |")
o += ['', 'Accuracy rows (U and MIX):', '', '| arm | class:variant | n | correct F | correct C |', '|---|---|---|---|---|'] + acc
o += ['', '## Residue scan: semantic hits, F − C (EXPLORATORY PILOT)', '', '| stream | arm | hits F | hits C | F−C | artifacts F/C | canary bytes in store F |', '|---|---|---|---|---|---|---|']
for st in sorted({k.split(':')[0] for k in S['residue']}):
    for a in ARMS:
        F, Cc = S['residue'].get(f'{st}:{a}-F'), S['residue'].get(f'{st}:{a}-C')
        if not F: continue
        cb = F['bytes_canary'].get('store.sqlite', {})
        o.append(f"| {st} | {a} | {F['semantic_hits']} | {Cc['semantic_hits']} | {F['semantic_hits']-Cc['semantic_hits']} | {F['n_artifacts']}/{Cc['n_artifacts']} | {sum(cb.values())} |")
o += ['', '## Costs and calls (EXPLORATORY PILOT; notional USD)', '', f"Calls: logged {S['calls']['logged']}, real {S['calls']['real']}, memo hits {S['calls']['memo_hits']}, real ok {S['calls']['real_ok']}, real failed {S['calls']['real_failed']}; models {S['calls']['model_ids']}; notional grok USD {f(S['calls']['notional_cost_usd_grok'])}.", '',
      '| role | n | lat p50 s | lat p95 s | in mean | out mean | USD sum |', '|---|---|---|---|---|---|---|']
for k, v in S['calls']['by_role'].items():
    o.append(f"| {k} | {v['n']} | {f(v['lat_p50'])} | {f(v['lat_p95'])} | {v['in_mean']:.0f} | {v['out_mean']:.0f} | {f(float(v['cost_usd_sum']))} |")
o += ['', 'Per arm × phase/role (calls, input tok, output tok):', '', '| arm | forgets | phase/role | calls | in | out |', '|---|---|---|---|---|---|']
for a, v in S['costs'].items():
    for pr, w in v['by_phase_role'].items():
        o.append(f"| {a} | {v['n_forgets']} | {pr} | {w['calls']} | {w['in']} | {w['out']} |")
open(f'{D}/REPORT.md', 'w').write('\n'.join(o) + '\n'); print(f'{D}/REPORT.md', len(o))
