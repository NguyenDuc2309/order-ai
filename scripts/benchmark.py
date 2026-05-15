from __future__ import annotations

import argparse
import json
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


DEFAULT_API_URL = "http://localhost:9199/api/v1/search/product"
DEFAULT_OUTPUT_DIR = "reports/benchmark"
PRECHECK_COUNT = 5


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    group: str
    query: str
    expected_type: str
    expected_brands: list[str]
    desc: str


@dataclass
class CaseResult:
    id: str
    group: str
    query: str
    expected_type: str
    actual_type: str
    pass_: bool
    brand_hit: bool
    expected_brands: list[str]
    latency_ms: float
    http_status: int
    confidence: float
    item_count: int
    top_items: list[str]
    error: str


TEST_CASES: list[BenchmarkCase] = [
    BenchmarkCase("G1-01", "G1 Brand-only", "coca cola", "needs_clarification", ["coca cola"], "Brand-only soft drink"),
    BenchmarkCase("G1-02", "G1 Brand-only", "pepsi", "needs_clarification", ["pepsi"], "Brand-only soft drink"),
    BenchmarkCase("G1-03", "G1 Brand-only", "sprite", "needs_clarification", ["sprite"], "Brand-only soft drink"),
    BenchmarkCase("G1-04", "G1 Brand-only", "lavie", "needs_clarification", ["lavie"], "Brand-only water"),
    BenchmarkCase("G1-05", "G1 Brand-only", "aquafina", "needs_clarification", ["aquafina"], "Brand-only water"),
    BenchmarkCase("G1-06", "G1 Brand-only", "tiger", "needs_clarification", ["tiger"], "Brand-only beer"),
    BenchmarkCase("G1-07", "G1 Brand-only", "heineken", "needs_clarification", ["heineken"], "Brand-only beer"),
    BenchmarkCase("G1-08", "G1 Brand-only", "vinamilk", "needs_clarification", ["vinamilk"], "Brand-only milk"),
    BenchmarkCase("G1-09", "G1 Brand-only", "omo", "needs_clarification", ["omo"], "Brand-only cleaning"),
    BenchmarkCase("G1-10", "G1 Brand-only", "sunlight", "needs_clarification", ["sunlight"], "Brand-only cleaning"),
    BenchmarkCase("G2-01", "G2 Brand + Packaging", "coca lon", "needs_clarification", ["coca cola"], "Packaging without size"),
    BenchmarkCase("G2-02", "G2 Brand + Packaging", "pepsi chai", "needs_clarification", ["pepsi"], "Packaging without size"),
    BenchmarkCase("G2-03", "G2 Brand + Packaging", "tiger lon", "needs_clarification", ["tiger"], "Packaging without size"),
    BenchmarkCase("G2-04", "G2 Brand + Packaging", "heineken chai", "needs_clarification", ["heineken"], "Packaging without size"),
    BenchmarkCase("G2-05", "G2 Brand + Packaging", "hao hao ly", "needs_clarification", ["hao hao", "hảo hảo"], "Packaging without size"),
    BenchmarkCase("G3-01", "G3 Brand + Size", "coca 330ml", "needs_clarification", ["coca cola"], "Size with multiple variants"),
    BenchmarkCase("G3-02", "G3 Brand + Size", "pepsi 1.5l", "needs_clarification", ["pepsi"], "Size with multiple variants"),
    BenchmarkCase("G3-03", "G3 Brand + Size", "lavie 500ml", "needs_clarification", ["lavie"], "Size with multiple variants"),
    BenchmarkCase("G3-04", "G3 Brand + Size", "vinamilk 1l", "needs_clarification", ["vinamilk"], "Size with multiple variants"),
    BenchmarkCase("G3-05", "G3 Brand + Size", "th true milk 180ml", "needs_clarification", ["th true milk"], "Size with multiple variants"),
    BenchmarkCase("G3-06", "G3 Brand + Size", "sting 330ml", "needs_clarification", ["sting"], "Size with multiple variants"),
    BenchmarkCase("G3-07", "G3 Brand + Size", "oishi 40g", "needs_clarification", ["oishi"], "Size hint for snack"),
    BenchmarkCase("G4-01", "G4 Category-only", "bia", "needs_clarification", ["tiger", "heineken", "bia sai gon", "bia sài gòn"], "Category-only beer"),
    BenchmarkCase("G4-02", "G4 Category-only", "sữa tươi", "needs_clarification", ["vinamilk", "th true milk"], "Category-only milk"),
    BenchmarkCase("G4-03", "G4 Category-only", "nước ngọt", "needs_clarification", ["coca cola", "pepsi", "sprite"], "Category-only soft drink"),
    BenchmarkCase("G4-04", "G4 Category-only", "nước suối", "needs_clarification", ["lavie", "aquafina"], "Category-only water"),
    BenchmarkCase("G4-05", "G4 Category-only", "mì ăn liền", "needs_clarification", ["hao hao", "hảo hảo", "omachi"], "Category-only instant noodle"),
    BenchmarkCase("G4-06", "G4 Category-only", "snack", "needs_clarification", ["oishi", "poca"], "Category-only snack"),
    BenchmarkCase("G4-07", "G4 Category-only", "nước mắm", "needs_clarification", ["nam ngu", "nam ngư"], "Category-only sauce"),
    BenchmarkCase("G5-01", "G5 Size hint", "chai lớn", "needs_clarification", [], "Size hint without brand"),
    BenchmarkCase("G5-02", "G5 Size hint", "lon nhỏ", "needs_clarification", [], "Size hint without brand"),
    BenchmarkCase("G5-03", "G5 Size hint", "hộp lớn", "needs_clarification", [], "Size hint without brand"),
    BenchmarkCase("G5-04", "G5 Size hint", "gói nhỏ", "needs_clarification", [], "Size hint without brand"),
    BenchmarkCase("G6-01", "G6 Synonyms", "bò húc", "needs_clarification", ["red bull"], "Colloquial brand"),
    BenchmarkCase("G6-02", "G6 Synonyms", "mì tôm", "needs_clarification", ["hao hao", "hảo hảo", "omachi"], "Colloquial category"),
    BenchmarkCase("G6-03", "G6 Synonyms", "coke", "needs_clarification", ["coca cola"], "English synonym"),
    BenchmarkCase("G6-04", "G6 Synonyms", "nước rửa chén", "needs_clarification", ["sunlight"], "Category synonym"),
    BenchmarkCase("G6-05", "G6 Synonyms", "bột giặt", "needs_clarification", ["omo"], "Category synonym"),
    BenchmarkCase("G6-06", "G6 Synonyms", "tương ớt", "needs_clarification", ["chinsu"], "Category synonym"),
    BenchmarkCase("G7-01", "G7 Quantity", "3 lon bia tiger", "needs_clarification", ["tiger"], "Quantity plus brand"),
    BenchmarkCase("G7-02", "G7 Quantity", "2 chai coca", "needs_clarification", ["coca cola"], "Quantity plus brand"),
    BenchmarkCase("G7-03", "G7 Quantity", "5 gói mì hảo hảo", "needs_clarification", ["hao hao", "hảo hảo"], "Quantity plus brand"),
    BenchmarkCase("G7-04", "G7 Quantity", "1 hộp sữa vinamilk", "needs_clarification", ["vinamilk"], "Quantity plus brand"),
    BenchmarkCase("G8-01", "G8 Attributes", "nước ngọt ít đường", "needs_clarification", ["coca cola", "pepsi", "sprite"], "Attribute filtered category"),
    BenchmarkCase("G8-02", "G8 Attributes", "bia không cồn", "no_result", [], "Unsupported attribute"),
    BenchmarkCase("G8-03", "G8 Attributes", "snack cao cấp", "needs_clarification", ["oishi", "poca"], "Tag attribute"),
    BenchmarkCase("G9-01", "G9 No-result", "iphone", "no_result", [], "Out-of-catalog electronics"),
    BenchmarkCase("G9-02", "G9 No-result", "vitamin C", "no_result", [], "Out-of-catalog supplement"),
    BenchmarkCase("G9-03", "G9 No-result", "áo thun nam", "no_result", [], "Out-of-catalog clothing"),
    BenchmarkCase("G9-04", "G9 No-result", "sữa rửa mặt", "no_result", [], "Out-of-catalog cosmetics"),
]


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


def score_case(case: BenchmarkCase, response: dict, latency_ms: float, http_status: int, error: str = "") -> CaseResult:
    items = response.get("items", []) if response else []
    top_items = [str(item.get("name", "")) for item in items[:3]]
    actual_type = response.get("type", "error") if response else "error"
    haystack = normalize_text(" ".join(top_items))
    brand_hit = not case.expected_brands or any(normalize_text(brand) in haystack for brand in case.expected_brands)

    return CaseResult(
        id=case.id,
        group=case.group,
        query=case.query,
        expected_type=case.expected_type,
        actual_type=actual_type,
        pass_=http_status == 200 and actual_type == case.expected_type,
        brand_hit=brand_hit,
        expected_brands=case.expected_brands,
        latency_ms=round(latency_ms, 2),
        http_status=http_status,
        confidence=float(response.get("confidence", 0.0)) if response else 0.0,
        item_count=len(items),
        top_items=top_items,
        error=error,
    )


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
        brand = "brand" if result.brand_hit else "brand-miss"
        print(
            f"[{index:02d}/{total:02d}] {status} {brand} "
            f"{case.id} {case.query!r}: expected={case.expected_type}, actual={result.actual_type}, "
            f"items={result.item_count}, {result.latency_ms:.0f}ms"
        )
    return results


def summarize(results: list[CaseResult]) -> dict:
    total = len(results)
    passed = sum(1 for result in results if result.pass_)
    failed = total - passed
    avg_latency = round(sum(result.latency_ms for result in results) / total, 2) if total else 0.0
    groups: dict[str, dict] = {}
    for result in results:
        bucket = groups.setdefault(result.group, {"total": 0, "pass": 0, "fail": 0, "brand_hit": 0})
        bucket["total"] += 1
        bucket["pass"] += 1 if result.pass_ else 0
        bucket["fail"] += 0 if result.pass_ else 1
        bucket["brand_hit"] += 1 if result.brand_hit else 0
    return {
        "total": total,
        "pass": passed,
        "fail": failed,
        "score_pct": round((passed / total) * 100, 2) if total else 0.0,
        "avg_latency_ms": avg_latency,
        "groups": groups,
    }


def save_report(results: list[CaseResult], output_dir: Path, api_url: str) -> tuple[Path, Path, dict]:
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
        "summary": summary,
        "results": [serialize_result(result) for result in results],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    append_history(output_dir / "history.json", run_id, summary, json_path.name, md_path.name)
    return json_path, md_path, summary


def serialize_result(result: CaseResult) -> dict:
    data = asdict(result)
    data["pass"] = data.pop("pass_")
    return data


def render_markdown(payload: dict) -> str:
    summary = payload["summary"]
    lines = [
        f"# Benchmark Report {payload['run_id']}",
        "",
        f"- API URL: `{payload['api_url']}`",
        f"- Score: {summary['score_pct']}% ({summary['pass']}/{summary['total']})",
        f"- Failed: {summary['fail']}",
        f"- Average latency: {summary['avg_latency_ms']} ms",
        "",
        "## Group Breakdown",
        "",
        "| Group | Total | Pass | Fail | Brand hit |",
        "|---|---:|---:|---:|---:|",
    ]
    for group, values in summary["groups"].items():
        lines.append(f"| {group} | {values['total']} | {values['pass']} | {values['fail']} | {values['brand_hit']} |")

    lines.extend([
        "",
        "## Cases",
        "",
        "| ID | Group | Query | Expected | Actual | Pass | Brand hit | Latency | Top items | Error |",
        "|---|---|---|---|---|---|---|---:|---|---|",
    ])
    for result in payload["results"]:
        top_items = "<br>".join(result["top_items"])
        error = result["error"].replace("|", "\\|")
        lines.append(
            f"| {result['id']} | {result['group']} | {result['query']} | {result['expected_type']} | "
            f"{result['actual_type']} | {result['pass']} | {result['brand_hit']} | "
            f"{result['latency_ms']} | {top_items} | {error} |"
        )
    return "\n".join(lines) + "\n"


def append_history(history_path: Path, run_id: str, summary: dict, json_report: str, md_report: str) -> None:
    history: list[dict] = []
    if history_path.exists():
        history = json.loads(history_path.read_text(encoding="utf-8"))
    history.append(
        {
            "run_id": run_id,
            "date": run_id,
            "score_pct": summary["score_pct"],
            "pass": summary["pass"],
            "fail": summary["fail"],
            "avg_latency_ms": summary["avg_latency_ms"],
            "json_report": json_report,
            "md_report": md_report,
        }
    )
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def precheck(api_url: str) -> bool:
    print(f"Precheck: running first {PRECHECK_COUNT} cases against {api_url}")
    results = run_cases(TEST_CASES[:PRECHECK_COUNT], api_url)
    summary = summarize(results)
    print(f"Precheck score: {summary['score_pct']}% ({summary['pass']}/{summary['total']})")
    return summary["fail"] == 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run order-resolve-ai benchmark cases.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help=f"Search API URL. Default: {DEFAULT_API_URL}")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help=f"Report output directory. Default: {DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--precheck-only", action="store_true", help="Run only the first 5 cases and do not save a full report.")
    parser.add_argument("--no-confirm", action="store_true", help="Skip the interactive confirmation after precheck.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if len(TEST_CASES) != 50:
        raise RuntimeError(f"Expected 50 test cases, found {len(TEST_CASES)}")

    precheck_ok = precheck(args.api_url)
    if args.precheck_only:
        return

    if not args.no_confirm:
        answer = input("Continue? [y/N] ").strip().lower()
        if answer != "y":
            print("Stopped after precheck. Full report was not saved.")
            return

    if not precheck_ok:
        print("Precheck has failures; continuing because confirmation/no-confirm allowed it.")

    print(f"Running all {len(TEST_CASES)} benchmark cases...")
    results = run_cases(TEST_CASES, args.api_url)
    json_path, md_path, summary = save_report(results, Path(args.output_dir), args.api_url)
    print(f"Score: {summary['score_pct']}% ({summary['pass']}/{summary['total']})")
    print(f"Saved JSON report: {json_path}")
    print(f"Saved Markdown report: {md_path}")
    print(f"Updated history: {Path(args.output_dir) / 'history.json'}")


if __name__ == "__main__":
    main()
