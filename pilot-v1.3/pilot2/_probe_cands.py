import json, re, collections as C
from pilot import targets as T
from pilot.common import DATA
from gen import ledger
from gen.probe_author import LedgerOnlyStream, value_regex
for seed in (7240241, 7240242):
    d = DATA / f'stream-{seed}'; st = LedgerOnlyStream(d); v0 = st.views[0]; keys = st.world['keys']
    m = st.manifest; sess = [s['session'] for s in m['sessions']]
    txt = {s: (d / 'sessions' / f'{s}.md').read_text() for s in sess}
    print(seed, len(sess), 'rows', len(v0['rows']), v0['rows'][0])
    cnt = C.Counter()
    for r in v0['rows']:
        if r['kind'] == 'base' and r['value'] and len(r['evidence_sessions']) == 1:
            s = r['evidence_sessions'][0]
            rx = re.compile(value_regex(r['value']))
            others = sum(bool(rx.search(txt[o])) for o in sess if o != s)
            if others == 0: cnt[s] += 1
    print('sessions w/ >=2 unique-value sole facts:', sum(1 for s in cnt if cnt[s] >= 2), sorted(cnt.items())[:70])
