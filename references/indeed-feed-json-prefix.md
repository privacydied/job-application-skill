# Indeed — `feed.py` emits a leading non-JSON line that breaks `json.loads`

Captured 2026-07-14.

## Symptom
`python3 sites/indeed.com/scripts/feed.py --nav "..."` writes its JSON array to
stdout, but the file begins with a stray line before the `[`:
```
clear: no modal open.
[
  {"id": "85c6e1920c99e177", ...},
```
Parsing the whole file with `json.loads` raises `Expecting value: line 1 column 1`.

## Fix (parse by finding the first `[`)
When consuming an Indeed feed JSON file in code, strip the leading prose:
```python
txt = open(f, encoding="utf-8", errors="replace").read()
i = txt.find("[")
data = json.loads(txt[i:]) if i >= 0 else []
```
The LinkedIn `feed.py` output does NOT have this prefix (it goes straight to `[`),
so only guard the Indeed files. The prefix is `dismiss_modal.py`'s stdout leaking
into the same pipe — harmless, just don't `json.loads` the raw file.
