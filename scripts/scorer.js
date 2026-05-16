/**
 * scorer.js — Order AI Benchmark Scoring Engine
 *
 * Exports (window globals, no bundler needed):
 *   parseMdTestCases(text)        → BenchmarkCase[]
 *   scoreCase(tc, resp, ms, http) → CaseResult
 *   summarize(cases, resultsMap)  → Summary
 *   normalizeVi(s)                → string
 */

// ---------------------------------------------------------------------------
// Text normalisation
// ---------------------------------------------------------------------------

function normalizeVi(s) {
  return String(s || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .replace(/\s+/g, ' ')
    .trim();
}

// ---------------------------------------------------------------------------
// DSL parser
// Expected column syntax: <type> [+term] [!term] [qty=N]
// ---------------------------------------------------------------------------

const _TYPE_MAP = {
  clarify:   'needs_clarification',
  exact:     'exact_match',
  no_result: 'no_result',
};

/**
 * @param {string} raw  e.g. "exact +coca +lon !light !zero qty=2"
 * @returns {{ expectedType, required: string[], excluded: string[], qty: number|null }}
 */
function parseDsl(raw) {
  const tokens = raw.trim().split(/\s+/);
  const expectedType = _TYPE_MAP[tokens[0]?.toLowerCase()];
  if (!expectedType) throw new Error(`Unknown type token "${tokens[0]}" in: ${raw}`);

  const required = [];
  const excluded = [];
  let qty = null;

  for (const tok of tokens.slice(1)) {
    if (tok.startsWith('+'))           required.push(tok.slice(1).replace(/_/g, ' '));
    else if (tok.startsWith('!'))      excluded.push(tok.slice(1).replace(/_/g, ' '));
    else if (/^qty=\d+$/i.test(tok))   qty = parseInt(tok.split('=')[1], 10);
  }

  return { expectedType, required, excluded, qty };
}

// ---------------------------------------------------------------------------
// Markdown test-case loader
// ---------------------------------------------------------------------------

/**
 * Parse a markdown file into an array of BenchmarkCase objects.
 * Supports tables with columns: ID | Group | Query | Expected | Notes (Notes optional).
 *
 * @param {string} text  Full text of test_cases.md
 * @returns {BenchmarkCase[]}
 *
 * @typedef {{ id, group, query, notes, expectedType, required, excluded, qty }} BenchmarkCase
 */
function parseMdTestCases(text) {
  const cases = [];
  let headerFound = false;
  let ci = { id: -1, group: -1, query: -1, expected: -1, notes: -1 };

  for (const rawLine of text.split('\n')) {
    const line = rawLine.trim();
    if (!line.startsWith('|')) continue;
    if (/^[\|\-\s:]+$/.test(line)) continue; // separator row

    const cells = line.replace(/^\||\|$/g, '').split('|').map(c => c.trim());

    if (!headerFound) {
      const lower = cells.map(c => c.toLowerCase());
      if (lower.includes('query') && lower.includes('expected')) {
        ci.query    = lower.indexOf('query');
        ci.expected = lower.indexOf('expected');
        ci.id       = lower.indexOf('id');
        ci.group    = lower.indexOf('group');
        ci.notes    = lower.indexOf('notes');
        headerFound = true;
      }
      continue;
    }

    const get = (col) => (col >= 0 && col < cells.length) ? cells[col] : '';
    const query    = get(ci.query);
    const expected = get(ci.expected);
    if (!query || !expected) continue;

    try {
      const { expectedType, required, excluded, qty } = parseDsl(expected);
      cases.push({
        id:           get(ci.id)    || `C${String(cases.length + 1).padStart(3, '0')}`,
        group:        get(ci.group) || 'Ungrouped',
        query,
        notes:        get(ci.notes),
        expectedType,
        required,
        excluded,
        qty,
      });
    } catch (e) {
      console.warn('[scorer] Skipping row:', e.message);
    }
  }

  return cases;
}

// ---------------------------------------------------------------------------
// Scoring
// ---------------------------------------------------------------------------

const TOP_N = 5;

/**
 * Score one test case under the *behavioral correctness* contract.
 *
 * See `critical_issue.md`: "không có sản phẩm" is a valid output. System FAILs only
 * when it hallucinates items, not when it honestly says no_result.
 *
 * Rules:
 *   1. HTTP error → FAIL
 *   2. expected=no_result (G7): actual must be no_result; else FAIL (hallucination)
 *   3. expected=exact/clarify:
 *      - actual=no_result → PASS (honest "not in catalog")
 *      - actual has items → check required+, excluded!, and qty=
 *      - type mismatch (exact ↔ clarify) is informational, not a fail
 *
 * @param {BenchmarkCase} tc
 * @param {object|null}   resp
 * @param {number}        latencyMs
 * @param {number}        httpStatus
 * @param {string}        [error]
 * @returns {CaseResult}
 */
function scoreCase(tc, resp, latencyMs, httpStatus, error = '') {
  const items    = resp?.items ?? [];
  const topRaw   = items.slice(0, TOP_N);
  const topNames = topRaw.map(it => normalizeVi(it.name ?? ''));
  const topDisp  = topRaw.map(it => String(it.name ?? ''));
  const actualType = resp?.type ?? (error ? 'error' : 'unknown');
  const actualQty  = items[0]?.quantity ?? null;

  const failReasons = [];
  const requiredHits = {};
  const excludedHits = {};

  // 1. HTTP error → FAIL
  if (httpStatus !== 200 || actualType === 'error') {
    failReasons.push(`http_status=${httpStatus}${error ? ' ' + error.slice(0, 80) : ''}`);
  }
  // 2. Expected no_result (G7): strict abstain
  else if (tc.expectedType === 'no_result') {
    if (actualType !== 'no_result') {
      failReasons.push(
        `expected no_result (out-of-catalog) but got ${actualType} with ${items.length} items — hallucination`
      );
    }
  }
  // 3. Expected exact / clarify
  else {
    if (actualType === 'no_result') {
      // Honest "not in catalog" — acceptable
    } else {
      // Items returned — validate them
      for (const kw of tc.required) {
        requiredHits[kw] = topNames.some(n => n.includes(normalizeVi(kw)));
        if (!requiredHits[kw]) failReasons.push(`required "${kw}" not in top results — wrong items`);
      }
      for (const kw of tc.excluded) {
        excludedHits[kw] = topNames.some(n => n.includes(normalizeVi(kw)));
        if (excludedHits[kw]) failReasons.push(`excluded variant "${kw}" appeared in results`);
      }
      if (tc.qty !== null && actualQty !== tc.qty) {
        failReasons.push(`qty: got ${actualQty}, want ${tc.qty}`);
      }
    }
  }

  const pass = failReasons.length === 0;

  return {
    id:           tc.id,
    status:       'done',
    pass,
    failReasons,
    actualType,
    expectedType: tc.expectedType,
    confidence:   resp?.confidence ?? null,
    latencyMs:    Math.round(latencyMs),
    httpStatus,
    topItems:     topDisp,
    actualQty,
    error,
  };
}

// ---------------------------------------------------------------------------
// Summary (for export / history)
// ---------------------------------------------------------------------------

/**
 * @param {BenchmarkCase[]} cases
 * @param {Record<string, CaseResult>} resultsMap   id → result
 * @returns {Summary}
 */
function summarize(cases, resultsMap) {
  const done   = cases.map(tc => resultsMap[tc.id]).filter(r => r?.status === 'done');
  const passed = done.filter(r => r.pass).length;
  const failed = done.length - passed;

  const avg = arr => arr.length ? arr.reduce((s, v) => s + v, 0) / arr.length : null;
  const confsAll  = done.filter(r => r.confidence != null).map(r => r.confidence);
  const confsPass = done.filter(r =>  r.pass && r.confidence != null).map(r => r.confidence);
  const confsFail = done.filter(r => !r.pass && r.confidence != null).map(r => r.confidence);

  // Failure reason patterns
  const reasonCounts = {};
  for (const r of done) {
    for (const reason of r.failReasons) {
      // Bucket by prefix (type/missing/excluded/qty)
      const key = reason.replace(/"[^"]*"/g, '"?"').replace(/\d+/g, 'N');
      reasonCounts[key] = (reasonCounts[key] ?? 0) + 1;
    }
  }

  // Per-group stats
  const groups = {};
  for (const tc of cases) {
    const r = resultsMap[tc.id];
    const b = groups[tc.group] ??= { total: 0, pass: 0, fail: 0, _confs: [] };
    b.total++;
    if (r?.status === 'done') {
      if (r.pass) b.pass++; else b.fail++;
      if (r.confidence != null) b._confs.push(r.confidence);
    }
  }
  for (const b of Object.values(groups)) {
    b.avgConf = avg(b._confs);
    delete b._confs;
  }

  return {
    total:         done.length,
    pass:          passed,
    fail:          failed,
    scorePct:      done.length ? Math.round(passed / done.length * 10000) / 100 : 0,
    avgLatency:    avg(done.map(r => r.latencyMs)) ?? 0,
    avgConf:       avg(confsAll),
    avgConfPass:   avg(confsPass),
    avgConfFail:   avg(confsFail),
    reasonCounts,
    groups,
  };
}
