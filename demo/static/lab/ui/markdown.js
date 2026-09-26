// ui/markdown.js: a small safe renderer (text nodes only). Supports paragraphs, headings,
// bullet and numbered lists, **bold**, `code` and path#Lx-Ly citations (clickable).
import { h, icon } from './dom.js';

const CITE = /((?:[\w.-]+\/)*[\w.-]+\.md)#L(\d+)(?:-L(\d+))?/;
const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|(?:[\w.-]+\/)*[\w.-]+\.md#L\d+(?:-L\d+)?)/g;

export function inline(text, onCite) {
  const frag = document.createDocumentFragment();
  const str = String(text ?? '');
  let last = 0; let m;
  INLINE.lastIndex = 0;
  while ((m = INLINE.exec(str))) {
    if (m.index > last) frag.append(document.createTextNode(str.slice(last, m.index)));
    const v = m[0];
    if (v.startsWith('**')) frag.append(h('strong', null, v.slice(2, -2)));
    else if (v.startsWith('`')) frag.append(h('code', { class: 'inline-code' }, v.slice(1, -1)));
    else {
      const cm = CITE.exec(v);
      frag.append(h('button', {
        type: 'button', class: 'cite', 'data-tip': v,
        onclick: () => onCite && cm && onCite(cm[1], Number(cm[2]), Number(cm[3] || cm[2])),
      }, icon('file-text', 12), v));
    }
    last = m.index + v.length;
  }
  if (last < str.length) frag.append(document.createTextNode(str.slice(last)));
  return frag;
}

export function markdown(text, { onCite } = {}) {
  const root = h('div', { class: 'md' });
  const lines = String(text || '').split('\n');
  let list = null; let para = [];
  const flushPara = () => { if (para.length) { root.append(h('p', null, inline(para.join(' '), onCite))); para = []; } };
  const flushList = () => { if (list) { root.append(list); list = null; } };
  for (const raw of lines) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const num = /^\s*(\d+)[.)]\s+(.*)$/.exec(line);
    const head = /^(#{1,6})\s+(.*)$/.exec(line);
    if (!line.trim()) { flushPara(); flushList(); continue; }
    if (head) { flushPara(); flushList(); root.append(h('p', { class: 'md-h' }, inline(head[2], onCite))); continue; }
    if (bullet || num) {
      flushPara();
      const want = bullet ? 'ul' : 'ol';
      if (!list || list.tagName.toLowerCase() !== want) { flushList(); list = h(want); }
      list.append(h('li', null, inline(bullet ? bullet[1] : num[2], onCite)));
      continue;
    }
    flushList(); para.push(line.trim());
  }
  flushPara(); flushList();
  return root;
}
