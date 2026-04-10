const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const items = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../fixtures/library_items.json'), 'utf8'));

function configuredPayload() {
  return {
    ui: { language: 'fr' },
    jellyseerr: { enabled: true },
    folders: [{ name: 'Cinema', type: 'movie', visible: true, missing: false }],
  };
}

function onboardingPayload() {
  return {
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

test('onboarding first run displays and export JSON disabled', async ({ page }) => {
  await mockCoreRoutes(page, { onboarding: true });
  await page.goto('/index.html');

  await expect(page.locator('#onboardingOverlay')).toBeVisible();

  const exportBtn = page.locator('#cfgExportJsonBtn');
  await expect(exportBtn).toBeDisabled();
});

test('global search keyboard interactions and filtering', async ({ page }) => {
  await mockCoreRoutes(page, { onboarding: false });
  await page.goto('/index.html');

  await page.keyboard.press('Control+k');
  await expect(page.locator('#searchInput')).toBeFocused();

  await page.locator('#searchInput').fill('film vf');
  await expect(page.locator('.media-card, .table-view tbody tr')).toHaveCount(1);

  await page.keyboard.press('Escape');
  await expect(page.locator('#searchInput')).toBeFocused();
  await expect(page.locator('#searchInput')).toHaveValue('');

  await page.keyboard.press('Escape');
  await expect(page.locator('#searchInput')).not.toBeFocused();
});

test('filters include/exclude and global reset', async ({ page }) => {
  await mockCoreRoutes(page, { onboarding: false });
  await page.goto('/index.html');

  await page.click('#providerSection .filter-dropdown-trigger');
  await page.click('#providerSection .filter-dropdown-option[data-key="Netflix"]');
  await expect(page.locator('#globalFilterResetBtn')).toBeEnabled();

  await page.click('#providerSection .filter-mode-toggle');
  await expect(page.locator('.media-card, .table-view tbody tr').first()).toBeVisible();

  await page.click('#globalFilterResetBtn');
  await expect(page.locator('#globalFilterResetBtn')).toBeDisabled();
});

test('export JSON present and triggers download only when library is valid', async ({ page }) => {
  await mockCoreRoutes(page, { onboarding: false });
  await page.goto('/index.html');

  await page.click('button[onclick="openSettings()"]');
  const exportBtn = page.locator('#cfgExportJsonBtn');
  await expect(exportBtn).toBeEnabled();

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    exportBtn.click(),
  ]);
  expect(download.suggestedFilename()).toContain('mymedialibrary-export-');
});
