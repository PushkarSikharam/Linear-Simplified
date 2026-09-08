const { chromium } = require('@playwright/test');
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://localhost:3000/architecture');
    await page.getByRole('heading', { name: 'A controlled demo workspace that listens, scopes, and acts.', exact: true }).waitFor();
    fs.mkdirSync('docs/assets', { recursive: true });
    for (const width of [1440, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) {
        throw new Error(`Horizontal overflow at ${width}`);
      }
      await page.screenshot({ path: width === 1440 ? 'docs/assets/system-atlas.png' : `tmp/atlas-${width}.png`, fullPage: true });
      console.log(`Layout ${width}px: passed`);
    }
    await page.getByRole('heading', { name: 'Four moments that prove the system.', exact: true }).waitFor();
    const brokenAnchors = await page.locator('a[href^="#"]').evaluateAll(links => links.filter(link => !document.querySelector(link.getAttribute('href'))).length);
    if (brokenAnchors || errors.length) throw new Error(JSON.stringify({ brokenAnchors, errors }));
    console.log('Content landmarks, anchor targets and browser errors: passed');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
