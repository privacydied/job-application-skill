#!/usr/bin/env python3
"""
test_core.py — regression tests for the pure/stubbable logic the apply loop trusts.

No browser, no external deps (stdlib unittest, Python 3.8+):

    python3 tests/test_core.py            # or: python3 -m unittest -v tests.test_core

WHY THIS EXISTS: the deterministic core — title eligibility, the precheck screen
(location / seniority / CSJ-grade), the board-cooldown roundtrip, the jd/precheck
shared city list, and atsform.fill idempotency — was each verified once with a
throwaway script and then only guarded by prose. A re-break now FAILS here instead
of silently shipping. Every case below locks in a specific fix (noted inline).

The browser layer (cfx) is stubbed at import time so atsform/jd load without a live
camofox; the pure modules (check_title/precheck/board_cooldown) don't import cfx.
"""
import contextlib
import os
import sys
import tempfile
import types
import unittest

# The functions under test print status lines to stdout ("OK= fill …", "REVIEW …").
# Silence stdout for the run so the output is just the unittest summary — failures
# still surface (unittest writes results to stderr). Restored after the module.
_REAL_STDOUT = sys.stdout


def setUpModule():
    sys.stdout = open(os.devnull, "w")


def tearDownModule():
    try:
        sys.stdout.close()
    finally:
        sys.stdout = _REAL_STDOUT

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_HERE, "..", "sites", "_common", "scripts")
sys.path.insert(0, _SCRIPTS)

# --- stub the browser layer BEFORE importing atsform/jd -----------------------
_cfx = types.ModuleType("cfx")
_cfx.CfxError = type("CfxError", (RuntimeError,), {})
_cfx._uid = lambda: "nasirjones"
_cfx._tab = lambda explicit=None: "TAB"
_cfx.evaluate = lambda *a, **k: None
_cfx.post = lambda *a, **k: {}
sys.modules["cfx"] = _cfx
_st = types.ModuleType("stagetimer")
_st.timed = lambda *a, **k: contextlib.nullcontext()
sys.modules["stagetimer"] = _st

import check_title            # noqa: E402
import board_cooldown as bc   # noqa: E402
import precheck               # noqa: E402


class TestCheckTitle(unittest.TestCase):
    def test_on_profile_tiers(self):
        self.assertTrue(check_title.check_title("Product Designer")["eligible"])
        self.assertTrue(check_title.check_title("Design Engineer")["eligible"])
        self.assertEqual(check_title.check_title("Product Designer")["tier"], "A")

    def test_seniority_flag(self):
        r = check_title.check_title("Senior Product Designer")
        self.assertTrue(r["eligible"])         # still matches a tier phrase
        self.assertTrue(r["seniority_flag"])   # but flagged as senior

    def test_off_profile(self):
        self.assertFalse(check_title.check_title("Warehouse Operative")["eligible"])
        self.assertFalse(check_title.check_title("Chief Financial Officer")["eligible"])

    def test_industrial_design_engineer_excluded(self):
        # Real gap (2026-07-15): these all CONTAIN the Tier-A phrase "design engineer"
        # but are industrial/CAD roles — must be excluded, not padded into the count.
        for t in ("Electrical Design Engineer", "ICT Design Engineer",
                  "Mechanical Design Engineer", "CAD Design Engineer",
                  "RF Design Engineer", "Systems Design Engineer",
                  "Structural Design Engineer"):
            r = check_title.check_title(t)
            self.assertFalse(r["eligible"], f"{t} should be off-profile")
            self.assertTrue(r["discipline_flag"], f"{t} should set discipline_flag")

    def test_design_engineer_keeps_bare_and_ux_hybrids(self):
        # Bare "Design Engineer" stays Tier A (his literal positioning); a UX/creative
        # signal rescues a hybrid; unrelated IT/support titles are untouched.
        for t in ("Design Engineer", "UX Design Engineer",
                  "Product Design Engineer", "Field Service Engineer",
                  "IT Support Technician"):
            self.assertTrue(check_title.check_title(t)["eligible"],
                            f"{t} should stay on-profile")

    def test_memoized_immutable(self):
        # iter-3: parse_target_roles is lru_cache'd -> identical cached object, and a
        # tuple (immutable) so a caller can't mutate the shared result.
        a = check_title.parse_target_roles()
        b = check_title.parse_target_roles()
        self.assertIs(a, b)
        self.assertIsInstance(a, tuple)


class TestNoDivergentTitleScreen(unittest.TestCase):
    """P0.2: title-eligibility word lists must live ONLY in check_title.py. A parallel
    orchestrator (run_pass.py) once re-implemented them, which quietly held the only
    correct discipline filter while the canonical path leaked — this fails the build if
    that class of divergence ever returns."""

    def test_no_reimplemented_title_wordlists(self):
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pat = re.compile(r"^(SENIOR_WORDS|OFF_WORDS|ONPROFILE_HINTS|SENIORITY_WORDS|"
                         r"OFF_PROFILE|OFFPROFILE_HINTS)\s*=", re.M)
        allowed = {os.path.join(root, "sites", "_common", "scripts", "check_title.py")}
        offenders = []
        for dirpath, _dirs, files in os.walk(root):
            if "__pycache__" in dirpath or "/.git" in dirpath or f"{os.sep}tests" in dirpath:
                continue
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                p = os.path.join(dirpath, fn)
                if p in allowed:
                    continue
                try:
                    txt = open(p, encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                if pat.search(txt):
                    offenders.append(os.path.relpath(p, root))
        self.assertEqual(offenders, [], "Title-eligibility word lists must live ONLY in "
                         f"check_title.py (single source of truth). Divergent copies: {offenders}")


class TestBoardCooldown(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        self._tmp.close()
        self._orig_log = bc.LOG
        bc.LOG = self._tmp.name           # never touch the real board-cooldown.csv
    def tearDown(self):
        bc.LOG = self._orig_log
        os.unlink(self._tmp.name)

    def test_mark_roundtrip(self):
        self.assertEqual(bc.remaining_hours("indeed", "ux designer"), 0.0)
        bc.mark("indeed", "ux designer", hours=12)
        self.assertGreater(bc.remaining_hours("indeed", "ux designer"), 11.0)
        self.assertEqual(bc.remaining_hours("indeed", "different query"), 0.0)

    def test_norm(self):
        self.assertEqual(bc.norm("UX  Designer"), "ux_designer")

    def test_norm_strips_easy_apply_label(self):
        # searches.csv labels Easy-Apply LinkedIn rows " (Easy Apply)" in the query column,
        # but the nav keyword (what the feed marks cooldown under) does not — the cooldown
        # key MUST ignore the label or preflight checks a different key than the feed marks.
        self.assertEqual(bc.norm('Product Designer (Easy Apply)'), bc.norm('Product Designer'))
        self.assertEqual(bc.norm('X OR Y NOT senior (Easy Apply)'), bc.norm('X OR Y NOT senior'))

    def test_query_from_url(self):
        # iter-19's preflight self-check relies on this matching the feeds' key.
        self.assertEqual(bc.query_from_url("https://uk.indeed.com/jobs?q=UX+Designer&l=London"),
                         "UX Designer")
        self.assertEqual(bc.query_from_url("https://x/jobs?keywords=Product%20Designer"),
                         "Product Designer")
        self.assertEqual(bc.query_from_url("https://x/job-search/"), "")  # path, not a param


class TestPrecheckLocation(unittest.TestCase):
    def v(self, loc):
        return precheck.screen_location(loc)[0]

    def test_london_and_remote_keep(self):
        self.assertEqual(self.v("London"), "keep")
        self.assertEqual(self.v("Remote"), "keep")

    def test_other_uk_city_drops(self):
        self.assertEqual(self.v("Manchester"), "drop")
        self.assertEqual(self.v("Leeds, UK"), "drop")

    def test_new_york_is_not_uk_york(self):
        # the (?<!new )york guard: "New York" must NOT screen as UK-city York
        self.assertNotEqual(self.v("New York, NY"), "drop")

    def test_generic_uk_and_abroad_review(self):
        self.assertEqual(self.v("United Kingdom"), "review")
        self.assertEqual(self.v("Berlin, Germany"), "review")
        self.assertEqual(self.v(""), "review")

    def test_london_substring_false_cognates_not_kept(self):
        # bare `"london" in low` wrongly kept these as commutable London — the same
        # substring-false-cognate class as the industrial-"design engineer" leak.
        self.assertNotEqual(self.v("Londonderry"), "keep")      # Northern Ireland
        self.assertNotEqual(self.v("New London, CT"), "keep")   # USA
        # genuine London variants still keep
        self.assertEqual(self.v("South London"), "keep")
        self.assertEqual(self.v("London Colney"), "keep")       # commuter belt
        self.assertEqual(self.v("Greater London, UK"), "keep")


class TestPrecheckPure(unittest.TestCase):
    def test_salary_band_top(self):
        self.assertEqual(precheck.salary_band_top("£42,665 to £50,495"), 50495)
        self.assertEqual(precheck.salary_band_top("£37,456 - £42,084 p.a."), 42084)
        self.assertIsNone(precheck.salary_band_top("competitive"))

    def test_salary_for_london_substring_guard(self):
        cache = [{"Role": "UX Designer", "Location": "London", "Median": "55000",
                  "Currency": "GBP", "DateChecked": "2026-01-01"}]
        # Londonderry / New London must NOT match the London cache row
        self.assertEqual(precheck.salary_for("UX Designer", "Londonderry", cache), {})
        self.assertEqual(precheck.salary_for("UX Designer", "New London", cache), {})
        # genuine London does attach
        self.assertTrue(precheck.salary_for("UX Designer", "London", cache))

    def test_canon_ids(self):
        self.assertIn("4012345678",
                      precheck.canon_ids("https://www.linkedin.com/jobs/view/4012345678"))
        self.assertIn("abc123", precheck.canon_ids("https://uk.indeed.com/viewjob?jk=abc123"))


class TestPrecheckScreen(unittest.TestCase):
    """Full precheck() with the tracker/salary stubbed so verdicts don't depend on
    the live application-tracker.csv."""
    def setUp(self):
        self._lt, self._ls = precheck.load_tracker, precheck.load_salary_cache
        precheck.load_tracker = lambda: ({}, {})
        precheck.load_salary_cache = lambda: []
    def tearDown(self):
        precheck.load_tracker, precheck.load_salary_cache = self._lt, self._ls

    def test_clean_keep(self):
        out = precheck.precheck([{"title": "Product Designer", "company": "Acme",
                                  "location": "London", "url": "https://ex.com/y/2"}])
        self.assertEqual(len(out["keep"]), 1)

    def test_noncsj_senior_drops(self):
        out = precheck.precheck([{"title": "Senior Product Designer", "company": "Acme",
                                  "location": "London", "url": "https://ex.com/x/1"}])
        self.assertEqual(len(out["drop"]), 1)

    def test_csj_grade_rescue_to_review(self):
        # iter-2 audit: a CSJ target-tier title with a seniority WORD but a junior GRADE
        # (HEO) is rescued to `review`, not dropped as "senior".
        out = precheck.precheck([{
            "title": "Senior Product Designer", "company": "Cabinet Office",
            "location": "London", "grade": "HEO", "salary": "£40,000",
            "url": "https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi?jcode=123"}])
        self.assertEqual(len(out["review"]), 1)
        self.assertEqual(len(out["drop"]), 0)

    def test_csj_senior_grade_drops(self):
        # the flip side: an explicit SENIOR grade (G7) is NOT rescued — stays dropped,
        # so the loop never applies to a genuinely senior CSJ role.
        out = precheck.precheck([{
            "title": "Senior Product Designer", "company": "Cabinet Office",
            "location": "London", "grade": "G7", "salary": "£72,000",
            "url": "https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi?jcode=456"}])
        self.assertEqual(len(out["drop"]), 1)
        self.assertEqual(len(out["review"]), 0)

    def test_tracked_blocked_goes_to_review_not_drop(self):
        # a Blocked posting is RETRYABLE -> review, never silently dropped forever.
        precheck.load_tracker = lambda: ({"999": "Blocked"}, {})
        out = precheck.precheck([{"title": "Product Designer", "company": "Acme",
                                  "location": "London",
                                  "url": "https://www.linkedin.com/jobs/view/999"}])
        self.assertEqual(len(out["review"]), 1)
        self.assertEqual(len(out["drop"]), 0)

    def test_tracked_applied_drops_as_duplicate(self):
        precheck.load_tracker = lambda: ({"999": "Applied"}, {})
        out = precheck.precheck([{"title": "Product Designer", "company": "Acme",
                                  "location": "London",
                                  "url": "https://www.linkedin.com/jobs/view/999"}])
        self.assertEqual(len(out["drop"]), 1)
        self.assertEqual(len(out["review"]), 0)


class TestSharedCityList(unittest.TestCase):
    def test_jd_shares_precheck_cities(self):
        # iter-4: jd imports UK_CITIES from precheck (single source of truth, 22 cities)
        import jd
        self.assertEqual(set(jd.UK_CITIES), set(precheck.UK_CITIES))
        self.assertEqual(len(precheck.UK_CITIES), 22)


class TestAtsformFillIdempotent(unittest.TestCase):
    """iter-7: fill() skips a re-type when the field already holds the target."""
    def setUp(self):
        self.state = {"value": "", "posts": 0}

        def evaluate(expr, *a, **k):
            if "querySelectorAll(kinds)" in expr or "labelText" in expr:
                return '[name="f"]'                      # _resolve -> a selector
            if "return e?e.value:null" in expr:
                return self.state["value"]               # current/readback value
            return None
        _cfx.evaluate = evaluate

        def post(path, body, *a, **k):
            self.state["posts"] += 1
            if path.endswith("/type"):
                self.state["value"] = body["text"]
            return {}
        _cfx.post = post

        # fill() now polls the read-back value (B.3) instead of a fixed sleep; the stub
        # poll evaluates the (mocked) expression and honours the predicate, exactly like
        # the real cfx.poll returning as soon as the value lands.
        def poll(expr, predicate=bool, timeout=0, interval=0, tab=None):
            r = None
            for _ in range(3):
                r = evaluate(expr)
                if predicate(r):
                    return r
            return r
        _cfx.poll = poll

        import atsform
        self.atsform = atsform

    def tearDown(self):
        _cfx.evaluate = lambda *a, **k: None
        _cfx.post = lambda *a, **k: {}
        if hasattr(_cfx, "poll"):
            delattr(_cfx, "poll")

    def test_empty_field_types(self):
        self.state["value"], self.state["posts"] = "", 0
        self.assertEqual(self.atsform.fill("Name", "Jane Doe"), 0)
        self.assertEqual(self.state["posts"], 1)          # actually typed

    def test_already_filled_skips_retype(self):
        self.state["value"], self.state["posts"] = "Jane Doe", 0
        self.assertEqual(self.atsform.fill("Name", "Jane Doe"), 0)
        self.assertEqual(self.state["posts"], 0)          # skipped (no re-type)

    def test_wrong_value_refills(self):
        self.state["value"], self.state["posts"] = "Old Value", 0
        self.assertEqual(self.atsform.fill("Name", "Jane Doe"), 0)
        self.assertEqual(self.state["posts"], 1)          # re-typed to correct it


class TestAtsformDefaultsSkip(unittest.TestCase):
    """E.2: every primitive returns NOTFOUND (silent skip for the defaults path) when
    its field is absent, and a normal rc when present — so _run_defaults needs no
    separate _field_exists pre-probe (one resolve per default, not two/three)."""
    def tearDown(self):
        _cfx.evaluate = lambda *a, **k: None

    def test_absent_fields_return_NOTFOUND(self):
        import atsform

        def ev(expr, *a, **k):
            if "formField-" in expr:
                return "NO_FIELD"          # Workday question field absent
            if "input[type=radio]" in expr or "input[type=checkbox]" in expr:
                return "NOT_FOUND"         # radio/checkbox match JS: none found
            return ""                       # native <select> / react-select probes: absent
        _cfx.evaluate = ev
        self.assertEqual(atsform.select("X", "Y", quiet_notfound=True), atsform.NOTFOUND)
        self.assertEqual(atsform.set_radio("Q", "Yes", quiet_notfound=True), atsform.NOTFOUND)
        self.assertEqual(atsform.set_checkbox("C", "on", quiet_notfound=True), atsform.NOTFOUND)

    def test_present_field_runs_normally(self):
        import atsform
        _cfx.evaluate = lambda expr, *a, **k: "OK checked=True"
        # present → real rc (0), NOT the skip sentinel
        self.assertEqual(atsform.set_checkbox("C", "on", quiet_notfound=True), 0)


class TestAtsformWorkday(unittest.TestCase):
    """Workday's My-Information controls (source multiselect + label-less Yes/No
    radios with value=true/false) are invisible to select()'s native/react-select
    paths and set_radio()'s label match. These Workday fallbacks must drive them
    via a TRUSTED click_selector (synthetic .click() no-ops on Workday). Regression
    here re-blocks every Workday application. See sites/myworkdayjobs/NOTES.md."""
    def setUp(self):
        self.state = {"source_selected": False, "clicks": []}

        def evaluate(expr, *a, **k):
            e = expr
            if "querySelectorAll(kinds)" in e or "labelText" in e:
                return ""                                  # no native <select>
            if "input[role=combobox]" in e:
                return ""                                  # no react-select
            if "multiSelectContainer" in e and "data-ats-target" in e:
                return "1"                                 # Workday multiselect found
            if "promptOption" in e and "map(o=>o.textContent" in e:
                return ["Civil Service Jobs", "Referral"]
            if "data-ats-pick" in e and "MARK" in e:
                self.state["source_selected"] = True
                return "MARK"
            if "selected" in e and "0 items" in e:
                return "OK" if self.state["source_selected"] else "?"
            if "querySelectorAll('input[type=radio]')" in e and "NOT_FOUND" in e:
                return "NOT_FOUND"                          # blank labels -> text match fails
            if "data-ats-radio" in e and "MARK" in e:
                return "MARK"                               # value=true/false found
            return None

        _cfx.evaluate = evaluate
        _cfx.click_selector = lambda sel, *a, **k: self.state["clicks"].append(sel)
        _cfx.poll = lambda *a, **k: None
        _cfx.press = lambda *a, **k: None
        import atsform
        self.atsform = atsform

    def tearDown(self):
        _cfx.evaluate = lambda *a, **k: None
        for n in ("click_selector", "poll", "press"):
            if hasattr(_cfx, n):
                delattr(_cfx, n)

    def test_source_multiselect_selected_via_trusted_click(self):
        self.assertEqual(self.atsform.select("How Did You Hear About Us?", "Civil Service Jobs"), 0)
        self.assertIn('input[data-ats-target="1"]', self.state["clicks"])   # opened via trusted click
        self.assertIn('[data-ats-pick="1"]', self.state["clicks"])          # option picked via trusted click

    def test_yesno_radio_matched_by_value(self):
        self.assertEqual(self.atsform.set_radio("previously worked", "No"), 0)
        self.assertIn('input[data-ats-radio="1"]', self.state["clicks"])    # value=false, trusted click


class TestLogApplicationFindMatch(unittest.TestCase):
    """The tracker is the dedup source of truth; find_match decides update-in-place
    vs append. Same two keys the feeds/precheck dedup on: canonical URL id, then
    normalized Company+Role."""
    @classmethod
    def setUpClass(cls):
        import importlib.util
        p = os.path.join(_SCRIPTS, "log-application.py")   # hyphenated -> load by path
        spec = importlib.util.spec_from_file_location("log_application", p)
        cls.la = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.la)

    def _rows(self):
        return [{"URL": "https://www.linkedin.com/jobs/view/999", "Company": "Acme",
                 "Role": "Product Designer", "Status": "Applied", "Notes": ""}]

    def test_match_by_url_id(self):
        # different company/role text, but same canonical LinkedIn id -> match
        self.assertEqual(self.la.find_match(self._rows(),
                         "https://www.linkedin.com/jobs/view/999?trk=x", "X", "Y"), 0)

    def test_match_by_company_role(self):
        # different URL, but same normalized Company+Role -> match
        self.assertEqual(self.la.find_match(self._rows(),
                         "https://elsewhere.example/job", "acme", "product  designer"), 0)

    def test_no_match(self):
        self.assertEqual(self.la.find_match(self._rows(),
                         "https://elsewhere.example/job", "Beta", "UX Researcher"), -1)


class TestAtsformReviewFailClosed(unittest.TestCase):
    """iter-18: the pre-submit review must FAIL CLOSED (rc!=0) on an unreadable form —
    never traceback, never silently pass an un-reviewed submit."""
    def setUp(self):
        import atsform
        self.atsform = atsform
        self._tc = atsform._tracker_companies
        atsform._tracker_companies = lambda: set()   # deterministic wrong-company check
    def tearDown(self):
        self.atsform._tracker_companies = self._tc
        _cfx.evaluate = lambda *a, **k: None

    def test_none_response_fails_closed(self):
        _cfx.evaluate = lambda *a, **k: None
        self.assertEqual(self.atsform.review("Acme", []), 1)

    def test_cfxerror_fails_closed(self):
        def ev(*a, **k):
            raise _cfx.CfxError("dead tab")
        _cfx.evaluate = ev
        self.assertEqual(self.atsform.review("Acme", []), 1)

    def test_clean_form_passes(self):
        _cfx.evaluate = lambda *a, **k: (
            '{"texts":[{"label":"Name","value":"Jane Doe","required":true,"long":false}],'
            '"emptyRequired":[],"radioGroups":{}}')
        self.assertEqual(self.atsform.review("Acme", []), 0)

    def test_empty_required_flagged(self):
        _cfx.evaluate = lambda *a, **k: (
            '{"texts":[{"label":"Name","value":"","required":true,"long":false}],'
            '"emptyRequired":["text: Name"],"radioGroups":{}}')
        self.assertEqual(self.atsform.review("Acme", []), 1)


class TestDismissModalOpen(unittest.TestCase):
    """iter-17: _open() must not TypeError when evaluate returns None (a resultless
    /evaluate response) — fail-open ('assume no modal')."""
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(_HERE, "..", "sites", "indeed.com", "scripts"))
        import dismiss_modal
        cls.dm = dismiss_modal
    def tearDown(self):
        _cfx.evaluate = lambda *a, **k: None

    def test_none_response_no_crash(self):
        _cfx.evaluate = lambda *a, **k: None
        self.assertFalse(self.dm._open())          # pre-iter17 this raised TypeError

    def test_open_true(self):
        _cfx.evaluate = lambda *a, **k: '{"open": true, "lockedScroll": true}'
        self.assertTrue(self.dm._open())

    def test_open_false(self):
        _cfx.evaluate = lambda *a, **k: '{"open": false}'
        self.assertFalse(self.dm._open())

    def test_non_json_no_crash(self):
        _cfx.evaluate = lambda *a, **k: 'not json'
        self.assertFalse(self.dm._open())


class TestFeedDedup(unittest.TestCase):
    """The feed load_seen_* regexes are the dedup source of truth — a regression here
    causes duplicate applications (a flagged critical failure) or missed dedup. Each
    must extract, from a tracker line, the canonical id its own feed logs. Pure regex
    over a temp CSV; no browser."""
    def _extract(self, relpath, fn_name, tracker_line):
        import importlib.util
        p = os.path.join(_HERE, "..", relpath)
        d = os.path.dirname(p)
        if d not in sys.path:
            sys.path.insert(0, d)
        name = "feeddedup_" + relpath.replace("/", "_")[:-3].replace(".", "_")
        spec = importlib.util.spec_from_file_location(name, p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
        tmp.write(tracker_line + "\n")
        tmp.close()
        orig = mod.TRACKER
        mod.TRACKER = tmp.name
        try:
            return getattr(mod, fn_name)()
        finally:
            mod.TRACKER = orig
            os.unlink(tmp.name)

    def test_indeed_jk(self):
        self.assertIn("a1b2c3", self._extract(
            "sites/indeed.com/scripts/feed.py", "load_seen_jks",
            "Acme,PD,indeed,https://uk.indeed.com/viewjob?jk=a1b2c3,Applied,,"))

    def test_linkedin_id(self):
        self.assertIn("4012345678", self._extract(
            "sites/linkedin/scripts/feed.py", "load_seen_ids",
            "Acme,X,linkedin,https://www.linkedin.com/jobs/view/4012345678,Applied,,"))

    def test_wttj_id_keeps_case(self):
        # WTTJ ids carry uppercase (e.g. NSPehZ_f) — the regex must preserve them
        self.assertIn("NSPehZ_f", self._extract(
            "sites/welcometothejungle/scripts/feed.py", "load_seen_ids",
            "Acme,X,wttj,https://app.welcometothejungle.com/jobs/NSPehZ_f,Applied,,"))

    def test_csj_jcode(self):
        self.assertIn("2003537", self._extract(
            "sites/civilservicejobs/scripts/feed.py", "load_seen_ids",
            "DWP,X,csj,https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi?jcode=2003537,Applied,,"))

    def test_hackney_slug(self):
        self.assertIn("help-desk-operative", self._extract(
            "sites/hackney/scripts/feed.py", "load_seen_slugs",
            "Hackney,X,hackney,https://recruitment.hackney.gov.uk/vacancy/help-desk-operative/,Applied,,"))


class TestSharedScriptsImport(unittest.TestCase):
    """Smoke test: every script in sites/_common/scripts must import cleanly (with the
    browser layer stubbed). Catches the #1 regression — a syntax/NameError/bad-import
    in a core module — across ALL of them, not just the ones unit-tested above. Each is
    loaded under a unique 'smoke_' name so it can't disturb the stubbed cfx or the
    modules the other tests imported."""
    def test_all_common_scripts_import(self):
        import glob
        import importlib.util
        failures = []
        for f in sorted(glob.glob(os.path.join(_SCRIPTS, "*.py"))):
            base = os.path.basename(f)
            name = "smoke_" + base[:-3].replace("-", "_")
            try:
                spec = importlib.util.spec_from_file_location(name, f)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception as e:            # noqa: BLE001 — report which file + why
                failures.append(f"{base}: {type(e).__name__}: {e}")
        self.assertEqual(failures, [], "core scripts failed to import -> " + " | ".join(failures))


class TestCliArgGuards(unittest.TestCase):
    """iter-12/16: numeric CLI args are guarded — a non-numeric value is a clean
    non-zero exit BEFORE any browser call, never a ValueError traceback."""
    def _with_argv(self, argv, fn):
        old = sys.argv
        try:
            sys.argv = argv
            return fn()
        finally:
            sys.argv = old

    def test_jd_bad_max_chars(self):
        import jd
        self.assertEqual(self._with_argv(["jd.py", "--max-chars", "abc"], jd.main), 2)

    def test_jd_bad_cache_ttl(self):
        import jd
        self.assertEqual(self._with_argv(["jd.py", "--cache-ttl", "xyz"], jd.main), 2)

    def test_recaptcha_bad_wait_token(self):
        import recaptcha
        self.assertEqual(self._with_argv(["recaptcha.py", "wait-token", "nope"], recaptcha.main), 1)


class TestSiteScriptsImport(unittest.TestCase):
    """Smoke-import every TRACKED site/root script (feeds, drivers, helpers, preflight)
    outside _common. Scoped to `git ls-files` so an untracked in-progress script can't
    cause a false failure. Skips cleanly outside a git checkout."""
    def test_tracked_scripts_import(self):
        import importlib.util
        import subprocess
        try:
            root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                                           cwd=_HERE, text=True,
                                           stderr=subprocess.DEVNULL).strip()
            listing = subprocess.check_output(["git", "ls-files"], cwd=root, text=True)
        except Exception:
            self.skipTest("not a git checkout / git unavailable")
        files = [os.path.join(root, p) for p in listing.splitlines()
                 if p.endswith(".py") and not p.startswith("tests/") and "/_common/" not in p]
        self.assertTrue(files, "no tracked non-_common scripts found")
        failures = []
        for f in files:
            base = os.path.basename(f)
            name = "sitesmoke_" + base[:-3].replace("-", "_")
            d = os.path.dirname(f)
            added = d not in sys.path
            if added:
                sys.path.insert(0, d)   # so a script's sibling imports resolve
            try:
                spec = importlib.util.spec_from_file_location(name, f)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception as e:      # noqa: BLE001 — report path + reason
                failures.append(f"{os.path.relpath(f, root)}: {type(e).__name__}: {e}")
            finally:
                if added and d in sys.path:
                    sys.path.remove(d)
        self.assertEqual(failures, [], "tracked scripts failed to import -> " + " | ".join(failures))


class TestCodebaseInvariants(unittest.TestCase):
    """Turn a manual audit sweep into an ENFORCED invariant, so any new/edited script
    (including hermes's, once committed) can't silently reintroduce a fixed bug class.
    git-scoped so untracked WIP doesn't cause false failures; skips outside a checkout."""
    def _tracked_py(self):
        import subprocess
        try:
            root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                                           cwd=_HERE, text=True,
                                           stderr=subprocess.DEVNULL).strip()
            listing = subprocess.check_output(["git", "ls-files", "*.py"], cwd=root, text=True)
        except Exception:
            return None, None
        return root, [os.path.join(root, p) for p in listing.splitlines() if p.strip()]

    def test_no_raw_cfx_tab_env_read(self):
        # iter-5/6 sweep, enforced forever: tab resolution must go through cfx._tab()
        # (which raises a clean CfxError when unset), never a raw os.environ['CFX_TAB']
        # read that KeyError-tracebacks past `except cfx.CfxError`. Only cfx.py — the
        # accessor + the setter — may reference it.
        root, files = self._tracked_py()
        if files is None:
            self.skipTest("not a git checkout")
        offenders = []
        for f in files:
            rel = os.path.relpath(f, root)
            if os.path.basename(f) == "cfx.py" or rel.startswith("tests/"):
                continue
            with open(f, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
            if "os.environ['CFX_TAB']" in src or 'os.environ["CFX_TAB"]' in src:
                offenders.append(rel)
        self.assertEqual(offenders, [],
                         "raw os.environ CFX_TAB read (use cfx._tab() instead) in: " + ", ".join(offenders))

    def test_no_raw_cfx_user_env_read(self):
        # sibling of the CFX_TAB rule (same iter-5/6 sweep): user id resolves via
        # cfx._uid(), not a raw os.environ.get('CFX_USER'). Only cfx.py may reference it.
        root, files = self._tracked_py()
        if files is None:
            self.skipTest("not a git checkout")
        offenders = []
        for f in files:
            rel = os.path.relpath(f, root)
            if os.path.basename(f) == "cfx.py" or rel.startswith("tests/"):
                continue
            with open(f, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
            if 'os.environ.get("CFX_USER"' in src or "os.environ.get('CFX_USER'" in src:
                offenders.append(rel)
        self.assertEqual(offenders, [],
                         "raw os.environ CFX_USER read (use cfx._uid() instead) in: " + ", ".join(offenders))

    def test_no_bare_except(self):
        # a bare `except:` swallows KeyboardInterrupt/SystemExit and masks real errors;
        # the codebase uses typed excepts throughout — keep it that way (ast, robust
        # against `except:` appearing inside a string/comment).
        import ast
        root, files = self._tracked_py()
        if files is None:
            self.skipTest("not a git checkout")
        offenders = []
        for f in files:
            rel = os.path.relpath(f, root)
            if rel.startswith("tests/"):
                continue
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    tree = ast.parse(fh.read())
            except SyntaxError:
                continue   # the import/smoke tests already fail on unparseable files
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.type is None:
                    offenders.append(f"{rel}:{node.lineno}")
        self.assertEqual(offenders, [], "bare `except:` (use a typed except) in: " + ", ".join(offenders))


class TestDataIntegrity(unittest.TestCase):
    """The loop depends on data files that hermes edits; a silent corruption here breaks
    it worse than a code bug. These lock the load-bearing invariants."""
    def _root(self):
        return os.path.abspath(os.path.join(_HERE, ".."))

    def test_applicant_profile_canonical_marker(self):
        # loop-preflight.assert_canonical_dir() halts the loop if line 1 of
        # applicant-profile.md doesn't start with the (name-agnostic) CANONICAL_MARKER.
        # The profile is user-created + gitignored, so on a fresh clone it's absent —
        # skip then. When it exists (your real profile), its heading must match the
        # marker prefix and NOT still be the shipped placeholder.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "lp_marker", os.path.join(self._root(), "loop-preflight.py"))
        lp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lp)
        profile = os.path.join(self._root(), "references", "applicant-profile.md")
        if not os.path.exists(profile):
            self.skipTest("applicant-profile.md not present (fresh clone — user-created)")
        with open(profile, encoding="utf-8") as fh:
            first = fh.readline().strip()
        self.assertTrue(first.startswith(lp.CANONICAL_MARKER),
                        f"applicant-profile.md line 1 {first!r} must start with "
                        f"{lp.CANONICAL_MARKER!r} -> assert_canonical_dir would ERROR")
        self.assertFalse(any(p in first for p in lp._PLACEHOLDER_NAMES),
                         "applicant-profile.md still has a placeholder name — personalise it")

    def test_apply_defaults_valid_json(self):
        import json
        # apply-defaults.json is user-created + gitignored; a fresh clone has only the
        # committed .example. Validate whichever is present (atsform falls back the same way).
        base = os.path.join(self._root(), "sites", "_common")
        path = os.path.join(base, "apply-defaults.json")
        if not os.path.exists(path):
            path = os.path.join(base, "apply-defaults.example.json")
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)     # raises loudly if the defaults file is corrupt
        self.assertIsInstance(d, dict)
        self.assertIsInstance(d.get("fill"), dict,
                              "apply-defaults.json missing its 'fill' section -> the "
                              "constant name/email/phone defaults would silently vanish")

    def test_cooldown_key_derived_from_nav_not_column(self):
        # Robustness (replaces the old column==nav check): the cooldown key preflight uses is
        # now derived from the NAV keyword — the SAME source the linkedin/indeed feeds mark
        # under — so a mangled or `(Easy Apply)`-labelled `query` column can't make preflight
        # check a different key than the feed marks (the silent-re-sourcing bug). The column is
        # documentary now; a strict column==nav test no longer reflects a correctness invariant
        # (and was permanently red on a concurrent track's malformed-CSV rows). Verify the real
        # invariant behaviorally: plan() passes the nav keyword, and falls back to the column
        # only when the nav has none (the fixed-QUERY boards csj/hackney/wttj).
        import board_cooldown as bc2, search_plan
        orig = (bc2.remaining_hours, bc2.expected_yield, search_plan.applied_today)

        def run_key(search):
            seen = []
            # query-aware: the daily-limit key is unset (0h) and not part of the observed
            # nav-key trace; only real search queries are recorded in `seen`.
            bc2.remaining_hours = lambda b, q, now=None, rows=None: (
                0.0 if q == bc2.DAILY_LIMIT_KEY else (seen.append(q) or 0.0))
            bc2.expected_yield = lambda b, q, lookback=5, yield_rows=None: 0.0
            search_plan.applied_today = lambda tracker=None, day=None: 0
            try:
                search_plan.plan(searches=[search], holds=[])
            finally:
                bc2.remaining_hours, bc2.expected_yield, search_plan.applied_today = orig
            return seen

        # URL search: the GARBLED/labelled column is ignored; the nav keyword is used.
        self.assertEqual(run_key({"board": "linkedin", "query": 'GARBLED" (Easy Apply)',
                                  "nav": "https://x/jobs?keywords=Product+Designer"}),
                         ["Product Designer"])
        # fixed-QUERY board (no nav keyword) → falls back to the column.
        self.assertEqual(run_key({"board": "wttj", "query": "home", "nav": ""}), ["home"])


class TestApplyQueueExit(unittest.TestCase):
    """Contract: apply_queue exits 9 when the run stops on a dead tab (docstring says '9
    no-tab' — previously it fell through to return 0)."""
    def test_tab_dead_exits_9(self):
        import tempfile, importlib.util, json as _json
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "apply_queue", os.path.join(root, "scripts", "apply_queue.py"))
        aq = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(aq)
        d = tempfile.mkdtemp()
        aq.QUEUE = os.path.join(d, "queue.jsonl")
        with open(aq.QUEUE, "w", encoding="utf-8") as f:
            f.write(_json.dumps({"url": "https://www.linkedin.com/jobs/view/1/",
                                 "title": "Product Designer", "company": "C",
                                 "ats_hint": "linkedin-easyapply"}) + "\n")
        aq.heal_tab = lambda: False          # tab dead on first drivable row
        aq.load_tracker = lambda: ({}, {})   # nothing tracked → the row is drivable
        aq.COUNT_FILE = os.path.join(d, "count.json")
        orig_argv = sys.argv
        sys.argv = ["apply_queue.py"]        # no --refresh → use the existing queue
        try:
            self.assertEqual(aq.main(), 9)
        finally:
            sys.argv = orig_argv


class TestLinkedinRateLimit(unittest.TestCase):
    """LinkedIn daily-submission cap: detect the banner, save the posting, trip a board-wide
    cooldown so sourcing/preflight skip LinkedIn, and re-inject saved postings once clear."""
    def _rl(self):
        import importlib
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "sites", "linkedin", "scripts"))
        import ratelimit
        return importlib.reload(ratelimit)

    def test_matcher_positive_and_negative(self):
        rl = self._rl()
        pos = [
            "You've reached the daily limit for Easy Apply.",
            "We limit daily submissions to maintain quality and prevent bots.",
            "You've applied to too many jobs. Weekly limit reached.",
            "You have hit the maximum number of applications for today.",
            "There is a limit of 100 applications per day.",
        ]
        neg = [
            "Senior Product Designer — push the limits of design in a fast-paced team.",
            "Apply now. Salary £45,000. Hybrid London. Unlimited holiday.",
            "",
        ]
        for t in pos:
            self.assertTrue(rl.looks_rate_limited(t), t)
        for t in neg:
            self.assertFalse(rl.looks_rate_limited(t), t)

    def test_detect_uses_scoped_read_and_is_error_safe(self):
        rl = self._rl()
        fake_hit = types.SimpleNamespace(evaluate=lambda js: "Daily limit reached — try tomorrow")
        fake_miss = types.SimpleNamespace(evaluate=lambda js: "")
        def boom(js): raise RuntimeError("dead tab")
        fake_err = types.SimpleNamespace(evaluate=boom)
        self.assertTrue(rl.detect(fake_hit))
        self.assertFalse(rl.detect(fake_miss))
        self.assertFalse(rl.detect(fake_err))   # flaky read never blocks the loop

    def test_cooldown_roundtrip_isolated(self):
        import board_cooldown as bc, tempfile
        rl = self._rl()
        saved_log = bc.LOG
        bc.LOG = os.path.join(tempfile.mkdtemp(), "board-cooldown.csv")
        try:
            self.assertFalse(bc.daily_limit_active("linkedin"))
            bc.mark_daily_limit("linkedin", hours=18)
            self.assertTrue(bc.daily_limit_active("linkedin"))
            self.assertFalse(bc.daily_limit_active("indeed"))   # scoped to the one board
        finally:
            bc.LOG = saved_log

    def test_plan_excludes_rate_limited_board(self):
        import search_plan as sp, board_cooldown as bc
        saved = (bc.daily_limit_active, bc.remaining_hours, bc.expected_yield,
                 bc._read_rows, bc._read_yield_rows)
        bc.daily_limit_active = lambda board, **k: bc.norm(board) == "linkedin"
        bc.remaining_hours = lambda *a, **k: 0
        bc.expected_yield = lambda *a, **k: 1.0
        bc._read_rows = lambda: []
        bc._read_yield_rows = lambda: []
        try:
            searches = [{"board": "linkedin", "query": "q", "nav": ""},
                        {"board": "indeed", "query": "q2", "nav": ""}]
            out = sp.plan(searches=searches, holds=[], count_applied=False)
        finally:
            (bc.daily_limit_active, bc.remaining_hours, bc.expected_yield,
             bc._read_rows, bc._read_yield_rows) = saved
        self.assertEqual(out["verdict"], "WORK")
        boards = {c["board"] for c in out["clear"]}
        self.assertNotIn("linkedin", boards)               # excluded
        self.assertIn("indeed", boards)                    # switched to
        self.assertIn("linkedin", out["rate_limited"])

    def test_deferred_store_roundtrip(self):
        import tempfile
        rl = self._rl()
        saved = rl.DEFERRED
        rl.DEFERRED = os.path.join(tempfile.mkdtemp(), "deferred.jsonl")
        try:
            self.assertEqual(rl.load_deferred(), [])
            rl.defer({"url": "https://linkedin.com/jobs/view/1/", "title": "PD", "company": "C"})
            rl.defer({"url": "https://linkedin.com/jobs/view/1/", "title": "PD", "company": "C"})
            self.assertEqual(len(rl.load_deferred()), 1)    # dedup by url
            rl.defer({"url": "https://linkedin.com/jobs/view/2/", "title": "UX", "company": "D"})
            self.assertEqual(len(rl.load_deferred()), 2)
            rl.rewrite_deferred([r for r in rl.load_deferred() if "2" in r["url"]])
            self.assertEqual([r["url"] for r in rl.load_deferred()],
                             ["https://linkedin.com/jobs/view/2/"])
        finally:
            rl.DEFERRED = saved

    def test_apply_queue_trips_and_defers_on_detected_limit(self):
        import importlib.util, tempfile, json as _json
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "apply_queue", os.path.join(root, "scripts", "apply_queue.py"))
        aq = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(aq)
        d = tempfile.mkdtemp()
        aq.QUEUE = os.path.join(d, "queue.jsonl")
        with open(aq.QUEUE, "w", encoding="utf-8") as f:
            for i in (1, 2):
                f.write(_json.dumps({"url": f"https://www.linkedin.com/jobs/view/{i}/",
                                     "title": "Product Designer", "company": "C",
                                     "ats_hint": "linkedin-easyapply"}) + "\n")
        aq.heal_tab = lambda: True
        aq.load_tracker = lambda: ({}, {})
        aq.COUNT_FILE = os.path.join(d, "count.json")
        # NB aq.subprocess IS the shared module — save/restore .run so we don't clobber it
        # process-wide (a leak that breaks later tests calling real subprocess.run).
        orig_run = aq.subprocess.run
        aq.subprocess.run = lambda *a, **k: types.SimpleNamespace(returncode=3)  # submit failed
        tripped = {"n": 0}
        deferred = []
        aq.ratelimit.active = lambda *a, **k: False
        aq.ratelimit.load_deferred = lambda: []
        aq.ratelimit.detect = lambda cfx: True                      # banner present
        aq.ratelimit.trip = lambda *a, **k: (tripped.__setitem__("n", tripped["n"] + 1), "T+18h")[1]
        aq.ratelimit.defer = lambda r: (deferred.append(r), True)[1]
        aq.ratelimit.rewrite_deferred = lambda rows: None
        orig_argv = sys.argv
        sys.argv = ["apply_queue.py"]
        try:
            code = aq.main()
        finally:
            sys.argv = orig_argv
            aq.subprocess.run = orig_run
        out = _json.load(open(aq.COUNT_FILE))
        self.assertTrue(out["rate_limited"])            # flagged
        self.assertEqual(tripped["n"], 1)               # cooldown tripped once
        self.assertEqual(len(deferred), 1)              # first posting saved for later
        self.assertEqual(out["attempted"], 1)           # stopped the drain (didn't grind row 2)

    def test_apply_queue_trips_on_rc8_even_if_detect_misses(self):
        """apply_ea rc==8 (limit detected at source) must trip+save+stop even when the
        queue's own banner scan misses (modal already dismissed)."""
        import importlib.util, tempfile, json as _json
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "apply_queue3", os.path.join(root, "scripts", "apply_queue.py"))
        aq = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(aq)
        d = tempfile.mkdtemp()
        aq.QUEUE = os.path.join(d, "queue.jsonl")
        with open(aq.QUEUE, "w", encoding="utf-8") as f:
            f.write(_json.dumps({"url": "https://www.linkedin.com/jobs/view/1/",
                                 "title": "Product Designer", "company": "C",
                                 "ats_hint": "linkedin-easyapply"}) + "\n")
        aq.heal_tab = lambda: True
        aq.load_tracker = lambda: ({}, {})
        aq.COUNT_FILE = os.path.join(d, "count.json")
        orig_run = aq.subprocess.run
        aq.subprocess.run = lambda *a, **k: types.SimpleNamespace(returncode=8)  # source signal
        tripped, deferred = {"n": 0}, []
        aq.ratelimit.active = lambda *a, **k: False
        aq.ratelimit.load_deferred = lambda: []
        aq.ratelimit.detect = lambda cfx: False           # queue scan MISSES (modal gone)
        aq.ratelimit.trip = lambda *a, **k: (tripped.__setitem__("n", tripped["n"] + 1), "T")[1]
        aq.ratelimit.defer = lambda r: (deferred.append(r), True)[1]
        aq.ratelimit.rewrite_deferred = lambda rows: None
        orig_argv = sys.argv
        sys.argv = ["apply_queue.py"]
        try:
            aq.main()
        finally:
            sys.argv = orig_argv
            aq.subprocess.run = orig_run
        out = _json.load(open(aq.COUNT_FILE))
        self.assertTrue(out["rate_limited"])
        self.assertEqual(tripped["n"], 1)
        self.assertEqual(len(deferred), 1)

    def test_apply_queue_skips_drain_when_limit_active(self):
        import importlib.util, tempfile, json as _json
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "apply_queue2", os.path.join(root, "scripts", "apply_queue.py"))
        aq = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(aq)
        d = tempfile.mkdtemp()
        aq.QUEUE = os.path.join(d, "queue.jsonl")
        with open(aq.QUEUE, "w", encoding="utf-8") as f:
            f.write(_json.dumps({"url": "https://www.linkedin.com/jobs/view/1/",
                                 "title": "Product Designer", "company": "C",
                                 "ats_hint": "linkedin-easyapply"}) + "\n")
        aq.heal_tab = lambda: True
        aq.load_tracker = lambda: ({}, {})
        aq.COUNT_FILE = os.path.join(d, "count.json")
        called = {"run": 0}
        orig_run = aq.subprocess.run
        aq.subprocess.run = lambda *a, **k: (called.__setitem__("run", called["run"] + 1),
                                             types.SimpleNamespace(returncode=0))[1]
        aq.ratelimit.active = lambda *a, **k: True     # already limited
        aq.ratelimit.load_deferred = lambda: []
        orig_argv = sys.argv
        sys.argv = ["apply_queue.py"]
        try:
            aq.main()
        finally:
            sys.argv = orig_argv
            aq.subprocess.run = orig_run
        self.assertEqual(called["run"], 0)             # never drove a single LinkedIn row


class TestAdzunaFeed(unittest.TestCase):
    """Adzuna JSON-API feed: pure parse + URL builder + nav extraction (no network/browser)."""
    def _load(self):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "adzuna_feed", os.path.join(root, "sites", "adzuna.co.uk", "scripts", "feed.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_parse_maps_nested_fields(self):
        m = self._load()
        payload = {"results": [
            {"id": 123, "title": "UX Designer", "company": {"display_name": "Acme"},
             "location": {"display_name": "London, UK"}, "salary_min": 40000,
             "salary_max": 50000, "created": "2026-07-14T09:00:00Z",
             "redirect_url": "https://www.adzuna.co.uk/land/ad/123"},
            {"id": 456, "title": "Product Designer", "company": {"display_name": "B"},
             "location": {"display_name": "Remote"}},          # no salary
            {"title": "no id — dropped"},                        # missing id
        ]}
        rows = m._parse(payload)
        self.assertEqual([r["id"] for r in rows], ["123", "456"])   # id stringified, no-id dropped
        r0 = rows[0]
        self.assertEqual(r0["url"], "https://www.adzuna.co.uk/details/123")
        self.assertEqual(r0["company"], "Acme")
        self.assertEqual(r0["location"], "London, UK")
        self.assertEqual(r0["salary"], "£40,000–£50,000")
        self.assertEqual(r0["created"], "2026-07-14")
        self.assertEqual(r0["source"], "adzuna")
        self.assertEqual(rows[1]["salary"], "")                    # tolerates missing salary

    def test_parse_tolerates_garbage(self):
        m = self._load()
        self.assertEqual(m._parse({}), [])
        self.assertEqual(m._parse({"results": None}), [])
        self.assertEqual(m._parse({"results": ["not-a-dict", 5]}), [])

    def test_api_url_has_keys_and_filters(self):
        from urllib.parse import urlparse, parse_qs
        m = self._load()
        u = m._api_url("UX Designer", "London", 2, 7, "APPID", "APPKEY")
        p = urlparse(u); qs = parse_qs(p.query)
        self.assertTrue(p.path.endswith("/search/2"))              # page in the path
        self.assertEqual(qs["app_id"], ["APPID"])
        self.assertEqual(qs["app_key"], ["APPKEY"])
        self.assertEqual(qs["what"], ["UX Designer"])
        self.assertEqual(qs["where"], ["London"])
        self.assertEqual(qs["max_days_old"], ["7"])
        self.assertEqual(qs["sort_by"], ["date"])

    def test_nav_extraction_and_default_where(self):
        m = self._load()
        self.assertEqual(m._query_from_nav("https://www.adzuna.co.uk/search?q=UX+Designer&w=London"),
                         ("UX Designer", "London"))
        self.assertEqual(m._query_from_nav("https://www.adzuna.co.uk/search?what=BA&where=Remote"),
                         ("BA", "Remote"))
        self.assertEqual(m._query_from_nav(""), ("", ""))
        # default location applied when where absent
        _, where = m._query_from_nav("https://www.adzuna.co.uk/search?q=x")
        self.assertEqual(where, "")

    def test_wired_into_pipeline_feeds(self):
        import pipeline
        self.assertIn("adzuna", pipeline.FEEDS)
        subdir, argb = pipeline.FEEDS["adzuna"]
        self.assertEqual(subdir, "adzuna.co.uk")
        self.assertEqual(argb("http://x?q=y"), ["--nav", "http://x?q=y"])


class TestReedFeed(unittest.TestCase):
    """Reed scraper pure logic (selectors verified live via :3006, 2026-07-15). Tests the
    normalization against the REAL sampled card data."""
    def _load(self):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "reed_feed", os.path.join(root, "sites", "reed.co.uk", "scripts", "feed.py"))
        # stub cfx so the module imports without a browser
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_helpers(self):
        m = self._load()
        self.assertEqual(m._job_id("job57081009"), "57081009")
        self.assertEqual(m._job_id(""), "")
        self.assertEqual(m._company_from_posted_by("2 July by Pharmica"), "Pharmica")
        self.assertEqual(m._company_from_posted_by("Yesterday by AJ Bell"), "AJ Bell")
        self.assertEqual(m._company_from_posted_by("Just a name"), "Just a name")
        self.assertEqual(m._canonical_url("/jobs/ux-writer/57119546?source=x&q=y"),
                         "https://www.reed.co.uk/jobs/ux-writer/57119546")
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(m._search_url("UX Designer", "London")).query)
        self.assertEqual(qs["keywords"], ["UX Designer"])
        self.assertEqual(qs["location"], ["London"])
        self.assertEqual(qs["sortby"], ["DisplayDate"])

    def test_normalize_real_card(self):
        m = self._load()
        raw = {"dataId": "job57081009",
               "href": "/jobs/web-graphic-designer-ux-ui/57081009?source=searchResults&q=ux",
               "title": "Web / Graphic Designer (UX/UI)", "postedBy": "2 July by Pharmica",
               "salary": "£32,000 - £36,000 per annum", "location": "London", "easyApply": True}
        n = m._normalize(raw)
        self.assertEqual(n["id"], "57081009")
        self.assertEqual(n["url"], "https://www.reed.co.uk/jobs/web-graphic-designer-ux-ui/57081009")
        self.assertEqual(n["company"], "Pharmica")
        self.assertEqual(n["location"], "London")
        self.assertEqual(n["salary"], "£32,000 - £36,000 per annum")
        self.assertEqual(n["ats_hint"], "reed-easyapply")   # easy-apply badge → hint
        self.assertEqual(n["source"], "reed")
        self.assertIsNone(m._normalize({"dataId": ""}))     # no id → dropped

    def test_wired_into_pipeline_feeds(self):
        import pipeline
        self.assertIn("reed", pipeline.FEEDS)
        self.assertEqual(pipeline.FEEDS["reed"][0], "reed.co.uk")


class TestTotaljobsFeed(unittest.TestCase):
    """Totaljobs / StepStone-family scraper pure logic (data-at hooks + path-based search URL,
    verified live 2026-07-17). Cooldown key is parsed from the /jobs/<what>/ path."""
    def _load(self):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "totaljobs_feed", os.path.join(root, "sites", "totaljobs.com", "scripts", "feed.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_helpers(self):
        m = self._load()
        self.assertEqual(m._job_id("/job/ux-designer/triad-group-plc-job107681590"), "107681590")
        self.assertEqual(m._job_id("/job/foo/bar"), "")            # no -job<id> → empty
        self.assertEqual(m._slug("UX Designer"), "ux-designer")
        self.assertEqual(m._search_url("UX Designer", "London"),
                         "https://www.totaljobs.com/jobs/ux-designer/in-london")
        # cooldown key parsed from the path, and it must match searches.csv 'query' after norm()
        import board_cooldown as bc
        self.assertEqual(m._query_from_nav("https://www.totaljobs.com/jobs/ux-designer/in-london"),
                         "ux designer")
        self.assertEqual(bc.norm(m._query_from_nav("https://www.totaljobs.com/jobs/ux-designer/in-london")),
                         bc.norm("ux designer"))
        self.assertEqual(m._query_from_nav("https://www.totaljobs.com/job/x/y-job1"), "")
        # relative href resolves against a sibling base (cwjobs), not the default host
        self.assertEqual(m._canonical_url("/job/x/y-job107663974?src=q", "https://www.cwjobs.co.uk"),
                         "https://www.cwjobs.co.uk/job/x/y-job107663974")

    def test_normalize_real_card(self):
        m = self._load()
        raw = {"href": "/job/ux-designer/triad-group-plc-job107681590?src=searchResults",
               "title": "UX Designer", "company": "Triad Group Plc",
               "salary": "£45,000 - £55,000 per annum", "location": "London", "posted": "2 days ago"}
        n = m._normalize(raw)
        self.assertEqual(n["id"], "107681590")
        self.assertEqual(n["url"], "https://www.totaljobs.com/job/ux-designer/triad-group-plc-job107681590")
        self.assertEqual(n["company"], "Triad Group Plc")
        self.assertEqual(n["location"], "London")
        self.assertEqual(n["source"], "totaljobs")
        self.assertIsNone(m._normalize({"href": "/job/no/id-here"}))   # no id → dropped

    def test_wired_into_pipeline_feeds(self):
        import pipeline
        self.assertIn("totaljobs", pipeline.FEEDS)
        self.assertEqual(pipeline.FEEDS["totaljobs"][0], "totaljobs.com")
        self.assertIn("cwjobs", pipeline.FEEDS)   # StepStone sibling shares the adapter dir
        self.assertEqual(pipeline.FEEDS["cwjobs"][0], "totaljobs.com")


class TestGuardianFeed(unittest.TestCase):
    """Guardian Jobs (Madgex) scraper pure logic — .lister__item cards + `?Keywords=` search
    (the /jobs/<what>/ PATH is a category browse, NOT keyword-filtered; verified live 2026-07-17)."""
    def _load(self):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "guardian_feed", os.path.join(root, "sites", "jobs.theguardian.com", "scripts", "feed.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_helpers(self):
        m = self._load()
        self.assertEqual(m._job_id("/job/10146125/digital-director/?LinkSource=x"), "10146125")
        self.assertEqual(m._job_id("/jobs/design/"), "")           # browse path, not a job
        self.assertEqual(m._canonical_url(" \n\t/job/10126456/product-designer/?q=1"),
                         "https://jobs.theguardian.com/job/10126456/product-designer/")
        # free-text search is the Keywords param, not a path segment
        from urllib.parse import urlparse, parse_qs
        u = m._search_url("user experience")
        self.assertIn("Keywords=user+experience", u)
        # cooldown key: Keywords param (case-insensitive) matches searches.csv 'query' after norm()
        import board_cooldown as bc
        self.assertEqual(m._query_from_nav("https://jobs.theguardian.com/jobs/?Keywords=user+experience"),
                         "user experience")
        self.assertEqual(bc.norm(m._query_from_nav(u)), bc.norm("user experience"))
        self.assertEqual(m._query_from_nav("https://jobs.theguardian.com/jobs/design/"), "design")

    def test_normalize_real_card(self):
        m = self._load()
        raw = {"href": " \n\t/job/10126456/product-designer/?LinkSource=searchResults",
               "title": "Product Designer", "company": "REVIVA SOFTWORKS",
               "salary": "Competitive salary", "location": "Shoreditch, London"}
        n = m._normalize(raw)
        self.assertEqual(n["id"], "10126456")
        self.assertEqual(n["url"], "https://jobs.theguardian.com/job/10126456/product-designer/")
        self.assertEqual(n["company"], "REVIVA SOFTWORKS")
        self.assertEqual(n["ats_hint"], "guardian-direct")   # on-page apply form
        self.assertEqual(n["source"], "guardian")
        self.assertIsNone(m._normalize({"href": "/jobs/design/"}))   # no job id → dropped

    def test_wired_into_pipeline_feeds(self):
        import pipeline
        self.assertIn("guardian", pipeline.FEEDS)
        self.assertEqual(pipeline.FEEDS["guardian"][0], "jobs.theguardian.com")


class TestApplicationTrackFeed(unittest.TestCase):
    """MI5/MI6 (applicationtrack.com VacancyFiller) board — one adapter, org inferred from the
    appcentre in the URL; apply is account-gated (filled w/ noVNC oversight). Verified 2026-07-17."""
    def _load(self):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "apptrack_feed", os.path.join(root, "sites", "applicationtrack.com", "scripts", "feed.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_helpers(self):
        m = self._load()
        self.assertEqual(m._ref("/vx/.../opp/3793-Technical-Risk-Adviser-Ref-3793/en-GB"), "3793")
        self.assertEqual(m._ref("/vx/.../jobboard/vacancy/2"), "")
        self.assertEqual(m._org_from_url(".../appcentre-a18/candidate/jobboard/vacancy/1"),
                         ("MI5 (Security Service)", "mi5"))
        self.assertEqual(m._org_from_url(".../appcentre-2/brand-2/candidate/jobboard/vacancy/2"),
                         ("MI6 (SIS)", "mi6"))
        self.assertTrue(m._canonical_url("/vx/x/opp/3726-Solutions-Architect-Ref-3726/en-GB?q=1")
                        .endswith("/opp/3726-Solutions-Architect-Ref-3726/en-GB"))

    def test_normalize_real_row(self):
        m = self._load()
        raw = {"href": "/vx/lang-en-GB/mobile-0/appcentre-2/brand-6/xf-h/candidate/so/pm/1/pl/5/opp/3793-Technical-Risk-Adviser-Ref-3793/en-GB",
               "title": "Technical Risk Adviser Ref. 3793", "location": "Cheltenham,London",
               "department": "Technology Roles", "closing": "2026/08/04 23:00 BST"}
        n = m._normalize(raw, "MI6 (SIS)", "mi6")
        self.assertEqual(n["id"], "3793")
        self.assertEqual(n["company"], "MI6 (SIS)")
        self.assertEqual(n["department"], "Technology Roles")
        self.assertEqual(n["ats_hint"], "applicationtrack")   # account-gated login
        self.assertEqual(n["source"], "mi6")
        self.assertIsNone(m._normalize({"href": "/no/ref"}, "MI6 (SIS)", "mi6"))

    def test_wired_into_pipeline_feeds(self):
        import pipeline
        for tok in ("mi5", "mi6"):
            self.assertIn(tok, pipeline.FEEDS)
            self.assertEqual(pipeline.FEEDS[tok][0], "applicationtrack.com")


class TestNHSFeed(unittest.TestCase):
    """NHS Jobs (jobs.nhs.uk) scraper pure logic — data-test hooks, /candidate/jobadvert/<REF>,
    employer folded as firstChild of the location hook (verified live 2026-07-17)."""
    def _load(self):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "nhs_feed", os.path.join(root, "sites", "jobs.nhs.uk", "scripts", "feed.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_helpers(self):
        m = self._load()
        self.assertEqual(m._job_ref("/candidate/jobadvert/C9289-SC-388?keyword=digital"), "C9289-SC-388")
        self.assertEqual(m._job_ref("/candidate/jobadvert/M0048-26-0366"), "M0048-26-0366")
        self.assertEqual(m._job_ref("/candidate/search/results"), "")
        self.assertEqual(m._clean_salary("Salary: £39,959 to £48,117 a year"), "£39,959 to £48,117 a year")
        self.assertEqual(m._canonical_url("/candidate/jobadvert/C9289-SC-388?keyword=x"),
                         "https://www.jobs.nhs.uk/candidate/jobadvert/C9289-SC-388")
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(m._search_url("digital", "London", 10)).query)
        self.assertEqual(qs["keyword"], ["digital"])
        self.assertEqual(qs["location"], ["London"])
        import board_cooldown as bc
        self.assertEqual(m._query_from_nav(m._search_url("digital", "London", 10)), "digital")
        self.assertEqual(bc.norm(m._query_from_nav(m._search_url("digital", "London", 10))), bc.norm("digital"))

    def test_normalize_real_card(self):
        m = self._load()
        raw = {"href": "/candidate/jobadvert/C9289-SC-388?keyword=digital",
               "title": "Digital Implementation Lead", "employer": "Chelsea and Westminster Hospital",
               "location": "London SW10", "salary": "Salary: £58,133 to £65,261 a year"}
        n = m._normalize(raw)
        self.assertEqual(n["id"], "C9289-SC-388")
        self.assertEqual(n["url"], "https://www.jobs.nhs.uk/candidate/jobadvert/C9289-SC-388")
        self.assertEqual(n["company"], "Chelsea and Westminster Hospital")
        self.assertEqual(n["location"], "London SW10")
        self.assertEqual(n["salary"], "£58,133 to £65,261 a year")
        self.assertEqual(n["ats_hint"], "nhs-jobs")
        self.assertEqual(n["source"], "nhs")
        self.assertIsNone(m._normalize({"href": "/candidate/search/results"}))

    def test_wired_into_pipeline_feeds(self):
        import pipeline
        self.assertIn("nhs", pipeline.FEEDS)
        self.assertEqual(pipeline.FEEDS["nhs"][0], "jobs.nhs.uk")


class TestCVLibraryFeed(unittest.TestCase):
    """CV-Library scraper pure logic — stable data-qa hooks, /job/<id>/<slug>, SEO path search
    /<role>-jobs-in-<location> (verified live 2026-07-17)."""
    def _load(self):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "cvlibrary_feed", os.path.join(root, "sites", "cv-library.co.uk", "scripts", "feed.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_helpers(self):
        m = self._load()
        self.assertEqual(m._job_id("/job/225344741/ux-designer?keyword=x"), "225344741")
        self.assertEqual(m._job_id("/foo/bar"), "")
        self.assertEqual(m._search_url("UX Designer", "London"),
                         "https://www.cv-library.co.uk/ux-designer-jobs-in-london")
        self.assertEqual(m._canonical_url("/job/225344741/ux-designer?keyword=x"),
                         "https://www.cv-library.co.uk/job/225344741/ux-designer")
        import board_cooldown as bc
        self.assertEqual(m._query_from_nav("https://www.cv-library.co.uk/ux-designer-jobs-in-london"),
                         "ux designer")
        self.assertEqual(bc.norm(m._query_from_nav(m._search_url("UX Designer", "London"))), bc.norm("ux designer"))

    def test_normalize_real_card(self):
        m = self._load()
        raw = {"href": "/job/225363128/ux-designer?keyword=ux", "title": "UX Designer",
               "company": "Triad", "location": "London", "salary": "£55,000 - £60,000 per annum",
               "easyApply": True}
        n = m._normalize(raw)
        self.assertEqual(n["id"], "225363128")
        self.assertEqual(n["url"], "https://www.cv-library.co.uk/job/225363128/ux-designer")
        self.assertEqual(n["company"], "Triad")
        self.assertEqual(n["salary"], "£55,000 - £60,000 per annum")
        self.assertEqual(n["ats_hint"], "cvlibrary-easyapply")
        self.assertEqual(n["source"], "cvlibrary")
        self.assertIsNone(m._normalize({"href": "/no/id"}))

    def test_wired_into_pipeline_feeds(self):
        import pipeline
        self.assertIn("cvlibrary", pipeline.FEEDS)
        self.assertEqual(pipeline.FEEDS["cvlibrary"][0], "cv-library.co.uk")


class TestCharityJobFeed(unittest.TestCase):
    """CharityJob scraper pure logic — article.job-card-wrapper + /jobs/<charity>/<role>/<id>,
    `.organisation` = "<charity>, <location>" (verified live 2026-07-17)."""
    def _load(self):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "charityjob_feed", os.path.join(root, "sites", "charityjob.co.uk", "scripts", "feed.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_helpers(self):
        m = self._load()
        self.assertEqual(m._job_id("/jobs/anna-freud/website-and-digital-marketing-officer/1076288"), "1076288")
        self.assertEqual(m._job_id("/jobs/foo/bar"), "")
        self.assertEqual(m._split_org("Anna Freud, London (Hybrid)"), ("Anna Freud", "London (Hybrid)"))
        self.assertEqual(m._split_org("Foxglove"), ("Foxglove", ""))
        self.assertEqual(m._canonical_url("/jobs/x/y/1076288?tsId=6"),
                         "https://www.charityjob.co.uk/jobs/x/y/1076288")
        self.assertIn("Keywords=digital", m._search_url("digital"))
        import board_cooldown as bc
        self.assertEqual(m._query_from_nav("https://www.charityjob.co.uk/jobs/?Keywords=digital"), "digital")
        self.assertEqual(bc.norm(m._query_from_nav("https://www.charityjob.co.uk/digital-jobs")), bc.norm("digital"))

    def test_normalize_real_card(self):
        m = self._load()
        raw = {"href": "/jobs/anna-freud/website-and-digital-marketing-officer/1076288?tsId=6",
               "title": "Website and Digital Marketing Officer", "org": "Anna Freud, London (Hybrid)", "salary": ""}
        n = m._normalize(raw)
        self.assertEqual(n["id"], "1076288")
        self.assertEqual(n["url"], "https://www.charityjob.co.uk/jobs/anna-freud/website-and-digital-marketing-officer/1076288")
        self.assertEqual(n["company"], "Anna Freud")
        self.assertEqual(n["location"], "London (Hybrid)")
        self.assertEqual(n["source"], "charityjob")
        self.assertIsNone(m._normalize({"href": "/jobs/no/id"}))

    def test_wired_into_pipeline_feeds(self):
        import pipeline
        self.assertIn("charityjob", pipeline.FEEDS)
        self.assertEqual(pipeline.FEEDS["charityjob"][0], "charityjob.co.uk")


class TestTheDotsFeed(unittest.TestCase):
    """The Dots JSON:API feed — pure _parse resolves sideloaded org/location (verified live
    2026-07-15: org is included type 'pages' with the name under 'title', not 'name')."""
    def _load(self):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "thedots_feed", os.path.join(root, "sites", "the-dots.com", "scripts", "feed.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_parse_resolves_jsonapi(self):
        m = self._load()
        payload = {
            "data": [{
                "type": "jobs", "id": "248353",
                "attributes": {"title": "Paid Media Account Manager",
                               "slug": "paid-media-account-manager-248353",
                               "applicationWebsite": "https://careers.next15.com/jobs/7861051",
                               "isRemote": False, "isAmountPublic": False, "formattedAmount": "0.00"},
                "relationships": {
                    "organisation-page": {"data": {"type": "pages", "id": "300793"}},
                    "location": {"data": {"type": "locations", "id": "1"}}},
            }, {
                "type": "jobs", "id": "9",
                "attributes": {"title": "Senior Product Designer", "slug": "spd-9",
                               "isRemote": True, "isAmountPublic": True, "formattedAmount": "£55,000"},
                "relationships": {"organisation-page": {"data": {"type": "pages", "id": "300793"}}},
            }, {"type": "jobs", "attributes": {"title": "no id"}}],   # dropped
            "included": [
                {"type": "pages", "id": "300793", "attributes": {"title": "Cubaka"}},   # name under 'title'
                {"type": "locations", "id": "1", "attributes": {"postalTownLong": "London",
                                                                "name": "London, United Kingdom"}}],
        }
        rows = m._parse(payload)
        self.assertEqual([r["id"] for r in rows], ["248353", "9"])   # no-id dropped
        r0 = rows[0]
        self.assertEqual(r0["url"], "https://the-dots.com/jobs/paid-media-account-manager-248353")
        self.assertEqual(r0["company"], "Cubaka")            # resolved from included 'pages'.title
        self.assertEqual(r0["location"], "London")           # postalTownLong preferred
        self.assertEqual(r0["salary"], "")                   # not public → blank
        self.assertFalse(r0["remote"])
        self.assertEqual(r0["apply_url"], "https://careers.next15.com/jobs/7861051")
        self.assertEqual(r0["source"], "thedots")
        self.assertEqual(rows[1]["salary"], "£55,000")       # public amount kept
        self.assertTrue(rows[1]["remote"])

    def test_parse_tolerates_missing(self):
        m = self._load()
        self.assertEqual(m._parse({}), [])
        # job with no relationships/included → empty company/location, still emitted
        rows = m._parse({"data": [{"id": "1", "attributes": {"title": "X", "slug": "x-1"}}]})
        self.assertEqual(rows[0]["company"], "")
        self.assertEqual(rows[0]["location"], "")

    def test_keyword_search_body_and_nav(self):
        m = self._load()
        self.assertEqual(m._query_from_nav("https://the-dots.com/jobs/search?q=UX+Designer"), "UX Designer")
        self.assertEqual(m._query_from_nav(""), "")
        # search body: keyword → data.query + relevance; empty → latest
        import json as _j
        captured = {}
        m._req = lambda url, method="GET", body=None, token=None, timeout=30: captured.update(body=body) or {"data": []}
        m._search_page("tok", 1, "UX Designer")
        self.assertEqual(captured["body"]["data"], {"query": "UX Designer", "filters": [], "order": "relevance"})
        m._search_page("tok", 1, "")
        self.assertEqual(captured["body"]["data"], {"filters": [], "order": "latest"})

    def test_wired_into_pipeline_feeds(self):
        import pipeline
        self.assertIn("thedots", pipeline.FEEDS)
        self.assertEqual(pipeline.FEEDS["thedots"][0], "the-dots.com")
        self.assertEqual(pipeline.FEEDS["thedots"][1]("http://x?q=y"), ["--nav", "http://x?q=y"])


class TestGenQueries(unittest.TestCase):
    """scripts/gen_queries.py emits BROAD alternate search URLs that hit NEW cooldown keys
    (the automated form of apply-mechanics §'Break cooldown with NEW query URLs')."""
    def _load(self):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "gen_queries", os.path.join(root, "scripts", "gen_queries.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_urls_are_valid_and_remote_london(self):
        from urllib.parse import urlparse, parse_qs
        m = self._load()
        for q in m.LI_TITLES:
            u = urlparse(m.li_url(q)); qs = parse_qs(u.query)
            self.assertEqual(u.netloc, "www.linkedin.com")
            self.assertEqual(qs["f_WT"], ["2"])            # remote
            self.assertIn("London", qs["location"][0])     # profile location
            self.assertIn(" OR ", parse_qs(u.query)["keywords"][0])  # OR-bundle survived encode
        for q in m.ID_TITLES:
            u = urlparse(m.id_url(q)); qs = parse_qs(u.query)
            self.assertEqual(u.netloc, "uk.indeed.com")
            self.assertEqual(qs["remotejob"], ["remote"])
            self.assertEqual(qs["l"], ["London"])

    def test_urls_yield_distinct_derivable_cooldown_keys(self):
        """Real invariant: every gen_queries URL derives a non-empty cooldown key via the
        SAME `query_from_url` the feeds use, and the bundles are mutually distinct — so each
        is its own cooldown lane. (We deliberately do NOT assert they differ from the live
        searches.csv: that file is user-editable data and may adopt the same broad bundles;
        when it does, feed.py's cooldown gate cheaply skips the already-cooled key. gen_queries'
        value is the families/recency not currently bundled — a property of data, not code.)"""
        import board_cooldown as bc
        m = self._load()
        for titles, urlfn in ((m.LI_TITLES, m.li_url), (m.ID_TITLES, m.id_url)):
            keys = [bc.query_from_url(urlfn(q)) for q in titles]
            self.assertTrue(all(keys), "every URL must yield a derivable cooldown key")
            self.assertEqual(len(set(keys)), len(keys),
                             "bundles must be mutually distinct cooldown lanes")

    def test_board_filter(self):
        import io, contextlib
        m = self._load()
        orig = sys.argv
        try:
            sys.argv = ["gen_queries.py", "--board", "linkedin"]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                m.main()
            out = buf.getvalue()
        finally:
            sys.argv = orig
        self.assertIn("LI_ALT_0", out)
        self.assertNotIn("ID_ALT_", out)     # indeed suppressed
        self.assertNotIn("---", out)         # separator only in combined mode


class TestPipelineTabHeal(unittest.TestCase):
    """run_feed self-heals a dead camofox tab: on a feed error WITH a dead tab it reopens via
    cfx.ensure_tab and retries ONCE (idempotent read). No heal when the tab is alive, and the
    retry is single-shot (never a double-submit — sourcing is read-only)."""
    def _run(self, pipeline, run_results, tab_dead):
        """Patch _run_feed_once/_tab_dead/cfx.ensure_tab, run run_feed once, restore.
        Returns (posts, err, calls). NB the test cfx is a stub without ensure_tab, so we
        set-then-remove it rather than save/restore an attribute that may not exist."""
        calls = {"run": 0, "ensure": 0}
        seq = list(run_results)

        def fake_once(cmd, board, timeout):
            calls["run"] += 1
            return seq[min(calls["run"] - 1, len(seq) - 1)]

        def fake_ensure(persist=True):
            calls["ensure"] += 1
            return "tab-new"

        saved_once, saved_dead = pipeline._run_feed_once, pipeline._tab_dead
        had_ensure = hasattr(pipeline.cfx, "ensure_tab")
        prev_ensure = getattr(pipeline.cfx, "ensure_tab", None)
        pipeline._run_feed_once = fake_once
        pipeline._tab_dead = lambda: tab_dead
        pipeline.cfx.ensure_tab = fake_ensure
        try:
            posts, err = pipeline.run_feed("linkedin", "http://nav", False)
        finally:
            pipeline._run_feed_once, pipeline._tab_dead = saved_once, saved_dead
            if had_ensure:
                pipeline.cfx.ensure_tab = prev_ensure
            else:
                del pipeline.cfx.ensure_tab
        return posts, err, calls

    def test_retries_once_on_dead_tab(self):
        import pipeline
        posts, err, calls = self._run(
            pipeline, [([], "boom exit 5"), ([{"id": "x"}], None)], tab_dead=True)
        self.assertEqual([p["id"] for p in posts], ["x"])   # retry's result used
        self.assertIsNone(err)
        self.assertEqual(calls["ensure"], 1)                # healed once
        self.assertEqual(calls["run"], 2)                   # exactly one retry

    def test_no_heal_when_tab_alive(self):
        import pipeline
        posts, err, calls = self._run(pipeline, [([], "boom exit 5")], tab_dead=False)
        self.assertEqual(err, "boom exit 5")                # error surfaced, not masked
        self.assertEqual(calls["ensure"], 0)                # no reopen when tab alive
        self.assertEqual(calls["run"], 1)                   # no retry

    def test_no_retry_on_clean_run(self):
        import pipeline
        posts, err, calls = self._run(pipeline, [([{"id": "ok"}], None)], tab_dead=True)
        self.assertEqual(calls["run"], 1)                   # success → no heal probe path
        self.assertEqual(calls["ensure"], 0)


class TestPipelineScreenCap(unittest.TestCase):
    """Silent-cap fix: survivors past --screen-limit are queued UNSCREENED, and the count is
    surfaced (counts.screen_capped) + marked on the row (screen_skipped), not silently dropped."""
    def test_screen_cap_surfaced(self):
        import pipeline, tempfile, types
        survivors = [{"url": f"u{i}", "title": "Product Designer", "company": "C",
                      "verdict": "keep", "eligibility": {"tier": "A"}} for i in range(45)]
        saved = (pipeline.sp.plan, pipeline.run_feed,
                 pipeline.merge_sources.merge_lists, pipeline.pc.precheck,
                 sys.modules.get("jd"))
        pipeline.sp.plan = lambda **k: {"verdict": "WORK", "login_blocked": set(),
                                        "clear": [{"board": "linkedin", "query": "q", "nav": ""}],
                                        "applied_today": 0, "target": 10}
        pipeline.run_feed = lambda *a, **k: ([], None)
        pipeline.merge_sources.merge_lists = lambda posts, **k: (
            survivors, {"in": 0, "out": 45, "dupes": 0, "tracked_dropped": 0, "no_key": 0})
        pipeline.pc.precheck = lambda cands: {"keep": survivors, "review": [], "drop": []}
        jdmod = types.ModuleType("jd")
        jdmod.screen_one = lambda url, **k: {"jd_text_full_len": 500}
        jdmod.compact = lambda d: {"ok": 1}
        sys.modules["jd"] = jdmod
        tmp = os.path.join(tempfile.mkdtemp(), "queue.jsonl")
        try:
            result, code = pipeline.run(screen_limit=40, out_path=tmp)
        finally:
            (pipeline.sp.plan, pipeline.run_feed, pipeline.merge_sources.merge_lists,
             pipeline.pc.precheck) = saved[:4]
            if saved[4] is not None:
                sys.modules["jd"] = saved[4]
            else:
                sys.modules.pop("jd", None)
        self.assertEqual(result["counts"]["screened"], 40)
        self.assertEqual(result["counts"]["screen_capped"], 5)   # 45 - 40, surfaced not dropped
        # the 5 capped rows are in the queue, marked, jd unset
        capped = [ln for ln in open(tmp, encoding="utf-8")
                  if '"screen_skipped": "screen-limit"' in ln]
        self.assertEqual(len(capped), 5)


class TestJdLocationSignal(unittest.TestCase):
    """jd.extract's london signal must be word-bounded (Londonderry/New London != London)."""
    def _extract_with_text(self, jd_text):
        import json as _json, jd
        payload = _json.dumps({"jd_text": jd_text, "title": "Data Analyst", "requirements": [],
                               "h1": "", "meta": {}, "form": {}, "hidden_raw": []})
        orig = _cfx.evaluate
        _cfx.evaluate = lambda expr, *a, **k: payload
        try:
            return jd.extract()
        finally:
            _cfx.evaluate = orig

    def test_london_word_boundary(self):
        self.assertFalse(self._extract_with_text("based in Londonderry")["location_signals"]["london"])
        self.assertFalse(self._extract_with_text("New London, CT")["location_signals"]["london"])
        self.assertTrue(self._extract_with_text("based in South London")["location_signals"]["london"])


class TestSearchPlanPerf(unittest.TestCase):
    """G.3: plan() parses each cooldown CSV ONCE for the whole pass, not once per search."""
    def test_plan_reads_cooldown_csvs_once_not_per_search(self):
        import board_cooldown as bc, search_plan
        counts = {"r": 0, "y": 0}
        orig_r, orig_y = bc._read_rows, bc._read_yield_rows
        bc._read_rows = lambda *a, **k: (counts.__setitem__("r", counts["r"] + 1) or orig_r(*a, **k))
        bc._read_yield_rows = lambda *a, **k: (counts.__setitem__("y", counts["y"] + 1) or orig_y(*a, **k))
        try:
            searches = [{"board": "linkedin", "query": f"q{i}", "nav": ""} for i in range(20)]
            r = search_plan.plan(searches=searches, holds=[], count_applied=False)
        finally:
            bc._read_rows, bc._read_yield_rows = orig_r, orig_y
        self.assertEqual(r["verdict"], "WORK")
        self.assertLessEqual(counts["r"], 1, "board-cooldown.csv read per search, not once")
        self.assertLessEqual(counts["y"], 1, "search-yields.csv read per search, not once")


class TestScreenerMemo(unittest.TestCase):
    """G.2: _rows memoized on mtime + _compiled caches; record() (bumps mtime) invalidates."""
    def setUp(self):
        import screener, tempfile
        self.s = screener
        self._orig = screener.CSV
        self._dir = tempfile.mkdtemp()
        screener.CSV = os.path.join(self._dir, "sc.csv")
        screener._rows_cached.cache_clear()
        screener._compiled.cache_clear()
        screener.seed()

    def tearDown(self):
        import shutil
        self.s.CSV = self._orig
        self.s._rows_cached.cache_clear()
        self.s._compiled.cache_clear()
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_memoized_and_record_invalidates(self):
        import time
        self.assertIs(self.s._rows(), self.s._rows())                 # stable file → memoized
        self.assertIs(self.s._compiled("a.*b"), self.s._compiled("a.*b"))
        self.assertEqual(self.s.lookup("legally authorized to work")["answer"], "Yes")
        self.s.record("unicorn wrangler", "Yes", "radio")
        os.utime(self.s.CSV, (time.time() + 2, time.time() + 2))       # ensure mtime advances
        self.assertEqual(self.s.lookup("are you a unicorn wrangler")["answer"], "Yes")


class TestCompanyCache(unittest.TestCase):
    """G.1: put() is a locked, atomic read-modify-write (no lost rows / torn reads)."""
    def setUp(self):
        import company_cache, tempfile
        self.cc = company_cache
        self._orig = company_cache.CSV
        self._dir = tempfile.mkdtemp()
        company_cache.CSV = os.path.join(self._dir, "company-cache.csv")

    def tearDown(self):
        import shutil
        self.cc.CSV = self._orig
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_put_get_roundtrip_normalized_atomic(self):
        self.assertTrue(self.cc.put("Acme Ltd.", "builds rockets", "careers", "2026-01-01"))
        self.assertEqual(self.cc.get("ACME"), "builds rockets")   # Ltd/case collide
        self.assertTrue(self.cc.put("Acme", "now builds boats"))  # rewrite path, one row
        self.assertEqual(self.cc.get("acme ltd"), "now builds boats")
        self.assertIsNone(self.cc.get("Nobody Inc"))
        # atomic_write leaves no stray temp file
        self.assertEqual([f for f in os.listdir(self._dir) if f.startswith(".tmp-")], [])


class TestLoadSeen(unittest.TestCase):
    """Shared feed pre-source dedup (precheck.load_seen) — was duplicated 5× per feed.
    Regex over RAW lines so a malformed/quoted tracker row can't break dedup (which would
    resurface an already-applied posting → duplicate application)."""
    def test_extract_and_quote_proof_and_missing(self):
        import precheck, tempfile
        d = tempfile.mkdtemp()
        t = os.path.join(d, "tracker.csv")
        with open(t, "w", encoding="utf-8") as f:
            f.write("Date,Company,Role,Source,URL,Status,Next Action,Notes\n")
            f.write("2026-01-01,Hackney,Designer,H,"
                    "https://recruitment.hackney.gov.uk/vacancy/ux-designer-123/,Applied,,\n")
            # a badly-quoted row must NOT blow up the raw-line scan
            f.write('2026-01-02,"Broken,Co,Analyst,H,'
                    "https://recruitment.hackney.gov.uk/vacancy/data-analyst-456/,Skipped,,\n")
        seen = precheck.load_seen(r"recruitment\.hackney\.gov\.uk/vacancy/([a-z0-9-]+)", tracker=t)
        self.assertEqual(seen, {"ux-designer-123", "data-analyst-456"})
        # missing file → empty set, no crash
        self.assertEqual(precheck.load_seen(r"x(\d+)", tracker=os.path.join(d, "nope.csv")), set())


class TestShellScriptsSyntax(unittest.TestCase):
    """`bash -n` (parse only, no execution) on every shared shell script — the sole
    automated guard for cfx.sh/make-pdf.sh/prerender/upload/fix-perms/board-cooldown,
    where a syntax slip breaks every hand-driven browser action or PDF render at
    runtime. Pure parse: touches no network/browser, so it's safe and deterministic."""
    def test_common_shell_scripts_parse(self):
        import glob
        import shutil
        import subprocess
        if not shutil.which("bash"):
            self.skipTest("bash not available")
        scripts = sorted(glob.glob(os.path.join(_SCRIPTS, "*.sh")))
        self.assertTrue(scripts, "no shell scripts found to check")
        failures = []
        for f in scripts:
            r = subprocess.run(["bash", "-n", f], capture_output=True, text=True)
            if r.returncode != 0:
                tail = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "?"
                failures.append(f"{os.path.basename(f)}: {tail}")
        self.assertEqual(failures, [], "shell syntax errors -> " + " | ".join(failures))


class TestAdaptiveCooldown(unittest.TestCase):
    """2026-07-15 perf work: yield history drives an ESCALATING cooldown on repeated
    dryness (12h × 2^(dry-1), cap 72h) and a SHORT one for a just-dried high-yield row."""
    def setUp(self):
        self._t1 = tempfile.NamedTemporaryFile(suffix=".csv", delete=False); self._t1.close()
        self._t2 = tempfile.NamedTemporaryFile(suffix=".csv", delete=False); self._t2.close()
        self._ol, self._oy = bc.LOG, bc.YIELDS
        bc.LOG, bc.YIELDS = self._t1.name, self._t2.name

    def tearDown(self):
        bc.LOG, bc.YIELDS = self._ol, self._oy
        os.unlink(self._t1.name); os.unlink(self._t2.name)

    def test_escalating_backoff_on_repeated_dry(self):
        for _ in range(1):
            bc.record_yield("linkedin", "dead", 0)
        self.assertEqual(bc.consecutive_dry("linkedin", "dead"), 1)
        self.assertEqual(bc.adaptive_hours("linkedin", "dead"), 12.0)   # 12×2^0
        bc.record_yield("linkedin", "dead", 0)
        self.assertEqual(bc.adaptive_hours("linkedin", "dead"), 24.0)   # 12×2^1
        bc.record_yield("linkedin", "dead", 0)
        self.assertEqual(bc.adaptive_hours("linkedin", "dead"), 48.0)   # 12×2^2
        bc.record_yield("linkedin", "dead", 0)
        self.assertEqual(bc.adaptive_hours("linkedin", "dead"), 72.0)   # 12×2^3 -> cap

    def test_hot_row_gets_short_cooldown(self):
        for n in (9, 7, 5):
            bc.record_yield("linkedin", "hot", n)
        bc.record_yield("linkedin", "hot", 0)                # first dry after a hot run
        self.assertEqual(bc.consecutive_dry("linkedin", "hot"), 1)
        self.assertLessEqual(bc.adaptive_hours("linkedin", "hot"), 6.0)

    def test_productive_pass_resets_streak(self):
        bc.record_yield("indeed", "q", 0)
        bc.record_yield("indeed", "q", 3)                    # produced -> streak resets
        self.assertEqual(bc.consecutive_dry("indeed", "q"), 0)
        self.assertGreater(bc.expected_yield("indeed", "q"), 0.0)

    def test_mark_adaptive_only_cools_dry(self):
        self.assertEqual(bc.mark_adaptive("wttj", "home", 5), "")        # productive -> not cooled
        self.assertEqual(bc.remaining_hours("wttj", "home"), 0.0)
        self.assertTrue(bc.mark_adaptive("wttj", "home", 0))             # dry -> cooled
        self.assertGreater(bc.remaining_hours("wttj", "home"), 0.0)


class TestSearchPlan(unittest.TestCase):
    """The single verdict function shared by loop-preflight.py and pipeline.py."""
    def setUp(self):
        import search_plan
        self.sp = search_plan
        self._searches = [{"board": "linkedin", "query": "a", "nav": ""},
                          {"board": "indeed", "query": "b", "nav": ""}]
        # neutralize on-disk state so verdicts are deterministic
        self._orh, self._oey = bc.remaining_hours, bc.expected_yield
        bc.remaining_hours = lambda b, q, now=None, rows=None: 0.0
        bc.expected_yield = lambda b, q, lookback=5, yield_rows=None: 0.0
        self._oat = search_plan.applied_today
        search_plan.applied_today = lambda tracker=None, day=None: 0

    def tearDown(self):
        bc.remaining_hours, bc.expected_yield = self._orh, self._oey
        self.sp.applied_today = self._oat

    def test_work_when_clear(self):
        r = self.sp.plan(searches=self._searches, holds=[])
        self.assertEqual(r["verdict"], "WORK")
        self.assertEqual(len(r["clear"]), 2)

    def test_done_when_target_met(self):
        self.sp.applied_today = lambda tracker=None, day=None: 10
        r = self.sp.plan(searches=self._searches, holds=[], target=10)
        self.assertEqual(r["verdict"], "DONE")

    def test_captcha_hold_beats_everything(self):
        r = self.sp.plan(searches=self._searches,
                         holds=[{"type": "captcha", "site": "x", "role": "", "url": "", "note": ""}])
        self.assertEqual(r["verdict"], "HOLD")

    def test_login_hold_skips_only_that_site(self):
        r = self.sp.plan(searches=self._searches,
                         holds=[{"type": "login", "site": "linkedin", "role": "", "url": "", "note": ""}])
        self.assertEqual(r["verdict"], "WORK")
        self.assertEqual([s["board"] for s in r["clear"]], ["indeed"])

    def test_done_reports_available_inventory_not_exhaustion(self):
        """Footgun fix: when the target is met but searches are still CLEAR, DONE must say so
        (clear_available>0 + a 'raise APPLY_TARGET' note) instead of looking like exhaustion."""
        import search_plan as sp2, board_cooldown as bc2
        saved = (bc2.remaining_hours, bc2.daily_limit_active, bc2.expected_yield,
                 bc2._read_rows, bc2._read_yield_rows, sp2.applied_today)
        bc2.remaining_hours = lambda *a, **k: 0            # nothing cooling
        bc2.daily_limit_active = lambda *a, **k: False
        bc2.expected_yield = lambda *a, **k: 5.0
        bc2._read_rows = lambda: []
        bc2._read_yield_rows = lambda: []
        sp2.applied_today = lambda tracker=None, day=None: 50   # well over target
        try:
            searches = [{"board": "linkedin", "query": "q", "nav": ""},
                        {"board": "indeed", "query": "q2", "nav": ""}]
            out = sp2.plan(searches=searches, holds=[], target=10)
        finally:
            (bc2.remaining_hours, bc2.daily_limit_active, bc2.expected_yield,
             bc2._read_rows, bc2._read_yield_rows, sp2.applied_today) = saved
        self.assertEqual(out["verdict"], "DONE")
        self.assertEqual(out["clear_available"], 2)        # inventory surfaced, not hidden
        self.assertIn("APPLY_TARGET", out["note"])         # actionable guidance
        self.assertIn("not exhausted", out["note"].lower())  # explicitly says it's NOT dry

    def test_sleep_when_all_cooling(self):
        # all real queries cooling, but the daily-limit key is unset (else every board would
        # be rate-limit-skipped and the plan couldn't compute a soonest wake time).
        bc.remaining_hours = lambda b, q, now=None, rows=None: (
            0.0 if q == bc.DAILY_LIMIT_KEY else 5.0)
        r = self.sp.plan(searches=self._searches, holds=[])
        self.assertEqual(r["verdict"], "SLEEP")
        self.assertTrue(r["wake_at"])

    def test_clear_ordered_by_expected_yield(self):
        ey = {("indeed", "b"): 9.0, ("linkedin", "a"): 1.0}
        bc.expected_yield = lambda b, q, lookback=5, yield_rows=None: ey.get((b, q), 0.0)
        r = self.sp.plan(searches=self._searches, holds=[])
        self.assertEqual([s["board"] for s in r["clear"]], ["indeed", "linkedin"])


class TestPipelineHelpers(unittest.TestCase):
    def setUp(self):
        import pipeline
        self.p = pipeline

    def test_family_classification(self):
        cases = {"Senior UX Researcher": "research", "Content Designer": "content",
                 "QA Test Analyst": "qa", "Service Desk Analyst": "support",
                 "DevOps Engineer": "devops", "Digital Content Officer": "digital",
                 "Product Owner": "product", "Prompt Engineer": "ai",
                 "Frontend Developer": "engineering", "Product Designer": "design",
                 "": "design"}
        for title, fam in cases.items():
            self.assertEqual(self.p.family_of(title), fam, title)

    def test_ats_hint(self):
        self.assertEqual(self.p.ats_hint("https://boards.greenhouse.io/x", "indeed"), "greenhouse")
        self.assertEqual(self.p.ats_hint("https://www.linkedin.com/jobs/view/1", "linkedin"),
                         "linkedin-easyapply")
        self.assertEqual(self.p.ats_hint("https://x.myworkdayjobs.com/y", "csj"), "workday")

    def test_feed_stdout_tolerant_parse(self):
        self.assertEqual(self.p._parse_feed_stdout('clear: no modal open.\n[{"id":"1"}]'),
                         [{"id": "1"}])
        self.assertEqual(self.p._parse_feed_stdout("garbage"), [])
        self.assertEqual(self.p._parse_feed_stdout('[{"a":1}] trailing'), [{"a": 1}])

    def test_apply_rank_uses_stats(self):
        self.assertLess(self.p.apply_rank("greenhouse", {"greenhouse": 1.0}),
                        self.p.apply_rank("greenhouse", {}))          # proven-good floats up
        self.assertGreater(self.p.apply_rank("greenhouse", {"greenhouse": 0.0}),
                           self.p.apply_rank("greenhouse", {}))       # proven-bad sinks


class TestScreenerBank(unittest.TestCase):
    """The shared answer bank: specific-before-generic ordering and regex patterns are
    load-bearing (a mis-order silently answers the wrong number). Uses the seed rows
    (no CSV) so it's deterministic and doesn't touch the real screener-answers.csv."""
    @classmethod
    def setUpClass(cls):
        import screener
        cls.s = screener
        cls._orig = screener.CSV
        screener.CSV = "/nonexistent-screener-test.csv"   # force _rows() to use _SEED

    @classmethod
    def tearDownClass(cls):
        cls.s.CSV = cls._orig

    def a(self, q):
        h = self.s.lookup(q)
        return h["answer"] if h else None

    def test_sponsorship_and_rtw(self):
        self.assertEqual(self.a("Do you require visa sponsorship?"), "No")
        self.assertEqual(self.a("Are you legally authorized to work in the UK?"), "Yes")

    def test_years_specific_beats_generic(self):
        self.assertEqual(self.a("How many years of experience with Figma?"), "6")
        self.assertEqual(self.a("Years of UX research experience?"), "5")
        self.assertEqual(self.a("How many years of DevOps experience?"), "3")
        self.assertEqual(self.a("How many years of experience overall?"), "5")  # generic

    def test_disclose_exceptions(self):
        # The committed seed ships neutral placeholders ("Prefer not to say"); the point
        # here is that the pronoun/age QUESTIONS still MATCH a rule (fire, non-None) — the
        # actual value is whatever the user sets in their (gitignored) screener-answers.csv.
        self.assertIsNotNone(self.a("What are your pronouns?"))
        self.assertIsNotNone(self.a("How old are you?"))

    def test_driving_truthful(self):
        self.assertEqual(self.a("Do you hold a full UK driving licence?"), "No")

    def test_unknown_returns_none(self):
        self.assertIsNone(self.a("What is your favourite colour?"))

    def test_no_substring_false_cognates(self):
        # a plain pattern must not embed as a SUFFIX of a larger word (naive `p in q`):
        # "city"⊄"ethni-city", "location"⊄"re-location", "gender"⊄"trans-gender".
        self.assertNotEqual(self.a("What is your ethnicity?"), "London")     # 'city' pattern
        self.assertNotEqual(self.a("Are you open to relocation?"), "London")  # 'location'
        self.assertIsNone(self.a("Are you transgender?"))                     # 'gender' must NOT suffix-match
        # but a leading-boundary match with a trailing suffix STILL works (plural/stem):
        self.assertIsNotNone(self.a("What are your pronouns?"))              # 'pronoun' -> pronouns fires
        self.assertEqual(self.a("Which city are you based in?"), "London")    # genuine 'city'

    def test_regex_vs_substring(self):
        self.assertTrue(self.s._matches("/years.*figma/", "how many years with figma"))
        self.assertFalse(self.s._matches("/years.*figma/", "figma then years"))
        self.assertTrue(self.s._matches("right to work", "do you have the right to work here"))


class TestWttjSendOutcomes(unittest.TestCase):
    """WTTJ send() must distinguish sent / EXTERNAL_FALLBACK / unclear. WTTJ's backend fails
    to relay in-platform applications to external ATSes (e.g. Maze→Ashby) with "We can't
    submit your application right now" — this was the true cause of the old "Send lands, no
    confirmation" reports and was mis-classified as unclear (rc 2), so the loop never routed
    to the company ATS. It must now return rc 3 so the caller runs open-external."""
    import types as _t

    def _load(self):
        import importlib.util
        p = os.path.join(_HERE, "..", "sites", "welcometothejungle", "scripts", "apply.py")
        spec = importlib.util.spec_from_file_location("wttj_apply_test", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _fake_time(self, step=5):
        import itertools
        ticks = itertools.count(0, step)
        return types.SimpleNamespace(time=lambda: next(ticks), sleep=lambda *a, **k: None)

    def test_regex_classification(self):
        import re
        m = self._load()
        self.assertTrue(re.search(m._SENT_OK, "We're rooting for you!", re.I))
        self.assertTrue(re.search(m._SENT_OK, "we've sent your application", re.I))
        self.assertTrue(re.search(m._CANT_SUBMIT, "We can't submit your application right now", re.I))
        self.assertTrue(re.search(m._CANT_SUBMIT, "Sorry, we couldn't submit your application to Maze", re.I))
        # an in-progress form is neither success nor the external-fallback error
        self.assertFalse(re.search(m._SENT_OK, "1 section left", re.I))
        self.assertFalse(re.search(m._CANT_SUBMIT, "1 section left", re.I))

    def test_send_external_fallback_is_rc3(self):
        m = self._load()
        m._send_enabled = lambda: True
        m._click_text = lambda *a, **k: "clicked"
        m.time = self._fake_time()

        def fake_eval(js, *a, **k):
            j = (js or "").lower()
            if "apply on" in j and "website" in j:
                return "Apply on Maze's website"
            if "innertext" in j:
                return "Sorry, we couldn't submit your application to Maze"
            return None
        m.cfx.evaluate = fake_eval
        self.assertEqual(m.send(), 3)

    def test_send_success_is_rc0(self):
        m = self._load()
        m._send_enabled = lambda: True
        m._click_text = lambda *a, **k: "clicked"
        m.time = self._fake_time()
        m.cfx.evaluate = lambda js, *a, **k: ("We're rooting for you!" if "innertext" in (js or "").lower() else None)
        self.assertEqual(m.send(), 0)

    def test_resolve_applied_noop_without_toast(self):
        m = self._load()
        m.time = self._fake_time()
        m.cfx.evaluate = lambda *a, **k: "a page with no such prompt"
        self.assertEqual(m.resolve_applied_prompt(True), 1)

    def test_resolve_applied_clicks_yes(self):
        m = self._load()
        m.time = self._fake_time()
        clicked = {}
        # first innerText read shows the toast; after the click, it's gone.
        state = {"toast": True}

        def fake_eval(js, *a, **k):
            j = (js or "").lower()
            if "innertext" in j:
                return "Did you apply?" if state["toast"] else "next job"
            if "dispatchevent" in j or "queryselectorall('button')" in j:
                clicked["yes"] = "^yes$" in j.replace(" ", "").lower() or "yes" in j.lower()
                state["toast"] = False   # the click clears it
                return "clicked"
            return None
        m.cfx.evaluate = fake_eval
        self.assertEqual(m.resolve_applied_prompt(True), 0)
        self.assertTrue(clicked.get("yes"))


class TestHttpFeedHelpers(unittest.TestCase):
    """httpfeed.py is the shared runtime EVERY new board feed is built on — a regression in
    one of these pure helpers silently corrupts a dozen feeds at once, so they're locked here."""
    def _m(self):
        import httpfeed
        return httpfeed

    def test_clean_strips_tags_entities_and_whitespace(self):
        h = self._m()
        self.assertEqual(h.clean("  <b>UX</b>&nbsp;Designer\n\n "), "UX Designer")
        self.assertEqual(h.clean("&pound;30,000 &amp; up"), "£30,000 & up")
        self.assertEqual(h.clean("&#163;45,000"), "£45,000")
        self.assertEqual(h.clean(None), "")
        self.assertEqual(h.clean(""), "")

    def test_clean_decodes_hex_entities(self):
        """REGRESSION: clean() decoded named + decimal but NOT hex, so GOV.UK's
        `&#xA3;` leaked through and salaries rendered as "&#xA3;19,747" (hit
        independently by the apprenticeships and Escape the City feeds)."""
        h = self._m()
        self.assertEqual(h.clean("&#xA3;19,747"), "£19,747")
        self.assertEqual(h.clean("&#x2019;"), "\u2019")
        self.assertEqual(h.clean("&#xa3;30,000 to &#xA3;40,000"), "£30,000 to £40,000")

    def test_absolutise(self):
        h = self._m()
        b = "https://x.com"
        self.assertEqual(h.absolutise("/job/1", b), "https://x.com/job/1")
        self.assertEqual(h.absolutise("https://y.com/j#frag", b), "https://y.com/j")
        self.assertEqual(h.absolutise("//cdn.z/j", b), "https://cdn.z/j")
        self.assertEqual(h.absolutise("", b), "")

    def test_money_formats_and_tolerates_junk(self):
        h = self._m()
        self.assertEqual(h.money(30000, 40000), "£30,000–£40,000")
        self.assertEqual(h.money(30000, 30000), "£30,000")   # equal min/max collapses
        self.assertEqual(h.money(30000, None), "£30,000")
        self.assertEqual(h.money(None, None), "")
        self.assertEqual(h.money("junk", None), "")
        self.assertEqual(h.money(50000, 60000, cur="$"), "$50,000–$60,000")

    def test_jsonpath_never_raises(self):
        h = self._m()
        row = {"company": {"name": "Acme"}, "tags": ["a", "b"]}
        self.assertEqual(h.jsonpath(row, "company", "name"), "Acme")
        self.assertEqual(h.jsonpath(row, "company", "missing"), "")
        self.assertEqual(h.jsonpath(row, "nope", "deep", "deeper"), "")
        self.assertEqual(h.jsonpath(row, "tags", 1), "b")
        self.assertEqual(h.jsonpath(row, "tags", 9), "")
        self.assertEqual(h.jsonpath(None, "a"), "")

    def test_query_param_case_insensitive(self):
        h = self._m()
        u = "https://b.com/search?Keywords=UX+Designer&Where=London"
        self.assertEqual(h.query_param(u, "keywords"), "UX Designer")
        self.assertEqual(h.query_param(u, "where"), "London")
        self.assertEqual(h.query_param(u, "absent"), "")
        self.assertEqual(h.query_param("", "q"), "")

    def test_ld_json_and_next_data_tolerate_garbage(self):
        h = self._m()
        good = '<script type="application/ld+json">{"@type":"JobPosting","title":"X"}</script>'
        self.assertEqual(h.ld_json(good)[0]["title"], "X")
        bad = '<script type="application/ld+json">{not json</script>'
        self.assertEqual(h.ld_json(bad), [])          # malformed blob must not raise
        self.assertEqual(h.ld_json(""), [])
        nd = '<script id="__NEXT_DATA__" type="application/json">{"props":{"n":1}}</script>'
        self.assertEqual(h.next_data(nd)["props"]["n"], 1)
        self.assertEqual(h.next_data("<html></html>"), {})

    def test_deep_find_locates_nested_dicts(self):
        h = self._m()
        blob = {"a": {"b": [{"jobId": 1}, {"jobId": 2}]}, "c": {"jobId": 3}}
        found = h.deep_find(blob, lambda d: "jobId" in d)
        self.assertEqual(sorted(d["jobId"] for d in found), [1, 2, 3])

    def test_board_spec_defaults(self):
        h = self._m()
        b = h.Board(board="x", name="X", base="https://x.com",
                    search_url=lambda w, r, p: "u", parse=lambda t, c: [],
                    normalize=lambda r, c: None, seen_pattern=r"x/(\d+)")
        self.assertEqual(b.fetch, "http")            # browser-free by default
        self.assertIsNone(b.needs())                 # no credential requirement by default
        self.assertTrue(b.apply_hint)                # always has an agent-facing hint


class TestAtsDirectFeed(unittest.TestCase):
    """ATS-direct: the feed that sources straight from account-less employer ATSes. Its
    per-ATS row mappers and the London/remote gate are pure — locked here (no network)."""
    def _load(self):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "atsdirect_feed", os.path.join(root, "sites", "ats-direct", "scripts", "feed.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_greenhouse_rows(self):
        m = self._load()
        co = {"slug": "monzo", "name": "Monzo", "ats": "greenhouse", "sector": "fintech"}
        payload = {"jobs": [{"id": 7564605, "title": "Product Designer",
                             "absolute_url": "https://job-boards.greenhouse.io/monzo/jobs/7564605",
                             "location": {"name": "London"}, "updated_at": "2026-07-15T10:00:00Z"},
                            {"title": "no id — dropped"}]}
        rows = list(m.gh_rows(payload, co))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "greenhouse:monzo:7564605")
        self.assertEqual(rows[0]["company"], "Monzo")
        self.assertEqual(rows[0]["location"], "London")
        self.assertEqual(rows[0]["ats_hint"], "greenhouse")   # names the driver to use
        self.assertEqual(rows[0]["created"], "2026-07-15")

    def test_lever_ashby_workable_rows(self):
        m = self._load()
        co = {"slug": "s", "name": "S", "ats": "x", "sector": ""}
        lv = list(m.lv_rows([{"id": "abc", "text": "UX Designer",
                              "hostedUrl": "https://jobs.lever.co/s/abc",
                              "categories": {"location": "London", "commitment": "Full-time"}}], co))
        self.assertEqual(lv[0]["id"], "lever:s:abc")
        self.assertEqual(lv[0]["title"], "UX Designer")
        ab = list(m.ab_rows({"jobs": [{"id": "u1", "title": "Designer", "location": "Remote",
                                       "isRemote": True, "jobUrl": "https://jobs.ashbyhq.com/s/u1",
                                       "publishedAt": "2026-07-10T00:00:00Z"}]}, co))
        self.assertEqual(ab[0]["id"], "ashby:s:u1")
        self.assertTrue(ab[0]["_remote"])
        wk = list(m.wk_rows({"jobs": [{"shortcode": "ABC123", "title": "IT Support",
                                       "city": "London", "country": "UK",
                                       "telecommuting": False}]}, co))
        self.assertEqual(wk[0]["id"], "workable:s:ABC123")
        self.assertEqual(wk[0]["location"], "London UK")

    def test_row_mappers_tolerate_garbage(self):
        m = self._load()
        co = {"slug": "s", "name": "S", "ats": "x", "sector": ""}
        for fn, junk in ((m.gh_rows, {}), (m.ab_rows, {"jobs": None}), (m.lv_rows, {}),
                         (m.wk_rows, {"jobs": []}), (m.sr_rows, {}), (m.rc_rows, {})):
            self.assertEqual(list(fn(junk, co)), [])

    def test_is_remote_and_where_gate(self):
        m = self._load()
        self.assertTrue(m.is_remote({"location": "Remote (UK)"}))
        self.assertTrue(m.is_remote({"location": "", "_remote": True}))
        self.assertTrue(m.is_remote({"location": "Work from home"}))
        self.assertFalse(m.is_remote({"location": "Manchester"}))
        # London matches; remote always passes; EMPTY location passes (a false negative here
        # silently drops real inventory — the JD screen catches those later).
        self.assertTrue(m.match_where({"location": "London, UK"}, "London"))
        self.assertTrue(m.match_where({"location": "Remote"}, "London"))
        self.assertTrue(m.match_where({"location": ""}, "London"))
        self.assertFalse(m.match_where({"location": "Berlin"}, "London"))
        self.assertTrue(m.match_where({"location": "Berlin"}, ""))     # empty where disables

    def test_match_what_or_semantics(self):
        m = self._load()
        j = {"title": "Junior UX Designer"}
        self.assertTrue(m.match_what(j, ""))                       # no filter = pass
        self.assertTrue(m.match_what(j, "designer"))
        self.assertTrue(m.match_what(j, "devops OR designer"))     # OR bundle
        self.assertTrue(m.match_what(j, "devops, designer"))       # comma bundle
        self.assertFalse(m.match_what(j, "devops OR sre"))
        self.assertTrue(m.match_what(j, '"ux designer"'))          # quoted = phrase
        self.assertFalse(m.match_what(j, '"senior ux designer"'))

    def test_companies_csv_is_wellformed(self):
        """Every registry row must name a REAL supported ATS and be unique per company —
        a company listed on two ATSes double-sources the same job under two ids."""
        m = self._load()
        cos = m.load_companies()
        self.assertGreater(len(cos), 20, "company registry suspiciously small")
        for c in cos:
            self.assertIn(c["ats"], m.ATS, f"{c['slug']}: unknown ats {c['ats']!r}")
            self.assertTrue(c["name"], f"{c['slug']}: missing name")
        slugs = [c["slug"].lower() for c in cos]
        dupes = {s for s in slugs if slugs.count(s) > 1}
        self.assertEqual(dupes, set(), f"company on 2+ ATSes double-sources: {dupes}")

    def test_every_ats_has_url_and_row_mapper(self):
        m = self._load()
        for name, (url_fn, rows_fn) in m.ATS.items():
            self.assertTrue(callable(url_fn) and callable(rows_fn), name)
            self.assertIn("://", url_fn("slug"))


class TestJobsAcFeed(unittest.TestCase):
    """jobs.ac.uk — the reference declarative feed; its normalize() is the shape every
    httpfeed-based board copies."""
    def _load(self):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "jobsac_feed", os.path.join(root, "sites", "jobs.ac.uk", "scripts", "feed.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_normalize_extracts_card_fields(self):
        m = self._load()
        card = {"advert_id": "1081894", "html": '''
            <div class="j-search-result__text">
              <a href="/job/DSG684/lecturer-in-digital-design"> Lecturer in Digital Design </a>
              <div class="j-search-result__employer"><b>Queen Margaret University</b></div>
              <div>Location: Edinburgh </div>
              <div class="j-search-result__info"><strong>Salary: </strong> £44,746 to £56,535 (Grade 8)</div>
              <div><strong>Date Placed: </strong>15 Jul</div>
            </div>'''}
        r = m.normalize(card, {})
        self.assertEqual(r["id"], "DSG684")             # the stable code, not the advert id
        self.assertEqual(r["url"], "https://www.jobs.ac.uk/job/DSG684/lecturer-in-digital-design")
        self.assertEqual(r["title"], "Lecturer in Digital Design")
        self.assertEqual(r["company"], "Queen Margaret University")
        self.assertEqual(r["location"], "Edinburgh")
        self.assertEqual(r["salary"], "£44,746 to £56,535")   # trailing (Grade 8) trimmed
        self.assertEqual(r["source"], "jobsac")

    def test_normalize_drops_unusable_cards(self):
        m = self._load()
        self.assertIsNone(m.normalize({"html": "<div>no link</div>"}, {}))
        self.assertIsNone(m.normalize({"html": '<a href="/job/X1/s"></a>'}, {}))  # empty title

    def test_search_url_paginates_by_startindex(self):
        from urllib.parse import urlparse, parse_qs
        m = self._load()
        qs = parse_qs(urlparse(m.search_url("ux", "London", 3)).query)
        self.assertEqual(qs["keywords"], ["ux"])
        self.assertEqual(qs["location"], ["London"])
        self.assertEqual(qs["startIndex"], ["51"])      # page 3 @ 25/page => 1-based 51
        self.assertEqual(qs["pageSize"], ["25"])


class TestAtsformResolvePrecedence(unittest.TestCase):
    """REGRESSION (live, Paddle/Ashby 2026-07-17): _RESOLVE took the FIRST loose
    substring hit in DOM order, so `fill "Phone"` wrote the phone number into
    **"Phonetic Pronunciation (Optional)"** — which appears earlier — and left the real
    "Phone" field empty. Silent wrong-data submission, not a crash. Exact/word matches
    must beat incidental substrings. Asserted on the JS source: the matcher runs in the
    browser, so this locks the tiering that implements the rule."""
    def _src(self):
        import atsform
        return atsform._RESOLVE

    def test_resolver_is_tiered_exact_first(self):
        js = self._src()
        self.assertIn("tiers", js, "resolver must rank candidates, not take first hit")
        # exact equality tier must exist and come before the loose `includes` tier
        self.assertIn("lab === want", js)
        self.assertLess(js.index("lab === want"), js.index("lab.includes(want)"),
                        "exact match must be tried before loose substring")

    def test_resolver_normalises_required_and_optional_markers(self):
        js = self._src()
        # "Phone*" / "Phone (Optional)" must still match a want of "phone"
        self.assertIn("optional|required", js)
        self.assertIn("replace(/\\*/g", js)

    def test_resolver_uses_word_boundaries(self):
        js = self._src()
        self.assertIn("\\b", js, "word-boundary matching is what stops Phone~Phonetic")

    def test_python_mirror_of_tiering(self):
        """The tiering rule, expressed in Python over the same inputs — documents and
        pins the intended semantics independently of the JS."""
        def norm(s):
            import re as _re
            s = _re.sub(r"\*", " ", s or "")
            s = _re.sub(r"\((?:optional|required)\)", " ", s, flags=_re.I)
            return _re.sub(r"\s+", " ", s).strip().lower()

        def resolve(labels, want):
            import re as _re
            want = want.lower().strip()
            esc = _re.escape(want)
            tiers = ([], [], [], [])
            for i, raw in enumerate(labels):
                lab = norm(raw)
                if not lab:
                    continue
                if lab == want:
                    tiers[0].append(i)
                elif _re.match(r"^" + esc + r"\b", lab):
                    tiers[1].append(i)
                elif _re.search(r"\b" + esc + r"\b", lab):
                    tiers[2].append(i)
                elif want in lab:
                    tiers[3].append(i)
            for t in tiers:
                if t:
                    return t[0]
            return None

        # the exact live DOM order that caused the bug
        labels = ["Full Name*", "Phonetic Pronunciation (Optional)", "Preferred Pronouns (Optional)",
                  "Email*", "Phone", "What are your annual salary expectations?*"]
        self.assertEqual(resolve(labels, "Phone"), 4)        # NOT 1 (Phonetic…)
        self.assertEqual(resolve(labels, "Full Name"), 0)
        self.assertEqual(resolve(labels, "Email"), 3)
        # exact beats an earlier prefix-match
        self.assertEqual(resolve(["Name of referrer", "Name"], "Name"), 1)
        # word-match still reachable when nothing is exact
        self.assertEqual(resolve(["Annual salary expectations"], "salary"), 0)
        self.assertIsNone(resolve(["Country"], "phone"))


class TestPipelineFeedSpec(unittest.TestCase):
    """FEEDS specs are (subdir, argb) or (subdir, argb, script). The 3rd element exists
    because reed.co.uk ships TWO feeds (browser scraper `feed.py` + official-API
    `feed_api.py`); without it the API feed is unroutable from the loop."""
    def test_every_feed_resolves_to_a_real_script(self):
        import pipeline
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        missing = []
        for name, spec in pipeline.FEEDS.items():
            self.assertGreaterEqual(len(spec), 2, f"{name}: malformed spec")
            subdir, argb = spec[0], spec[1]
            script = spec[2] if len(spec) > 2 else "feed.py"
            p = os.path.join(root, "sites", subdir, "scripts", script)
            if not os.path.isfile(p):
                missing.append(f"{name} -> {os.path.relpath(p, root)}")
            self.assertTrue(callable(argb), f"{name}: argbuilder not callable")
            argb("https://x/?q=y")            # must not raise
            argb(None)                        # nav-less form must not raise
        self.assertEqual(missing, [], "FEEDS point at missing scripts -> " + "; ".join(missing))

    def test_custom_script_name_is_honoured(self):
        import pipeline
        spec = pipeline.FEEDS["reedapi"]
        self.assertEqual(len(spec), 3)
        self.assertEqual(spec[2], "feed_api.py")
        # and the plain `reed` scraper is still its own, separate entry
        self.assertEqual(len(pipeline.FEEDS["reed"]), 2)

    def test_new_channels_are_registered(self):
        import pipeline
        for slug in ("atsdirect", "jobsac", "gchq", "jgp", "himalayas", "mbw", "hackajob"):
            self.assertIn(slug, pipeline.FEEDS, f"{slug} missing from FEEDS")


class TestNoHandRolledFunnel(unittest.TestCase):
    """The 'never hand-write a harvester' rule had a loophole: it forbade re-implementing the
    *fetch* layer while explicitly endorsing `feed.py --nav`, so a bash sweep that LOOPS the
    shipped feed.py, greps its stdout JSON and `sort -u`s the result read as compliant. It
    isn't — it re-implements pipeline.run() minus merge_sources (canonical-id dedup) and
    minus precheck (title/seniority screen). These tests keep the closed loophole closed:
    the rule must stay documented, and no tracked script may re-introduce the pattern."""

    def _root(self):
        import subprocess
        try:
            return subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=_HERE,
                                           text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return None

    def _tracked(self, *globs):
        import subprocess
        root = self._root()
        if not root:
            return None, []
        out = []
        for g in globs:
            try:
                listing = subprocess.check_output(["git", "ls-files", g], cwd=root, text=True)
            except Exception:
                continue
            out += [os.path.join(root, p) for p in listing.splitlines() if p.strip()]
        return root, out

    def test_rule_documented_in_both_surfaces(self):
        """SKILL.md and tool-manifest.md both carry the funnel rule. It is mirrored on
        purpose (same reason the CAPTCHA directive is) — deleting either re-opens it."""
        root = self._root()
        if not root:
            self.skipTest("not a git checkout")
        for rel in ("SKILL.md", "references/tool-manifest.md"):
            with open(os.path.join(root, rel), encoding="utf-8") as fh:
                body = fh.read().lower()
            self.assertIn("sort -u", body, f"{rel}: lost the sort-u-is-not-dedup warning")
            self.assertIn("funnel", body, f"{rel}: lost the funnel rule")
            self.assertTrue("searches.csv" in body,
                            f"{rel}: must point at the sanctioned knob (searches.csv row)")

    def test_no_tracked_script_reimplements_the_funnel(self):
        """A committed .sh/.py must not loop feed.py and hand-dedup its stdout."""
        import re
        root, files = self._tracked("*.sh", "*.py")
        if root is None:
            self.skipTest("not a git checkout")
        offenders = []
        for f in files:
            rel = os.path.relpath(f, root)
            if rel.startswith("tests/"):
                continue
            try:
                body = open(f, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            calls_feed = re.search(r"sites/[^\s\"']+/scripts/feed\.py", body) is not None
            if not calls_feed:
                continue
            # the funnel-reimplementation tells
            if re.search(r"sort\s+-u", body):
                offenders.append(f"{rel}: `sort -u` over feed output — use merge_sources "
                                 f"(canonical-id dedup); sort -u dedups JSON strings")
            if re.search(r"raw_decode|\.find\(\s*['\"]\[['\"]\s*\)", body):
                offenders.append(f"{rel}: hand-rolled feed-stdout JSON extraction — use "
                                 f"pipeline._parse_feed_stdout()")
        self.assertEqual(offenders, [],
                         "tracked script re-implements the pipeline funnel -> " + " | ".join(offenders))

    def test_pipeline_is_the_documented_alternative(self):
        """The rule sends you to pipeline.run()/apply_queue.py — they must actually exist
        with the signature the docs promise, or the rule is unfollowable."""
        import inspect
        import pipeline
        sig = inspect.signature(pipeline.run)
        for p in ("only_boards", "force", "no_screen"):
            self.assertIn(p, sig.parameters, f"pipeline.run lost {p!r} — SKILL.md promises it")
        root = self._root()
        if root:
            self.assertTrue(os.path.isfile(os.path.join(root, "scripts", "apply_queue.py")),
                            "apply_queue.py missing — SKILL.md points at it")


class TestParliamentFeed(unittest.TestCase):
    """UK Parliament (MHR iTrent). Pure bits: the 3-stream registry, the session-free
    canonical URL, and card normalisation. No browser/network."""
    def _load(self):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "parliament_feed", os.path.join(root, "sites", "parliament.uk", "scripts", "feed.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_three_streams_registered(self):
        m = self._load()
        self.assertEqual(set(m.TENANTS), {"pds", "commons", "lords"})
        # Lords is a DIFFERENT host + instance path, not just another WVID
        self.assertIn("hrhol", m.TENANTS["lords"]["base"])
        self.assertIn("ce0913li", m.TENANTS["lords"]["base"])
        self.assertIn("hrhoc", m.TENANTS["commons"]["base"])
        self.assertIn("ce0912li", m.TENANTS["pds"]["base"])
        for t in m.TENANTS.values():
            self.assertTrue(t["wvid"] and t["employer"])

    def test_canonical_url_is_session_free_deep_link(self):
        """Must be ETREC179GF + WVID + VACANCY_ID. Never ETREC148GF (the apply/screening
        flow) and never carry USESSION (expires -> dead tracker links)."""
        m = self._load()
        u = m.canonical_url("commons", "4199306Sbb")
        self.assertIn("ETREC179GF.open", u)
        self.assertIn("WVID=3402965kYE", u)
        self.assertIn("VACANCY_ID=4199306Sbb", u)
        self.assertNotIn("USESSION", u)
        self.assertNotIn("ETREC148GF", u)
        self.assertTrue(m.canonical_url("lords", "X1").startswith("https://hrhol."))

    def test_normalize_maps_entry_labels(self):
        m = self._load()
        card = {"id": "4199306Sbb", "title": " Investigations Support Officer ",
                "entries": {"apply by": "27/07/2026", "location": "Hybrid (on-site and remote)",
                            "salary": "Band B1 - \u00a345,359 - \u00a351,885 per annum",
                            "basis": "Full Time"}}
        r = m.normalize(card, "commons")
        self.assertEqual(r["id"], "4199306Sbb")
        self.assertEqual(r["title"], "Investigations Support Officer")
        self.assertEqual(r["location"], "Hybrid (on-site and remote)")
        self.assertEqual(r["closes"], "27/07/2026")
        self.assertEqual(r["basis"], "Full Time")
        self.assertEqual(r["ats_hint"], "mhr-webrec")
        self.assertEqual(r["source"], "parliament")
        self.assertEqual(r["tenant"], "commons")
        self.assertIn("House of Commons", r["company"])
        self.assertIn("VACANCY_ID=4199306Sbb", r["url"])

    def test_normalize_drops_unusable_cards(self):
        m = self._load()
        self.assertIsNone(m.normalize({"id": "", "title": "x", "entries": {}}, "pds"))
        self.assertIsNone(m.normalize({"id": "A1", "title": "", "entries": {}}, "pds"))
        self.assertIsNone(m.normalize({}, "pds"))
        # missing entries must not raise — fields just come back empty
        r = m.normalize({"id": "A1", "title": "T"}, "pds")
        self.assertEqual((r["location"], r["salary"], r["closes"]), ("", "", ""))

    def test_match_what_or_semantics(self):
        m = self._load()
        j = {"title": "Investigations Support Officer"}
        self.assertTrue(m.match_what(j, ""))
        self.assertTrue(m.match_what(j, "support"))
        self.assertTrue(m.match_what(j, "designer OR support"))
        self.assertFalse(m.match_what(j, "designer OR devops"))
        self.assertTrue(m.match_what(j, '"support officer"'))
        self.assertFalse(m.match_what(j, '"senior support officer"'))

    def test_wired_into_pipeline_feeds(self):
        import pipeline
        self.assertIn("parliament", pipeline.FEEDS)
        subdir, argb = pipeline.FEEDS["parliament"][0], pipeline.FEEDS["parliament"][1]
        self.assertEqual(subdir, "parliament.uk")
        # nav is meaningless for an SPA the feed sweeps itself
        self.assertEqual(argb("http://x?q=y"), [])
        self.assertEqual(argb(None), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
