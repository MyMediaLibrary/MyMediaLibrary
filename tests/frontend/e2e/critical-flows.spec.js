const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const items = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../fixtures/library_items.json'), 'utf8'));

function configuredPayload() {
  return {
    needs_onboarding: false,
    ui: { language: 'fr' },
    score: { enabled: true },
    seerr: { enabled: true },
    folders: [{ name: 'Cinema', type: 'movie', enabled: true, missing: false }],
  };
}

function onboardingPayload() {
  return {
    needs_onboarding: true,
    ui: { language: 'fr' },
    seerr: { enabled: false },
    folders: [{ name: 'Cinema', type: '', enabled: true, missing: false }],
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

function scoreSettingsPayload() {
  return {
    enabled: true,
    defaults: {
      weights: { video: 50, audio: 20, languages: 15, size: 15 },
    },
    effective: {
      weights: { video: 50, audio: 20, languages: 15, size: 15 },
      video: {
        codec: { hevc: 15, vp9: 9, default: 6 },
        resolution: { '1080p': 20, default: 8 },
        hdr: { hdr10: 5, default: 0 },
      },
      audio: { codec: { dts: 15, default: 8 } },
      languages: { profile: { multi: 15, default: 3 } },
      size: { points: { coherent: 15, default: 5 }, profiles: { movie: { default: { default: { min_gb: 1, max_gb: 10 } } }, series: { default: { default: { min_gb: 0.2, max_gb: 4 } } } } },
      penalties: { max_total: 20, rules: { good_video_few_languages: -5 } },
      custom_unknown_key: 42,
    },
    ui_schema: {
      weights: { field_type: 'integer', min: 0, max: 100, sum_must_equal: 100 },
      numeric_default: { field_type: 'number' },
    },
    status: { weights_total: 100, weights_valid: true },
  };
}

async function mockCoreRoutes(page, { onboarding = false, missingLibrary = false } = {}) {
  await page.route('**/api/settings/score', async (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      await route.fulfill({ json: scoreSettingsPayload() });
      return;
    }
    await route.fulfill({ json: { ok: true, effective: scoreSettingsPayload().effective, status: { weights_total: 100, weights_valid: true, recalculated_items: 3, mode: 'score_only' } } });
  });
  await page.route('**/api/settings/score/reset', async (route) => {
    await route.fulfill({ json: { ok: true, effective: scoreSettingsPayload().effective, status: { weights_total: 100, weights_valid: true, recalculated_items: 3, mode: 'score_only' } } });
  });
  await page.route('**/api/config', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: onboarding ? onboardingPayload() : configuredPayload() });
      return;
    }
    await route.fulfill({ json: { ok: true } });
  });
  await page.route('**/library.json**', async (route) => {
    if (onboarding || missingLibrary) {
      await route.fulfill({ status: 404, body: 'not-found' });
      return;
    }
    await route.fulfill({ json: libraryPayload() });
  });
  await page.route('**/version.json**', async (route) => {
    await route.fulfill({ json: { version: '1.0.0-test', commit: 'abc123', build_date: '2026-04-01T00:00:00Z' } });
  });
  await page.route('**/api/providers-map**', async (route) => {
    await route.fulfill({
      json: {
        'Netflix': 'Netflix',
        'Prime Video': 'Prime Video',
        'Disney+': 'Disney+',
        'Other': null,
      },
    });
  });
  await page.route('**/providers_logo.json**', async (route) => {
    await route.fulfill({
      json: {
        'Netflix': 'netflix.webp',
        'Prime Video': 'primevideo.webp',
        'Disney+': 'disneyplus.webp',
        'Autres': 'other_play.webp',
      },
    });
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

test('configured app with missing library.json shows empty-library state without onboarding', async ({ page }) => {
  await mockCoreRoutes(page, { onboarding: false, missingLibrary: true });
  await page.goto('/index.html');

  await expect(page.locator('#onboardingOverlay')).toBeHidden();
  await expect(page.locator('#library')).toContainText('Veuillez lancer un scan');
  await expect(page.locator('#library')).not.toContainText('Aucun résultat');
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
  await expect(inventoryToggle).toBeAttached();
  await expect(inventoryToggle).not.toBeChecked();

  await page.evaluate(() => {
    const el = document.getElementById('cfgInventoryEnabled');
    if (!el) return;
    el.checked = true;
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.click('#settingsSaveBtn');

  await expect.poll(() => capturedPayload).not.toBeNull();
  expect(capturedPayload.system.inventory_enabled).toBe(true);
});

test('folder active toggle persists using enabled without visible persistence', async ({ page }) => {
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
  // Wait for the library to render — this ensures loadConfig() has completed
  // and appConfig.folders is populated before openSettings() calls renderFoldersUI().
  await expect(page.locator('#library')).toContainText('Film VF');
  await page.evaluate(() => openSettings());

  const folderToggle = page.locator('input[data-folder-key="enabled"]').first();
  await expect(folderToggle).toBeChecked();
  await folderToggle.evaluate((el) => {
    el.checked = false;
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.click('#settingsSaveBtn');

  await expect.poll(() => capturedPayload).not.toBeNull();
  expect(capturedPayload.folders[0].enabled).toBe(false);
  expect(capturedPayload.folders[0].visible).toBeUndefined();
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

test('score settings tab renders dynamic keys and blocks save when weights total is invalid', async ({ page }) => {
  let capturedScorePayload = null;

  await page.route('**/api/settings/score', async (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      await route.fulfill({ json: scoreSettingsPayload() });
      return;
    }
    capturedScorePayload = JSON.parse(route.request().postData() || '{}');
    await route.fulfill({ json: { ok: true, effective: capturedScorePayload.score, status: { weights_total: 100, weights_valid: true, recalculated_items: 2, mode: 'score_only' } } });
  });
  await page.route('**/api/settings/score/reset', async (route) => {
    await route.fulfill({ json: { ok: true, effective: scoreSettingsPayload().effective, status: { weights_total: 100, weights_valid: true, recalculated_items: 2, mode: 'score_only' } } });
  });
  await page.route('**/api/config', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: configuredPayload() });
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
  await page.route('**/api/providers-map**', async (route) => {
    await route.fulfill({ json: {} });
  });
  await page.route('**/providers_logo.json**', async (route) => {
    await route.fulfill({ json: { Autres: 'other_play.webp' } });
  });

  await page.goto('/index.html');
  await page.evaluate(() => {
    openSettings();
    const btn = document.querySelector('button.stab[onclick*="stab-score"]');
    if (btn) switchStab(btn, 'stab-score');
  });

  await expect(page.locator('#stab-score')).toBeVisible();
  const scoreSections = page.locator('#scoreSettingsContainer .settings-collapsible');
  const sectionCount = await scoreSections.count();
  for (let i = 0; i < sectionCount; i += 1) {
    await scoreSections.nth(i).click();
  }
  await expect(page.locator('#scoreSettingsContainer')).toContainText(/vp9|VP9/i);
  await expect(page.locator('#scoreSettingsContainer')).toContainText('Custom Unknown Key');

  const videoWeightInput = page.locator('input[data-score-path="weights.video"]');
  await videoWeightInput.fill('40');
  await videoWeightInput.dispatchEvent('input');
  await expect(page.locator('#settingsSaveBtn')).toBeDisabled();

  await videoWeightInput.fill('50');
  await videoWeightInput.dispatchEvent('input');
  await expect(page.locator('#settingsSaveBtn')).toBeEnabled();

  await page.click('#settingsSaveBtn');
  await expect.poll(() => capturedScorePayload).not.toBeNull();
  expect(capturedScorePayload.score.video.codec.vp9).toBe(9);
});

test('score tab remains visible and shows disabled state when score feature is off', async ({ page }) => {
  await page.route('**/api/settings/score', async (route) => {
    await route.fulfill({ json: { ...scoreSettingsPayload(), enabled: false } });
  });
  await page.route('**/api/settings/score/reset', async (route) => {
    await route.fulfill({ json: { ok: true } });
  });
  await page.route('**/api/config', async (route) => {
    if (route.request().method() === 'GET') {
      const cfg = configuredPayload();
      cfg.score = { enabled: false };
      await route.fulfill({ json: cfg });
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
  await page.route('**/api/providers-map**', async (route) => {
    await route.fulfill({ json: {} });
  });
  await page.route('**/providers_logo.json**', async (route) => {
    await route.fulfill({ json: { Autres: 'other_play.webp' } });
  });

  await page.goto('/index.html');
  await page.evaluate(() => {
    openSettings();
    const btn = document.querySelector('button.stab[onclick*="stab-score"]');
    if (btn) switchStab(btn, 'stab-score');
  });

  await expect(page.locator('#stab-score')).toBeVisible();
  await expect(page.locator('#scoreSettingsDisabled')).toContainText('Le score qualité est actuellement désactivé');
  await expect(page.locator('#scoreSettingsContainer')).toBeEmpty();
  await expect(page.locator('#scoreResetRow')).toBeHidden();
});

test('score settings displays friendly error when API load fails', async ({ page }) => {
  await page.route('**/api/settings/score', async (route) => {
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { code: 'SCORE_SETTINGS_LOAD_FAILED' } }) });
  });
  await page.route('**/api/settings/score/reset', async (route) => {
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ ok: false }) });
  });
  await page.route('**/api/config', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: configuredPayload() });
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
  await page.route('**/api/providers-map**', async (route) => {
    await route.fulfill({ json: {} });
  });
  await page.route('**/providers_logo.json**', async (route) => {
    await route.fulfill({ json: { Autres: 'other_play.webp' } });
  });

  await page.goto('/index.html');
  await page.evaluate(() => {
    openSettings();
    const btn = document.querySelector('button.stab[onclick*="stab-score"]');
    if (btn) switchStab(btn, 'stab-score');
  });

  await expect(page.locator('#scoreSettingsStatus')).toBeVisible();
  await expect(page.locator('#scoreSettingsStatus')).toContainText('Impossible de charger la configuration du score');
});
