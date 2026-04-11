const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const items = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../fixtures/library_items.json'), 'utf8'));

function configuredPayload() {
  return {
    needs_onboarding: false,
    ui: { language: 'fr' },
    jellyseerr: { enabled: true },
    folders: [{ name: 'Cinema', type: 'movie', visible: true, missing: false }],
  };
}

function onboardingPayload() {
  return {
    needs_onboarding: true,
    ui: { language: 'fr' },
    jellyseerr: { enabled: false },
    folders: [{ name: 'Cinema', type: '', visible: true, missing: false }],
  };
}

function libraryPayload() {
  return {
    scanned_at: '2026-04-01T12:00:00Z',
    library_path: '/library',
    items,
    categories: ['Cinema'],
    groups: ['Movies'],
  };
}

async function mockCoreRoutes(page, { onboarding = false } = {}) {
  await page.route('**/api/config', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: onboarding ? onboardingPayload() : configuredPayload() });
      return;
    }
    await route.fulfill({ json: { ok: true } });
  });
  await page.route('**/library.json**', async (route) => {
    if (onboarding) {
      await route.fulfill({ status: 404, body: 'not-found' });
      return;
    }
    await route.fulfill({ json: libraryPayload() });
  });
  await page.route('**/version.json**', async (route) => {
    await route.fulfill({ json: { version: '1.0.0-test', commit: 'abc123', build_date: '2026-04-01T00:00:00Z' } });
  });
}

async function openConfiguredLibrary(page) {
  await mockCoreRoutes(page, { onboarding: false });
  await page.goto('/index.html');
  await expect(page.locator('#library')).toContainText('Film VF');
}

test('onboarding first run displays and export JSON disabled', async ({ page }) => {
  await mockCoreRoutes(page, { onboarding: true });
  await page.goto('/index.html');

  await expect(page.locator('#onboardingOverlay')).toBeVisible();
  await expect(page.locator('#onboardingOverlay')).not.toContainText('library_inventory.json');
  await expect(page.locator('#cfgExportJsonBtn')).toBeDisabled();
});

test('global search keyboard interactions and filtering', async ({ page }) => {
  await openConfiguredLibrary(page);

  await page.keyboard.press('Control+k');
  await expect(page.locator('#searchInput')).toBeFocused();

  await page.locator('#searchInput').fill('film vf');
  await expect(page.locator('#library')).toContainText('Film VF');
  await expect(page.locator('#library')).not.toContainText('Film VO');

  await page.keyboard.press('Escape');
  await expect(page.locator('#searchInput')).toBeFocused();
  await expect(page.locator('#searchInput')).toHaveValue('');

  await page.keyboard.press('Escape');
  await expect(page.locator('#searchInput')).not.toBeFocused();
});

test('filters include/exclude and global reset', async ({ page }) => {
  await openConfiguredLibrary(page);

  await page.evaluate(() => {
    toggleProviderFilter('Netflix');
  });
  await expect(page.locator('#globalFilterResetBtn')).toBeEnabled();
  await expect(page.locator('#library')).toContainText('Film VF');
  await expect(page.locator('#library')).not.toContainText('Film VO');

  await page.evaluate(() => {
    toggleProviderExclude();
  });
  await expect(page.locator('#library')).toContainText('Film VO');
  await expect(page.locator('#library')).not.toContainText('Film VF');

  await page.click('#globalFilterResetBtn');
  await expect(page.locator('#globalFilterResetBtn')).toBeDisabled();
});

test('export JSON present and triggers download only when library is valid', async ({ page }) => {
  await openConfiguredLibrary(page);

  await page.evaluate(() => {
    window.__mmlExportClickCount = 0;
    window.__mmlExportFilename = null;
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    window.__mmlExpectedExportDate = `${y}-${m}-${day}`;
    const origClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function patchedClick() {
      if (this.download && this.download.startsWith('mymedialibrary-export-')) {
        window.__mmlExportClickCount += 1;
        window.__mmlExportFilename = this.download;
      }
      return origClick.call(this);
    };
  });

  await page.evaluate(() => openSettings());
  const exportBtn = page.locator('#cfgExportJsonBtn');
  await expect(exportBtn).toBeEnabled();
  await page.evaluate(() => exportLibraryJson());

  await expect.poll(async () => page.evaluate(() => window.__mmlExportClickCount)).toBe(1);

  const exportMeta = await page.evaluate(() => ({
    filename: window.__mmlExportFilename,
    expectedDate: window.__mmlExpectedExportDate,
  }));
  expect(exportMeta.filename).toBe(`mymedialibrary-export-${exportMeta.expectedDate}.json`);
});


test('backend onboarding flag ignores stale localStorage/sessionStorage flags', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('onboardingDone', 'true');
    localStorage.setItem('mediaState', JSON.stringify({ onboardingDismissed: true }));
    sessionStorage.setItem('onboardingStep', 'done');
  });
  await mockCoreRoutes(page, { onboarding: true });
  await page.goto('/index.html');

  await expect(page.locator('#onboardingOverlay')).toBeVisible();
});

test('configured app stays on main screen across reloads', async ({ page }) => {
  await openConfiguredLibrary(page);
  await expect(page.locator('#onboardingOverlay')).toBeHidden();

  await page.reload();
  await expect(page.locator('#library')).toContainText('Film VF');
  await expect(page.locator('#onboardingOverlay')).toBeHidden();
});

test('inventory toggle is in settings and persists via /api/config', async ({ page }) => {
  let capturedPayload = null;

  await page.route('**/api/config', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: configuredPayload() });
      return;
    }
    capturedPayload = JSON.parse(route.request().postData() || '{}');
    await route.fulfill({ json: { ok: true } });
  });
  await page.route('**/library.json**', async (route) => {
    await route.fulfill({ json: libraryPayload() });
  });
  await page.route('**/version.json**', async (route) => {
    await route.fulfill({ json: { version: '1.0.0-test', commit: 'abc123', build_date: '2026-04-01T00:00:00Z' } });
  });

  await page.goto('/index.html');
  await page.evaluate(() => {
    openSettings();
    const btn = document.querySelector('button.stab[onclick*="stab-system"]');
    if (btn) switchStab(btn, 'stab-system');
  });
  await expect(page.locator('#stab-system')).toBeVisible();

  const inventoryToggle = page.locator('#cfgInventoryEnabled');
  await expect(inventoryToggle).toBeVisible();
  await expect(inventoryToggle).not.toBeChecked();

  await inventoryToggle.check();
  await page.click('#settingsSaveBtn');

  await expect.poll(() => capturedPayload).not.toBeNull();
  expect(capturedPayload.system.inventory_enabled).toBe(true);
});

test('resetting persisted config makes onboarding visible again', async ({ page }) => {
  let onboarding = false;
  await page.route('**/api/config', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: onboarding ? onboardingPayload() : configuredPayload() });
      return;
    }
    await route.fulfill({ json: { ok: true } });
  });
  await page.route('**/library.json**', async (route) => {
    await route.fulfill({ json: libraryPayload() });
  });
  await page.route('**/version.json**', async (route) => {
    await route.fulfill({ json: { version: '1.0.0-test', commit: 'abc123', build_date: '2026-04-01T00:00:00Z' } });
  });

  await page.goto('/index.html');
  await expect(page.locator('#library')).toContainText('Film VF');
  await expect(page.locator('#onboardingOverlay')).toBeHidden();

  onboarding = true;
  await page.reload();
  await expect(page.locator('#onboardingOverlay')).toBeVisible();
});
