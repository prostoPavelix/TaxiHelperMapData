"""AUTO1 pure planning contracts. No network, signing, builds or publication side effects."""
import datetime as dt
import hashlib
import json
import re

HASH = re.compile(r"[a-f0-9]{64}")
CONTRACT = "GEO4_AUTO1_INPUTS_1"
ROLES = {"dated_osm", "additional_private_map_data", "historical_supplement", "compiler", "policy", "aoi", "sector", "capabilities"}

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")

def fingerprint(inputs):
    if inputs.get("contract") != CONTRACT or set(inputs.get("pins", {})) != ROLES:
        raise ValueError("INPUT_CLOSURE")
    for role, pin in inputs["pins"].items():
        if not isinstance(pin, dict) or not HASH.fullmatch(pin.get("sha256", "")):
            raise ValueError("UNKNOWN_INPUT:" + role)
    return hashlib.sha256(canonical(inputs)).hexdigest()

def plan(inputs, previous):
    try:
        current = fingerprint(inputs)
    except (ValueError, TypeError):
        return {"action": "RESOLVE_INPUTS", "reason": "UNKNOWN_IS_NOT_UNCHANGED"}
    unchanged = previous and previous.get("status") == "PASS" and previous.get("checked_fingerprint") == current
    return {"action": "SKIP_BUILD" if unchanged else "BUILD_ONCE", "fingerprint": current}

def semantic_contract(inputs):
    fingerprint(inputs) # complete exact input closure is mandatory
    roles={"compiler", "policy", "aoi", "sector", "capabilities"}
    return hashlib.sha256(canonical({k:inputs["pins"][k] for k in sorted(roles)})).hexdigest()

def semantic_equal(old, new):
    # Existing parity contract excludes only validated physical bindings inside table digests.
    # Source SHA is intentionally not compared across monthly snapshots. No new table exclusions.
    keys = {"tables", "policy_semantic_sha256", "algorithm_lf_sha256"}
    allowed = keys | {"contract", "source_sha256", "exclusion", "scope", "comparison"}
    for value in (old, new):
        if not isinstance(value,dict) or value.get("contract") != "GEO4_CROSS_PLATFORM_SEMANTICS_1" or set(value) - allowed or not keys <= value.keys():
            return False
        tables = value["tables"]
        if not isinstance(tables,dict) or set(tables) != {"base", "resolver"} or not all(isinstance(x,dict) and x for x in tables.values()):
            return False
        for component in tables.values():
            for digest in component.values():
                if not isinstance(digest,dict) or set(digest) != {"rows", "sha256"} or type(digest["rows"]) is not int or digest["rows"] < 0 or not isinstance(digest["sha256"],str) or not HASH.fullmatch(digest["sha256"]):
                    return False
    return all(old[k] == new[k] for k in keys)

def completed_snapshot(entries, today):
    """Select only a completed dated Ukraine PBF with bounded supplier transport metadata.
    Discovery adapter must supply listing+HEAD evidence; never fall back to latest.osm.pbf.
    MD5/ETag are signals only; fingerprint requires the subsequently acquired exact SHA256.
    """
    valid = []
    for e in entries:
        date = dt.date.fromisoformat(e["date"])
        expected = "https://download.geofabrik.de/europe/ukraine-" + date.strftime("%y%m%d") + ".osm.pbf"
        if date < today and e.get("completed") is True and e.get("url") == expected and e.get("http_status") == 200 and type(e.get("bytes")) is int and e["bytes"] > 0 and e.get("coverage") == "ukraine":
            valid.append(e)
    if not valid:
        raise ValueError("NO_COMPLETED_DATED_SNAPSHOT")
    return max(valid, key=lambda e: e["date"])

def publication_gate(expected_head, current_head, prior_sequence, next_sequence, readbacks, immutable):
    if not HASH.fullmatch(expected_head) or expected_head != current_head:
        raise ValueError("CHANNEL_CAS")
    if type(prior_sequence) is not int or type(next_sequence) is not int or prior_sequence < 1 or next_sequence != prior_sequence + 1:
        raise ValueError("SEQUENCE")
    if not readbacks or not all(x is True for x in readbacks.values()) or immutable is not True:
        raise ValueError("PUBLIC_READBACK_OR_IMMUTABILITY")
    return "READY_FOR_ATOMIC_REF_CAS"

def compatibility_summary(manifest, envelope_sha256, minimum_apk):
    from transport import validate
    validate(manifest)
    # Envelope authentication is performed by authenticated_summary below in the signing adapter.
    if not HASH.fullmatch(envelope_sha256) or type(minimum_apk) is not int or minimum_apk < 1:
        raise ValueError("SUMMARY_BINDING")
    return {"contract": "GEO4_COMPATIBILITY_1", "manifest_sha256": envelope_sha256,
            "minimum_apk": minimum_apk, "sector_sha256": manifest["identity"]["sector_sha256"],
            "capabilities": manifest["capabilities"]}

def authenticated_summary(envelope, public_keys, minimum_apk):
    from transport import authenticate
    manifest=authenticate(envelope,public_keys)
    return compatibility_summary(manifest,hashlib.sha256(envelope).hexdigest(),minimum_apk)


def status_record(now, outcome, checked_fingerprint, last_success, last_published, error_category, run_url):
    if outcome not in {"UNCHANGED_INPUTS", "UNCHANGED_CONTENT", "PUBLISHED", "FAILED"}:
        raise ValueError("OUTCOME")
    dt.datetime.fromisoformat(now.replace("Z", "+00:00"))
    return dict(contract="GEO4_CLOUD_STATUS_1", checked_at=now, outcome=outcome,
                checked_fingerprint=checked_fingerprint, last_successful_check=last_success,
                last_published=last_published, error_category=error_category, run_url=run_url)


def resume_gate(receipt, actual, expected_channel, current_channel):
    """Exact previously verified bundle only; artifact name/run ID alone is insufficient."""
    keys = {"source_sha256", "compiler_sha256", "manifest_sha256", "payload_sha256"}
    if receipt.get("status") != "VERIFIED" or not keys <= receipt.keys() or any(receipt[k] != actual.get(k) for k in keys):
        raise ValueError("RESUME_IDENTITY")
    if expected_channel != current_channel or not HASH.fullmatch(expected_channel):
        raise ValueError("RESUME_CHANNEL_CHANGED")
    return "PUBLISH_ONLY_NO_REBUILD"


def cycle(inputs, previous, old_passport=None, new_passport=None):
    result = plan(inputs, previous)
    if result["action"] == "BUILD_ONCE" and new_passport is not None:
        same_contract = previous and previous.get("semantic_contract") == semantic_contract(inputs)
        result["action"] = "SKIP_RELEASE" if same_contract and old_passport is not None and semantic_equal(old_passport,new_passport) else "VERIFY_RELEASE"
    return result


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs",type=Path,required=True)
    parser.add_argument("--previous",type=Path)
    parser.add_argument("--old-passport",type=Path)
    parser.add_argument("--new-passport",type=Path)
    args=parser.parse_args()
    def read(path):return json.loads(path.read_text(encoding="utf-8")) if path else None
    print(canonical(cycle(read(args.inputs),read(args.previous),read(args.old_passport),read(args.new_passport))).decode("utf-8"))
