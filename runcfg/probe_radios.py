import sys, json
sys.path.insert(0, 'sites/_common/scripts'); sys.path.insert(0, 'sites/ashbyhq/scripts')
import cfx, ashby
URL = sys.argv[1]
cfx.goto(URL); ashby.reveal()
expr = r"""
(() => {
  const groups = {};
  for (const r of document.querySelectorAll('input[type=radio]')) {
    const nm = r.getAttribute('name') || '?';
    let opt = r.closest('[class*=option]');
    let txt = opt ? opt.innerText.trim().replace(/\s+/g,' ').slice(0,80) : '(?)';
    groups[nm] = groups[nm] || [];
    if (!groups[nm].includes(txt)) groups[nm].push(txt);
  }
  const out = [];
  for (const [nm, opts] of Object.entries(groups)) {
    const r0 = document.querySelector('input[type=radio][name="' + nm + '"]');
    let q='(?)'; let p=r0;
    for (let i=0;i<10;i++){ p=p.parentElement; if(!p) break;
      const lab=p.querySelector('label, [class*=heading], [class*=question]');
      if(lab){ q=lab.innerText.trim().replace(/\s+/g,' ').slice(0,70); break; } }
    out.push({name:nm.slice(0,24), q, opts});
  }
  return JSON.stringify(out);
})()
"""
for d in json.loads(cfx.evaluate(expr)):
    print("GRP:", d['name'])
    print("  Q:", d['q'])
    for o in d['opts']: print("    -", o)
