from __future__ import annotations

import csv
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Use port 9199 as confirmed by the user
API_URL = os.getenv("API_URL", "http://localhost:9199/api/v1/search/product")
OUTPUT_DIR = Path("reports")
CSV_PATH = OUTPUT_DIR / "testcase_results.csv"
MD_PATH = OUTPUT_DIR / "testcase_report.md"


@dataclass
class TestcaseRow:
    idx: int
    prompt: str
    latency_ms: float
    http_status: int
    result_status: str
    confidence: float
    items_count: int
    top_items: str
    ok: bool
    message: str
    error: str


PROMPTS = [
    "cho mua coca",
    "cho mua chai bia sài gòn",
    "mua sữa vinamilk hộp một lít",
    "cho nước ngọt lít rưỡi",
    "cho mua 3 lon bò húc",
]


def call_api(prompt: str) -> tuple[dict, int]:
    payload = json.dumps({"query": prompt, "user_id": "testcase"}).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body), resp.status


def run() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[TestcaseRow] = []

    print(f"Running {len(PROMPTS)} testcases on {API_URL}...")

    for idx, prompt in enumerate(PROMPTS, start=1):
        start = time.perf_counter()
        try:
            response, http_status = call_api(prompt)
            elapsed = (time.perf_counter() - start) * 1000
            items = response.get("items", [])
            top_items_str = ", ".join([f"{it.get('name')} (S:{it.get('score', 0)})" for it in items[:3]])
            rows.append(
                TestcaseRow(
                    idx=idx,
                    prompt=prompt,
                    latency_ms=round(elapsed, 2),
                    http_status=http_status,
                    result_status=response.get("status", "success"),
                    confidence=float(response.get("confidence", 0.0)),
                    items_count=len(items),
                    top_items=top_items_str,
                    ok=http_status == 200,
                    message=response.get("message", ""),
                    error="",
                )
            )
            print(f"[{idx}/{len(PROMPTS)}] Prompt: {prompt} | Status: {http_status} | Latency: {elapsed:.2f}ms | Top: {top_items_str}")
        except urllib.error.HTTPError as exc:
            elapsed = (time.perf_counter() - start) * 1000
            body = exc.read().decode("utf-8", errors="ignore")
            rows.append(
                TestcaseRow(
                    idx=idx,
                    prompt=prompt,
                    latency_ms=round(elapsed, 2),
                    http_status=exc.code,
                    result_status="error",
                    confidence=0.0,
                    items_count=0,
                    top_items="",
                    ok=False,
                    message="",
                    error=body[:180],
                )
            )
            print(f"[{idx}/{len(PROMPTS)}] Prompt: {prompt} | Error: {exc.code} | Latency: {elapsed:.2f}ms")
        except Exception as exc:  # noqa: BLE001
            elapsed = (time.perf_counter() - start) * 1000
            rows.append(
                TestcaseRow(
                    idx=idx,
                    prompt=prompt,
                    latency_ms=round(elapsed, 2),
                    http_status=0,
                    result_status="error",
                    confidence=0.0,
                    items_count=0,
                    top_items="",
                    ok=False,
                    message="",
                    error=str(exc)[:180],
                )
            )
            print(f"[{idx}/{len(PROMPTS)}] Prompt: {prompt} | Exception: {str(exc)[:180]}")

    write_csv(rows)
    write_markdown(rows)
    print(f"Saved CSV report to {CSV_PATH}")
    print(f"Saved Markdown report to {MD_PATH}")


def write_csv(rows: list[TestcaseRow]) -> None:
    with CSV_PATH.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(
            [
                "idx",
                "prompt",
                "latency_ms",
                "http_status",
                "result_status",
                "confidence",
                "items_count",
                "top_items",
                "ok",
                "message",
                "error",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.idx,
                    row.prompt,
                    row.latency_ms,
                    row.http_status,
                    row.result_status,
                    row.confidence,
                    row.items_count,
                    row.top_items,
                    row.ok,
                    row.message,
                    row.error,
                ]
            )


def write_markdown(rows: list[TestcaseRow]) -> None:
    total = len(rows)
    passed = sum(1 for row in rows if row.ok)
    avg_latency = round(sum(row.latency_ms for row in rows) / total, 2) if rows else 0.0

    lines = [
        f"# Testcase Report ({total} Prompts)",
        "",
        f"- Total prompts: {total}",
        f"- HTTP 200 count: {passed}",
        f"- Average latency: {avg_latency} ms",
        "",
        "| # | Prompt | Latency (ms) | HTTP | Status | Conf | Items | Top Results (Top 3) |",
        "|---|---|---:|---:|---|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.idx} | {row.prompt} | {row.latency_ms} | {row.http_status} | "
            f"{row.result_status} | {row.confidence:.2f} | {row.items_count} | {row.top_items} |"
        )

    lines.append("")
    lines.append("## Errors")
    for row in rows:
        if row.error:
            lines.append(f"- Prompt {row.idx}: `{row.error}`")
    if not any(row.error for row in rows):
        lines.append("- None")

    MD_PATH.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    run()
