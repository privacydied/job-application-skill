import sys, time, json
sys.path.insert(0, 'sites/_common/scripts'); sys.path.insert(0, 'sites/ashbyhq/scripts')
import cfx, ashby
URL = sys.argv[1]
cfx.goto(URL); ashby.reveal()
clicked = cfx.evaluate("(()=>{const b=[...document.querySelectorAll('button')].find(x=>/submit application/i.test(x.innerText));if(!b)return 'NO_BUTTON';b.scrollIntoView({block:'center'});b.click();return 'clicked';})()")
print("click:", clicked)
for i in range(6):
    time.sleep(3)
    st = json.loads(cfx.evaluate(
        "(()=>JSON.stringify({"
        "success:/successfully submitted|thank you/i.test(document.body.innerText),"
        "formGone:!document.querySelector('input[name=_systemfield_name]'),"
        "recap:!!document.querySelector('iframe[src*=recaptcha]'),"
        "body:document.body.innerText.replace(/\\s+/g,' ').slice(0,200)"
        "}))()"))
    print(f"  t{i}: formGone={st['formGone']} success={st['success']} recap={st['recap']} body={st['body'][:120]}")
