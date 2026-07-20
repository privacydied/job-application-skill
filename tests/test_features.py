#!/usr/bin/env python3
"""
test_features.py — regression tests for the feature-roadmap tools (H/N/M/X tiers).

Same posture as test_core.py: no browser (cfx stubbed at import), stdlib unittest, pure /
temp-file-isolated logic only. Each case locks in a specific behavior a re-break would
otherwise ship silently.

    python3 tests/test_features.py   # or: python3 -m unittest -v tests.test_features
"""
import contextlib
import json
import os
import sys
import tempfile
import types
import unittest

_REAL_STDOUT = sys.stdout
# Silence noisy CLI prints when run via `python -m unittest` (which doesn't capture stdout).
# Under pytest, do NOT reassign sys.stdout — pytest already captures output, and swapping it
# fights pytest's fd-capture, raising "I/O operation on closed file" at every test's capture
# teardown (the 61 spurious errors). pytest's own capture keeps the tests quiet.
_UNDER_PYTEST = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ


def setUpModule():
    global _REAL_STDOUT
    if not _UNDER_PYTEST:
        _REAL_STDOUT = sys.stdout
        sys.stdout = open(os.devnull, "w")


def tearDownModule():
    if not _UNDER_PYTEST:
        try:
            sys.stdout.close()
        finally:
            sys.stdout = _REAL_STDOUT


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_ROOT, "sites", "_common", "scripts")
sys.path.insert(0, _SCRIPTS)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

# stub cfx (some modules import it lazily; stub keeps import-time safe + deterministic)
_cfx = types.ModuleType("cfx")
_cfx.CfxError = type("CfxError", (RuntimeError,), {})
_cfx.health_fingerprint = lambda *a, **k: {"degraded": None, "browser_connected": None}
_cfx.evaluate = lambda *a, **k: None
sys.modules.setdefault("cfx", _cfx)
_st = types.ModuleType("stagetimer")
_st.timed = lambda *a, **k: contextlib.nullcontext()
sys.modules.setdefault("stagetimer", _st)

import accounts          # noqa: E402
import journal           # noqa: E402
import tracker_stats     # noqa: E402
import verdicts          # noqa: E402
import blockers          # noqa: E402
import quirks            # noqa: E402
import merge_sources     # noqa: E402
import screener          # noqa: E402
import fit_score         # noqa: E402
import outcomes          # noqa: E402
import statedb           # noqa: E402
import state_view        # noqa: E402
import email_ingest      # noqa: E402


class TestAccounts(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        accounts.CSV = os.path.join(self.d, "accounts-needed.csv")
        accounts.SEEN = os.path.join(self.d, ".accounts-postings.csv")

    def test_distinct_posting_count_and_ranking(self):
        accounts.record("amazon-jobs", board="wttj", est_inventory=186, posting="j1")
        accounts.record("amazon-jobs", board="adzuna", posting="j2")
        accounts.record("amazon-jobs", board="adzuna", posting="j1")  # dup -> no double count
        accounts.record("cvlibrary", posting="c1")
        r = accounts.ranked()
        self.assertEqual(r[0]["ats"], "amazon-jobs")
        self.assertEqual(int(r[0]["blocked_count"]), 2, "distinct postings only")
        self.assertEqual(int(r[0]["est_inventory"]), 186)

    def test_resolve_removes_row(self):
        accounts.record("totaljobs", posting="t1")
        self.assertTrue(accounts.resolve("totaljobs"))
        self.assertFalse(any(x["ats"] == "totaljobs" for x in accounts.ranked()))


class TestJournal(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        journal.APPS = self.d

    def test_state_progression_and_submitted_unconfirmed(self):
        s = "acme-ux-designer"
        journal.record(s, "opened", url="http://x")
        journal.record(s, "filled", step="contact")
        journal.record(s, "submitted")
        self.assertEqual(journal.last_state(s), "submitted")
        self.assertTrue(journal.is_submitted_unconfirmed(s))
        self.assertFalse(journal.is_confirmed(s))
        journal.record(s, "confirmed", proof="confirmation.png")
        self.assertEqual(journal.last_state(s), "confirmed")
        self.assertFalse(journal.is_submitted_unconfirmed(s))
        self.assertTrue(journal.is_confirmed(s))

    def test_last_state_terminal_is_not_sticky_after_progress(self):
        # A posting blocked on first attempt, then retried into forward progress, must
        # report its forward state — a once-seen `blocked` must NOT stay sticky.
        s = "gamma-blocked-then-progress"
        journal.record(s, "blocked", reason="hCaptcha")
        self.assertEqual(journal.last_state(s), "blocked")
        journal.record(s, "opened", url="http://x")
        journal.record(s, "filled", step="contact")
        journal.record(s, "submitted")
        self.assertEqual(journal.last_state(s), "submitted")
        # But a terminal marker that IS the last meaningful event stays reported.
        journal.record(s, "blocked", reason="hCaptcha again")
        self.assertEqual(journal.last_state(s), "blocked")

    def test_attempts_counter(self):
        s = "beta-role"
        journal.record(s, "opened")
        journal.record(s, "attempt", note="no progress")
        journal.record(s, "attempt", note="no progress")
        self.assertEqual(journal.attempts(s), 2)


class TestTrackerStats(unittest.TestCase):
    def _tracker(self, rows):
        fd, p = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", newline="") as f:
            f.write("Date,Company,Role,Source,URL,Status,Next Action,Notes\n")
            for d, c, r, s in rows:
                f.write(f"{d},{c},{r},src,http://x,{s},,\n")
        return p

    def test_strict_vs_loose(self):
        p = self._tracker([("2026-07-17", "A", "UX", "Applied"),
                           ("2026-07-17", "B", "UX", "Applied?"),
                           ("2026-07-16", "C", "UX", "Applied"),
                           ("2026-07-17", "D", "UX", "Skipped")])
        s = tracker_stats.stats(path=p, day="2026-07-17")
        self.assertEqual(s["applied"], 2, "strict excludes Applied?")
        self.assertEqual(s["applied_today"], 1)
        self.assertEqual(s["loose_applied"], 3, "loose grep-style includes Applied?")
        os.unlink(p)


class TestVerdicts(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        verdicts.VERDICTS = os.path.join(self.d, "verdicts.jsonl")
        verdicts.REVALIDATE = os.path.join(self.d, "revalidate.jsonl")

    def test_degraded_is_suspect_and_enqueued(self):
        res = verdicts.stamp("external-route", "http://x/1", "no apply button",
                             fp={"degraded": True})
        self.assertTrue(res["suspect"])
        self.assertEqual(len(verdicts.pending()), 1)

    def test_healthy_verdict_not_suspect(self):
        res = verdicts.stamp("exhausted", "reed", "0 fresh",
                             fp={"degraded": False, "blank_render": False})
        self.assertFalse(res["suspect"])
        self.assertEqual(len(verdicts.pending()), 0)

    def test_blank_render_page_verdict_suspect(self):
        res = verdicts.stamp("no-apply-button", "http://x/2", "",
                             fp={"degraded": False, "blank_render": True})
        self.assertTrue(res["suspect"], "blank render on a page-verdict is suspect")

    def test_resolve_clears_pending(self):
        r = verdicts.stamp("wedge", "cvlibrary", "", fp={"degraded": True})
        self.assertTrue(verdicts.resolve(r["id"], "reversed"))
        self.assertEqual(len(verdicts.pending()), 0)


class TestBlockers(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        blockers.BLOCKERS = os.path.join(self.d, "blockers.jsonl")
        journal.APPS = os.path.join(self.d, "applications")
        os.environ.pop("NOTIFY_CMD", None)  # keep notify a no-op

    def test_record_resolve_resumable(self):
        bid = blockers.record("account", "amazon.jobs", company="Amazon", role="UX Designer",
                              what="account needed")
        self.assertEqual(len(blockers.pending()), 1)
        self.assertTrue(blockers.resolve(bid, "created account"))
        self.assertEqual(len(blockers.pending()), 0)
        # resolved + not confirmed -> resumable
        self.assertEqual(len(blockers.resumable()), 1)
        # once confirmed, it drops out of the resume list
        journal.record("amazon-ux-designer", "confirmed", proof="p.png")
        self.assertEqual(len(blockers.resumable()), 0)


class TestQuirks(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        quirks.SITES = self.d
        os.makedirs(os.path.join(self.d, "reed"))

    def test_add_get_and_staleness(self):
        quirks.add("reed", "sym1", "fix1", verified="2026-07-17")
        quirks.add("reed", "sym2", "fix2", verified="2020-01-01")  # old
        got = quirks.get("reed")
        self.assertEqual(len(got), 2)
        from datetime import datetime
        stale = quirks.stale(now=datetime(2026, 7, 17), max_age_days=45)
        syms = {q["symptom"] for _b, q, _w in stale}
        self.assertIn("sym2", syms)
        self.assertNotIn("sym1", syms)


class TestMergeFingerprint(unittest.TestCase):
    def test_company_suffix_normalized(self):
        a = merge_sources.fingerprint({"company": "Acme Ltd", "title": "UX Designer", "location": "London"})
        b = merge_sources.fingerprint({"company": "Acme Limited", "title": "UX Designer", "location": "London, UK"})
        self.assertEqual(a, b, "Ltd/Limited must fingerprint identically")

    def test_seniority_stays_distinct(self):
        a = merge_sources.fingerprint({"company": "Acme", "title": "UX Designer", "location": "London"})
        b = merge_sources.fingerprint({"company": "Acme", "title": "Senior UX Designer", "location": "London"})
        self.assertNotEqual(a, b)

    def test_cross_board_collapse_keeps_alt_url(self):
        posts = [
            {"id": "1", "url": "https://www.reed.co.uk/jobs/ux/11111111", "title": "UX Designer",
             "company": "Acme Ltd", "location": "London"},
            {"id": "2", "url": "https://www.linkedin.com/jobs/view/4440000001", "title": "UX Designer",
             "company": "Acme Limited", "location": "London, UK"},
        ]
        out, stats = merge_sources.merge_lists(posts, cross_board=True)
        self.assertEqual(len(out), 1)
        self.assertEqual(stats["fuzzy_dropped"], 1)
        self.assertIn("linkedin.com", (out[0].get("_dup_urls") or [""])[0])

    def test_cross_board_off_by_default(self):
        posts = [
            {"id": "1", "url": "https://www.reed.co.uk/jobs/ux/11111111", "title": "UX Designer",
             "company": "Acme Ltd", "location": "London"},
            {"id": "2", "url": "https://www.linkedin.com/jobs/view/4440000001", "title": "UX Designer",
             "company": "Acme Limited", "location": "London"},
        ]
        out, _ = merge_sources.merge_lists(posts)  # default cross_board=False
        self.assertEqual(len(out), 2, "id-only dedup keeps both when cross_board off")


class TestScreenerTriage(unittest.TestCase):
    def test_classify_eligibility_vs_teachable(self):
        self.assertEqual(screener.classify_question("Are you a recent graduate (2026)?"), "never_teach")
        self.assertEqual(screener.classify_question("Do you have a degree in CS?"), "never_teach")
        self.assertEqual(screener.classify_question("What is your notice period?"), "teachable")
        self.assertEqual(screener.classify_question("Do you require visa sponsorship?"), "teachable")

    def test_triage_aggregates_and_dedups(self):
        fd, p = tempfile.mkstemp(suffix=".log")
        with os.fdopen(fd, "w") as f:
            f.write("BLOCKED_UNANSWERED_REQUIRED: What is your notice period?\n")
            f.write("BLOCKED_UNANSWERED_REQUIRED: What is your notice period?\n")
            f.write("BLOCKED_UNANSWERED_REQUIRED: Are you a recent graduate?\n")
        rows = screener.triage([p])
        os.unlink(p)
        by_q = {r["question"]: r for r in rows}
        self.assertEqual(by_q["What is your notice period?"]["count"], 2)
        self.assertEqual(by_q["Are you a recent graduate?"]["class"], "never_teach")


class TestFitScore(unittest.TestCase):
    def test_neutral_when_no_corpus(self):
        # point the corpus paths at nothing, bust the lru_cache
        fit_score._profile_model.cache_clear()
        old = (fit_score.PROFILE, fit_score.FAMILY_BASES, fit_score.TARGET_ROLES)
        fit_score.PROFILE = fit_score.FAMILY_BASES = fit_score.TARGET_ROLES = "/nonexistent/x"
        try:
            self.assertEqual(fit_score.fit("anything at all"), 0.5)
        finally:
            fit_score.PROFILE, fit_score.FAMILY_BASES, fit_score.TARGET_ROLES = old
            fit_score._profile_model.cache_clear()

    def test_discriminates_with_synthetic_corpus(self):
        fit_score._profile_model.cache_clear()
        fd, p = tempfile.mkstemp(suffix=".md")
        with os.fdopen(fd, "w") as f:
            f.write("UX designer user research figma prototyping accessibility design systems "
                    "interaction wireframe usability london product design")
        old = fit_score.PROFILE
        fit_score.PROFILE = p
        try:
            hi = fit_score.fit("Senior UX Designer figma user research prototyping accessibility")
            lo = fit_score.fit("Registered Nurse ICU ward clinical patient care medication")
            self.assertGreater(hi, lo)
            self.assertGreater(hi, 0.5)
        finally:
            fit_score.PROFILE = old
            fit_score._profile_model.cache_clear()
            os.unlink(p)


class TestEmailIngest(unittest.TestCase):
    def test_alerts_from_html_extracts_board_links(self):
        html = ('<a href="https://www.reed.co.uk/jobs/ux-designer/55667788">UX Designer</a>'
                '<a href="https://track.example/x">unsub</a>'
                '<a href="https://jobicy.com/jobs/149404-x">Product Designer</a>')
        rows = email_ingest.alerts_from_html(html)
        srcs = {r["source"] for r in rows}
        self.assertEqual(srcs, {"email:reed", "email:jobicy"})

    def test_classify_response(self):
        self.assertEqual(email_ingest.classify_response("Invitation to interview for UX", ""), "Interview")
        self.assertEqual(email_ingest.classify_response("We are pleased to offer you", ""), "Offer")
        self.assertEqual(email_ingest.classify_response("Please complete an online assessment", ""), "Assessment")
        self.assertEqual(email_ingest.classify_response("Unfortunately we won't be progressing", ""), "Rejected")
        self.assertIsNone(email_ingest.classify_response("Your weekly newsletter", ""))


class TestOutcomes(unittest.TestCase):
    def test_status_mapping(self):
        self.assertEqual(outcomes._MAP["Interview"], "Interview")
        self.assertEqual(outcomes._MAP["Assessment"], "Phone screen")

    def test_aggregate_on_temp_tracker(self):
        fd, p = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", newline="") as f:
            f.write("Date,Company,Role,Source,URL,Status,Next Action,Notes\n")
            f.write("2026-07-17,A,UX Designer,reed,http://x,Applied,,\n")
            f.write("2026-07-17,B,UX Designer,reed,http://y,Interview,,\n")
        old_t, old_s = outcomes.TRACKER, outcomes.STATS
        outcomes.TRACKER = p
        outcomes.STATS = p + ".stats.csv"
        try:
            rows = outcomes.aggregate()
            reed = next(r for r in rows if r["dimension"] == "board" and r["key"] == "reed")
            self.assertEqual(reed["applied"], 2)
            self.assertEqual(reed["positive"], 1)  # the Interview row
        finally:
            outcomes.TRACKER, outcomes.STATS = old_t, old_s
            for f in (p, p + ".stats.csv"):
                if os.path.exists(f):
                    os.unlink(f)


class TestStateDb(unittest.TestCase):
    def test_import_export_roundtrip(self):
        d = tempfile.mkdtemp()
        old_db, old_root = statedb.DB, statedb._ROOT
        statedb.DB = os.path.join(d, "state.db")
        statedb._ROOT = d
        # write a screener CSV to import
        with open(os.path.join(d, "screener-answers.csv"), "w", newline="") as f:
            f.write("pattern,kind,answer,source\n")
            f.write("notice period,select,Immediately,profile\n")
        try:
            counts = statedb.import_csvs()
            self.assertEqual(counts["screener"], 1)
            out = os.path.join(d, "export.csv")
            statedb.export("screener", out)
            body = open(out).read()
            self.assertIn("notice period", body)
            self.assertIn("Immediately", body)
        finally:
            statedb.DB, statedb._ROOT = old_db, old_root


class TestStateView(unittest.TestCase):
    def test_compute_returns_expected_keys(self):
        st = state_view.compute()
        for k in ("applied_strict", "queue", "cooldowns_active", "blockers_open",
                  "suspect_verdicts", "accounts_needed_top"):
            self.assertIn(k, st)
        self.assertIn("depth", st["queue"])


class TestNewFeeds(unittest.TestCase):
    """The new keyless-feed normalize() functions are pure — screen a raw API row."""
    def _load(self, path):
        import importlib.util
        spec = importlib.util.spec_from_file_location("feedmod_" + os.path.basename(os.path.dirname(path)), path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_remotive_normalize_uk_keep_usa_drop(self):
        m = self._load(os.path.join(_ROOT, "sites", "remotive.com", "scripts", "feed.py"))
        keep = m.normalize({"id": 1, "url": "https://remotive.com/remote-jobs/design/ux-1",
                            "title": "UX Designer", "company_name": "Acme",
                            "candidate_required_location": "UK"}, {"europe": False})
        self.assertIsNotNone(keep)
        drop = m.normalize({"id": 2, "url": "https://remotive.com/remote-jobs/design/ux-2",
                            "title": "UX Designer", "company_name": "Acme",
                            "candidate_required_location": "USA Only"}, {"europe": False})
        self.assertIsNone(drop)

    def test_jobicy_normalize_geo_filter(self):
        m = self._load(os.path.join(_ROOT, "sites", "jobicy.com", "scripts", "feed.py"))
        keep = m.normalize({"id": 3, "url": "https://jobicy.com/jobs/3-x", "jobTitle": "Designer",
                            "companyName": "X", "jobGeo": "United Kingdom"}, {"europe": False})
        self.assertIsNotNone(keep)
        drop = m.normalize({"id": 4, "url": "https://jobicy.com/jobs/4-x", "jobTitle": "Designer",
                            "companyName": "X", "jobGeo": "USA"}, {"europe": False})
        self.assertIsNone(drop)

    def test_hn_normalize_requires_remote_or_london_and_role(self):
        m = self._load(os.path.join(_ROOT, "sites", "news.ycombinator.com", "scripts", "feed.py"))
        keep = m.normalize({"id": 5, "text": "Acme | UX Designer | London | full-time"}, {"what": "all"})
        self.assertIsNotNone(keep)
        self.assertEqual(keep["location"], "London")
        # no remote/london context -> dropped
        drop = m.normalize({"id": 6, "text": "Acme | UX Designer | onsite NYC only"}, {"what": "all"})
        self.assertIsNone(drop)


class TestScrubPII(unittest.TestCase):
    """The PII-guard scrubber (wired into loop-preflight): replaces the applicant's real
    tokens with placeholders in tracked files, and is itself PII-free."""
    def setUp(self):
        sys.path.insert(0, os.path.join(_ROOT, "scripts"))
        import scrub_pii  # noqa: E402
        self.m = scrub_pii
        self.fill = json.load(open(os.path.join(_ROOT, "sites", "_common", "apply-defaults.json"),
                                   encoding="utf-8"))["fill"]

    def test_replacements_placeholderize(self):
        reps = self.m.build_replacements()
        self.assertTrue(reps, "should derive replacements from the config")
        real = f"{self.fill['Full name']} <{self.fill['Email']}> first {self.fill['First name']}"
        out = real
        for rx, ph in reps:
            out = rx.sub(ph, out)
        self.assertIn("Jane Doe", out)
        self.assertIn("you@example.com", out)
        self.assertNotIn(self.fill["Last name"], out, "real surname must be scrubbed")
        self.assertNotIn(self.fill["Email"], out, "real email must be scrubbed")

    def test_scrubber_source_is_pii_free(self):
        """scrub_pii.py is TRACKED — it must hardcode only placeholders, never the real
        values (it reads those from the gitignored config at runtime)."""
        src = open(os.path.join(_ROOT, "scripts", "scrub_pii.py"), encoding="utf-8").read()
        for key in ("First name", "Last name", "Email"):
            val = self.fill.get(key, "")
            if val:
                self.assertNotIn(val, src, f"scrub_pii.py must not hardcode the real {key}")


class TestPipelineDemandAndConcurrency(unittest.TestCase):
    """#2 demand-driven min-queue gate + #3 off-tab HTTP concurrency classification."""

    def setUp(self):
        import pipeline
        self.pipeline = pipeline

    def _set_env(self, **kv):
        for k, v in kv.items():
            old = os.environ.get(k)
            self.addCleanup(lambda k=k, old=old:
                            os.environ.__setitem__(k, old) if old is not None
                            else os.environ.pop(k, None))
            os.environ[k] = v

    def test_queue_depth_counts_nonblank_lines(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write('{"a":1}\n\n   \n{"b":2}\n')
            p = f.name
        self.addCleanup(os.unlink, p)
        self.assertEqual(self.pipeline.queue_depth(p), 2)
        self.assertEqual(self.pipeline.queue_depth("/no/such/file.jsonl"), 0)

    def test_http_only_boards_exclude_browser_bound(self):
        # cfx-only and auto-fallback boards must NEVER be in the concurrent off-tab set,
        # or a concurrent pass could open a second camofox tab and wedge the backend.
        for b in ("csj", "linkedin", "hackney", "wttj", "mi5", "mi6",
                  "indeed", "reed", "nhs", "guardian", "dezeen", "gchq", "parliament"):
            self.assertNotIn(b, self.pipeline.HTTP_ONLY_BOARDS, f"{b} must stay on-tab")
        for b in ("adzuna", "atsdirect", "remotive", "himalayas", "jobicy"):
            self.assertIn(b, self.pipeline.HTTP_ONLY_BOARDS)

    def test_scrubbed_env_strips_cfx_creds(self):
        self._set_env(CFX_KEY="secret", CFX_TAB="tabid")
        e = self.pipeline._scrubbed_env()
        self.assertNotIn("CFX_KEY", e)
        self.assertNotIn("CFX_TAB", e)
        # a non-CFX var is preserved
        self.assertEqual(e.get("PATH"), os.environ.get("PATH"))

    def test_min_queue_gate_short_circuits_without_planning(self):
        # Queue already deep => run() returns skipped_sourcing WITHOUT calling sp.plan
        # (so it never opens a browser). Force bypasses the gate.
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            for i in range(5):
                f.write('{"i":%d}\n' % i)
            p = f.name
        self.addCleanup(os.unlink, p)
        planned = {"n": 0}
        saved = self.pipeline.sp.plan
        self.pipeline.sp.plan = lambda *a, **k: planned.__setitem__("n", planned["n"] + 1) or \
            {"verdict": "SLEEP"}
        try:
            res, code = self.pipeline.run(min_queue=3, out_path=p)
            self.assertEqual(code, 0)
            self.assertTrue(res["counts"].get("skipped_sourcing"))
            self.assertEqual(planned["n"], 0, "gate must skip planning entirely")
            # below the threshold, the gate does NOT fire (planning proceeds)
            self.pipeline.run(min_queue=99, out_path=p)
            self.assertEqual(planned["n"], 1)
        finally:
            self.pipeline.sp.plan = saved


class TestCfxTabGuardAndSync(unittest.TestCase):
    """#4 tab-budget prune guard + #5 canonical tab-pointer sync (real cfx, no browser)."""

    def _real_cfx(self):
        # test_features stubs `cfx`; load the REAL module from its file so we exercise the
        # actual prune/sync logic. No browser is touched — list_tabs/close_tab are patched.
        import importlib.util
        path = os.path.join(_SCRIPTS, "cfx.py")
        spec = importlib.util.spec_from_file_location("cfx_real_test", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_prune_reaps_oldest_and_never_the_active_tab(self):
        cfx = self._real_cfx()
        tabs = [f"t{i}" for i in range(1, 9)]   # 8 live, budget 7 -> must free room for 1 more
        closed = []
        cfx.list_tabs = lambda: [{"tabId": t} for t in tabs]
        cfx.close_tab = lambda t: closed.append(t)
        got = cfx.prune_tabs(budget=7, keep="t1")
        # excess = 8 - (7-1) = 2; reap 2 oldest that aren't the active tab (t1) -> t2,t3
        self.assertEqual(got, ["t2", "t3"])
        self.assertNotIn("t1", got)

    def test_prune_is_noop_under_budget(self):
        cfx = self._real_cfx()
        cfx.list_tabs = lambda: [{"tabId": "a"}, {"tabId": "b"}]
        cfx.close_tab = lambda t: self.fail("must not close under budget")
        self.assertEqual(cfx.prune_tabs(budget=7), [])

    def test_sync_tab_writes_complete_export_blocks(self):
        cfx = self._real_cfx()
        d = tempfile.mkdtemp()
        cfx._ROOT = d                       # keep the built-in pointer set off the REAL root
        os.environ.pop("CFX_TAB_FILE", None)
        os.environ.pop("CFX_TAB_FILES", None)
        old_key = os.environ.get("CFX_KEY")
        os.environ["CFX_KEY"] = "KEY123"
        self.addCleanup(lambda: os.environ.__setitem__("CFX_KEY", old_key)
                        if old_key is not None else os.environ.pop("CFX_KEY", None))
        f1, f2 = os.path.join(d, "p1"), os.path.join(d, "p2")
        written = cfx.sync_tab(tab_id="TAB999", extra_files=[f1, f2])
        self.assertIn(f1, written)
        self.assertIn(f2, written)
        body = open(f1, encoding="utf-8").read()
        self.assertIn('CFX_TAB="TAB999"', body)
        self.assertIn('CFX_KEY="KEY123"', body)   # never a half-written keyless file


class TestHumanQueue(unittest.TestCase):
    """#1 coalesced human worklist — pure matchers + the leverage-sorted invariant."""

    def setUp(self):
        import human_queue
        self.hq = human_queue

    def test_site_matching_is_loose_both_ways(self):
        self.assertTrue(self.hq._site_matches("guardian", "jobs.theguardian.com"))
        self.assertTrue(self.hq._site_matches("https://jobs.theguardian.com/x", "guardian"))
        self.assertTrue(self.hq._site_matches("tfl", "tfl.gov.uk"))
        self.assertFalse(self.hq._site_matches("tfl", "adzuna.co.uk"))
        self.assertFalse(self.hq._site_matches("", "anything"))

    def test_worklist_is_sorted_by_unlocks_desc(self):
        # Runs against real (read-only) state; asserts the invariant, not any count.
        wl = self.hq.build_worklist()
        self.assertIsInstance(wl, list)
        unlocks = [int(i.get("unlocks") or 0) for i in wl]
        self.assertEqual(unlocks, sorted(unlocks, reverse=True))
        for item in wl:
            for key in ("kind", "target", "unlocks", "action", "resolve"):
                self.assertIn(key, item)


class TestPrerenderQueue(unittest.TestCase):
    """#6 async pre-render — pure staleness + queue-read helpers (no render subprocess)."""

    def setUp(self):
        import prerender_queue
        self.pr = prerender_queue

    def test_needs_render_staleness(self):
        d = tempfile.mkdtemp()
        html = os.path.join(d, "resume.html")
        pdf = os.path.join(d, "resume.pdf")
        self.assertFalse(self.pr._needs_render(d))           # no html -> nothing to render
        open(html, "w").close()
        self.assertTrue(self.pr._needs_render(d))            # html, no pdf -> render
        open(pdf, "w").close()
        os.utime(pdf, (10, 10))
        os.utime(html, (20, 20))                             # html newer than pdf -> stale
        self.assertTrue(self.pr._needs_render(d))
        os.utime(pdf, (30, 30))                              # pdf newer -> fresh
        self.assertFalse(self.pr._needs_render(d))

    def test_read_queue_skips_bad_lines(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write('{"family":"design"}\nnot-json\n\n{"family":"ai"}\n')
            p = f.name
        self.addCleanup(os.unlink, p)
        rows = self.pr._read_queue(p)
        self.assertEqual([r["family"] for r in rows], ["design", "ai"])


class _FakeCfx:
    """A scripted cfx stand-in for the combobox ladder tests. It routes each JS template to a
    recorded-style response (the way a real widget would answer), and records every press /
    click_selector so a test can assert WHICH ladder rung fired. `opts` is a queue of
    READ_OPTS responses consumed one per rung — the DOM-fixture: recorded menu states."""
    CfxError = type("CfxError", (RuntimeError,), {})

    def __init__(self, resolve='{"kind":"none"}', opts=None, click="OK:X", native="OK:X"):
        self.resolve, self.opts = resolve, list(opts or [])
        self.click, self.native = click, native
        self.presses, self.clicks, self.evals = [], [], []

    def evaluate(self, expr, *a, **k):
        self.evals.append(expr)
        if "isMulti" in expr:                        # _COMBO_RESOLVE
            return self.resolve
        if "HTMLSelectElement" in expr:              # _COMBO_NATIVE_SET
            return self.native
        if "NO_OPTION:" in expr:                     # _COMBO_CLICK (terminal)
            return self.click
        if "slice(0,80)" in expr:                    # _COMBO_READ_OPTS
            return self.opts.pop(0) if self.opts else "[]"
        if "multi-value__remove" in expr:            # _COMBO_CLEAR_CHIPS
            return 2
        return ""                                    # focus / pointer-open / close

    def poll(self, expr, predicate=None, **k):
        return None                                  # value is read via _combo_options next

    def press(self, key, *a, **k):
        self.presses.append(key)

    def click_selector(self, sel, *a, **k):
        self.clicks.append(sel)


class TestComboboxLadder(unittest.TestCase):
    """DOM-fixture regression tests for the ONE combobox engine (atsform.combobox_pick) —
    exercises the resolve→branch decision and the open LADDER offline against recorded widget
    responses, so a refactor can't silently re-break Greenhouse/Lever/Ashby driving."""

    def setUp(self):
        import atsform
        self.atsform = atsform
        self._real_cfx = atsform.cfx
        self._real_sleep = atsform.time.sleep
        atsform.time.sleep = lambda *a, **k: None    # keep the ladder tests fast

    def tearDown(self):
        self.atsform.cfx = self._real_cfx
        self.atsform.time.sleep = self._real_sleep

    def _use(self, fake):
        self.atsform.cfx = fake
        return fake

    def test_none_returns_notfound_or_fail(self):
        self._use(_FakeCfx(resolve='{"kind":"none"}'))
        self.assertEqual(self.atsform.combobox_pick("nope", "x", quiet_notfound=True),
                         self.atsform.NOTFOUND)
        self._use(_FakeCfx(resolve='{"kind":"none"}'))
        self.assertEqual(self.atsform.combobox_pick("nope", "x"), 1)

    def test_native_select_path(self):
        f = self._use(_FakeCfx(resolve='{"kind":"native","current":[]}', native="OK:United States"))
        self.assertEqual(self.atsform.combobox_pick("Country", "United States"), 0)
        self.assertTrue(any("HTMLSelectElement" in e for e in f.evals), "native setter must run")
        self.assertEqual(f.presses, [], "native path must not use keyboard")

    def test_idempotent_skip_no_interaction(self):
        f = self._use(_FakeCfx(resolve='{"kind":"combo","current":["no"],"isMulti":false}'))
        self.assertEqual(self.atsform.combobox_pick("Visa", "No"), 0)
        self.assertEqual(f.presses, [])
        self.assertEqual(f.clicks, [])
        self.assertFalse(any("NO_OPTION:" in e for e in f.evals), "must not open/click when already set")

    def test_pointer_rung_wins_no_arrowdown(self):
        f = self._use(_FakeCfx(resolve='{"kind":"combo","current":[],"isMulti":false}',
                               opts=['["Yes","No"]'], click="OK:No"))
        self.assertEqual(self.atsform.combobox_pick("Visa", "No"), 0)
        self.assertNotIn("ArrowDown", f.presses, "pointer opened it — ladder must stop before ArrowDown")

    def test_arrowdown_rung_when_pointer_empty(self):
        f = self._use(_FakeCfx(resolve='{"kind":"combo","current":[],"isMulti":false}',
                               opts=['[]', '["Yes","No"]'], click="OK:No"))
        self.assertEqual(self.atsform.combobox_pick("Visa", "No"), 0)
        self.assertIn("ArrowDown", f.presses, "pointer yielded nothing — must escalate to ArrowDown")

    def test_typeahead_filter_rung(self):
        f = self._use(_FakeCfx(resolve='{"kind":"combo","current":[],"isMulti":false}',
                               opts=['[]', '[]', '[]', '["United Kingdom +44"]'],
                               click="OK:United Kingdom +44"))
        self.assertEqual(self.atsform.combobox_pick("Country", "United Kingdom"), 0)
        # rungs 1-3 empty → type-to-filter fires real per-char keystrokes
        self.assertIn("U", f.presses)
        self.assertGreater(len([p for p in f.presses if len(p) == 1]), 3)

    def test_no_match_anywhere_fails(self):
        self._use(_FakeCfx(resolve='{"kind":"combo","current":[],"isMulti":false}',
                           opts=['["Yes","No"]'], click="NO_OPTION:Yes | No"))
        self.assertEqual(self.atsform.combobox_pick("Visa", "Maybe"), 1)

    def test_word_boundary_no_midword_match(self):
        # "No" must NOT match "Norway"/"Monaco" (mid-word) — ladder finds nothing → fail,
        # instead of the old `includes` matcher wrongly stopping on "Norway".
        self._use(_FakeCfx(resolve='{"kind":"combo","current":[],"isMulti":false}',
                           opts=['["Norway","Monaco"]', '["Norway","Monaco"]',
                                 '["Norway","Monaco"]', '["Norway","Monaco"]'],
                           click="NO_OPTION:Norway | Monaco"))
        self.assertEqual(self.atsform.combobox_pick("Country", "No"), 1)

    def test_word_boundary_phrase_match(self):
        # exact fails but the whole phrase matches at a boundary → stop on rung 1, commit.
        f = self._use(_FakeCfx(resolve='{"kind":"combo","current":[],"isMulti":false}',
                               opts=['["United Kingdom +44","United States +1"]'],
                               click="OK:United Kingdom +44"))
        self.assertEqual(self.atsform.combobox_pick("Country", "United Kingdom"), 0)
        self.assertNotIn("ArrowDown", f.presses, "phrase matched on rung 1 — no escalation")

    def test_multi_clear_first_removes_chips(self):
        f = self._use(_FakeCfx(resolve='{"kind":"combo","current":["i don\'t wish to answer"],"isMulti":true}',
                               opts=['["Man"]'], click="OK:Man"))
        self.assertEqual(self.atsform.combobox_pick("gender identity", "Man",
                                                    multi=True, clear_first=True), 0)
        self.assertTrue(any("multi-value__remove" in e for e in f.evals),
                        "clear_first must remove existing chips before selecting")


if __name__ == "__main__":
    unittest.main(verbosity=2)
