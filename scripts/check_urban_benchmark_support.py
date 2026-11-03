"""Check the most optimistic label support possible; never convert availability to a label."""

from collections import Counter
import json
from scripts import urban_change_benchmark as b
from scripts.audit_urban_reference import PIN

ASSIGNMENT = "f5914a2426b9f066152fcf6042445dc464035a5f34e8d8dbc8eb94986fbe119c"


def ceiling(sites, metadata):
    if len(sites) != len(metadata) or {s["id"] for s in sites} != set(metadata):
        raise ValueError("Reference audit does not account for every site")
    counts = {}
    for split in ("development", "evaluation"):
        assigned = [s for s in sites if s["split"] == split]
        paired = [s for s in assigned if set(metadata[s["id"]]) == {"2020", "2025"}]
        blocks = Counter(s["block"] for s in paired)
        counts[split] = dict(
            assigned=len(assigned),
            assigned_blocks=len({s["block"] for s in assigned}),
            candidates_2020=sum("2020" in metadata[s["id"]] for s in assigned),
            candidates_2025=sum("2025" in metadata[s["id"]] for s in assigned),
            paired=len(paired),
            paired_blocks=len(blocks),
            upper_bound_can_meet_minimum=len(paired) >= 30 and len(blocks) >= 20,
        )
    return counts


def main():
    a = b.OUT / "assignment.json"
    r = b.OUT / "reference_availability.json"
    meta = json.loads(r.read_text(encoding="utf8"))
    if (
        b.sha256_file(a) != ASSIGNMENT
        or meta["assignment_sha256"] != ASSIGNMENT
        or meta["protocol_sha256"] != PIN
        or b.sha256_file(b.OUT / "protocol.json") != PIN
    ):
        raise ValueError("Evidence pins do not agree")
    c = ceiling(json.loads(a.read_text())["sites"], meta["sites"])
    verdict = (
        "needs_blinded_reviews_not_yet_scorable"
        if all(v["upper_bound_can_meet_minimum"] for v in c.values())
        else "insufficient_reference_support_do_not_score"
    )
    b.write_new(
        b.OUT / "support_gate.json",
        dict(
            protocol_sha256=PIN,
            reference_sha256=b.sha256_file(r),
            counts=c,
            decision=verdict,
            confirmed_labels=0,
            caveat="Best case before visual review, land/water exclusions, reviewer agreement, class balance and common baseline coverage. Not a test result for either model.",
        ),
    )
    print(json.dumps(c), verdict)


if __name__ == "__main__":
    main()
