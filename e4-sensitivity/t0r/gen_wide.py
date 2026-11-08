"""gen_wide: a model-free generator whose gold evidence does NOT fit the budget (T0-REDESIGN.md).

Four task families, 10 tasks each (40 per stream). Every gold answer needs many facts scattered over ~60 sessions:
  COUNT  "How many services run on <db> right now?"            services migrate between databases (update chains)
  SUM    "What is the combined headcount of the teams in <region> right now?"   per-team headcount update chains
  DELTA  "What is the <param> of <service> right now?"          base value + K relative adjustments ("raised by 50")
  ARGMAX "Which team logged the most incidents between <d1> and <d2>?"   M incident reports in the window
Distractors in every family: hypothetical / proposed / rejected statements that must NOT change the answer.
Size knob: `scale` multiplies the entity counts (COUNT/SUM), chain lengths (DELTA) and incident counts (ARGMAX).

Output (per seed, in out_dir): sessions/sNN.md (paragraphs separated by blank lines; one fact per paragraph),
MANIFEST.json (session -> t_start), tasks.json (question, gold, family, evidence refs: `minimal` = paragraphs that
are necessary to derive gold, `union` = every paragraph about the entities the task touches, distractors included).
No model calls. Pure function of (seed, scale).
"""
from __future__ import annotations
import json, random, datetime as dt
from pathlib import Path

N_SESS = 60
T0 = dt.datetime(2030, 1, 7, 9, 0)
DBS = ["Postgres", "MySQL", "Redis", "Spanner", "DynamoDB", "Cassandra", "MongoDB", "CockroachDB", "Bigtable", "ClickHouse"]
REGIONS = ["Lisbon", "Austin", "Pune", "Osaka", "Nairobi", "Oslo", "Bogota", "Seoul", "Dublin", "Perth"]
PARAMS = [("request timeout", "ms"), ("retry budget", "retries"), ("batch size", "rows"), ("cache TTL", "s"),
          ("connection pool size", "conns"), ("queue depth limit", "msgs"), ("rate limit", "rps"),
          ("worker count", "workers"), ("shard count", "shards"), ("log sample rate", "per 10k")]
PRE = ["ledger", "ranker", "vault", "atlas", "quill", "ember", "harbor", "pivot", "lumen", "cobalt", "delta", "falcon",
       "garnet", "helix", "ion", "jade", "kite", "lynx", "maple", "nova", "onyx", "prism", "quartz", "raven", "sable"]
MID = ["svc", "api", "bridge", "sync", "store", "gate", "relay", "index", "feed", "core"]
ADJ = ["Amber", "Blue", "Copper", "Dawn", "Echo", "Frost", "Gold", "Hollow", "Iron", "Jet", "Keen", "Lunar", "Moss",
       "North", "Opal", "Pine", "Quiet", "Red", "Silver", "Tidal"]
NOUN = ["Owls", "Foxes", "Herons", "Lynxes", "Otters", "Wolves", "Hawks", "Bears", "Cranes", "Seals"]
FILL = ["The comments are mostly about wording, nothing blocking.",
        "We agreed to revisit it once more people have read it.",
        "The discussion ran long, so the remaining items move to the next sync.",
        "Someone asked for more eyes on the docs before the end of the week.",
        "Nobody objected, and the notes were circulated afterwards.",
        "The dashboard numbers looked noisy but nobody flagged anything.",
        "This came up briefly between two other agenda items."]
NOISE = ["Reminder that the dependency upgrade still needs an owner for the follow-up actions.",
         "We spent a while on the onboarding checklist and agreed to revisit it later.",
         "The mentoring programme discussion ran long, so the remaining items move to the next sync.",
         "Quick note on the dashboard cleanup: the comments are mostly about wording, nothing blocking.",
         "The hiring loop got a cleaner version, circulated by the end of the day."]


def _zipf_sizes(rng, total, k, s=1.1):
    w = [1 / (i + 1) ** s for i in range(k)]; rng.shuffle(w)
    z = sum(w)
    return [max(3, round(total * x / z)) for x in w]


def generate(seed: int, out: Path, scale: float = 1.0):
    rng = random.Random(seed * 1009 + int(scale * 100))
    paras = []                       # (sess_idx, text, tags) ; tags: set of (task_id, role) role in {"min","union"}
    tasks = []
    names = rng.sample([f"{p}-{m}-v{v}" for p in PRE for m in MID for v in range(1, 5)], k=1000)
    teams = rng.sample([f"Team {a} {n}" for a in ADJ for n in NOUN] + [f"Team {a} {b} {n}" for a in ADJ[:10] for b in ADJ[10:] for n in NOUN], k=min(1200, int(600 * scale) + 50))
    t_q = T0 + dt.timedelta(days=N_SESS * 1.5 + 1)

    def add(sess, text, tags=()):
        paras.append((sess, text + " " + rng.choice(FILL), set(tags)))

    # ---- COUNT: services migrate between DBs; question per DB value (10 values, Zipf popularity) ----
    n_svc = int(260 * scale)
    svcs, names = names[:n_svc], names[n_svc:]
    pop = [1 / (i + 1) ** 0.9 for i in range(len(DBS))]
    hist = {}
    for s in svcs:
        k = rng.choice([1, 1, 2, 2, 3, 4])
        sess = sorted(rng.sample(range(N_SESS), k))
        dbs = []
        for _ in range(k):
            d = rng.choices(DBS, weights=pop)[0]
            while dbs and d == dbs[-1]:
                d = rng.choices(DBS, weights=pop)[0]
            dbs.append(d)
        hist[s] = list(zip(sess, dbs))
    for qi, v in enumerate(DBS):
        tid = f"{seed}:COUNT:{qi:02d}"
        touched = [s for s in svcs if any(d == v for _, d in hist[s])]
        gold = sum(1 for s in svcs if hist[s][-1][1] == v)
        tasks.append({"task_id": tid, "family": "COUNT", "cls": "AGG", "question":
                      f"How many services run on {v} right now?", "gold": str(gold), "n_entities": len(touched)})
    for s in svcs:
        for j, (si, d) in enumerate(hist[s]):
            last = j == len(hist[s]) - 1
            tags = set()
            for qi, v in enumerate(DBS):
                if any(dd == v for _, dd in hist[s]):
                    tid = f"{seed}:COUNT:{qi:02d}"
                    tags.add((tid, "min" if last else "union"))
            verb = "now runs on" if j else "runs on"
            add(si, rng.choice([f"Quick update: {s} {verb} {d} after the cutover.",
                                f"Migration note: {s} was moved to {d} this week.",
                                f"Infra sync: {s} {verb} {d} from today."]) if j else f"For the record, {s} runs on {d}.",
                tags)
        if rng.random() < 0.35:     # distractor
            d = rng.choice(DBS); si = rng.randrange(N_SESS)
            tags = {(f"{seed}:COUNT:{DBS.index(d):02d}", "union")}
            add(si, rng.choice([f"Hypothetically, if {s} moved to {d}, the on-call rota would change; nothing is planned.",
                                f"Rejected proposal: migrate {s} to {d}.",
                                f"Someone floated trying {d} for {s}, but the idea was dropped."]), tags)

    # ---- SUM: teams with region (static, stated once) and headcount update chains ----
    n_team = int(150 * scale)
    tm = teams[:n_team]
    reg_sizes = _zipf_sizes(rng, n_team, len(REGIONS), s=0.9)
    reg_of, idx = {}, 0
    pool = tm[:]; rng.shuffle(pool)
    for r, n in zip(REGIONS, reg_sizes):
        for t in pool[idx: idx + n]:
            reg_of[t] = r
        idx += n
    for t in pool[idx:]:
        reg_of[t] = rng.choice(REGIONS)
    hc = {}
    for t in reg_of:
        k = rng.choice([1, 2, 2, 3, 4])
        sess = sorted(rng.sample(range(N_SESS), k + 1))
        hc[t] = (sess[0], [(si, rng.randint(3, 19)) for si in sess[1:]])
    for qi, r in enumerate(REGIONS):
        tid = f"{seed}:SUM:{qi:02d}"
        mem = [t for t in reg_of if reg_of[t] == r]
        gold = sum(hc[t][1][-1][1] for t in mem)
        tasks.append({"task_id": tid, "family": "SUM", "cls": "AGG", "question":
                      f"What is the combined headcount of all teams based in {r} right now?", "gold": str(gold),
                      "n_entities": len(mem)})
    for t, r in reg_of.items():
        tid = f"{seed}:SUM:{REGIONS.index(r):02d}"
        add(hc[t][0], f"{t} is based in {r}.", {(tid, "min")})
        for j, (si, n) in enumerate(hc[t][1]):
            last = j == len(hc[t][1]) - 1
            add(si, rng.choice([f"Headcount check: {t} is now {n} people.", f"{t} now has {n} engineers after the reshuffle.",
                                f"Staffing update: {t} stands at {n}."]), {(tid, "min" if last else "union")})
        if rng.random() < 0.3:
            add(rng.randrange(N_SESS), f"{t} plans to grow to {rng.randint(10, 30)} people next year; not approved yet.",
                {(tid, "union")})

    # ---- DELTA: base + K relative adjustments ----
    Ks = [6, 9, 13, 18, 25, 35, 50, 70, 95, 130]
    rng.shuffle(Ks)
    dsvc, names = names[:10], names[10:]
    for qi, ((p, unit), s, K) in enumerate(zip(PARAMS, dsvc, Ks)):
        K = max(3, int(K * scale)); tid = f"{seed}:DELTA:{qi:02d}"
        sess = sorted(rng.choices(range(N_SESS), k=K + 1))
        base = rng.randint(20, 60) * 10; val = base
        add(sess[0], f"Initial setting: the {p} of {s} is {base} {unit}.", {(tid, "min")})
        for si in sess[1:]:
            step = rng.randint(1, 6) * 5
            if val - step < 10 or rng.random() < 0.55:
                val += step; txt = rng.choice([f"We raised the {p} of {s} by {step} {unit}.",
                                                 f"Bumped {s}'s {p} up by {step} {unit}."])
            else:
                val -= step; txt = rng.choice([f"We lowered the {p} of {s} by {step} {unit}.",
                                                 f"Cut {s}'s {p} by {step} {unit}."])
            add(si, txt, {(tid, "min")})
        for _ in range(max(1, K // 5)):
            add(rng.randrange(N_SESS), rng.choice([f"Proposal (rejected): raise the {p} of {s} by {rng.randint(1, 9) * 10} {unit}.",
                                                   f"Hypothetically, cutting {s}'s {p} by {rng.randint(1, 9) * 10} {unit} might help; not done."]),
                {(tid, "union")})
        tasks.append({"task_id": tid, "family": "DELTA", "cls": "AGG", "question":
                      f"What is the {p} of {s} right now? Answer with the number.", "gold": str(val), "unit": unit,
                      "n_entities": K + 1})

    # ---- ARGMAX: incidents in 10 disjoint 6-session windows ----
    Ms = [15, 22, 30, 42, 58, 80, 110, 150, 200, 260]
    rng.shuffle(Ms)
    for qi, M in enumerate(Ms):
        M = max(8, int(M * scale)); tid = f"{seed}:ARGMAX:{qi:02d}"
        win = list(range(qi * 6, qi * 6 + 6))
        cand = rng.sample(tm, 8)
        while True:
            w = [rng.random() + 0.2 for _ in cand]
            counts = [0] * 8
            for _ in range(M):
                counts[rng.choices(range(8), weights=w)[0]] += 1
            srt = sorted(counts, reverse=True)
            if srt[0] - srt[1] >= max(2, M // 20):
                break
        win_t = cand[counts.index(srt[0])]
        top2 = {cand[counts.index(srt[0])], cand[counts.index(srt[1])]}
        for c, n in zip(cand, counts):
            for _ in range(n):
                svc = rng.choice(svcs)
                add(rng.choice(win), rng.choice([f"Incident logged: {c} handled a {svc} outage.",
                                                 f"New incident ticket for {c}: {svc} latency spike.",
                                                 f"{c} logged an incident after {svc} paged overnight."]),
                    {(tid, "min" if c in top2 else "union")})
        for _ in range(M // 6):
            add(rng.choice(win), f"Near miss for {rng.choice(cand)}: an alert fired but no incident was logged.",
                {(tid, "union")})
        d1 = (T0 + dt.timedelta(days=win[0] * 1.5)).strftime("%b %d"); d2 = (T0 + dt.timedelta(days=win[-1] * 1.5 + 1)).strftime("%b %d")
        tasks.append({"task_id": tid, "family": "ARGMAX", "cls": "ARGMAX", "question":
                      f"Which team logged the most incidents between {d1} and {d2} 2030?", "gold": win_t,
                      "truth_any": [rf"\b{win_t}\b"], "wrong_any": [rf"\b{c}\b" for c in cand if c != win_t],
                      "n_entities": M, "counts": sorted(counts, reverse=True)})

    # ---- noise paragraphs so ~30% of paragraphs carry no task fact; write sessions ----
    for _ in range(int(len(paras) * 0.4)):
        paras.append((rng.randrange(N_SESS), rng.choice(NOISE), set()))
    by_s = {i: [] for i in range(N_SESS)}
    for p in paras:
        by_s[p[0]].append(p)
    (out / "sessions").mkdir(parents=True, exist_ok=True)
    refs, sessions = {}, []
    for i in range(N_SESS):
        rng.shuffle(by_s[i])
        t = T0 + dt.timedelta(days=i * 1.5)
        name = f"s{i:02d}"
        sessions.append({"session": name, "t_start": t.strftime("%Y-%m-%dT%H:%M:00Z")})
        body = [f"# Session {i:02d} - {t.strftime('%a %Y-%m-%d')}"] + [p[1] for p in by_s[i]]
        (out / "sessions" / f"{name}.md").write_text("\n\n".join(body) + "\n")
        for seg, p in enumerate(by_s[i], start=1):
            for tid, role in p[2]:
                refs.setdefault(tid, {"min": [], "union": []})[role].append([name, seg])
    for tk in tasks:
        r = refs.get(tk["task_id"], {"min": [], "union": []})
        tk["minimal_refs"] = r["min"]; tk["union_refs"] = r["min"] + r["union"]
        tk["t_query"] = t_q.strftime("%Y-%m-%dT%H:%M:00Z"); tk["seed"] = seed
    (out / "MANIFEST.json").write_text(json.dumps({"seed": seed, "scale": scale, "sessions": sessions}, indent=1))
    (out / "tasks.json").write_text(json.dumps({"seed": seed, "t_end": tk["t_query"], "tasks": tasks}, indent=1))
    return tasks
