(function () {
  const params = new URLSearchParams(window.location.search);
  const lang = params.get('lang') === 'en' ? 'en' : 'fr';
  const docPath = `/docs/${lang}.md`;

  const sourceLink = document.getElementById('docsSourceLink');
  const statusEl = document.getElementById('docsStatus');
  const contentEl = document.getElementById('docsContent');

  if (sourceLink) sourceLink.href = docPath;
  document.documentElement.lang = lang;

  fetch(docPath, { cache: 'no-store' })
    .then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.text();
    })
    .then((md) => {
      const html = window.DocsMarkdown.parseMarkdown(md);
      contentEl.innerHTML = html;
      contentEl.hidden = false;
      statusEl.hidden = true;
    })
    .catch((err) => {
      statusEl.textContent = `Impossible de charger la documentation (${err.message}).`;
      statusEl.classList.add('is-error');
    });
}());
