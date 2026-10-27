const { chromium } = require('playwright');

const BASE = 'http://192.168.110.172:8890';
const pages = [
  ['/admin/system/account/user', 'acct'],
  ['/enterprise/chemical/bom/index', 'bom'],
];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await page.goto(BASE + '/#/login', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);
  await page.fill('input[type=text]', 'admin');
  await page.fill('input[type=password]', '123456');
  await page.click('button:has-text("登")');
  await page.waitForTimeout(7000);
  for (const [p, name] of pages) {
    await page.goto(BASE + '/#' + p, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3500);
    const box = await page.evaluate(() => {
      const tbl = document.querySelector('.el-table');
      const r = tbl.getBoundingClientRect();
      return { x: Math.max(0, r.right - 420), y: Math.max(0, r.top - 10), width: 420, height: Math.min(400, r.height) };
    });
    await page.screenshot({ path: `/tmp/at172/ac-${name}.png`, clip: box });
    console.log(name, JSON.stringify(box));
  }
  await browser.close();
})();
