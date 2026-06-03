const puppeteer = require('puppeteer');
const path = require('path');

const BASE = 'https://agentops.krishna1parchuri.workers.dev';
const OUT  = path.join(__dirname, 'screenshots');

const wait = ms => new Promise(r => setTimeout(r, ms));

// Click the first element whose visible text matches a string
async function clickText(page, text) {
  await page.evaluate((t) => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.textContent.trim() === t) {
        const el = node.parentElement;
        if (el) { el.click(); return true; }
      }
    }
    return false;
  }, text);
}

async function run() {
  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox'],
    defaultViewport: { width: 1440, height: 820 },
  });
  const page = await browser.newPage();

  // 1. Login screen
  await page.goto(BASE, { waitUntil: 'networkidle0' });
  await page.screenshot({ path: path.join(OUT, '01-login.png') });
  console.log('01-login.png');

  // Authenticate
  await page.evaluate(() => sessionStorage.setItem('ao_user', 'admin'));
  await page.reload({ waitUntil: 'networkidle0' });
  await wait(2500);

  // 2. Registry
  await page.screenshot({ path: path.join(OUT, '02-registry.png'), fullPage: true });
  console.log('02-registry.png');

  // 3. Navigate to MediAssist Router detail
  await page.evaluate(() => {
    const allLinks = Array.from(document.querySelectorAll('a, button, td div, li'));
    for (const el of allLinks) {
      if (el.textContent.trim() === 'MediAssist Router') {
        el.click();
        return;
      }
    }
    // Broader search
    const all = Array.from(document.querySelectorAll('*'));
    for (const el of all) {
      if (el.children.length === 0 && el.textContent.trim() === 'MediAssist Router') {
        el.click();
        return;
      }
    }
  });
  await wait(3000);
  await page.screenshot({ path: path.join(OUT, '03-detail-overview.png') });
  console.log('03-detail-overview.png');

  // 4. Evals tab
  await clickText(page, 'Evals');
  await wait(1000);
  // Expand first <details> for dimensions
  await page.evaluate(() => {
    const d = document.querySelector('details');
    if (d) d.open = true;
  });
  await wait(400);
  await page.screenshot({ path: path.join(OUT, '04-detail-evals.png') });
  console.log('04-detail-evals.png');

  // 5. Costs tab
  await clickText(page, 'Costs');
  await wait(800);
  await page.screenshot({ path: path.join(OUT, '05-detail-costs.png') });
  console.log('05-detail-costs.png');

  // 6. Audit tab
  await clickText(page, 'Audit');
  await wait(800);
  await page.screenshot({ path: path.join(OUT, '06-detail-audit.png') });
  console.log('06-detail-audit.png');

  // 7. Governance Queue — click nav link
  await page.evaluate(() => {
    const all = Array.from(document.querySelectorAll('nav *, header *'));
    for (const el of all) {
      if (el.textContent.includes('Governance Queue')) {
        el.click();
        return;
      }
    }
    // Try any clickable element
    const any = Array.from(document.querySelectorAll('a, button'));
    for (const el of any) {
      if (el.textContent.includes('Governance')) {
        el.click();
        return;
      }
    }
  });
  await wait(5000);
  await page.screenshot({ path: path.join(OUT, '07-governance-queue.png') });
  console.log('07-governance-queue.png');

  await browser.close();
  console.log('\nAll done →', OUT);
}

run().catch(e => { console.error(e); process.exit(1); });
