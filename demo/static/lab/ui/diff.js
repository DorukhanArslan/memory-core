// ui/diff.js: client-side line diff (prompt-vs-previous-turn only; file diffs come from the
// server as unified text), a unified-diff parser and the shared DiffView renderer.
import { h } from './dom.js';
import { t } from '../i18n/index.js';

/** LCS line diff with common prefix/suffix trimming. ops: {t:'='|'+'|'-', text, na?, nb?}. */
export function lineDiff(a, b) {
  if (a === null || a === undefined) return String(b ?? '').split('\n').map((text, i) => ({ t: '+', text, nb: i + 1 }));
  if (b === null || b === undefined) return String(a).split('\n').map((text, i) => ({ t: '-', text, na: i + 1 }));
  const A = String(a).split('\n'); const B = String(b).split('\n');
  let pre = 0; while (pre < A.length && pre < B.length && A[pre] === B[pre]) pre++;
  let suf = 0; while (suf < A.length - pre && suf < B.length - pre && A[A.length - 1 - suf] === B[B.length - 1 - suf]) suf++;
  const a2 = A.slice(pre, A.length - suf); const b2 = B.slice(pre, B.length - suf);
  const n = a2.length; const m = b2.length;
  const ops = [];
  for (let i = 0; i < pre; i++) ops.push({ t: '=', text: A[i], na: i + 1, nb: i + 1 });
  if (n * m > 4_000_000) {
    a2.forEach((text, i) => ops.push({ t: '-', text, na: pre + i + 1 }));
    b2.forEach((text, i) => ops.push({ t: '+', text, nb: pre + i + 1 }));
  } else {
    const dp = new Uint32Array((n + 1) * (m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) {
      dp[i * (m + 1) + j] = a2[i] === b2[j] ? dp[(i + 1) * (m + 1) + j + 1] + 1 : Math.max(dp[(i + 1) * (m + 1) + j], dp[i * (m + 1) + j + 1]);
    }
    let i = 0; let j = 0;
    while (i < n && j < m) {
      if (a2[i] === b2[j]) { ops.push({ t: '=', text: a2[i], na: pre + i + 1, nb: pre + j + 1 }); i++; j++; }
      else if (dp[(i + 1) * (m + 1) + j] >= dp[i * (m + 1) + j + 1]) { ops.push({ t: '-', text: a2[i], na: pre + i + 1 }); i++; }
      else { ops.push({ t: '+', text: b2[j], nb: pre + j + 1 }); j++; }
    }
    while (i < n) { ops.push({ t: '-', text: a2[i], na: pre + i + 1 }); i++; }
    while (j < m) { ops.push({ t: '+', text: b2[j], nb: pre + j + 1 }); j++; }
  }
  for (let k = 0; k < suf; k++) {
    const ia = A.length - suf + k; const ib = B.length - suf + k;
    ops.push({ t: '=', text: A[ia], na: ia + 1, nb: ib + 1 });
  }
  return ops;
}
export function diffStats(ops) {
  let added = 0; let removed = 0;
  for (const o of ops) { if (o.t === '+') added++; else if (o.t === '-') removed++; }
  return { added, removed };
}
/** Groups ops into hunks with `ctx` lines of context. */
export function hunks(ops, ctx = 3) {
  const out = []; let cur = null; let lastChange = -Infinity;
  ops.forEach((o, idx) => {
    if (o.t === '=') return;
    if (!cur || idx - lastChange > ctx * 2) {
      cur = { lines: [], start: idx }; out.push(cur);
      for (let k = Math.max(0, idx - ctx); k < idx; k++) if (ops[k].t === '=') cur.lines.push(ops[k]);
    } else for (let k = lastChange + 1; k < idx; k++) cur.lines.push(ops[k]);
    cur.lines.push(o); lastChange = idx; cur.end = idx;
  });
  for (const hk of out) {
    for (let k = hk.end + 1; k < Math.min(ops.length, hk.end + 1 + ctx); k++) { if (ops[k].t !== '=') break; hk.lines.push(ops[k]); }
    const first = hk.lines.find((l) => l.na) || {}; const firstB = hk.lines.find((l) => l.nb) || {};
    hk.header = `@@ -${first.na || 0},${hk.lines.filter((l) => l.t !== '+').length} +${firstB.nb || 0},${hk.lines.filter((l) => l.t !== '-').length} @@`;
  }
  return out;
}
/** Parses a unified diff (server-provided) into hunks of ops. File header lines are skipped. */
export function parseUnified(text) {
  const out = []; let cur = null; let na = 0; let nb = 0;
  for (const line of String(text || '').split('\n')) {
    if (line.startsWith('--- ') || line.startsWith('+++ ') || line.startsWith('diff ') || line.startsWith('index ')) continue;
    const m = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
    if (m) { cur = { header: line, lines: [] }; out.push(cur); na = Number(m[1]); nb = Number(m[2]); continue; }
    if (!cur) continue;
    if (line.startsWith('\\')) continue; // "\ No newline at end of file"
    const c = line[0]; const body = line.slice(1);
    if (c === '+') cur.lines.push({ t: '+', text: body, nb: nb++ });
    else if (c === '-') cur.lines.push({ t: '-', text: body, na: na++ });
    else if (c === ' ' || line === '') cur.lines.push({ t: '=', text: body, na: na++, nb: nb++ });
  }
  return out;
}
export function unifiedStats(text) {
  let added = 0; let removed = 0;
  for (const hk of parseUnified(text)) for (const l of hk.lines) { if (l.t === '+') added++; else if (l.t === '-') removed++; }
  return { added, removed };
}
/** Added lines (text only) of a unified diff; used for step-captured scenario references. */
export function addedLines(text) {
  return parseUnified(text).flatMap((hk) => hk.lines.filter((l) => l.t === '+').map((l) => l.text));
}

/** DiffView: accepts hunks (from hunks() or parseUnified()). */
export function diffView(hs, { maxLines = 400, compact = false } = {}) {
  const root = h('div', { class: ['diff', compact ? 'is-compact' : ''], 'data-testid': 'diff-view' });
  if (!hs.length) { root.append(h('div', { class: 'diff-empty muted' }, t('diff.none'))); return root; }
  let shown = 0;
  for (const hk of hs) {
    if (!compact) root.append(h('div', { class: 'diff-hunk' }, hk.header));
    for (const l of hk.lines) {
      if (shown++ >= maxLines) { root.append(h('div', { class: 'diff-more muted' }, t('diff.more'))); return root; }
      const kind = l.t === '+' ? 'is-add' : l.t === '-' ? 'is-del' : '';
      root.append(h('div', { class: ['diff-line', kind], 'aria-label': l.t === '+' ? t('diff.added') : l.t === '-' ? t('diff.removed') : null },
        compact ? null : h('span', { class: 'dg' }, l.na ?? ''), compact ? null : h('span', { class: 'dg' }, l.nb ?? ''),
        h('span', { class: 'dm' }, l.t === '=' ? ' ' : l.t === '-' ? '−' : '+'), h('span', { class: 'dt' }, l.text || ' ')));
    }
  }
  return root;
}
