"""Provider-free contract integrity checks, not a consumer implementation/evaluation."""
import json
from pathlib import Path

from contract import Packet
from build_packet import ACTS, HERE, ROOT, build, sha


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pointer(value, path):
    for part in path.strip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def validate(packet):
    Packet.model_validate(packet)
    require(packet["production_effect"] == "none", "production must remain inactive")
    require(set(packet["holds"]) == set(build()["holds"]), "authorization holds drift")
    require([x["characteristic_id"] for x in packet["field_contracts"]] == [f"C{i:02}" for i in range(1,21)], "C01-C20 inventory drift")
    require(set(packet["downstream_holds"]) == {f"D{i:02}" for i in range(1,7)}, "D01-D06 inventory drift")
    source_paths = {s["path"] for s in packet["sources"]}
    for source in packet["sources"]:
        require(sha((ROOT/source["path"]).read_bytes()) == source["sha256"], "frozen source hash mismatch: "+source["path"])
    estimands = {e["estimand_id"] for e in packet["estimands"]}
    require(len(estimands) == len(packet["estimands"]), "duplicate estimand")
    for f in packet["field_contracts"]:
        require(set(f["estimand_ids"]) <= estimands, "unknown field-contract estimand")
    require(len({c["case_id"] for c in packet["cases"]}) == len(packet["cases"]), "duplicate case")
    for c in packet["cases"]:
        evidence={e["evidence_id"]:e for e in c["evidence"]}
        require(len(evidence) == len(c["evidence"]), "duplicate evidence ID in case")
        expected=c["expected"]
        require(expected["retained_evidence"] == list(evidence), "evidence lost from visible provenance")
        require(expected["unique_utterance_groups"] == len({e["independence"]["utterance_group"] for e in evidence.values()}), "duplicate/overlap inflation")
        for e in evidence.values():
            s=e["source"]; p=e["provenance"]
            require(sha(s["target_text"].encode()) == s["target_sha256"], "target hash mismatch")
            require(s["date_basis"] != "unknown" or s["sermon_date"] is None, "unknown sermon date was invented")
            for sp in e["spans"]:
                text=s[{"target":"target_text","leading_context":"leading_context","trailing_context":"trailing_context"}[sp["role"]]]
                require(sp["start"] < sp["end"] <= len(text) and text[sp["start"]:sp["end"]] == sp["text"], "span is not grounded")
            payload=e["payload"]
            if payload["kind"] == "relation":
                for key in ["left_span","right_span"]:
                    require(0 <= payload[key] < len(e["spans"]), "invalid relation endpoint")
                    require(e["spans"][payload[key]]["role"] == "target", "context cannot supply relation endpoint")
            if payload["kind"] == "address":
                require(set(payload["acts"]) == set(ACTS), "independent address acts missing")
                require(e["spans"][0]["role"] == "target", "context cannot supply address act")
            if p["origin"] == "frozen_provider_output":
                for key in ["input_path","result_path"]:
                    require(p[key] in source_paths, "unfrozen provenance source")
                inp=pointer(json.loads((ROOT/p["input_path"]).read_text()),p["input_pointer"])
                result=pointer(json.loads((ROOT/p["result_path"]).read_text()),p["result_pointer"])
                require(all(s[k] == inp[k] for k in ["target_text","leading_context","trailing_context"]), "frozen text changed")
                raw=pointer(json.loads((ROOT/p["result_path"]).read_text()),p["raw_output_ref"])
                require(raw == result["raw_answers"], "raw distribution reference drift")
                require(bool(pointer(json.loads((ROOT/p["result_path"]).read_text()),p["answer_provenance_ref"])), "per-answer reuse provenance lost")
                d=result["decisions"]
                if payload["kind"] == "address":
                    require(payload["acts"] == {a:d[a] for a in ACTS} and
                            payload["circumstance_relevance"] == d["circumstance_relevance"] and
                            payload["recipient_binding"] == d["recipient_circumstance_binding"] and
                            all(payload[k] == d[k] for k in ["adoption","voice","addressee"]), "frozen G3 decision drift")
                else:
                    require(payload["decision"] == d[payload["relation"]] and
                            all(payload[k] == d[k] for k in ["adoption","left_voice","right_voice"]), "frozen G2 decision drift")
                require(e["eligibility"]["membership"] == "unknown" and e["eligibility"]["content"] == "unknown", "pilot cannot certify ownership or eligibility")
        if c["origin"] != "synthetic_design":
            require(expected["independently_eligible_sermons"] is None, "pilot locators cannot become independent eligible sermons")
        else:
            groups={e["independence"]["sermon_group"] for e in evidence.values() if e["eligibility"]["membership"] == "reviewed_member" and e["eligibility"]["content"] == "eligible" and e["provenance"]["compatibility"] == "compatible"}
            require(expected["independently_eligible_sermons"] == len(groups), "eligible-sermon count drift")
        for f in expected["fields"]:
            require(f["characteristic_id"] in {x["characteristic_id"] for x in packet["field_contracts"]}, "unknown characteristic")
            require(f["estimand_id"] in estimands, "unknown expected estimand")
            require(set(f["supporting"] + f["counter"] + f["unresolved"]) <= set(evidence), "dangling field evidence link")
            require(f["claim_level"] == ("local_example" if f["supporting"] or (f["counter"] and f["availability"] == "negative_in_unit") else "unavailable"), "unsupported claim level")
            require(bool(f["visible_wording"]) and bool(f["uncertainty_wording"]), "missing visible limitations")
            if f["availability"] != "local_examples":
                require(not f["supporting"], "withheld field cannot become supported")
            if f["availability"] == "negative_in_unit":
                require(bool(f["counter"]), "local negative requires assessed evidence")
                require(all(evidence[eid]["observation_state"] == "negative_in_unit" and evidence[eid]["coverage"]["local_boundary"] == "sufficient" for eid in f["counter"]), "local negative cannot use unknown or incomplete evidence")
            for eid in f["supporting"]:
                e=evidence[eid]
                require(e["eligibility"]["membership"] != "conflict" and e["eligibility"]["content"] != "excluded", "ineligible evidence credited")
                require(e["provenance"]["compatibility"] == "compatible", "incompatible evidence credited")
                require(e["coverage"]["local_boundary"] == "sufficient", "incomplete local evidence credited")
            text=f["visible_wording"].lower()
            require(not any(phrase.lower() in text for phrase in expected["forbidden_wording"]), "forbidden visible claim")
    return packet


def check():
    packet=json.loads((HERE/"packet-v1.json").read_text())
    validate(packet)
    require(packet == build(), "packet differs from fixed authored specification")
    require(json.loads((HERE/"schema-v1.json").read_text()) == Packet.model_json_schema(), "schema drift")
    return packet


if __name__ == "__main__":
    p=check()
    print(f"PASS: {len(p['field_contracts'])} field contracts, {len(p['estimands'])} estimands, {len(p['cases'])} authored acceptance cases; frozen source/decision integrity verified.")
    print("This is packet integrity only. No consumer, semantic accuracy, recall, projection or population validation has passed.")
