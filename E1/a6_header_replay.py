"""Replay A6 read-path header decision (arms.py:156-173) for PILOT3 A6-F/A6-C final probes from saved state only:
db/store.sqlite (opened immutable/read-only), on-disk vector cache runs/_vec (np.load only; embedder is NOT loaded;
model files are only hashed to reproduce the cache namespace, embed.py:27-33), artifacts.json final summaries.
No model calls. Run from research/: python3 -B E1/a6_header_replay.py > E1/a6_header_replay.out"""
import json, hashlib, sqlite3, collections, os, re, math
from pathlib import Path
import numpy as np
P = Path(__file__).resolve().parents[1] / 'pilot-v1.3'; RUN = P / 'runs/PILOT3'; VEC = P / 'runs/_vec'
sha = lambda s: hashlib.sha256(s.encode() if isinstance(s, str) else s).hexdigest()
MD = Path(os.environ.get('EYWA_MODELS_DIR', Path.home() / '.eywa/models')) / 'gte-modernbert-base'
assets = []
for p in sorted(MD.rglob('*')):
    if p.is_file() and p.suffix in ('.onnx', '.json', '.txt', '.model'):
        with p.open('rb') as f: assets.append(f"{p.relative_to(MD)}:{hashlib.file_digest(f, 'sha256').hexdigest()}")
MID = 'gte-modernbert-base:' + sha('CLS|L2|512|v2|' + '\n'.join(assets))
def vec(text):
    k = sha(MID + '|' + text); p = VEC / k[:2] / f'{k}.npy'
    if not p.exists(): return None
    v = np.load(p).astype(np.float64); return v / np.linalg.norm(v)
SCALE = 2 ** 30
_PIECE = re.compile(r"[A-Za-z]+|\d|[^\sA-Za-z\d]")
def local_tokens(t):
    if not t: return 0
    n = sum(max(1, math.ceil(len(s) / 4)) if s[0].isalpha() else 1 for s in (m.group(0) for m in _PIECE.finditer(t)))
    return max(n, math.ceil(len(t.encode()) / 4))
item_cost = lambda t: local_tokens(t + '\n\n') * 1.15
CAP = 2000 / 5
kind_of = lambda pid: pid.split(':')[-1] if pid.startswith('mix:') else pid.split(':')[2]
print('embedder namespace', MID[:40] + '...')
for inst in ['A6-F', 'A6-C']:
    tot = collections.Counter(); bykind = collections.defaultdict(collections.Counter); missing = 0
    for sd in sorted(RUN.glob('stream-*')):
        d = sd / inst
        if not (d / 'DONE').exists() or not (sd.name <= 'stream-7240245'): continue
        db = sqlite3.connect(f'file:{d}/db/store.sqlite?mode=ro&immutable=1', uri=True)
        units = {i: json.loads(b) for k, i, b in db.execute("select kind,id,body from obj where kind in ('raw','wb')")}
        S = collections.defaultdict(lambda: 0); C = collections.Counter()
        for u, x in units.items():
            v = vec(x['text'])
            if v is None: missing += 1; continue
            q = np.round(v * SCALE).astype(np.int64)
            S[x['node']] = S[x['node']] + q; C[x['node']] += 1
        cent = {}
        for n in C:
            c = S[n].astype(np.float64) / C[n]; cent[n] = c / np.linalg.norm(c)
        summ = {int(r[1][1:]): item_cost(f'[summary:{r[1]}] {r[2]}') for r in json.load(open(d / 'artifacts.json')) if r[0] == 'summary'}
        for line in open(d / 'answers.jsonl'):
            a = json.loads(line); qv = vec(a['question'])
            if qv is None: tot['q_vec_missing'] += 1; continue
            top = sorted(cent, key=lambda n: (-float(cent[n] @ qv), n))[:3]
            served = [s for s in a['served'] if s.startswith('summary:')]
            # replay header loop
            used, hdr, reason = 0.0, [], None
            for n in top:
                if n not in summ: continue            # None (<2 inputs) or not cached
                if used + summ[n] > CAP: reason = reason or ('first_summary_over_cap' if not hdr else 'second_would_exceed'); break
                hdr.append(f'summary:n{n:02d}'); used += summ[n]
            agree = hdr == served; tot['agree'] += agree; tot['n'] += 1
            k = kind_of(a['probe_id'])
            if hdr: cat = 'served'
            elif reason: cat = 'blocked:first_existing_summary_over_cap'
            else: cat = 'no_summary_for_top3'
            # would anything in top3 have fit alone?
            fit_alone = any(n in summ and summ[n] <= CAP for n in top)
            if cat.startswith('blocked') and fit_alone: cat += '+later_fit_skipped_by_break'
            bykind[k][cat] += 1; tot[cat] += 1
    print(f'\n## {inst} (PILOT3 streams 7240241-45) units with missing cached vector: {missing}')
    print(f"replayed header == logged served summaries: {tot['agree']}/{tot['n']}")
    for c in sorted(k for k in tot if k not in ('agree', 'n')): print(f'  {c}: {tot[c]}')
    for k in sorted(bykind): print(f'  {k}: ' + ', '.join(f'{c}={v}' for c, v in sorted(bykind[k].items())))
