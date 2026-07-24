# Design-specific boards — harvest & apply mechanics (junior→mid designer lane)

This session (2026-07-23) re-harvested the design-specific boards fresh and found
**genuine new on-lane inventory that the ats-direct preaudit misses entirely**. For a
product/UX/creative designer the convertible ceiling is dominated by these boards, NOT
ats-direct (whose universe is ~90% US-onsite + senior + engineering/infra). If you've
exhausted ats-direct + WTTJ + Guardian + Hackney and still see "0 convertible", harvest
THESE before declaring a ceiling.

All five live under `pipeline.FEEDS` in the `design / music` lane
(`ifyoucould`, `thedots`, `designweek`, `dezeen`, `dribbble`) — but the re-harvest
guard only enumerates `ats-direct`, so they get skipped in practice. Per-board feeds are
keyless/accountless except The Dots (OAuth2 password grant, creds in `ats-credentials.csv`
row `the-dots.com`) and Dribbble (account-gated, no shipped `apply.py`).

## Harvest commands (verified live 2026-07-23)
```
python3 sites/ifyoucouldjobs.com/scripts/feed.py --what "designer" --all   # 43 fresh
python3 sites/the-dots.com/scripts/feed.py --what "product designer" --all  # 48 fresh
python3 sites/designweek.co.uk/scripts/feed.py --what "designer" --all      # 10 fresh
python3 sites/dezeen.com/scripts/feed.py --what "designer" --all            # design roles
python3 sites/dribbble.com/scripts/feed.py --what "product designer" --all  # 16 fresh, account wall
```
Note: `feed.py --all` with NO `--what` often returns the full board; `--what` narrows.
CreativePool (`sites/creativepool.com/scripts/feed.py`) returned HTTP 404 this session —
treat as DEAD, skip it.

## Per-board apply mechanics (the part that bites)
- **IfYouCould (`ifyoucouldjobs.com`)** — HIGHEST-SIGNAL London design board for this lane.
  Off-site per employer: each JD carries a `mailto:` to the employer careers address OR a
  link to the employer's own ATS/WordPress site. **No If You Could account needed.** The
  index passes a `level` field (Junior / Midweight / Senior / Director) and `contract`, so
  seniority is graded OFF THE INDEX — no JD fetch needed to screen. ~18 of 43 fresh were
  on-lane (Midweight/Junior Designer, Graphic/UI, Motion). WARNING `jd.py resolve(url)` returns
  `NO_JD` for these (it doesn't handle off-site mailto targets) — resolve the apply target
  by reading the JD page directly (mailto address or the employer ATS URL), don't rely on
  `jd.resolve`. Drive the employer ATS (Greenhouse/Ashby/etc.) as usual once you have it.
- **The Dots (`the-dots.com`)** — login-gated but `feed.py` works via OAuth2 password grant
  (creds row `the-dots.com`). `apply_url` (`applicationWebsite`) hops to the REAL employer
  ATS (Lever / careers.X / Workday / Greenhouse). Tailor + drive that ATS. Filter: keep
  non-Senior/Lead/Principal Product/UX/UI Designers (ITV Product Designer, John Lewis,
  Zopa, Expedia all surfaced). `level` field present for seniority screen.
- **DesignWeek (`designweek.co.uk`)** — apply is **EMAIL to the employer**. The address is
  Cloudflare-obfuscated: a `span.__cf_email__[data-cfemail]` hex blob. Decode it
  (the `data-cfemail` is a XOR cipher with key 0x3D over pairs of hex chars → the email
  string). No account. Mostly CAD/Senior/Interior/Graphic this session; a few on-lane
  (Graphic Designer, generic Designer). Email apply = outside the ATS-driver loop.
- **Dezeen** — design/architecture board; mostly interior/architecture/senior. Screen by
  title + `level` if present.
- **Dribbble (`dribbble.com`)** — **account-gated** (Apply-now is a data-signup trigger;
  creds in `ats-credentials.csv` IF a row exists). WARNING **NO `apply.py` shipped** in
  `sites/dribbble.com/scripts/` — only `feed.py`. So Dribbble is a WALL unless you write a
  driver. On-lane-but-blocked this session (Product Designer — Junior, Graphic/Product
  Designer, Freelance AI Product Designer). Don't count it convertible.

## Honest convertible count from this session's fresh harvest
- IfYouCould: 43 fresh → ~18 on-lane (Midweight/Junior, non-Senior). REAL new inventory.
- The Dots: 48 fresh → ~6 non-Senior Product/UX Designers resolving to drivable ATS.
- DesignWeek: 10 fresh → ~2-3 on-lane (rest CAD/Senior/Interior).
- ats-direct re-harvest (4,298): 19 "real-drivable" but every on-lane design role already
  tracked (Figma/Lendable Applied, Storyblok Blocked, Canonical Skipped/Applied-dup); the
  remainder off-lane engineering. Confirms ats-direct is NOT the designer's frontier.

## Lesson
For a designer, the convertible ceiling is **design-board-dominated**. When the ats-direct
preaudit says "0 convertible / ceiling reached", that is a PARTIAL view — harvest
IfYouCould + The Dots + DesignWeek (commands above) before concluding. The design boards
carry the junior→mid on-lane roles that ats-direct's US/senior skew hides.
