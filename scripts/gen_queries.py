#!/usr/bin/env python3
"""gen_queries.py — emit BROAD alternate LinkedIn/Indeed search URLs to break cooldown.

When the curated `searches.csv` bundles have all cooled down (every board+query in
`board-cooldown.csv` still on its adaptive timer) but the on-profile pool isn't truly
exhausted, the playbook (`references/apply-mechanics.md` §"Break cooldown with NEW query
URLs") is to hit DIFFERENT cooldown keys with wider-vocabulary OR-bundles. This script
is that recipe as code — no more hand-building URLs.

Each printed URL:
  * uses a WIDER title vocab than the bundled searches (adjacent families included),
  * carries NO seniority exclusion — the title pre-filter (`check_title.py`) + precheck
    are the gate, so recall-widening here is safe (screening happens downstream),
  * pins remote + London (`f_WT=2` / `remotejob=remote`, `l=London`) per the profile,
  * uses a longer recency window (LinkedIn `f_TPR=r604800` = 7d, Indeed `fromage=14`)
    so it surfaces postings the tighter bundled searches skipped.

Each bundle derives its own cooldown key via `query_from_url()`. Families NOT already in
`searches.csv` give a genuine cooldown break; for any that ARE already bundled and cooled,
`feed.py`'s cooldown gate cheaply skips them (prints `[]` without re-fetching) — so it is
safe to feed the whole list and let the gate sort out which are still live.

Usage:
    python3 scripts/gen_queries.py            # all bundles, both boards
    python3 scripts/gen_queries.py --board linkedin   # or indeed
Pick a line and source it:  feed.py --nav "<url>"   (no --force needed; new key).

NB: the title vocab below is a SUPERSET snapshot of `references/target-roles.md`
families — deliberately broad and static. If target-roles gains a whole new family,
add it here too; day-to-day drift is fine because precheck screens the results.
"""
import sys
import urllib.parse

# Broader title sets (Tier A/B/C families) — quoted phrases so LinkedIn OR-bundle works.
LI_TITLES = [
    '"Product Designer" OR "UX Designer" OR "UX/UI Designer" OR "UI Designer" OR "Interaction Designer" OR "Digital Designer" OR "Web Designer" OR "Visual Designer" OR "Service Designer" OR "Content Designer" OR "Accessibility Designer"',
    '"User Researcher" OR "UX Researcher" OR "Design Researcher" OR "Usability Analyst" OR "Usability Tester" OR "Information Architect" OR "UX Writer" OR "Research Ops"',
    '"UX Engineer" OR "Design Engineer" OR "Design Technologist" OR "Creative Technologist" OR "Frontend Developer" OR "Front End Developer" OR "Web Developer" OR "WordPress Developer" OR "Prototyper" OR "Webflow Developer"',
    '"Growth Designer" OR "Growth Marketer" OR "CRO Specialist" OR "Conversion Rate Optimisation" OR "Performance Marketing" OR "Paid Social" OR "Digital Marketing" OR "Social Media Manager" OR "Content Creator"',
    '"DevOps Engineer" OR "Linux Engineer" OR "SOC Analyst" OR "Security Analyst" OR "Platform Engineer" OR "Site Reliability Engineer" OR "Infrastructure Engineer" OR "Cloud Engineer" OR "Cloud Support" OR "IT Support" OR "Service Desk" OR "Desktop Support" OR "IT Technician"',
    '"Junior Product Designer" OR "Associate Product Designer" OR "Mid Product Designer" OR "Junior UX Designer" OR "Graduate Designer" OR "Junior Designer" OR "Product Designer II" OR "UX Designer II" OR "Assistant Designer"',
]

ID_TITLES = [t.replace(' OR ', ' or ') for t in LI_TITLES]


def li_url(q):
    kw = urllib.parse.quote(q)
    return (f"https://www.linkedin.com/jobs/search/?keywords={kw}"
            "&location=London%2C%20England%2C%20United%20Kingdom"
            "&f_TPR=r604800&sortBy=DD&f_WT=2")


def id_url(q):
    kw = urllib.parse.quote(q)
    return f"https://uk.indeed.com/jobs?q={kw}&sort=date&fromage=14&l=London&remotejob=remote"


def main():
    args = sys.argv[1:]
    board = None
    if "--board" in args:
        try:
            board = args[args.index("--board") + 1].lower()
        except IndexError:
            pass
    if board in (None, "linkedin"):
        for i, q in enumerate(LI_TITLES):
            print(f"LI_ALT_{i}\t{li_url(q)}")
    if board is None:
        print("---")
    if board in (None, "indeed"):
        for i, q in enumerate(ID_TITLES):
            print(f"ID_ALT_{i}\t{id_url(q)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
