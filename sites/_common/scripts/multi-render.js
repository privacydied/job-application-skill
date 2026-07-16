// multi-render.js — render MANY resume HTMLs to PDF over ONE Playwright connection
// (perf-roadmap D.4). The per-dir make-pdf.sh opens its own node + chromium.connect +
// http.server per posting; this collapses that to a SINGLE node process and a SINGLE
// browser connection, rendering each posting on its own page. Per-page try/catch keeps
// one bad posting from aborting the whole batch (the isolation the per-process path got
// for free). Prints one line per job to stdout: "<index> <rc> [detail]" (rc 0 = ok).
//
//   node multi-render.js <ws> <url1> <out1> <url2> <out2> ...
//
// Serving + the pdftotext ATS-safety gate stay in prerender-pdfs.sh (this only renders).
const { chromium } = require("playwright-core");

(async () => {
  const a = process.argv.slice(2);
  const ws = a[0];
  const jobs = [];
  for (let i = 1; i + 1 < a.length; i += 2) jobs.push({ url: a[i], out: a[i + 1] });

  let browser;
  try {
    browser = await chromium.connect(ws, { timeout: 20000 });
  } catch (e) {
    // The one connection failed → every job fails (the caller falls back per-dir).
    const msg = String(e).replace(/\s+/g, " ").slice(0, 160);
    jobs.forEach((_, i) => console.log(i + " 1 connect-failed: " + msg));
    process.exit(0);
  }

  for (let i = 0; i < jobs.length; i++) {
    const { url, out } = jobs[i];
    let page;
    try {
      page = await browser.newPage();
      // D.2 wait semantics: self-contained HTML → "load" + fonts, not networkidle.
      const resp = await page.goto(url, { waitUntil: "load", timeout: 30000 });
      // Defense-in-depth: a missing HTML serves a 404 page that "loads" fine and would
      // otherwise be rendered as a bogus resume PDF (pdftotext even finds the "404"
      // text). Reject any non-2xx so a stray dir can't produce a fake PDF.
      if (resp && !resp.ok()) throw new Error("HTTP " + resp.status() + " for " + url);
      await page.evaluate(() => (document.fonts && document.fonts.ready)
        ? document.fonts.ready.then(() => true) : true).catch(() => {});
      await page.pdf({ path: out, format: "A4", printBackground: true });
      console.log(i + " 0");
    } catch (e) {
      console.log(i + " 1 " + String(e).replace(/\s+/g, " ").slice(0, 200));
    } finally {
      if (page) { try { await page.close(); } catch (e) { /* ignore */ } }
    }
  }
  try { await browser.close(); } catch (e) { /* ignore */ }
})().catch(e => { console.error("multi-render fatal: " + String(e)); process.exit(1); });
