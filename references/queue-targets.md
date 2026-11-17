# Queue-size sourcing targets

Use this when the user asks for N fresh postings rather than N applications.

## Steps

1. Treat `pipeline.py --target` as the **applied-count gate**, not the requested queue length. Set it above `applied_today` so the gate stays `WORK`; a `DONE` verdict from `loop-preflight.py` compares applications against that gate and is not a reason to stop a sourcing run with an explicit queue target.
2. Run the funnel across the configured `searches.csv` rows, then rescreen anything left past `--screen-limit`. Drop rows still unscreened after the retry (tab/navigation errors) instead of padding the count.
3. If the funnel wrote more than N keeps, back up `queue.jsonl`, remove unscreened/error rows, dedupe by URL, and keep the first N rows in the file's existing value order (`apply_rank - 2*fit`). Verify `len(rows) == N` and `len({r['url'] for r in rows}) == N`.
4. Before any apply batch, apply the strict London geo-filter to the queue. `precheck.py` admits out-of-London Reed/Reed API/Adzuna rows; the applicant profile is London-only, so those rows must not reach a submit driver just because precheck kept them.
5. Report per board: sourced / fresh / dropped (tracked, precheck, duplicate) / status, then the queued total against N.

## Pitfalls

- Do not stop on a preflight `DONE` when the user's number refers to queue rows. Only `HOLD` stops an apply run; a sourcing run with an explicit N overrides the applied-count gate.
- Do not hand-write a scraper or a `sort -u` funnel to reach N. Add a board/query row to `searches.csv` and rerun the shipped pipeline instead.
- Never count `Applied?` rows as `Applied`; report strict tracker counts only.
