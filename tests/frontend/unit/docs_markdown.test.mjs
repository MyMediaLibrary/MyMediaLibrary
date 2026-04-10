import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { parseMarkdown } = require('../../../app/docs_markdown.js');

test('parses common markdown blocks and inline styles', () => {
  const input = [
    '# Titre',
    '',
    'Texte **gras** et *italique* avec [lien](https://example.com).',
    '',
    '- item 1',
    '- item 2',
    '',
    '> Citation',
    '',
    '---',
    '',
    '```js',
    'const x = 1;',
    '```'
  ].join('\n');

  const html = parseMarkdown(input);
  assert.match(html, /<h1 id="titre">Titre<\/h1>/);
  assert.match(html, /<strong>gras<\/strong>/);
  assert.match(html, /<em>italique<\/em>/);
  assert.match(html, /<a href="https:\/\/example.com"/);
  assert.match(html, /<ul><li>item 1<\/li><li>item 2<\/li><\/ul>/);
  assert.match(html, /<blockquote>/);
  assert.match(html, /<hr\/>/);
  assert.match(html, /<pre><code class="language-js">const x = 1;<\/code><\/pre>/);
});

test('escapes raw html and supports table syntax', () => {
  const html = parseMarkdown([
    '<script>alert(1)</script>',
    '',
    '| A | B |',
    '|---|---|',
    '| 1 | 2 |'
  ].join('\n'));

  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(html, /<table>/);
  assert.match(html, /<th>A<\/th>/);
  assert.match(html, /<td>2<\/td>/);
});


test('supports in-page anchors with heading ids and same-tab links', () => {
  const html = parseMarkdown([
    "## 1. Vue d'ensemble",
    '',
    '[Aller à la section](#1-vue-densemble)'
  ].join('\n'));

  assert.match(html, /<h2 id="1-vue-densemble">1\. Vue d&#39;ensemble<\/h2>/);
  assert.match(html, /<a href="#1-vue-densemble">Aller à la section<\/a>/);
  assert.doesNotMatch(html, /target="_blank"/);
});


test('renders inline code entities without double escaping', () => {
  const html = parseMarkdown('Utiliser `<tag attr="x">` et `a & b`.');
  assert.match(html, /<code>&lt;tag attr=&quot;x&quot;&gt;<\/code>/);
  assert.match(html, /<code>a &amp; b<\/code>/);
  assert.doesNotMatch(html, /&amp;lt;tag/);
});
