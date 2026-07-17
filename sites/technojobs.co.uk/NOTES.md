# technojobs.co.uk — ⛔ VERIFIED DEAD (no feed, do not build one)

TechnoJobs was a UK IT board (1st/2nd-line support + junior sysadmin heavy) — squarely
on-profile had it survived. **It is offline.** There is no feed here and none should be
written. This file exists so the next agent doesn't re-probe it and doesn't mistake the
symptom (a bare connection failure) for a bot wall worth defeating with a browser.

## Evidence (probed 2026-07-17)

| Check | Result |
|---|---|
| `curl -A '<Chrome UA>' -L https://www.technojobs.co.uk/` | **HTTP 000** — `Could not resolve host` |
| `www.technojobs.co.uk` A/CNAME (via Cloudflare DoH, not local DNS) | CNAME → `technojobs.co.uk.cdn.cloudflare.net.` |
| `technojobs.co.uk.cdn.cloudflare.net` A | **no A record** — dangling CNAME |
| `technojobs.co.uk` (apex) A | `3.9.65.81` (`ec2-3-9-65-81.eu-west-2.compute.amazonaws.com`) |
| TCP connect `3.9.65.81:443` / `:80` | **both closed/filtered** |
| `curl --resolve` apex + www → `3.9.65.81` | HTTP 000, no TLS handshake (no cert served) |
| archive.org CDX, `www.technojobs.co.uk`, 2025-01-01 → now | last **HTTP 200 capture 2025-11-03**; nothing since |
| Control (same host, same moment): `https://www.jobserve.com/` | HTTP 302 — outbound network is fine |

## Why this is the site, not us

The failure is **not** a local DNS quirk and **not** a UA/TLS bot wall:

- `www` resolves fine from a public resolver — it just points at a **Cloudflare CDN target
  that has been deprovisioned** (CNAME present, no A record). That is broken for every
  client on the internet, not just this host.
- The apex still has an A record, but the EC2 instance behind it **accepts no connections on
  80 or 443**, so there is nothing to bot-wall. A wall returns 403/503 with a body; this
  returns nothing at all.
- Wayback stopped getting 200s in **November 2025** — ~8 months of silence, consistent with
  the CDN being torn down rather than a transient outage.

A bot wall would have been worth escalating to camofox. This isn't one — a browser cannot
connect to a host that has no listening socket. **NEEDS-BROWSER does not apply.**

## If it ever returns

It was a plain server-rendered board. Re-probe with `curl -A '<Chrome UA>' -L` first; only
reach for camofox if you get a real HTTP response that's visibly walled (403/JS challenge).
Until a probe returns an actual HTTP status, treat this board as dead.
