"""Task-3 audit (post-hoc, no model calls): for each PILOT deletion target, where does the deleted FACT
(subject name + deleted value in the same paragraph/artifact) survive? surviving raw vs derived artifacts."""
import json, re, sys
from pilot import targets as T          # sets eng-pin path
from pilot.common import DATA
from gen.probe_author import LedgerOnlyStream
L = sys.argv[1] if len(sys.argv) > 1 else 'PILOT'
out = []
for seed in (7240241, 7240242):
    sd = DATA / f'stream-{seed}'; st = LedgerOnlyStream(sd); keys = st.world['keys']; ents = st.world['entities']
    R = f'runs/{L}/stream-{seed}'
    tg = json.load(open(f'{R}/targets.json'))
    arts = {}
    for a in ('A3n-F', 'A3+DoT-F', 'A3n-C', 'A6-F', 'A6-C', 'A6m-F'):
        try: arts[a] = json.load(open(f'{R}/{a}/artifacts.json'))
        except FileNotFoundError: pass
    for t in tg['targets']:
        if not t.get('deleted_value') or t['cls'] in ('U',) or t['variant'] == 'AGG':
            continue
        nm = keys[t['key']]['subject_name'] if t.get('key') else ents[t['subject']]['name']
        rx = re.compile(t['deleted_any'][0])
        hit = lambda x: bool(x) and nm in x and bool(rx.search(x))
        row = dict(seed=seed, probe_id=t['probe_id'], cls=t['cls'], variant=t['variant'], name=nm, value=t['deleted_value'],
                   raw_surv=bool(t.get('supported_elsewhere')))
        for a, A in arts.items():
            row[a] = [f'{k}:{i}' for k, i, x in A if hit(x)]
        row['notes_only_F'] = bool(row.get('A3n-F')) and not row['raw_surv'] and not row.get('A3n-C')
        out.append(row)
json.dump(out, open(f'runs/{L}/residue_audit.json', 'w'), indent=1)
print('n targets', len(out), 'raw_surv', sum(r['raw_surv'] for r in out),
      'A3n-F fact-residue', sum(bool(r.get('A3n-F')) for r in out), 'DoT-F', sum(bool(r.get('A3+DoT-F')) for r in out),
      'A3n-C', sum(bool(r.get('A3n-C')) for r in out), 'A6-F', sum(bool(r.get('A6-F')) for r in out),
      'notes_only_F', sum(r['notes_only_F'] for r in out))
for r in out: print(r['probe_id'], r['seed'], r['name'], '=', r['value'], 'raw', r['raw_surv'], 'A3nF', r.get('A3n-F')[:3], 'A3nC', len(r.get('A3n-C') or []), 'A6F', len(r.get('A6-F') or []))
