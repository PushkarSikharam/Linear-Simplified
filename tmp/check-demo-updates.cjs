const { chromium } = require('@playwright/test');

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://localhost:3000');
    await page.getByTestId('current-view-title').waitFor();
    await page.getByTestId('scope-lockup').waitFor();

    await page.getByTestId('chat-input').fill('what should I try next');
    await page.getByTestId('chat-send').click();
    await page.getByText('A strong next move is sprint planning').waitFor();

    await page.getByTestId('chat-input').fill('connect GitHub');
    await page.getByTestId('chat-send').click();
    await page.getByTestId('github-setup-panel').waitFor();
    await page.getByText('Repository activity is mapped').waitFor();
    await page.getByTestId('activity-popup').waitFor();

    await page.screenshot({ path: 'tmp/demo-updates-desktop.png', fullPage: true });

    await page.setViewportSize({ width: 390, height: 1000 });
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) {
      throw new Error('Horizontal overflow at 390px');
    }
    await page.screenshot({ path: 'tmp/demo-updates-mobile.png', fullPage: true });

    if (errors.length) throw new Error(JSON.stringify(errors));
    console.log('Demo update UI checks passed');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
