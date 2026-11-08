"""v1.3 F08: explicitly adopt the frozen v1.2 anchors for v1.3 (no refit, no model calls).
Checks (1) the .npy bytes equal the v1.2 freeze's anchors sha256_npy, (2) the encoder's legacy v1.2 identity equals the
v1.2 frozen embedder id; then stamps the sidecar with the v1.3 cache identity so load_or_fit accepts it.
    PYTHONPATH=. python3 -m pilot.adopt_anchors"""
import hashlib, json
from .common import ROOT
from .embed import Embedder
from .anchors import cache_identity


def main(npy=ROOT / "runs" / "anchors-7240240.npy", freeze=ROOT / "PILOT-FREEZE.v1.2.json"):
    fz = json.loads(freeze.read_text())
    if hashlib.sha256(npy.read_bytes()).hexdigest() != fz["anchors"]["sha256_npy"]:
        raise ValueError("anchor bytes differ from the v1.2 freeze")
    emb = Embedder(ROOT / "runs" / "_vec")
    if emb.legacy_model_id != fz["models"]["embedder"]:
        raise ValueError(f"encoder differs from v1.2 ({emb.legacy_model_id} != {fz['models']['embedder']})")
    side = npy.with_suffix(".json"); info = json.loads(side.read_text())
    info["cache_identity"] = cache_identity(emb)
    info["adopted_from"] = {"freeze": freeze.name, "sha256_npy": fz["anchors"]["sha256_npy"], "legacy_embedder": emb.legacy_model_id}
    side.write_text(json.dumps(info)); print(json.dumps(info["cache_identity"]))


if __name__ == "__main__":
    main()
