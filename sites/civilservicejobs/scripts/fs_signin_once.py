"""One sign-in attempt on the Fast Stream portal using the stored credential (never printed)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "sites" / "_common" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cfx
import fast_stream as fs

SET_JS = """(([n, v]) => {
  const e = document.querySelector('[name="' + n + '"]');
  const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  s.call(e, v); e.dispatchEvent(new Event('input', {bubbles: true}));
  e.dispatchEvent(new Event('change', {bubbles: true})); return e.value.length;
})"""

def main():
    email, pw = fs.load_credential()
    print(cfx.evaluate("(%s)(%s)" % (SET_JS, json.dumps(["signIn", email]))))
    print(cfx.evaluate("(%s)(%s)" % (SET_JS, json.dumps(["signInPassword", pw]))))
    print(cfx.evaluate("(() => { document.querySelector('input[name=signInPassword]').form.requestSubmit(); return 'submitted'; })()"))
    cfx.poll("document.readyState", timeout=20)
    print(cfx.current_url())
    print(cfx.evaluate("document.querySelector('main') ? document.querySelector('main').innerText.slice(0, 400) : ''"))

if __name__ == "__main__":
    main()
