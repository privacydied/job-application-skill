#!/usr/bin/env python3
"""
tailor.py — batch, substitution-based resume/cover-letter tailoring engine.

WHY THIS EXISTS (speed levers 1+3 against slow inference): a real tailored resume
differs from the master by a HANDFUL of substitutions (measured live: the Experian
tailoring was 14 tiny opcodes on an 11.5KB file — a summary rewrite + skills tweaks).
Having the model re-emit the whole single-line HTML blob per posting wastes the
slowest tokens there are (output tokens), and doing it one posting at a time
interleaves "writing mode" and "browser mode" turns. Instead the model writes ONE
small spec JSON covering the WHOLE work list (find/replace substitutions + bullet
drops + cover-letter text per posting) and this script does the mechanical part:
clone master -> apply verified substitutions -> write cover letter -> run the
tailoring checklist -> (optionally) chain-render every PDF in one parallel pass.
One model turn tailors + renders N postings.

It also sidesteps the known single-line-blob trap (references/resume-assets.md):
`find` strings are verbatim substring matches on the blob, verified to occur an
exact expected count — never line-based patching.

CLI:
  tailor.py apply <spec.json> [--render]   tailor every posting in the spec; with
                                           --render, chain prerender-pdfs.sh on the
                                           dirs that tailored cleanly (resume.pdf)
  tailor.py find "<substring>"             locate verbatim text in the master blob
                                           (prints occurrence count + surrounding
                                           context) — use this to compose exact
                                           `find` strings instead of dump-and-slice

Spec JSON — a {"postings":[...]} object or a bare list. Per posting:
  {
    "dir": "applications/<company>-<role>",   # created if missing
    "company": "Acme",                        # for the cover-letter checks
    "subs": [                                  # verbatim find/replace on the master
      {"find": "<exact substring of master>", "replace": "<new text>"},
      {"find": "...", "replace": "...", "count": 2}   # expected occurrences (default 1)
    ],
    "drop": ["unique substring inside a bullet"],     # removes the enclosing <li>…</li>
    "cover": "@cover.txt OR inline letter text",      # -> <dir>/cover-letter.md (optional)
    "must_haves": ["design systems", "Figma"]         # advisory keyword check (WARN)
  }

Checks per posting (FAIL blocks --render for that dir; WARN doesn't):
  FAIL: a `find`/`drop` string missing or ambiguous (wrong occurrence count);
        surviving [bracketed] placeholder in resume visible text or cover letter;
        cover letter mentions the company < 2 times, or mentions a DIFFERENT
        tracked company (wrong-company letter is the #1 autonomous failure).
  WARN: cover letter outside 150–250 words; a must_have keyword absent from both
        the resume visible text and the cover letter.

Substitutions apply IN ORDER; each `find` is matched against the already-partly-
tailored text, so a later sub may target text a previous sub introduced.
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stagetimer  # noqa: E402  (no-op unless STAGETIMER is set)

PLACEHOLDER = re.compile(r"\[[A-Za-z][^\]]*\]")


def _root():
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isfile(os.path.join(d, "SKILL.md")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        d = parent


def master_path():
    """Path to the master resume HTML.

    Resolution order (first hit wins):
      1. $RESUME_MASTER — explicit override (absolute, or relative to the skill root).
      2. The single `*-resume.html` at the skill root — the real user's master, whatever
         they are called.
      3. `jane-doe-resume.html` — the shipped placeholder / example name.

    WHY: this used to hard-code the placeholder name, so tailoring was silently broken for
    every real user (their master is `<their-name>-resume.html`) — `tailor.py find` and
    `apply` both failed with "cannot read master resume". The glob makes the engine work
    out of the box for anyone who dropped their own master in, with no config.
    If several `*-resume.html` files exist the choice would be ambiguous, so we require
    $RESUME_MASTER rather than guess.
    """
    import glob
    root = _root()
    env = os.environ.get("RESUME_MASTER")
    if env:
        return env if os.path.isabs(env) else os.path.join(root, env)
    found = sorted(glob.glob(os.path.join(root, "*-resume.html")))
    real = [f for f in found if os.path.basename(f) != "jane-doe-resume.html"]
    if len(real) == 1:
        return real[0]
    if len(real) > 1:
        raise SystemExit(
            "FAIL: several master resumes at the skill root (%s) — set RESUME_MASTER to "
            "the one to tailor." % ", ".join(os.path.basename(f) for f in real))
    return os.path.join(root, "jane-doe-resume.html")


def _family_data():
    """Load sites/_common/family-bases.json (anchor + per-family summary/cover_fit).
    The real file holds YOUR career positioning and is gitignored; a fresh clone ships
    only family-bases.example.json — fall back to it so tailoring still works (with
    placeholder copy) until you create your own. Returns {} if neither exists."""
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    for name in ("family-bases.json", "family-bases.example.json"):
        p = os.path.join(base, name)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                return {}
    return {}


def family_sub(family):
    """A one-element subs LIST (`[{find, replace}]`, apply_subs shape) that swaps the
    master summary for `family`'s positioning, or None. Applied BEFORE the per-posting
    subs so a posting only needs its company-specific tweaks — the family already leads
    with the right positioning (Tier-2 per-family bases)."""
    fam = (family or "").strip().lower()
    data = _family_data()
    fams = data.get("families", {})
    if fam not in fams or not data.get("_anchor"):
        return None
    return [{"find": data["_anchor"], "replace": fams[fam]["summary"]}]


def visible_text(html):
    """Approximate human-visible text: strip <style>/<script> blocks (their CSS/JS
    is textContent, not markup, so a bare tag-strip would leak selectors like
    `[class]` into the placeholder scan), then strip tags."""
    html = re.sub(r"<(style|script)\b[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", html)


def _tracker_companies():
    """Reuse atsform's tracker-derived company set for the wrong-company check
    (same semantics as the pre-submit review, applied at tailor time)."""
    try:
        import atsform
        return atsform._tracker_companies()
    except Exception:
        return set()


def apply_subs(text, subs, findings):
    """Apply verbatim substitutions in order. Each must occur exactly its expected
    count (default 1) — a miss or ambiguity is a FAIL finding and the sub is skipped
    (the rest still apply, atsform-apply style: one consolidated summary)."""
    for i, sub in enumerate(subs or []):
        find, repl = sub.get("find", ""), sub.get("replace", "")
        want = int(sub.get("count", 1))
        if not find:
            findings.append(("FAIL", f"sub[{i}]: empty 'find'"))
            continue
        n = text.count(find)
        if n != want:
            tag = "not found in master" if n == 0 else f"ambiguous ({n} occurrences, expected {want})"
            findings.append(("FAIL", f"sub[{i}] {find[:60]!r}: {tag} — use `tailor.py find` to pin it"))
            continue
        text = text.replace(find, repl, want)
    return text


def _enclosing_block(text, idx):
    """Innermost <li>/<p>/<tr> block containing position idx, as (start, end_after_close).
    The master resume is a Google-Docs export — its bullets are <p> blocks, not <li>,
    so this must not assume list markup. Returns None if idx isn't cleanly inside one."""
    best = None
    for tag in ("li", "p", "tr"):
        start = text.rfind("<" + tag, 0, idx)
        # guard against matching a longer tag name (e.g. '<pre' for 'p')
        while start != -1 and text[start + 1 + len(tag)] not in (" ", ">", "\t"):
            start = text.rfind("<" + tag, 0, start)
        if start == -1:
            continue
        close = "</" + tag + ">"
        if text.find(close, start, idx) != -1:  # that block closed before the needle
            continue
        end = text.find(close, idx)
        if end == -1:
            continue
        if best is None or start > best[0]:  # innermost wins
            best = (start, end + len(close))
    return best


def drop_bullets(text, drops, findings):
    """Remove the bullet block (<li>, <p>, or <tr>) enclosing each unique needle."""
    for i, needle in enumerate(drops or []):
        n = text.count(needle) if needle else 0
        if n != 1:
            tag = "not found/empty" if n == 0 else f"ambiguous ({n} occurrences)"
            findings.append(("FAIL", f"drop[{i}] {needle[:60]!r}: {tag}"))
            continue
        idx = text.index(needle)
        block = _enclosing_block(text, idx)
        if not block:
            findings.append(("FAIL", f"drop[{i}] {needle[:60]!r}: no enclosing <li>/<p>/<tr> block"))
            continue
        text = text[:block[0]] + text[block[1]:]
    return text


def check_cover(cover, company, findings):
    for m in PLACEHOLDER.findall(cover):
        findings.append(("FAIL", f"cover: surviving placeholder {m!r}"))
    low = cover.lower()
    tgt = (company or "").strip().lower()
    if tgt:
        mentions = len(re.findall(r"\b" + re.escape(tgt) + r"\b", low)) or low.count(tgt)
        if mentions < 2:
            findings.append(("FAIL", f"cover: company {company!r} mentioned {mentions}x (need >=2)"))
    for other in sorted(_tracker_companies()):
        if not other or other == tgt or (tgt and (tgt in other or other in tgt)):
            continue
        if re.search(r"\b" + re.escape(other) + r"\b", low):
            # A multi-word other-company ("AJ Bell", "Reviva Softworks") is distinctive, so a
            # match is almost certainly a real wrong-company (copy-paste) letter -> FAIL. A single
            # common word ("Access", "Which", "Reach") can match incidental prose, so WARN there
            # instead of hard-blocking a correct letter from --render on a coincidence.
            sev = "FAIL" if " " in other.strip() else "WARN"
            findings.append((sev, f"cover: mentions OTHER company {other!r} — wrong-company letter?"))
    words = len(cover.split())
    if not 150 <= words <= 250:
        findings.append(("WARN", f"cover: {words} words (target 150-250)"))


def tailor_one(posting, master_html, spec_dir):
    """Returns (findings, out_dir or None). out_dir is set iff resume.html was written."""
    findings = []
    out_dir = posting.get("dir")
    if not out_dir:
        return [("FAIL", "posting missing 'dir'")], None
    company = posting.get("company", "")

    # Family base (Tier-2): swap the master summary for the family's positioning FIRST,
    # so the per-posting subs are just company-specific tweaks. `family` is set by
    # pipeline.py on every queue row; a spec can also set it explicitly.
    fsub = family_sub(posting.get("family"))
    text = apply_subs(master_html, fsub, findings) if fsub else master_html
    text = apply_subs(text, posting.get("subs"), findings)
    text = drop_bullets(text, posting.get("drop"), findings)

    vis = visible_text(text)
    for m in set(PLACEHOLDER.findall(vis)):
        findings.append(("FAIL", f"resume: placeholder {m!r} in visible text"))

    cover = posting.get("cover")
    if cover:
        if cover.startswith("@"):
            p = cover[1:]
            if not os.path.isabs(p) and not os.path.exists(p):
                alt = os.path.join(spec_dir, p)
                p = alt if os.path.exists(alt) else p
            try:
                with open(p, encoding="utf-8") as f:
                    cover = f.read().strip()
            except OSError as e:
                findings.append(("FAIL", f"cover: cannot read {p!r}: {e}"))
                cover = None
        if cover:
            check_cover(cover, company, findings)

    for kw in posting.get("must_haves") or []:
        hay = vis.lower() + " " + (cover or "").lower()
        if kw and kw.lower() not in hay:
            findings.append(("WARN", f"must-have {kw!r} absent from resume+cover"))

    hard_fail = any(sev == "FAIL" for sev, _ in findings)
    # Write outputs even on FAIL (so the agent can inspect/fix), but report clearly;
    # --render only picks up clean dirs.
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "resume.html"), "w", encoding="utf-8") as f:
        f.write(text)
    if cover:
        with open(os.path.join(out_dir, "cover-letter.md"), "w", encoding="utf-8") as f:
            f.write(cover + "\n")
    return findings, (None if hard_fail else out_dir)


def cmd_apply(spec_path, render=False):
    try:
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
    except (OSError, ValueError) as e:
        print(f"FAIL: cannot read spec {spec_path!r}: {e}")
        return 2
    postings = spec.get("postings") if isinstance(spec, dict) else spec
    if not isinstance(postings, list) or not postings:
        print("FAIL: spec must be a list of postings or {\"postings\": [...]}")
        return 2
    try:
        with open(master_path(), encoding="utf-8") as f:
            master_html = f.read()
    except OSError as e:
        print(f"FAIL: cannot read master resume: {e}")
        return 2

    spec_dir = os.path.dirname(os.path.abspath(spec_path))
    clean_dirs, n_failed = [], 0
    with stagetimer.timed("tailor-exec", meta=f"{len(postings)} postings"):
        for posting in postings:
            findings, ok_dir = tailor_one(posting, master_html, spec_dir)
            name = posting.get("dir", "?")
            status = "OK  " if ok_dir else "FAIL"
            print(f"{status} {name}")
            for sev, msg in findings:
                print(f"       {sev}: {msg}")
            if ok_dir:
                clean_dirs.append(ok_dir)
            else:
                n_failed += 1

    print(f"---- tailor summary: {len(clean_dirs)}/{len(postings)} clean ----")
    rc = 1 if n_failed else 0
    if render:
        if not clean_dirs:
            print("render: nothing clean to render")
            return 1
        if n_failed:
            print(f"render: rendering the {len(clean_dirs)} clean dir(s); "
                  f"{n_failed} failed posting(s) NOT rendered — fix and re-run")
        prerender = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prerender-pdfs.sh")
        rrc = subprocess.call([prerender] + clean_dirs)
        rc = rc or rrc
    return rc


def cmd_find(needle, ctx=120):
    try:
        with open(master_path(), encoding="utf-8") as f:
            blob = f.read()
    except OSError as e:
        print(f"FAIL: cannot read master resume: {e}")
        return 2
    hits = [m.start() for m in re.finditer(re.escape(needle), blob)]
    print(f"{len(hits)} occurrence(s) of {needle!r} in master")
    for pos in hits[:5]:
        lo, hi = max(0, pos - ctx), min(len(blob), pos + len(needle) + ctx)
        print(f"  @{pos}: …{blob[lo:pos]}⟦{blob[pos:pos+len(needle)]}⟧{blob[pos+len(needle):hi]}…")
    return 0 if len(hits) == 1 else 1


_COVER_SLOTS = """Dear {{Hiring Team}},

I'm applying for the {role} role at {company}. {hook}

{fit}

I'd welcome the chance to talk. You can reach me at you@example.com or on +44 7700 900000.

Best regards,
Jane Doe
"""


def cmd_build_bases():
    """Materialize applications/_bases/<family>/{resume.html,cover.md} from the master
    resume + family-bases.json. resume.html = master with the summary swapped to the
    family positioning; cover.md = the slot-template with the family's fit line. These
    are DERIVED artifacts — regenerate after editing family-bases.json or the master."""
    data = _family_data()
    fams = data.get("families", {})
    if not fams or not data.get("_anchor"):
        print("FAIL: family-bases.json missing/empty")
        return 2
    try:
        with open(master_path(), encoding="utf-8") as f:
            master_html = f.read()
    except OSError as e:
        print(f"FAIL: cannot read master resume: {e}")
        return 2
    if data["_anchor"] not in master_html:
        print(f"FAIL: summary anchor not found in master — update family-bases.json "
              f"'_anchor' (looked for {data['_anchor'][:50]!r}…)")
        return 2
    base_root = os.path.join(_root(), "applications", "_bases")
    os.makedirs(base_root, exist_ok=True)
    n = 0
    for fam, spec in fams.items():
        d = os.path.join(base_root, fam)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "resume.html"), "w", encoding="utf-8") as f:
            f.write(master_html.replace(data["_anchor"], spec["summary"]))
        cover = _COVER_SLOTS.replace("{fit}", spec.get("cover_fit", "{fit}"))
        with open(os.path.join(d, "cover.md"), "w", encoding="utf-8") as f:
            f.write("<!-- Slot template: fill {company} {role} {hook}; {fit} is the "
                    "family default (edit to the JD). 150-250 words; see SKILL.md Step 3. -->\n"
                    + cover)
        n += 1
    with open(os.path.join(base_root, "README.md"), "w", encoding="utf-8") as f:
        f.write("# Per-family resume/cover bases (DERIVED — do not hand-edit)\n\n"
                "Regenerate with `python3 sites/_common/scripts/tailor.py build-bases` after "
                "editing `sites/_common/family-bases.json` or the master resume.\n\n"
                "Each `<family>/resume.html` is the master with the summary swapped to that "
                "family's positioning; `<family>/cover.md` is the cover slot-template with the "
                "family fit line. Tailoring a posting = start from its family base (pipeline.py "
                "sets `family` per queue row) + ~3 company subs.\n")
    print(f"built {n} family base(s) in {base_root}")
    return 0


def main():
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "apply":
        return cmd_apply(a[1], render="--render" in a[2:])
    if len(a) == 2 and a[0] == "find":
        return cmd_find(a[1])
    if a and a[0] == "build-bases":
        return cmd_build_bases()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
