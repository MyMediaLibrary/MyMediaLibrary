(function () {
  const params = new URLSearchParams(window.location.search);
  const lang = params.get('lang') === 'en' ? 'en' : 'fr';
  const docPath = `/docs/${lang}.md`;

  const statusEl = document.getElementById('docsStatus');
  const contentEl = document.getElementById('docsContent');
  const themeBtn = document.getElementById('docsThemeToggle');
  const backToTopBtn = document.getElementById('docsBackToTop');
  const langFrBtn = document.getElementById('docsLangFr');
  const langEnBtn = document.getElementById('docsLangEn');
  const backToTopThreshold = 280;

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
  }

  function currentTheme() {
    return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  }

  function initTheme() {
    const saved = localStorage.getItem('mml_docs_theme');
    if (saved === 'light' || saved === 'dark') {
      applyTheme(saved);
      return;
    }
    applyTheme(window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  }

  function updateThemeButtonLabel() {
    if (!themeBtn) return;
    const isDark = currentTheme() === 'dark';
    themeBtn.setAttribute('title', isDark ? 'Activer le thème clair' : 'Activer le thème sombre');
  }

  function toggleTheme() {
    const next = currentTheme() === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    localStorage.setItem('mml_docs_theme', next);
    updateThemeButtonLabel();
  }

  function updateLanguageButtons() {
    const langMap = {
      fr: langFrBtn,
      en: langEnBtn
    };
    Object.entries(langMap).forEach(([buttonLang, button]) => {
      if (!button) return;
      const isActive = buttonLang === lang;
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
      button.disabled = isActive;
    });
  }

  function switchLanguage(nextLang) {
    if (nextLang === lang || (nextLang !== 'fr' && nextLang !== 'en')) return;
    const nextParams = new URLSearchParams(window.location.search);
    nextParams.set('lang', nextLang);
    const query = nextParams.toString();
    const nextUrl = `${window.location.pathname}${query ? `?${query}` : ''}`;

    history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
    window.location.assign(nextUrl);
  }

  function bindLanguageSwitch() {
    if (langFrBtn) langFrBtn.addEventListener('click', () => switchLanguage('fr'));
    if (langEnBtn) langEnBtn.addEventListener('click', () => switchLanguage('en'));
    updateLanguageButtons();
  }

  function scrollToHash(hash) {
    if (!hash) return;
    const id = decodeURIComponent(hash.replace(/^#/, ''));
    const target = document.getElementById(id);
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function bindInPageAnchors() {
    contentEl.addEventListener('click', (event) => {
      const link = event.target.closest('a[href^="#"]');
      if (!link) return;
      event.preventDefault();
      const hash = link.getAttribute('href');
      history.replaceState(null, '', hash);
      scrollToHash(hash);
    });
  }

  function updateBackToTopVisibility() {
    if (!backToTopBtn) return;
    const shouldShow = window.scrollY > backToTopThreshold;
    backToTopBtn.classList.toggle('is-visible', shouldShow);
    backToTopBtn.setAttribute('aria-hidden', shouldShow ? 'false' : 'true');
    backToTopBtn.tabIndex = shouldShow ? 0 : -1;
    if (!shouldShow && document.activeElement === backToTopBtn) {
      backToTopBtn.blur();
    }
  }

  function scrollToTop() {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  if (themeBtn) themeBtn.addEventListener('click', toggleTheme);
  bindLanguageSwitch();
  if (backToTopBtn) {
    backToTopBtn.addEventListener('click', scrollToTop);
    updateBackToTopVisibility();
    window.addEventListener('scroll', updateBackToTopVisibility, { passive: true });
  }
  initTheme();
  updateThemeButtonLabel();
  document.documentElement.lang = lang;

  function loadDoc() {
    fetch(docPath, { cache: 'no-store' })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.text();
      })
      .then((md) => {
        const html = window.DocsMarkdown.parseMarkdown(md);
        contentEl.innerHTML = html;
        bindInPageAnchors();
        contentEl.hidden = false;
        statusEl.hidden = true;
        scrollToHash(window.location.hash);
      })
      .catch((err) => {
        statusEl.textContent = `Impossible de charger la documentation (${err.message}).`;
        statusEl.classList.add('is-error');
      });
  }

  function init() {
    // Auth is enforced server-side by nginx auth_request on /docs.html.
    // The mml_session cookie is shared across tabs, so a valid session opened
    // in another tab grants access here automatically — no JS check needed.
    loadDoc();
  }

  init();
}());
