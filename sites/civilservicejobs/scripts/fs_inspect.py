"""Dump the visible form fields on the current Fast Stream page (read-only)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "sites" / "_common" / "scripts"))
import cfx

JS = """JSON.stringify([...document.querySelectorAll('input,select,textarea')]
 .filter(e => e.type !== 'hidden' && e.offsetParent !== null)
 .map(e => ({tag: e.tagName, type: e.type, name: e.name, id: e.id,
   label: ((e.labels && e.labels[0]) || {}).innerText || e.getAttribute('aria-label') || '',
   opts: e.tagName === 'SELECT' ? [...e.options].map(o => o.text).slice(0, 12) : undefined,
   value: (e.type === 'password') ? '' : (e.value || '').slice(0, 30)})))"""

if __name__ == "__main__":
    print(cfx.current_url())
    print(cfx.evaluate(JS))
    print(cfx.evaluate("document.querySelector('h1') ? document.querySelector('h1').innerText : ''"))
