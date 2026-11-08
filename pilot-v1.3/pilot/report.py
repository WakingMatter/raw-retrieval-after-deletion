"""REPORT.md writer.  python3 -m pilot.report --label SMOKE|PILOT"""
import argparse, json
from .common import ROOT

def f(x, p=3):
    return "—" if x is None else (f"{x:.{p}f}" if isinstance(x, float) else str(x))

def ci(b):
    return "—" if not b else f"{b['est']:+.3f} [{b['lo95']:+.3f}, {b['hi95']:+.3f}] (n={b['n_pairs']}, streams={b['n_streams']})"

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--label", required=True); a = ap.parse_args()
    rd = ROOT / "runs" / a.label
    S = json.loads((rd / "SUMMARY.json").read_text()); M = json.loads((rd / "RUN-META.json").read_text())
    tag = "SMOKE" if M.get("smoke") else "EXPLORATORY"
    L = [f"# currency v1.2.1 §P pilot — {a.label} — **{tag}**", "",
         f"_{tag}: not confirmatory; no hypothesis in v1.2.1 is tested by this run. 2 streams = 2 bootstrap clusters (degenerate CI)._", "",
         f"- started {M['started']} · finished {M.get('finished')} · B={M['B']} · embedder {M['embedder']} · anchors sha {M['anchors_sha'][:16]}",
         f"- template overhead (empty prompt) in-tokens: {M['template_in_tokens']} · model reported: {M['template_model_reported']}",
         f"- errors: {len(M.get('errors') or [])} · C-world aliases: {M.get('alias_C')}", "",
         "## Frontier (headline): leak ΔRec*, retained recall, cost", "",
         "| arm | n leak probes (DIRECT, non-RR, non-void) | Rec_F | Rec_C | ΔRec* | ΔRec ENUM | retained Acc_F | retained Acc_C | retained-recall loss (C−F) | J1 ΔLeak | X canary Rec_F / RS | voids | RR |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    rsx = S["per_arm"]["RS"]["X_canary"]["RecF"]
    for arm, x in S["per_arm"].items():
        L.append(f"| {arm} | {x['n_leak_probes_DIRECT_nonRR_nonvoid']} | {f(x['RecF'])} | {f(x['RecC'])} | {f(x['dRec_star'])} | {f(x['dRec_ENUM_star'])} | "
                 f"{f(x['retained_AccF'])} | {f(x['retained_AccC'])} | {f(x['retained_recall_loss'])} | {f(x['judge_dLeak'])} | "
                 f"{f(x['X_canary']['RecF'])} / {f(rsx)} | {len(x['voids'])} | {len(x['rr'])} |")
    L += ["", "### Per-arm CIs and current-state accuracy (MIX `current` probes)", "",
          "| arm | ΔRec* [95% CI] | retained-recall loss [95% CI] | n current | current Acc_F | current Acc_C |", "|---|---|---|---|---|---|"]
    for arm, x in S["per_arm"].items():
        L.append(f"| {arm} | {ci(x.get('dRec_star_CI'))} | {ci(x.get('retained_loss_CI'))} | {x.get('current_n')} | {f(x.get('current_AccF'))} | {f(x.get('current_AccC'))} |")
    L += ["", "### Paired differences (2-stage stream-cluster bootstrap, 10k)", "", "| comparison | ΔRec* diff (A − B) | retained Acc_F diff (A − B) |", "|---|---|---|"]
    for k, v in S["frontier"].items():
        L.append(f"| {k} | {ci(v['dRec_star_diff'])} | {ci(v['retainedF_diff'])} |")
    L += ["", "## Cost per arm (F world; logical tokens incl. memo hits; latency from real calls only)", ""]
    for arm, c in S["costs"].items():
        L.append(f"**{arm}** (forgets: {c['n_forgets']})"); L.append("")
        L.append("| phase/role | calls | in tok | out tok | lat p50 s | lat p95 s | n lat |"); L.append("|---|---|---|---|---|---|---|")
        for k, v in c["by_phase_role"].items():
            L.append(f"| {k} | {v['calls']} | {v['in']} | {v['out']} | {f(v['lat_p50'],1)} | {f(v['lat_p95'],1)} | {v['lat_n']} |")
        L.append("")
        L.append("Actual attempts owned by this arm in this run (includes retries; excludes memo hits): "
                 + json.dumps(c.get("actual_attempts_this_run"))); L.append("")
    C = S["calls"]
    L += ["## Calls", "", f"- logged {C['logged']} · real {C['real']} (ok {C['real_ok']}, failed attempts {C['real_failed']}) · memo hits {C['memo_hits']}",
          f"- model ids (requested->reported): {', '.join(C['model_ids'])}",
          f"- notional Grok cost reported by CLI (subscription; not billed per call): ${C['notional_cost_usd_grok']:.2f}", "",
          "| role | n real | p50 s | p95 s | mean in tok | mean out tok | notional $ |", "|---|---|---|---|---|---|---|"]
    for r, v in C["by_role"].items():
        L.append(f"| {r} | {v['n']} | {f(v['lat_p50'],1)} | {f(v['lat_p95'],1)} | {f(v['in_mean'],0)} | {f(v['out_mean'],0)} | {v['cost_usd_sum']:.3f} |")
    L += ["", "## Checks", "", "### Cache poisoning (cached non-answers / serves)", ""]
    for arm, x in S["per_arm"].items():
        kinds = {}
        for p in x["poison_log"]:
            kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
        L.append(f"- {arm}: {kinds or 'none'} · answers with failed calls: {x['failed_calls_in_answers']} · KC1(a) subtraction==rebuild at forgets: {x['kc1a'] or '—'}")
    L += ["", "### Residue (end-of-stream)", "", "| instance | deleted-value regex hits in derived artifacts (NOT semantic residue) | canary bytes in DB files | artifacts |", "|---|---|---|---|"]
    for k, v in S["residue"].items():
        b = sum(sum(d.values()) for d in v["bytes_canary"].values())
        L.append(f"| {k} | {v['value_regex_hits']} | {b} | {v['n_artifacts']} |")
    L += ["", "### Voids and RR (excluded from ΔRec*)", ""]
    for arm, x in S["per_arm"].items():
        L.append(f"- {arm}: voids {x['voids'] or '—'}; RR {x['rr'] or '—'}")
    L += ["", "## Disclosures", "",
          "- Correctness/leak = regex over gold/deleted values (no Eng grader module at 863fb79); J1 (Codex) leak flag reported alongside.",
          "- Call memo shared across arms/worlds/labels: identical prompts get identical outputs (dedupes shared prefixes; replay ≠ counterfactual).",
          "- Grok CLI adds ~21.6k fixed input tokens per call (system scaffolding); tokens above include it; template overhead measured once.",
          "- No temperature / max_tokens control in the Grok CLI; reasoning effort 'low'; system prompt overridden (see PILOT-FREEZE).",
          "- Voids and residue_semantic use the deleted-value regex, not J1.", ""]
    (rd / "REPORT.md").write_text("\n".join(L)); print(rd / "REPORT.md")

if __name__ == "__main__":
    main()
