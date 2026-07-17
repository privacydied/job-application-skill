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


def setUpModule():
    sys.stdout = open(os.devnull, "w")


def tearDownModule():
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
        import json
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
