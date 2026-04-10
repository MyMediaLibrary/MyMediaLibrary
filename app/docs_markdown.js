(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.DocsMarkdown = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function sanitizeUrl(url) {
    const trimmed = (url || '').trim();
    if (/^(https?:|mailto:|\/|#)/i.test(trimmed)) return trimmed;
    return '#';
  }

  function renderInline(text) {
    const codeTokens = [];
    let safe = escapeHtml(text || '');

    safe = safe.replace(/`([^`]+)`/g, (_, code) => {
      const token = `@@CODE_${codeTokens.length}@@`;
      codeTokens.push(`<code>${escapeHtml(code)}</code>`);
      return token;
    });

    safe = safe.replace(/\[([^\]]+)\]\(([^\)]+)\)/g, (_, label, url) => {
      const cleanUrl = sanitizeUrl(url);
      return `<a href="${escapeHtml(cleanUrl)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
    });

    safe = safe.replace(/(\*\*|__)(.*?)\1/g, '<strong>$2</strong>');
    safe = safe.replace(/(^|\s)(\*|_)([^*_]+?)\2(?=\s|$|[.,;:!?])/g, '$1<em>$3</em>');

    safe = safe.replace(/@@CODE_(\d+)@@/g, (_, idx) => codeTokens[Number(idx)] || '');
    return safe;
  }

  function isSpecialLine(line) {
    return /^(#{1,6}\s+|\s*[-*_]{3,}\s*$|\s*>|\s*([-*+]\s+|\d+\.\s+)|\s*```)/.test(line);
  }

  function parseTable(lines, startIndex) {
    const headerLine = lines[startIndex];
    const separatorLine = lines[startIndex + 1] || '';
    if (!headerLine.includes('|')) return null;
    if (!/^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(separatorLine)) return null;

    const splitCells = (line) => line.replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
    const headers = splitCells(headerLine);
    const alignRaw = splitCells(separatorLine);
    const aligns = alignRaw.map((cell) => {
      if (/^:-+:$/.test(cell)) return 'center';
      if (/^-+:$/.test(cell)) return 'right';
      if (/^:-+$/.test(cell)) return 'left';
      return '';
    });

    let i = startIndex + 2;
    const rows = [];
    while (i < lines.length && lines[i].includes('|') && lines[i].trim() !== '') {
      rows.push(splitCells(lines[i]));
      i += 1;
    }

    const th = headers.map((h, idx) => `<th${aligns[idx] ? ` style="text-align:${aligns[idx]}"` : ''}>${renderInline(h)}</th>`).join('');
    const body = rows.map((row) => {
      const cells = headers.map((_, idx) => `<td${aligns[idx] ? ` style="text-align:${aligns[idx]}"` : ''}>${renderInline(row[idx] || '')}</td>`).join('');
      return `<tr>${cells}</tr>`;
    }).join('');

    return {
      html: `<table><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table>`,
      nextIndex: i
    };
  }

  function parseMarkdown(mdText) {
    const lines = String(mdText || '').replace(/\r/g, '').split('\n');
    const out = [];
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];
      const trimmed = line.trim();

      if (!trimmed) {
        i += 1;
        continue;
      }

      if (/^```/.test(trimmed)) {
        const lang = trimmed.slice(3).trim();
        const code = [];
        i += 1;
        while (i < lines.length && !/^```/.test(lines[i].trim())) {
          code.push(lines[i]);
          i += 1;
        }
        if (i < lines.length) i += 1;
        out.push(`<pre><code${lang ? ` class="language-${escapeHtml(lang)}"` : ''}>${escapeHtml(code.join('\n'))}</code></pre>`);
        continue;
      }

      if (/^#{1,6}\s+/.test(trimmed)) {
        const level = trimmed.match(/^#+/)[0].length;
        const text = trimmed.replace(/^#{1,6}\s+/, '');
        out.push(`<h${level}>${renderInline(text)}</h${level}>`);
        i += 1;
        continue;
      }

      if (/^\s*[-*_]{3,}\s*$/.test(trimmed)) {
        out.push('<hr/>');
        i += 1;
        continue;
      }

      if (/^>\s?/.test(trimmed)) {
        const quoteLines = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
          quoteLines.push(lines[i].replace(/^\s*>\s?/, ''));
          i += 1;
        }
        const quoteHtml = parseMarkdown(quoteLines.join('\n'));
        out.push(`<blockquote>${quoteHtml}</blockquote>`);
        continue;
      }

      const table = parseTable(lines, i);
      if (table) {
        out.push(table.html);
        i = table.nextIndex;
        continue;
      }

      if (/^\s*([-*+])\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
        const ordered = /^\s*\d+\.\s+/.test(line);
        const tag = ordered ? 'ol' : 'ul';
        const items = [];
        while (i < lines.length) {
          const current = lines[i];
          const m = ordered ? current.match(/^\s*\d+\.\s+(.+)$/) : current.match(/^\s*[-*+]\s+(.+)$/);
          if (!m) break;
          items.push(`<li>${renderInline(m[1])}</li>`);
          i += 1;
        }
        out.push(`<${tag}>${items.join('')}</${tag}>`);
        continue;
      }

      const para = [trimmed];
      i += 1;
      while (i < lines.length && lines[i].trim() && !isSpecialLine(lines[i].trim())) {
        para.push(lines[i].trim());
        i += 1;
      }
      out.push(`<p>${renderInline(para.join(' '))}</p>`);
    }

    return out.join('\n');
  }

  return {
    parseMarkdown,
    renderInline,
    escapeHtml
  };
}));
