#!/usr/bin/env python3
"""eval_gate.py — AND-gate theo docs/eval-goal.md §5.

Usage:
    # Chỉ dev set
    python scripts/eval_gate.py --dev reports/gate/dev.json

    # Dev + blind (drift check)
    python scripts/eval_gate.py --dev reports/gate/dev.json --blind reports/gate/blind.json

    # Dev + chạy INV/DIR live
    python scripts/eval_gate.py --dev reports/gate/dev.json \\
        --api-url http://localhost:9199/api/v1/search/product

    # Tạo results JSON trước từ benchmark.py:
    python scripts/benchmark.py --no-confirm --output-dir reports/gate

Exit code: 0 = DONE (all gates passed), 1 = FAIL (in ra metric/capability nào fail).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Floors — eval-goal.md §5.1 (frozen, không sửa để pass)
# ---------------------------------------------------------------------------

FLOORS: dict[str, float] = {
    "decision_type_accuracy":       0.85,
    "constraint_compliance":        0.90,
    "mrr_at_3":                     0.80,
    # joint_slot_exact_match: 0.75 — NOT_MEASURED (cần extraction log)
    "abstention_precision":         0.95,
    "abstention_recall":            0.85,
    "hallucination_rate":           0.00,   # upper bound
    "false_abstention_rate":        0.10,   # upper bound
    "behavioral_invariance_rate":   0.95,
    "brier_score":                  0.20,   # upper bound
}

# Trong FLOORS, metric này là "càng thấp càng tốt" (upper bound)
UPPER_BOUND = {"hallucination_rate", "false_abstention_rate", "brier_score"}

CAP_TYPE_FLOOR = 0.80
CAP_CONSTRAINT_FLOOR = 0.85
DRIFT_BOUND = 0.05  # max drop dev → blind (absolute pp)

SENTINEL = "NOT_MEASURED"   # metric không thể đo do thiếu dữ liệu


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    text = text.lower()
    # 'đ' (U+0111) is a Latin d-stroke, not decomposed by NFD — must replace explicitly
    text = text.replace("đ", "d").replace("Đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def _parse_md_rows(text: str) -> list[dict[str, str]]:
    """Đọc tất cả bảng markdown trong text, trả row dicts. Header detection auto."""
    rows: list[dict[str, str]] = []
    headers: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            headers = []
            continue
        if re.fullmatch(r"[\|\-\s:]+", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue

        if not headers:
            headers = [c.lower() for c in cells]
            continue

        if len(cells) < len(headers):
            cells += [""] * (len(headers) - len(cells))
        rows.append(dict(zip(headers, cells)))

    return rows


@dataclass
class MFTMeta:
    """Metadata bổ sung từ test_cases.md không có trong results JSON."""
    cap: str            # C-ALIAS … C-NL
    in_catalog: bool
    top1_id: str | None     # None nếu TBD
    gold_slots: dict        # brand, uom, size_value, size_hint, must_not, category


@dataclass
class INVPair:
    id: str
    cap: str
    query_a: str
    query_b: str
    invariant: str  # same_type | same_top1 | same_type_and_top1


@dataclass
class DIRPair:
    id: str
    cap: str
    query_a: str
    query_b: str
    rule: str  # raw string, eg "type B phải là no_result"


def _parse_gold_slots(raw: str) -> dict:
    """Parse compact gold slot string: 'b:coca_cola; u:lon; n:light,zero'"""
    if not raw or raw.strip() in ("-", ""):
        return {}
    slots: dict = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        k, _, v = part.partition(":")
        k, v = k.strip(), v.strip()
        key_map = {"b": "brand", "u": "uom", "s": "size_value", "h": "size_hint",
                   "n": "must_not", "c": "category", "a": "attributes"}
        full_key = key_map.get(k, k)
        if full_key == "must_not":
            slots[full_key] = [x.strip() for x in v.split(",") if x.strip()]
        else:
            slots[full_key] = v
    return slots


def load_test_case_meta(path: Path) -> tuple[dict[str, MFTMeta], list[INVPair], list[DIRPair]]:
    """Parse test_cases.md → {id: MFTMeta}, [INVPair], [DIRPair]."""
    text = path.read_text(encoding="utf-8")

    mft_meta: dict[str, MFTMeta] = {}
    inv_pairs: list[INVPair] = []
    dir_pairs: list[DIRPair] = []

    current_section = "mft"
    current_headers: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()

        # Track section
        if line.startswith("## "):
            lw = line.lower()
            if "inv" in lw:
                current_section = "inv"
            elif "dir" in lw:
                current_section = "dir"
            elif "mft" in lw or "test cases" in lw or "g1" in lw or "g2" in lw:
                current_section = "mft"
            current_headers = []
            continue

        if not line.startswith("|"):
            continue
        if re.fullmatch(r"[\|\-\s:]+", line):
            continue

        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue

        # Header row
        if not current_headers:
            current_headers = [c.lower() for c in cells]
            continue

        if len(cells) < len(current_headers):
            cells += [""] * (len(current_headers) - len(cells))
        row = dict(zip(current_headers, cells))

        case_id = row.get("id", "").strip()
        if not case_id or case_id.startswith("-"):
            continue

        if current_section == "inv":
            inv_pairs.append(INVPair(
                id=case_id,
                cap=row.get("cap", ""),
                query_a=row.get("query a", ""),
                query_b=row.get("query b", ""),
                invariant=row.get("invariant", "same_type"),
            ))
        elif current_section == "dir":
            dir_pairs.append(DIRPair(
                id=case_id,
                cap=row.get("cap", ""),
                query_a=row.get("query a", ""),
                query_b=row.get("query b", ""),
                rule=row.get("directional rule", row.get("directional_rule", "")),
            ))
        else:
            # MFT row
            cap = row.get("cap", "").strip()
            if not cap:
                continue
            in_catalog_raw = row.get("in-cat", "true").lower()
            in_catalog = in_catalog_raw not in ("false", "0", "no")
            top1_raw = row.get("top1", "TBD").strip()
            top1_id = None if top1_raw in ("TBD", "", "–", "-") else top1_raw
            gold_raw = row.get("gold", "-").strip()
            mft_meta[case_id] = MFTMeta(
                cap=cap,
                in_catalog=in_catalog,
                top1_id=top1_id,
                gold_slots=_parse_gold_slots(gold_raw),
            )

    return mft_meta, inv_pairs, dir_pairs


def load_benchmark_results(path: Path) -> list[dict]:
    """Load results JSON từ benchmark.py output."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("results", [])


def load_blind_jsonl(path: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """Load blind_set.jsonl → (mft_cases, inv_pairs, dir_pairs) raw dicts."""
    mft, inv, dirs = [], [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        obj = json.loads(line)
        kind = obj.get("kind", "MFT").upper()
        if kind == "INV":
            inv.append(obj)
        elif kind == "DIR":
            dirs.append(obj)
        else:
            mft.append(obj)
    return mft, inv, dirs


# ---------------------------------------------------------------------------
# API caller (for INV/DIR live runs)
# ---------------------------------------------------------------------------

def call_api(api_url: str, query: str) -> tuple[dict, int]:
    payload = json.dumps({"query": query, "user_id": "eval_gate"}).encode("utf-8")
    req = urllib.request.Request(api_url, data=payload,
                                  headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.status


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def _contains_all(names: list[str], terms: list[str]) -> bool:
    norms = [_normalize(n) for n in names]
    return all(any(_normalize(t) in n for n in norms) for t in terms)


def _contains_any(names: list[str], terms: list[str]) -> bool:
    norms = [_normalize(n) for n in names]
    return any(any(_normalize(t) in n for n in norms) for t in terms)


def compute_mft_metrics(
    results: list[dict],
    meta: dict[str, MFTMeta],
) -> dict:
    """Compute all MFT-based metrics. Returns dict metric→value|SENTINEL."""

    # ------------------------------------------------------------------
    # Join results with metadata
    # ------------------------------------------------------------------
    joined = []
    for r in results:
        cid = r.get("id", "")
        m = meta.get(cid)
        if m is None:
            # Case ID không có trong metadata (vd case cũ không có cap) — skip
            continue
        joined.append((r, m))

    if not joined:
        return {k: SENTINEL for k in FLOORS}

    total = len(joined)

    # ------------------------------------------------------------------
    # A. Decision Type Accuracy
    # ------------------------------------------------------------------
    correct_type = 0
    for r, m in joined:
        expected = r.get("expected_type", "")
        actual = r.get("actual_type", "error")
        # Strict: no_result expected → must be no_result
        # For in_catalog=true + expected≠no_result: actual=no_result is WRONG (false abstention)
        if expected == "no_result":
            if actual == "no_result":
                correct_type += 1
        elif expected in ("exact", "exact_match", "clarify", "needs_clarification"):
            # Normalize: benchmark.py emits "exact_match"/"needs_clarification";
            # test_cases.md raw values are "exact"/"clarify" — treat both as equivalent.
            expected_norm = "exact_match" if expected in ("exact", "exact_match") else "needs_clarification"
            if m.in_catalog:
                # in-catalog: actual must match expected type (no_result = wrong)
                if actual == expected_norm:
                    correct_type += 1
            else:
                # out-of-catalog + expected=clarify/exact: shouldn't happen in well-formed set
                # treat as pass if not hallucinating (no items)
                if actual == "no_result" or r.get("item_count", 0) == 0:
                    correct_type += 1

    decision_type_accuracy = correct_type / total

    # ------------------------------------------------------------------
    # B. Constraint Compliance
    # ------------------------------------------------------------------
    # Cases where system returned items — check +terms / !terms
    cases_with_items = [(r, m) for r, m in joined
                        if r.get("item_count", 0) > 0 or len(r.get("top_items", [])) > 0]
    if cases_with_items:
        compliant = 0
        for r, _ in cases_with_items:
            items = r.get("top_items", [])
            required = r.get("required_keywords", [])
            excluded = r.get("excluded_keywords", [])
            req_ok = (not required) or _contains_all(items, required)
            exc_ok = (not excluded) or not _contains_any(items, excluded)
            if req_ok and exc_ok:
                compliant += 1
        constraint_compliance = compliant / len(cases_with_items)
    else:
        constraint_compliance = SENTINEL  # no items → cannot measure

    # ------------------------------------------------------------------
    # C. MRR@3
    # ------------------------------------------------------------------
    mrr_cases = [(r, m) for r, m in joined
                 if r.get("expected_type", "") != "no_result" and m.in_catalog]
    if mrr_cases:
        reciprocal_ranks = []
        for r, _ in mrr_cases:
            items = r.get("top_items", [])[:3]
            required = r.get("required_keywords", [])
            if not required:
                # No required terms → assume rank-1 is correct if items exist
                rr = 1.0 if items else 0.0
            else:
                rr = 0.0
                for rank, name in enumerate(items, start=1):
                    if all(_normalize(t) in _normalize(name) for t in required):
                        rr = 1.0 / rank
                        break
            reciprocal_ranks.append(rr)
        mrr_at_3 = sum(reciprocal_ranks) / len(reciprocal_ranks)
    else:
        mrr_at_3 = SENTINEL

    # ------------------------------------------------------------------
    # D. Abstention metrics (no_result as its own task)
    # ------------------------------------------------------------------
    # in_catalog=false → "should abstain" ground truth
    should_abstain = [(r, m) for r, m in joined if not m.in_catalog]
    did_abstain = [(r, m) for r, m in joined if r.get("actual_type") == "no_result"]
    true_abstain = [(r, m) for r, m in joined
                    if not m.in_catalog and r.get("actual_type") == "no_result"]
    hallucinated = [(r, m) for r, m in joined
                    if not m.in_catalog and r.get("actual_type") != "no_result"]
    false_abstained = [(r, m) for r, m in joined
                       if m.in_catalog and r.get("expected_type") != "no_result"
                       and r.get("actual_type") == "no_result"]
    in_catalog_non_abst = [(r, m) for r, m in joined
                           if m.in_catalog and r.get("expected_type") != "no_result"]

    abstention_precision = len(true_abstain) / len(did_abstain) if did_abstain else SENTINEL
    abstention_recall = len(true_abstain) / len(should_abstain) if should_abstain else SENTINEL
    hallucination_rate = len(hallucinated) / len(should_abstain) if should_abstain else SENTINEL
    false_abstention_rate = (len(false_abstained) / len(in_catalog_non_abst)
                             if in_catalog_non_abst else SENTINEL)

    # ------------------------------------------------------------------
    # F. Brier score
    # ------------------------------------------------------------------
    brier_cases = [(r, m) for r, m in joined
                   if r.get("expected_type") != "no_result" and m.in_catalog and r.get("confidence", 0) > 0]
    if brier_cases:
        brier_total = 0.0
        for r, _ in brier_cases:
            conf = r.get("confidence", 0.0)
            correct = 1.0 if r.get("pass", False) else 0.0
            brier_total += (conf - correct) ** 2
        brier_score = brier_total / len(brier_cases)
    else:
        brier_score = SENTINEL

    # ------------------------------------------------------------------
    # Per-capability breakdown
    # ------------------------------------------------------------------
    caps = sorted({m.cap for _, m in joined})
    cap_breakdown: dict[str, dict] = {}
    for cap in caps:
        cap_cases = [(r, m) for r, m in joined if m.cap == cap]
        if not cap_cases:
            continue
        cap_correct_type = 0
        cap_compliant = 0
        cap_with_items = 0
        for r, cm in cap_cases:
            expected = r.get("expected_type", "")
            actual = r.get("actual_type", "error")
            if expected == "no_result":
                if actual == "no_result":
                    cap_correct_type += 1
            elif cm.in_catalog:
                if actual == expected:
                    cap_correct_type += 1
            items = r.get("top_items", [])
            if items:
                cap_with_items += 1
                required = r.get("required_keywords", [])
                excluded = r.get("excluded_keywords", [])
                if ((not required) or _contains_all(items, required)) and \
                   ((not excluded) or not _contains_any(items, excluded)):
                    cap_compliant += 1
        cap_breakdown[cap] = {
            "total": len(cap_cases),
            "type_accuracy": round(cap_correct_type / len(cap_cases), 3),
            "constraint_compliance": (round(cap_compliant / cap_with_items, 3)
                                      if cap_with_items else SENTINEL),
        }

    return {
        "decision_type_accuracy": round(decision_type_accuracy, 3),
        "constraint_compliance": (round(constraint_compliance, 3)
                                  if constraint_compliance != SENTINEL else SENTINEL),
        "mrr_at_3": (round(mrr_at_3, 3) if mrr_at_3 != SENTINEL else SENTINEL),
        "joint_slot_exact_match": SENTINEL,  # cần extraction log
        "abstention_precision": (round(abstention_precision, 3)
                                 if abstention_precision != SENTINEL else SENTINEL),
        "abstention_recall": (round(abstention_recall, 3)
                              if abstention_recall != SENTINEL else SENTINEL),
        "hallucination_rate": (round(hallucination_rate, 3)
                               if hallucination_rate != SENTINEL else SENTINEL),
        "false_abstention_rate": (round(false_abstention_rate, 3)
                                  if false_abstention_rate != SENTINEL else SENTINEL),
        "behavioral_invariance_rate": SENTINEL,  # filled by INV check
        "brier_score": (round(brier_score, 3) if brier_score != SENTINEL else SENTINEL),
        "_cap_breakdown": cap_breakdown,
        "_case_count": total,
    }


def compute_inv_metrics(pairs: list[INVPair], api_url: str) -> dict:
    """Chạy INV pairs qua API, trả behavioral_invariance_rate."""
    if not pairs:
        return {"behavioral_invariance_rate": SENTINEL}

    passed = 0
    failures: list[str] = []

    for pair in pairs:
        try:
            resp_a, _ = call_api(api_url, pair.query_a)
            time.sleep(0.3)
            resp_b, _ = call_api(api_url, pair.query_b)
        except Exception as exc:
            failures.append(f"{pair.id}: API error — {exc}")
            continue

        type_a = resp_a.get("type", "error")
        type_b = resp_b.get("type", "error")
        items_a = resp_a.get("items", [])
        items_b = resp_b.get("items", [])
        top1_a = items_a[0].get("id", "") if items_a else ""
        top1_b = items_b[0].get("id", "") if items_b else ""

        inv = pair.invariant.lower()
        ok = True
        if "type" in inv and type_a != type_b:
            ok = False
            failures.append(f"{pair.id}: type mismatch ({type_a!r} ≠ {type_b!r})")
        if "top1" in inv and top1_a != top1_b:
            ok = False
            failures.append(f"{pair.id}: top1 mismatch ({top1_a!r} ≠ {top1_b!r})")

        if ok:
            passed += 1

    rate = passed / len(pairs) if pairs else 0.0
    return {
        "behavioral_invariance_rate": round(rate, 3),
        "_inv_failures": failures,
        "_inv_total": len(pairs),
        "_inv_passed": passed,
    }


def compute_blind_metrics(
    blind_cases: list[dict],
) -> dict:
    """Compute metrics từ blind JSONL cases (sau khi đã chạy API và thêm actual_type, top_items)."""
    # Chuyển blind format → format tương thích compute_mft_metrics
    results = []
    meta: dict[str, MFTMeta] = {}

    for obj in blind_cases:
        cid = obj.get("id", "")
        results.append({
            "id": cid,
            "group": obj.get("cap", ""),
            "query": obj.get("query", ""),
            "expected_type": obj.get("expected_type", "").replace("exact", "exact"),
            "actual_type": obj.get("actual_type", ""),
            "pass": obj.get("pass", False),
            "confidence": obj.get("confidence", 0.0),
            "item_count": len(obj.get("top_items", [])),
            "top_items": obj.get("top_items", []),
            "required_keywords": obj.get("required_terms", []),
            "excluded_keywords": obj.get("excluded_terms", []),
            "fail_reasons": obj.get("fail_reasons", []),
        })
        meta[cid] = MFTMeta(
            cap=obj.get("cap", ""),
            in_catalog=obj.get("in_catalog", True),
            top1_id=None,
            gold_slots={},
        )

    return compute_mft_metrics(results, meta)


# ---------------------------------------------------------------------------
# Gate checker
# ---------------------------------------------------------------------------

METRIC_LABEL = {
    "decision_type_accuracy": "Decision Type Accuracy",
    "constraint_compliance":  "Constraint Compliance",
    "mrr_at_3":               "MRR@3",
    "joint_slot_exact_match": "Joint Slot Exact-Match",
    "abstention_precision":   "Abstention Precision",
    "abstention_recall":      "Abstention Recall",
    "hallucination_rate":     "Hallucination Rate     (↓)",
    "false_abstention_rate":  "False Abstention Rate  (↓)",
    "behavioral_invariance_rate": "Behavioral Invariance",
    "brier_score":            "Brier Score            (↓)",
}


def check_gates(
    dev: dict,
    blind: dict | None = None,
) -> tuple[bool, list[str]]:
    """Áp AND-gate. Returns (all_passed, list_of_failures)."""
    failures: list[str] = []

    # 5.1 Overall floors on dev
    for key, floor in FLOORS.items():
        val = dev.get(key, SENTINEL)
        if val == SENTINEL:
            continue  # NOT_MEASURED → không fail
        upper = key in UPPER_BOUND
        passed = (val <= floor) if upper else (val >= floor)
        if not passed:
            cmp = f"≤{floor}" if upper else f"≥{floor}"
            failures.append(
                f"[DEV OVERALL] {METRIC_LABEL.get(key, key)}: {val:.3f}  (floor {cmp})"
            )

    # 5.2 Per-capability floors
    cap_bd = dev.get("_cap_breakdown", {})
    for cap, stats in cap_bd.items():
        ta = stats.get("type_accuracy", SENTINEL)
        cc = stats.get("constraint_compliance", SENTINEL)
        if ta != SENTINEL and ta < CAP_TYPE_FLOOR:
            failures.append(
                f"[DEV CAP {cap}] Type Accuracy: {ta:.3f}  (floor ≥{CAP_TYPE_FLOOR})"
            )
        if cc != SENTINEL and cc < CAP_CONSTRAINT_FLOOR:
            failures.append(
                f"[DEV CAP {cap}] Constraint Compliance: {cc:.3f}  (floor ≥{CAP_CONSTRAINT_FLOOR})"
            )

    # 5.3 Drift dev → blind
    if blind is not None:
        for key in FLOORS:
            dv = dev.get(key, SENTINEL)
            bv = blind.get(key, SENTINEL)
            if dv == SENTINEL or bv == SENTINEL:
                continue
            upper = key in UPPER_BOUND
            if upper:
                drift = bv - dv   # blind worse = higher for upper-bound metrics
            else:
                drift = dv - bv   # blind worse = lower for lower-bound metrics
            if drift > DRIFT_BOUND:
                failures.append(
                    f"[DRIFT DEV→BLIND] {METRIC_LABEL.get(key, key)}: "
                    f"dev={dv:.3f} blind={bv:.3f}  drift={drift:.3f} > {DRIFT_BOUND}"
                )

    return len(failures) == 0, failures


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------

def _fmt(val) -> str:
    if val == SENTINEL:
        return "NOT_MEASURED"
    return f"{val:.3f}"


def print_report(
    dev: dict,
    blind: dict | None,
    failures: list[str],
    all_passed: bool,
) -> None:
    sep = "─" * 62
    print(f"\n{sep}")
    print("  EVAL GATE — Order-AI  (docs/eval-goal.md §5)")
    print(sep)

    print(f"\n{'Metric':<40} {'Dev':>8}", end="")
    if blind:
        print(f"  {'Blind':>8}", end="")
    print(f"  {'Floor':>8}  {'Status'}")
    print("─" * (62 + (10 if blind else 0)))

    for key, floor in FLOORS.items():
        dv = dev.get(key, SENTINEL)
        upper = key in UPPER_BOUND
        cmp = f"≤{floor}" if upper else f"≥{floor}"
        if dv == SENTINEL:
            status = "○ SKIP"
        else:
            passed = (dv <= floor) if upper else (dv >= floor)
            status = "✓ PASS" if passed else "✗ FAIL"
        label = METRIC_LABEL.get(key, key)
        line = f"  {label:<38} {_fmt(dv):>8}"
        if blind:
            bv = blind.get(key, SENTINEL)
            line += f"  {_fmt(bv):>8}"
        line += f"  {cmp:>8}  {status}"
        print(line)

    print(f"\n{'Per-Capability (Dev)':─<62}")
    cap_bd = dev.get("_cap_breakdown", {})
    if cap_bd:
        print(f"  {'Cap':<10} {'TypeAcc':>8} {'CstCompl':>10}  Floors: ≥{CAP_TYPE_FLOOR}/≥{CAP_CONSTRAINT_FLOOR}")
        for cap, stats in sorted(cap_bd.items()):
            ta = stats.get("type_accuracy", SENTINEL)
            cc = stats.get("constraint_compliance", SENTINEL)
            ta_ok = ta == SENTINEL or ta >= CAP_TYPE_FLOOR
            cc_ok = cc == SENTINEL or cc >= CAP_CONSTRAINT_FLOOR
            flag = "" if (ta_ok and cc_ok) else "  ← FAIL"
            print(f"  {cap:<10} {_fmt(ta):>8} {_fmt(cc):>10}{flag}")
    else:
        print("  (không có metadata cap — chạy eval_gate với test_cases.md đúng path)")

    if dev.get("_inv_total"):
        print(f"\nINV pairs: {dev['_inv_passed']}/{dev['_inv_total']} passed")
        for fail in dev.get("_inv_failures", []):
            print(f"  ✗ {fail}")

    print(f"\n{sep}")
    print(f"  Cases evaluated: {dev.get('_case_count', '?')}")
    if blind:
        print(f"  Blind cases:     {blind.get('_case_count', '?')}")

    if all_passed:
        print("\n  ✓  ALL GATES PASSED — system is DONE")
    else:
        print(f"\n  ✗  {len(failures)} gate(s) FAILED:")
        for f in failures:
            print(f"    • {f}")
    print(f"{sep}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Gate-check theo eval-goal.md §5. Exit 0=DONE, 1=FAIL."
    )
    p.add_argument(
        "--dev", required=True, metavar="PATH",
        help="Path đến results JSON từ benchmark.py (dev set)",
    )
    p.add_argument(
        "--blind", metavar="PATH", default=None,
        help="Path đến results JSON từ blind set run (optional, drift check)",
    )
    p.add_argument(
        "--blind-jsonl", metavar="PATH", default=None,
        help="Path đến blind_set.jsonl đã được annotate actual_type (alternative to --blind)",
    )
    p.add_argument(
        "--api-url", metavar="URL", default=None,
        help="API URL để chạy INV pairs live (bỏ qua nếu không muốn đo behavioral invariance)",
    )
    p.add_argument(
        "--test-cases", metavar="PATH",
        default=str(Path(__file__).parent / "test_cases.md"),
        help="Path đến test_cases.md (để lấy metadata cap/in_catalog)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # Load metadata from test_cases.md
    tc_path = Path(args.test_cases)
    if not tc_path.exists():
        print(f"[ERROR] test_cases.md not found: {tc_path}", file=sys.stderr)
        return 1
    mft_meta, inv_pairs, dir_pairs = load_test_case_meta(tc_path)

    # Load dev results
    dev_path = Path(args.dev)
    if not dev_path.exists():
        print(f"[ERROR] Dev results not found: {dev_path}", file=sys.stderr)
        return 1
    dev_results = load_benchmark_results(dev_path)

    # Compute dev metrics
    dev_metrics = compute_mft_metrics(dev_results, mft_meta)

    # INV/DIR via live API
    if args.api_url and inv_pairs:
        print(f"[INV] Running {len(inv_pairs)} invariance pairs against API...")
        inv_metrics = compute_inv_metrics(inv_pairs, args.api_url)
        dev_metrics.update(inv_metrics)

    # Blind set
    blind_metrics: dict | None = None
    if args.blind:
        bp = Path(args.blind)
        if bp.exists():
            blind_results = load_benchmark_results(bp)
            blind_metrics = compute_mft_metrics(blind_results, mft_meta)
        else:
            print(f"[WARN] Blind results not found: {bp}", file=sys.stderr)
    elif args.blind_jsonl:
        bjp = Path(args.blind_jsonl)
        if bjp.exists():
            blind_mft, _, _ = load_blind_jsonl(bjp)
            blind_metrics = compute_blind_metrics(blind_mft)
        else:
            print(f"[WARN] Blind JSONL not found: {bjp}", file=sys.stderr)

    # Gate check
    all_passed, failures = check_gates(dev_metrics, blind_metrics)

    # Report
    print_report(dev_metrics, blind_metrics, failures, all_passed)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
