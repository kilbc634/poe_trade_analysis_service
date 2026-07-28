// Read-only cookie export for refresh_poe_cookies.py.
//
// Returns the POE auth cookies + the UA they were captured under, as JSON.
// Deliberately does nothing else: no navigation, no writes, no other origins,
// so the wrapper command is safe to put on the permission allowlist.
//
// cf_clearance is bound to (IP x UA), so the UA MUST travel with the cookies —
// see .claude/skills/poe-trade-query/common/tricks.md (UA 紀律).
async page => {
  const wanted = ['POESESSID', 'cf_clearance'];
  const jar = await page.context().cookies('https://www.pathofexile.com');
  const cookies = {};
  for (const c of jar) {
    if (wanted.includes(c.name)) cookies[c.name] = c.value;
  }
  // Is this session actually logged in? 200 = yes, 401 = anonymous POESESSID.
  // Recorded so the wrapper can refuse to clobber a good cache with a dud.
  let profile = 0;
  try {
    profile = (await page.evaluate(async () => (await fetch('/api/profile')).status));
  } catch (e) {
    profile = -1;
  }
  return JSON.stringify({
    user_agent: await page.evaluate(() => navigator.userAgent),
    profile_status: profile,
    cookies,
  });
}
