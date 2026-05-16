from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


DEFAULT_API_URL = "http://localhost:9199/api/v1/search/product"
DEFAULT_OUTPUT_DIR = "reports/benchmark"
DEFAULT_TEST_CASES = Path(__file__).parent / "test_cases.md"
PRECHECK_COUNT = 5
TOP_N = 5  # số sản phẩm top dùng để chấm điểm


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    group: str
    query: str
    notes: str
    expected_type: str          # exact | clarify | no_result
    required_keywords: list[str]  # +term: ít nhất 1 kết quả phải chứa
    excluded_keywords: list[str]  # !term: không kết quả nào được chứa
    expected_qty: int | None      # qty=N: items[0].quantity phải bằng N


@dataclass
class CaseResult:
    id: str
    group: str
    query: str
    notes: str
    expected_type: str
    actual_type: str
    pass_: bool
    fail_reasons: list[str]  # mô tả chi tiết tại sao fail
    required_keywords: list[str]
    excluded_keywords: list[str]
    expected_qty: int | None
    actual_qty: int | None
    latency_ms: float
    http_status: int
    confidence: float
    item_count: int
    top_items: list[str]
    error: str


# ---------------------------------------------------------------------------
# DSL parser
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "clarify": "needs_clarification",
    "exact": "exact_match",
    "no_result": "no_result",
}


def parse_expected(raw: str) -> tuple[str, list[str], list[str], int | None]:
    """Parse the Expected column DSL.

    Syntax: <type> [+term] [!term] [qty=N]
    Underscores in terms are replaced with spaces.
    Returns (expected_type, required_keywords, excluded_keywords, expected_qty).
    """
    tokens = raw.strip().split()
    if not tokens:
        raise ValueError(f"Empty expected string: {raw!r}")

    type_token = tokens[0].lower()
    if type_token not in _TYPE_MAP:
        raise ValueError(f"Unknown type token {type_token!r} in {raw!r}")
    expected_type = _TYPE_MAP[type_token]

    required: list[str] = []
    excluded: list[str] = []
    expected_qty: int | None = None

    for tok in tokens[1:]:
        if tok.startswith("+"):
            required.append(tok[1:].replace("_", " "))
        elif tok.startswith("!"):
            excluded.append(tok[1:].replace("_", " "))
        elif tok.lower().startswith("qty="):
            expected_qty = int(tok.split("=", 1)[1])

    return expected_type, required, excluded, expected_qty


# ---------------------------------------------------------------------------
# Markdown loader
# ---------------------------------------------------------------------------

def _parse_md_row(line: str) -> list[str]:
    """Split a markdown table row into cells, stripping whitespace."""
    parts = line.strip().strip("|").split("|")
    return [p.strip() for p in parts]


def load_test_cases(path: Path) -> list[BenchmarkCase]:
    """Load test cases from a markdown file.

    Supported table formats (header detection is automatic):
      4 cols: | ID | Group | Query | Expected |
      5 cols: | ID | Group | Query | Expected | Notes |
    """
    text = path.read_text(encoding="utf-8")
    cases: list[BenchmarkCase] = []
    header_found = False
    col_id = col_group = col_query = col_expected = col_notes = -1

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        # Skip separator rows (---|---)
        if re.fullmatch(r"[\|\-\s:]+", line):
            continue

        cells = _parse_md_row(line)
        if not cells:
            continue

        # Detect header row
        if not header_found:
            lower_cells = [c.lower() for c in cells]
            if "query" in lower_cells and "expected" in lower_cells:
                col_query = lower_cells.index("query")
                col_expected = lower_cells.index("expected")
                col_id = lower_cells.index("id") if "id" in lower_cells else -1
                col_group = lower_cells.index("group") if "group" in lower_cells else -1
                col_notes = lower_cells.index("notes") if "notes" in lower_cells else -1
                header_found = True
            continue

        # Data row
        if len(cells) <= max(col_query, col_expected):
            continue

        query = cells[col_query]
        expected_raw = cells[col_expected]
        case_id = cells[col_id] if col_id >= 0 and col_id < len(cells) else f"C{len(cases)+1:03d}"
        group = cells[col_group] if col_group >= 0 and col_group < len(cells) else "Ungrouped"
        notes = cells[col_notes] if col_notes >= 0 and col_notes < len(cells) else ""

        # Strip group prefix from group cell (e.g. "G1 Brand-only" → "G1 Brand-only")
        if not query or not expected_raw:
            continue

        try:
            expected_type, required, excluded, qty = parse_expected(expected_raw)
        except ValueError as exc:
            print(f"[WARN] Skipping row {case_id!r}: {exc}")
            continue

        cases.append(BenchmarkCase(
            id=case_id,
            group=group,
            query=query,
            notes=notes,
            expected_type=expected_type,
            required_keywords=required,
            excluded_keywords=excluded,
            expected_qty=qty,
        ))

    return cases


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def normalize_text(value: str) -> str:
    value = value.lower()
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return " ".join(value.split())


def call_api(api_url: str, query: str) -> tuple[dict, int]:
    payload = json.dumps({"query": query, "user_id": "benchmark"}).encode("utf-8")
    request = urllib.request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8")), response.status


def score_case(
    case: BenchmarkCase,
    response: dict,
    latency_ms: float,
    http_status: int,
    error: str = "",
) -> CaseResult:
    items = response.get("items", []) if response else []
    top_items_raw = items[:TOP_N]
    top_names_norm = [normalize_text(str(item.get("name", ""))) for item in top_items_raw]
    top_items_display = [str(item.get("name", "")) for item in top_items_raw]

    actual_type = response.get("type", "error") if response else "error"

    # --- Kiểm tra type ---
    type_ok = http_status == 200 and actual_type == case.expected_type

    # --- Kiểm tra required keywords (+term) ---
    # Mỗi term phải xuất hiện trong ít nhất 1 kết quả top
    required_hits: dict[str, bool] = {}
    for kw in case.required_keywords:
        kw_norm = normalize_text(kw)
        required_hits[kw] = any(kw_norm in name for name in top_names_norm)

    # --- Kiểm tra excluded keywords (!term) ---
    # Không được có bất kỳ kết quả nào chứa term bị cấm
    excluded_hits: dict[str, bool] = {}
    for kw in case.excluded_keywords:
        kw_norm = normalize_text(kw)
        excluded_hits[kw] = any(kw_norm in name for name in top_names_norm)

    # --- Kiểm tra quantity ---
    actual_qty: int | None = None
    qty_ok = True
    if case.expected_qty is not None:
        first_item = items[0] if items else {}
        actual_qty = first_item.get("quantity")
        qty_ok = actual_qty == case.expected_qty

    # --- Tổng hợp pass/fail ---
    required_ok = all(required_hits.values()) if required_hits else True
    excluded_ok = not any(excluded_hits.values())
    pass_ = type_ok and required_ok and excluded_ok and qty_ok

    # --- Mô tả lý do fail (chi tiết) ---
    fail_reasons: list[str] = []
    if not type_ok:
        fail_reasons.append(f"type={actual_type}≠{case.expected_type}")
    for kw, hit in required_hits.items():
        if not hit:
            fail_reasons.append(f"required '{kw}' not found in top results")
    for kw, hit in excluded_hits.items():
        if hit:
            fail_reasons.append(f"excluded variant '{kw}' appeared in results")
    if case.expected_qty is not None and not qty_ok:
        fail_reasons.append(f"qty={actual_qty}≠expected {case.expected_qty}")

    return CaseResult(
        id=case.id,
        group=case.group,
        query=case.query,
        notes=case.notes,
        expected_type=case.expected_type,
        actual_type=actual_type,
        pass_=pass_,
        fail_reasons=fail_reasons,
        required_keywords=case.required_keywords,
        excluded_keywords=case.excluded_keywords,
        expected_qty=case.expected_qty,
        actual_qty=actual_qty,
        latency_ms=round(latency_ms, 2),
        http_status=http_status,
        confidence=float(response.get("confidence", 0.0)) if response else 0.0,
        item_count=len(items),
        top_items=top_items_display,
        error=error,
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_cases(cases: list[BenchmarkCase], api_url: str) -> list[CaseResult]:
    results: list[CaseResult] = []
    total = len(cases)
    for index, case in enumerate(cases, start=1):
        start = time.perf_counter()
        response: dict = {}
        http_status = 0
        error = ""
        try:
            response, http_status = call_api(api_url, case.query)
        except urllib.error.HTTPError as exc:
            http_status = exc.code
            error = exc.read().decode("utf-8", errors="ignore")[:300]
        except Exception as exc:  # noqa: BLE001
            error = str(exc)[:300]
        latency_ms = (time.perf_counter() - start) * 1000
        result = score_case(case, response, latency_ms, http_status, error)
        results.append(result)

        status = "PASS" if result.pass_ else "FAIL"
        reasons = " | ".join(result.fail_reasons) if result.fail_reasons else "ok"
        print(
            f"[{index:02d}/{total:02d}] {status}  {case.id:<8} {case.query!r:<35} "
            f"actual={result.actual_type:<22} conf={result.confidence:.2f}  {reasons}"
        )
    return results


# ---------------------------------------------------------------------------
# Summary & reporting
# ---------------------------------------------------------------------------

def summarize(results: list[CaseResult]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r.pass_)
    failed = total - passed
    avg_latency = round(sum(r.latency_ms for r in results) / total, 2) if total else 0.0

    confs_all  = [r.confidence for r in results if r.confidence > 0]
    confs_pass = [r.confidence for r in results if r.pass_ and r.confidence > 0]
    confs_fail = [r.confidence for r in results if not r.pass_ and r.confidence > 0]

    def avg(lst: list[float]) -> float:
        return round(sum(lst) / len(lst), 3) if lst else 0.0

    # Failure reason breakdown
    reason_counts: dict[str, int] = {}
    for r in results:
        for reason in r.fail_reasons:
            # Normalize to a pattern (strip specific keyword values)
            key = re.sub(r"'[^']*'", "'?'", reason)
            key = re.sub(r"=\d+", "=N", key)
            reason_counts[key] = reason_counts.get(key, 0) + 1
    reason_counts = dict(sorted(reason_counts.items(), key=lambda kv: kv[1], reverse=True))

    # Per-group stats
    groups: dict[str, dict] = {}
    for r in results:
        b = groups.setdefault(r.group, {"total": 0, "pass": 0, "fail": 0, "_confs": []})
        b["total"] += 1
        b["pass"] += 1 if r.pass_ else 0
        b["fail"] += 0 if r.pass_ else 1
        if r.confidence > 0:
            b["_confs"].append(r.confidence)
    for b in groups.values():
        gc = b.pop("_confs")
        b["avg_confidence"] = avg(gc)

    return {
        "total": total,
        "pass": passed,
        "fail": failed,
        "score_pct": round((passed / total) * 100, 2) if total else 0.0,
        "avg_latency_ms": avg_latency,
        "avg_confidence": avg(confs_all),
        "avg_confidence_pass": avg(confs_pass),
        "avg_confidence_fail": avg(confs_fail),
        "failure_reasons": reason_counts,
        "groups": groups,
    }


def serialize_result(r: CaseResult) -> dict:
    data = asdict(r)
    data["pass"] = data.pop("pass_")
    return data


def render_markdown(payload: dict) -> str:
    summary = payload["summary"]
    lines = [
        f"# Benchmark Report — {payload['run_id']}",
        "",
        f"- API: `{payload['api_url']}`",
        f"- Test cases file: `{payload['test_cases_file']}`",
        f"- Score: **{summary['score_pct']}%** ({summary['pass']}/{summary['total']})",
        f"- Failed: {summary['fail']}",
        f"- Avg latency: {summary['avg_latency_ms']} ms",
        f"- Avg confidence — all: {summary['avg_confidence']}  |  pass: {summary['avg_confidence_pass']}  |  fail: {summary['avg_confidence_fail']}",
        "",
        "## Failure Analysis",
        "",
        "Frequency of each fail reason pattern:",
        "",
        "| Reason | Count |",
        "|---|---:|",
    ]
    for reason, count in summary.get("failure_reasons", {}).items():
        lines.append(f"| `{reason}` | {count} |")
    if not summary.get("failure_reasons"):
        lines.append("| — | — |")

    lines += [
        "",
        "## Group Breakdown",
        "",
        "| Group | Total | Pass | Fail | Avg conf |",
        "|---|---:|---:|---:|---:|",
    ]
    for group, v in summary["groups"].items():
        lines.append(f"| {group} | {v['total']} | {v['pass']} | {v['fail']} | {v['avg_confidence']} |")

    lines += [
        "",
        "## Cases",
        "",
        "| ID | Group | Query | Expected type | Actual type | Pass | Conf | Qty exp→act | Fail reasons | Top items |",
        "|---|---|---|---|---|---|---:|---|---|---|",
    ]
    for r in payload["results"]:
        top = "<br>".join(r["top_items"])
        fail_str = "; ".join(r["fail_reasons"]) if r["fail_reasons"] else "—"
        conf = f"{r['confidence']:.2f}" if r["confidence"] else "—"
        qty_str = f"{r['expected_qty']}→{r['actual_qty']}" if r["expected_qty"] is not None else "—"
        pass_str = "✓" if r["pass"] else "✗"
        lines.append(
            f"| {r['id']} | {r['group']} | {r['query']} "
            f"| {r['expected_type']} | {r['actual_type']} "
            f"| {pass_str} | {conf} | {qty_str} "
            f"| {fail_str} | {top} |"
        )
    return "\n".join(lines) + "\n"


def save_report(
    results: list[CaseResult],
    output_dir: Path,
    api_url: str,
    test_cases_file: str,
) -> tuple[Path, Path, dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(results)
    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    score_int = round(summary["score_pct"])
    base_name = f"{run_id}_score-{score_int}pct"
    json_path = output_dir / f"{base_name}.json"
    md_path = output_dir / f"{base_name}.md"
    payload = {
        "run_id": run_id,
        "api_url": api_url,
        "test_cases_file": test_cases_file,
        "summary": summary,
        "results": [serialize_result(r) for r in results],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    _append_history(output_dir / "history.json", run_id, summary, json_path.name, md_path.name, test_cases_file)
    return json_path, md_path, summary


def _append_history(
    history_path: Path,
    run_id: str,
    summary: dict,
    json_report: str,
    md_report: str,
    test_cases_file: str,
) -> None:
    history: list[dict] = []
    if history_path.exists():
        history = json.loads(history_path.read_text(encoding="utf-8"))
    history.append({
        "run_id": run_id,
        "test_cases_file": test_cases_file,
        "score_pct": summary["score_pct"],
        "pass": summary["pass"],
        "fail": summary["fail"],
        "total": summary["total"],
        "avg_latency_ms": summary["avg_latency_ms"],
        "avg_confidence": summary["avg_confidence"],
        "failure_reasons": summary["failure_reasons"],
        "json_report": json_report,
        "md_report": md_report,
    })
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Precheck
# ---------------------------------------------------------------------------

def precheck(cases: list[BenchmarkCase], api_url: str) -> bool:
    subset = cases[:PRECHECK_COUNT]
    print(f"Precheck: running first {len(subset)} cases against {api_url}")
    results = run_cases(subset, api_url)
    summary = summarize(results)
    print(f"Precheck score: {summary['score_pct']}% ({summary['pass']}/{summary['total']})")
    return summary["fail"] == 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run order-resolve-ai benchmark. Test cases are loaded from a Markdown file."
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"Search API URL. Default: {DEFAULT_API_URL}",
    )
    parser.add_argument(
        "--test-cases",
        default=str(DEFAULT_TEST_CASES),
        help=f"Path to Markdown test-case file. Default: {DEFAULT_TEST_CASES}",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Report output directory. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--precheck-only",
        action="store_true",
        help=f"Run only the first {PRECHECK_COUNT} cases and exit without saving a full report.",
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Skip interactive confirmation after precheck.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tc_path = Path(args.test_cases)
    if not tc_path.exists():
        raise FileNotFoundError(f"Test cases file not found: {tc_path}")

    cases = load_test_cases(tc_path)
    if not cases:
        raise RuntimeError(f"No test cases loaded from {tc_path}")
    print(f"Loaded {len(cases)} test cases from {tc_path}")

    precheck_ok = precheck(cases, args.api_url)
    if args.precheck_only:
        return

    if not args.no_confirm:
        answer = input("Continue with full run? [y/N] ").strip().lower()
        if answer != "y":
            print("Stopped after precheck. Full report was not saved.")
            return

    if not precheck_ok:
        print("Precheck has failures; continuing because confirmation/no-confirm allowed it.")

    print(f"\nRunning all {len(cases)} benchmark cases...")
    results = run_cases(cases, args.api_url)
    json_path, md_path, summary = save_report(
        results, Path(args.output_dir), args.api_url, str(tc_path)
    )
    print(f"\nScore: {summary['score_pct']}% ({summary['pass']}/{summary['total']})")
    print(f"Saved JSON: {json_path}")
    print(f"Saved Markdown: {md_path}")
    print(f"Updated history: {Path(args.output_dir) / 'history.json'}")


if __name__ == "__main__":
    main()
