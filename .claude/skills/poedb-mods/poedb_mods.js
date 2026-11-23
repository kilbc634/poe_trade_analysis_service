// Runs inside the page through `playwright-cli run-code --filename`.
// Returns every modifier group poedb shows in "Modifiers Calc" (Base Prefix / Base Suffix / Delve … / Veiled … / Corrupted / Synthesis …),
// each as a list of families with their tiers. Numbers are copied from the page, nothing is computed here.
async page => {
  let waited = 'ok';
  try {
    await page.waitForFunction(() => document.querySelectorAll('h5.identify-title').length > 0 && document.querySelectorAll('.mod-title').length > 0, null, { timeout: 25000 });
  } catch (e) { waited = 'timeout'; }
  return await page.evaluate((waited) => {
    const txt = e => (e ? e.textContent : '').replace(/\s+/g, ' ').trim();
    // text of an element with its badges (weights, levels, tags) stripped out
    const bare = e => { const c = e.cloneNode(true); c.querySelectorAll('.badge').forEach(b => b.remove()); return txt(c); };
    const isNum = b => /bg-(danger|secondary|success)/.test(b.className);
    const out = { waited, title: document.title, url: location.href, groups: [] };
    for (const h of document.querySelectorAll('h5.identify-title')) {
      const box = h.parentElement;
      const g = { name: txt(h), families: [] };
      for (const row of box.querySelectorAll('.mod-title')) {
        const wb = row.querySelector('.badge.bg-danger');
        const fam = {
          gengroup: row.getAttribute('data-gengroup') || '',
          weight: txt(wb), pct: wb ? (wb.getAttribute('data-bs-title') || wb.getAttribute('title') || '') : '',
          ilvl: txt(row.querySelector('.badge.bg-secondary')), ntiers: txt(row.querySelector('.badge.bg-success')),
          text: bare(row), tags: [...row.querySelectorAll('.badge')].filter(b => !isNum(b)).map(txt),
          tiers: [],
        };
        const sel = row.getAttribute('data-bs-target') || row.getAttribute('href') || '';
        const tgt = sel.startsWith('#') ? document.getElementById(sel.slice(1)) : null;
        if (tgt) {
          for (const tr of tgt.querySelectorAll('tr')) {
            const tds = [...tr.querySelectorAll('td')];
            if (tds.length < 4) continue;
            fam.tiers.push({
              tier: txt(tds[0]), name: txt(tds[1]), ilvl: txt(tds[2]), text: bare(tds[3]),
              weight: txt(tr.querySelector('.badge.bg-danger')),
              tags: [...tds[3].querySelectorAll('.badge')].filter(b => !isNum(b)).map(txt),
            });
          }
        }
        g.families.push(fam);
      }
      out.groups.push(g);
    }
    return out;
  }, waited);
}
