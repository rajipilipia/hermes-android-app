// Code-derived, synthetic-only UI wireframes. No phone, backend, shared browser or git write.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { chromium } from '@playwright/test';
import { bootApkLayoutFixture } from '../tests/browser/android-layout-bootstrap.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(ROOT, '.cache/wireframe-code');
const BUILD = path.join(OUT, 'build');
const ORIGIN = 'http://127.0.0.1:18779'; // Intercepted in-process; no listening server.
const CLI = process.env.FIGCRAFT_CLI ?? 'C:/example-projects/storytold_CRAFTs/figcraft/portable/figcraft-0.6.0-windows-x64-portable/figcraft-cli.exe';
const probe = process.argv.includes('--probe');
const skipBuild = process.argv.includes('--reuse-build');
const log = [];
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const write = (file, value) => { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, value); };
const json = (file, value) => write(file, JSON.stringify(value, null, 2) + '\n');
const relative = file => path.relative(ROOT, file).replaceAll('\\', '/');
const check = (ok, message) => { if (!ok) throw new Error(message); };
function memoryGate() {
  const bytes = os.freemem();
  check(bytes >= 2.5 * 1024 ** 3, `PAUSED: ${(bytes / 1024 ** 3).toFixed(2)} GiB free; need 2.5 GiB before Chromium.`);
  return bytes;
}
function run(exe, args, timeout = 120000) {
  const p = spawnSync(exe, args, { cwd: ROOT, encoding: 'utf8', timeout, maxBuffer: 16 * 1024 ** 2, windowsHide: true });
  log.push({ executable: exe, args, exit: p.status, error: p.error?.message, stdout: p.stdout, stderr: p.stderr });
  json(path.join(OUT, 'commands.json'), log);
  check(p.status === 0, `${path.basename(exe)} failed (${p.status}): ${(p.stderr || p.error?.message || '').slice(-1500)}`);
  return p.stdout;
}
function sourceSnapshot() {
  const paths = run('git', ['ls-files', '-z']).split('\0').filter(Boolean)
    .filter(p => /^(src\/|vendor\/hermes\/apps\/(desktop|shared)\/src\/|tests\/browser\/)|^(package(-lock)?\.json|vite\.config\.ts)$/.test(p));
  return Object.fromEntries(paths.sort().filter(p => fs.existsSync(path.join(ROOT, p))).map(p => [p, hash(fs.readFileSync(path.join(ROOT, p)))]));
}
const FIXED = 1792584000000;
const profiles = Array.from({ length: 11 }, (_, i) => ({
  name: i ? `profile-${String.fromCharCode(97 + i)}` : 'default',
  display_name: `Profile ${String.fromCharCode(65 + i)}`, is_active: i === 0, is_default: i === 0,
}));
const sessions = Array.from({ length: 10 }, (_, i) => ({
  id: `wireframe-session-${i + 1}`, session_id: `wireframe-session-${i + 1}`,
  title: `Session title ${i + 1}`, preview: 'Placeholder message', profile: 'default', message_count: 0,
  started_at: FIXED / 1000 - (i < 2 ? 3600 : 7 * 86400) - i * 3600,
  last_active: FIXED / 1000 - (i < 2 ? 3600 : 7 * 86400) - i * 3600,
  source: i === 8 ? 'whatsapp' : i === 9 ? 'api_server' : 'desktop', model: 'gpt-5', pinned: i === 0,
}));
function fixtureRest(params, fallback, calls) {
  const op = params.operation; calls.push({ kind: 'rest', operation: op });
  if (op === 'GET /api/profiles/active') return { status: 200, body: { active: 'default', current: 'default' } };
  if (op === 'GET /api/profiles') return { status: 200, body: { profiles, active_profile: 'default' } };
  if (op === 'GET /api/config') return { status: 200, body: { display: { language: 'en', skin: 'nous' }, model: { default: 'gpt-5', provider: 'openai' }, agent: { max_turns: 90, reasoning_effort: 'high' }, compression: { enabled: true }, terminal: { cwd: '/synthetic/project-folder' } } };
  if (op === 'GET /api/fs/default-cwd') return { status: 200, body: { cwd: '/synthetic/project-folder', branch: 'example' } };
  if (op === 'GET /api/model/info') return { status: 200, body: { model: 'gpt-5', provider: 'openai', context_length: 32768, reasoning_effort: 'high' } };
  if (op === 'GET /api/model/options') return { status: 200, body: { providers: [{ slug: 'openai', name: 'Model provider', models: ['gpt-5'], is_current: true, authenticated: true }], model: 'gpt-5', provider: 'openai', current: { model: 'gpt-5', provider: 'openai' } } };
  if (op === 'GET /api/sessions' || op === 'GET /api/profiles/sessions') return { status: 200, body: { sessions, total: sessions.length, has_more: false } };
  if (op === 'GET /api/profiles/sessions/sidebar') return { status: 200, body: {
    recents: { sessions: sessions.filter(s => s.source === 'desktop'), profiles_truncated: { default: false }, profiles_usage: {} },
    cron: { sessions: [], total: 0 }, messaging: { sessions: sessions.filter(s => s.source !== 'desktop'), total: 2 }, errors: [], storage: {},
  } };
  if (op === 'GET /api/sessions/{session_id}') return { status: 200, body: sessions.find(s => s.id === params.pathParams?.session_id) ?? sessions[0] };
  if (op === 'GET /api/sessions/{session_id}/messages') return { status: 200, body: { session_id: params.pathParams?.session_id, profile: 'default', messages: [], pagination: { has_more: false, limit: 120, offset: 0, order: 'latest' } } };
  return fallback(params, [], true);
}
function socketPeer(calls) {
  let created = 0;
  return ws => ws.onMessage(raw => {
    const frame = JSON.parse(String(raw));
    if (!frame.method || frame.id == null) return;
    const m = frame.method; calls.push({ kind: 'socket', operation: m });
    let result = {};
    if (m === 'session.list') result = { sessions, total: sessions.length, has_more: false };
    else if (m === 'profiles.list') result = { profiles, active_profile: 'default' };
    else if (m === 'commands.catalog') result = { commands: [] };
    else if (m === 'session.events.since') result = { events: [], count: 0, latest_seq: 0, epoch: 'wireframe-fixture', open_requests: [] };
    else if (m === 'setup.status') result = { provider_configured: true, ready: true };
    else if (m === 'setup.runtime_check') result = { ok: true, model: 'gpt-5', provider: 'openai' };
    else if (m === 'model.options') result = { providers: [{ slug: 'openai', name: 'Model provider', models: ['gpt-5'], is_current: true, authenticated: true }], model: 'gpt-5', provider: 'openai', current: { model: 'gpt-5', provider: 'openai' } };
    else if (m === 'session.active_list') result = { sessions: [] };
    else if (m === 'onboarding.state') result = { eligible: false, run: false, run_id: null, session_id: null };
    else if (m === 'i18n.languages') result = { languages: [] };
    else if (m === 'i18n.catalog') result = { locale: 'en', messages: {} };
    else if (m === 'free_tier.status') result = { enabled: false, notice_pending: false };
    else if (m === 'models.list') result = { models: [] };
    else if (m === 'session.control.read') result = { control: { goal: null, loop: null, heartbeat: null, revision: 'wireframe', updated_at: FIXED / 1000 } };
    else if (m === 'session.create' || m === 'session.resume') {
      const id = m === 'session.create' ? `wireframe-new-${++created}` : frame.params?.session_id ?? sessions[0].id;
      result = { session_id: `runtime-${id}`, stored_session_id: id, messages: [], message_count: 0, running: false,
        info: { desktop_contract: 8, model: 'gpt-5', provider: 'openai', reasoning_effort: 'high', cwd: '/synthetic/project-folder' } };
    } else if (m === 'session.history') result = { messages: [], count: 0 };
    ws.send(JSON.stringify({ jsonrpc: '2.0', id: frame.id, result }));
  });
}
async function stable(page) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => !document.querySelector('[data-contrib-shell] .animate-pulse'));
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
async function drawerState(page, open) {
  const current = await page.locator('[data-sessions-mode]').isVisible();
  if (open !== current) {
    if (!open && await page.locator('[data-narrow-overlay]').isVisible()) await page.touchscreen.tap(page.viewportSize().width - 8, 120);
    else await page.getByRole('button', { name: open ? 'Show sidebar' : 'Hide sidebar', exact: true }).tap();
  }
  await page.locator('[data-sessions-mode]').waitFor({ state: open ? 'visible' : 'hidden' });
  await stable(page);
}
async function captureStates(app, dir) {
  const { page } = app, states = [];
  await drawerState(page, false);
  states.push(await inspect(page, 'F1', dir));
  await drawerState(page, true);
  await page.locator('[data-slot="profile-rail"]').waitFor();
  states.push(await inspect(page, 'F2', dir));
  await page.getByRole('button', { name: 'Filters', exact: true }).tap();
  await page.getByRole('menuitemcheckbox', { name: 'Profile rail', exact: true }).tap();
  await page.locator('[data-slot="profile-rail"]').waitFor({ state: 'hidden' });
  await page.keyboard.press('Escape');
  states.push(await inspect(page, 'F3', dir));
  await drawerState(page, false);
  await page.locator('footer [data-slot="profile-switcher"] button').tap();
  await page.getByRole('menuitemradio', { name: /Profile A/ }).waitFor();
  states.push(await inspect(page, 'F4', dir));
  await page.keyboard.press('Escape');
  await drawerState(page, true);
  await page.getByRole('button', { name: 'Filters', exact: true }).tap();
  await page.getByRole('menuitemcheckbox', { name: 'Profile rail', exact: true }).tap();
  await page.locator('[data-slot="profile-rail"]').waitFor();
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Filters', exact: true }).tap();
  await page.getByRole('menuitemcheckbox', { name: 'Profile rail', exact: true }).waitFor();
  states.push(await inspect(page, 'F5', dir));
  await page.keyboard.press('Escape'); await drawerState(page, false);
  for (let i = 0; i < 7; i++) {
    const count = await page.locator('[data-tree-tab]').count();
    await page.getByRole('button', { name: 'New session tab', exact: true }).tap();
    await page.waitForFunction(n => document.querySelectorAll('[data-tree-tab]').length > n, count);
    await stable(page);
  }
  await page.locator('[data-tree-tab]').first().tap(); await stable(page);
  states.push(await inspect(page, 'CROWDED', dir));
  return states;
}
async function boot(browser, viewport, harness, dir) {
  const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, screen: { width: viewport.width, height: viewport.height }, deviceScaleFactor: viewport.dpr, isMobile: true, hasTouch: true, colorScheme: 'light', reducedMotion: 'reduce', serviceWorkers: 'block' });
  const page = await context.newPage(); page.setDefaultTimeout(12000);
  const inherited = await harness.configureLayoutFixture(page, { detailed: true, multiProfile: true });
  const calls = [], blocked = [];
  await page.exposeFunction('__wireframeRestFixture', request => fixtureRest(JSON.parse(request), harness.restReply, calls));
  await page.addInitScript(({ now }) => {
    const OriginalDate = Date;
    window.Date = class extends OriginalDate { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } };
    Math.random = () => 0.314159265;
    window.__hermesRestFixture = window.__wireframeRestFixture;
    localStorage.setItem('hermes.desktop.pinnedSessions', JSON.stringify(['wireframe-session-1']));
    localStorage.setItem('hermes.desktop.pinnedSessions.remote.' + encodeURIComponent('https://layout-fixture.invalid'), JSON.stringify(['wireframe-session-1']));
    localStorage.setItem('hermes.desktop.sidebarGrouping', JSON.stringify('date'));
  }, { now: FIXED });
  await page.routeWebSocket(/\/api\/ws(\?|$)/, socketPeer(calls));
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.woff2': 'font/woff2', '.woff': 'font/woff', '.svg': 'image/svg+xml', '.png': 'image/png' };
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== ORIGIN) { blocked.push(url.origin); await route.abort(); return; }
    const file = path.resolve(BUILD, '.' + decodeURIComponent(url.pathname === '/' ? '/index.html' : url.pathname));
    if (!file.startsWith(BUILD + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { await route.fulfill({ status: 404, body: '' }); return; }
    let body = fs.readFileSync(file);
    if (file.endsWith('index.html')) body = Buffer.from(body.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, ''));
    await route.fulfill({ status: 200, contentType: types[path.extname(file)] ?? 'application/octet-stream', body });
  });
  await page.goto(ORIGIN + '/', { waitUntil: 'networkidle' });
  await bootApkLayoutFixture(page, BUILD);
  await page.locator('[data-slot="composer-root"]').first().waitFor();
  await stable(page);
  return { page, context, errors: inherited.errors, calls, blocked };
}
async function inspect(page, key, dir) {
  await stable(page);
  const mapping = JSON.parse(fs.readFileSync(path.join(ROOT, 'scripts/wireframe-element-map.json'), 'utf8'));
  for (const rule of mapping.rules) {
    if (rule.id.startsWith('PP-')) { rule.states = ['F4']; if (rule.nameRegex?.startsWith('^Profile ')) rule.nameRegex = rule.nameRegex.replace('^Profile ', '^(?:P )?Profile '); }
    if (rule.id.startsWith('FM-')) rule.states = ['F5'];
  }
  const data = await page.evaluate(({ rules, state }) => {
    const clipOf = e => {
      const r = e.getBoundingClientRect();
      const c = { x: Math.max(0, r.left), y: Math.max(0, r.top), right: Math.min(innerWidth, r.right), bottom: Math.min(innerHeight, r.bottom) };
      for (let p = e.parentElement; p; p = p.parentElement) {
        const s = getComputedStyle(p), b = p.getBoundingClientRect();
        if (['hidden', 'clip', 'auto', 'scroll'].includes(s.overflowX)) { c.x = Math.max(c.x, b.left); c.right = Math.min(c.right, b.right); }
        if (['hidden', 'clip', 'auto', 'scroll'].includes(s.overflowY)) { c.y = Math.max(c.y, b.top); c.bottom = Math.min(c.bottom, b.bottom); }
      }
      return { ...c, width: Math.max(0, c.right - c.x), height: Math.max(0, c.bottom - c.y) };
    };
    const visible = e => {
      const r = e.getBoundingClientRect(), s = getComputedStyle(e);
      if (r.width <= 0 || r.height <= 0 || s.display === 'none' || s.visibility !== 'visible' || e.closest('[hidden],[inert]')) return false;
      for (let p = e; p; p = p.parentElement) if (Number(getComputedStyle(p).opacity) === 0) return false;
      const c = clipOf(e); return c.width > 0 && c.height > 0;
    };
    const selector = e => {
      const bits = [];
      while (e && e !== document.documentElement) {
        const tag = e.localName, slot = e.getAttribute('data-slot'), testid = e.getAttribute('data-testid'), aria = e.getAttribute('aria-label');
        let bit = tag;
        if (testid) bit += `[data-testid=${JSON.stringify(testid)}]`;
        else if (slot) bit += `[data-slot=${JSON.stringify(slot)}]`;
        else if (aria) bit += `[aria-label=${JSON.stringify(aria)}]`;
        else if (e.hasAttribute('data-tree-tab')) bit += '[data-tree-tab]';
        else if (e.getAttribute('data-pane-host')) bit += `[data-pane-host=${JSON.stringify(e.getAttribute('data-pane-host'))}]`;
        else if (e.parentElement) bit += `:nth-of-type(${[...e.parentElement.children].filter(c => c.localName === tag).indexOf(e) + 1})`;
        if (e.parentElement && [...e.parentElement.children].filter(c => c.matches(bit)).length > 1) bit += `:nth-of-type(${[...e.parentElement.children].filter(c => c.localName === tag).indexOf(e) + 1})`;
        bits.unshift(bit);
        const joined = bits.join(' > ');
        if (document.querySelectorAll(joined).length === 1 && (aria || slot || testid || e.hasAttribute('data-pane-host'))) return joined;
        e = e.parentElement;
      }
      return 'html > ' + bits.join(' > ');
    };
    const used = new Set();
    return { state, viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio, screen: [screen.width, screen.height], compact: document.documentElement.hasAttribute('data-android-compact') }, elements: [...document.querySelectorAll('body *')].filter(e => {
      if (['SCRIPT', 'STYLE', 'LINK', 'META', 'PATH', 'DEFS', 'CLIPPATH'].includes(e.tagName.toUpperCase())) return false;
      const direct = [...e.childNodes].some(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim());
      return visible(e) && (direct || e.matches('button,a,input,textarea') || ['aria-label', 'role', 'data-slot', 'data-testid', 'data-tree-tab'].some(a => e.hasAttribute(a)));
    }).map(e => {
      const r = e.getBoundingClientRect(), s = getComputedStyle(e);
      const text = [...e.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join(' ').replace(/\s+/g, ' ').trim();
      const name = e.getAttribute('aria-label') || e.getAttribute('title') || e.getAttribute('placeholder') || (e.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => document.getElementById(id)?.textContent || '').join(' ').trim() || (e.innerText || text || '').replace(/\s+/g, ' ').trim().slice(0, 180);
      const rule = rules.find(rule => (!rule.states || rule.states.includes(state)) && e.matches(rule.selector) && (!rule.inside || e.closest(rule.inside)) && (!rule.nameRegex || new RegExp(rule.nameRegex, 'i').test(name)) && (!rule.textExact || text.toLowerCase() === rule.textExact.toLowerCase()) && (!rule.leafText || text) && !used.has(rule.id));
      if (rule) used.add(rule.id);
      const owner = e.parentElement?.closest('button,a,[role="tab"],[role^="menuitem"],[contenteditable="true"]');
      const range = document.createRange(); range.selectNodeContents(e);
      const tr = range.getBoundingClientRect();
      return { id: rule?.id ?? null, mappedName: rule?.name, sourceHint: rule?.sourceHint, codeHint: rule?.codeHint, tag: e.localName, role: e.getAttribute('role') || '', accessibleName: name, ariaLabel: e.getAttribute('aria-label'), text, slot: e.getAttribute('data-slot'), testId: e.getAttribute('data-testid'), selector: selector(e), ownerSelector: owner ? selector(owner) : null, box: { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }, visibleBox: clipOf(e), clientWidth: e.clientWidth, scrollWidth: e.scrollWidth, clientHeight: e.clientHeight, scrollHeight: e.scrollHeight, textExtent: { width: tr.width, height: tr.height }, style: { fontSize: parseFloat(s.fontSize), lineHeight: parseFloat(s.lineHeight), overflowX: s.overflowX, overflowY: s.overflowY, textOverflow: s.textOverflow, whiteSpace: s.whiteSpace, background: s.backgroundColor, borderRadius: parseFloat(s.borderRadius) }, region: e.closest('footer[data-slot="statusbar"]') ? 'statusbar' : e.closest('[data-zone-tabstrip],[data-titlebar-cluster]') ? 'tabstrip' : 'body', interactive: e.matches('button,a,input,textarea,[contenteditable="true"],[role="tab"],[role^="menuitem"]'), childElements: e.childElementCount };
    }) };
  }, { rules: mapping.rules, state: key });
  for (const e of data.elements) e.id ??= 'NEW-' + hash(e.selector).slice(0, 8);
  check(new Set(data.elements.map(e => e.selector)).size === data.elements.length, key + ': selectors must be unique.');
  check(new Set(data.elements.map(e => e.id)).size === data.elements.length, key + ': IDs must be unique.');
  const details = await page.evaluate(selectors => selectors.map(selector => {
    const e = document.querySelector(selector), s = getComputedStyle(e), runs = [];
    for (const n of e.childNodes) {
      if (n.nodeType !== Node.TEXT_NODE || !n.textContent.trim()) continue;
      let current;
      for (let i = 0; i < n.textContent.length; i++) {
        const range = document.createRange(); range.setStart(n, i); range.setEnd(n, i + 1);
        const r = range.getClientRects()[0]; if (!r || !r.width || !r.height) continue;
        let char = n.textContent[i];
        if (s.textTransform === 'uppercase') char = char.toUpperCase();
        if (s.textTransform === 'lowercase') char = char.toLowerCase();
        if (current && Math.abs(current.y - r.y) < 0.5 && Math.abs(current.right - r.x) < 1) { current.text += char; current.right = r.right; current.width = r.right - current.x; }
        else { current = { text: char, x: r.x, y: r.y, width: r.width, height: r.height, right: r.right }; runs.push(current); }
      }
    }
    const r = e.getBoundingClientRect(), x = Math.max(0, Math.min(innerWidth - 1, r.x + r.width / 2)), y = Math.max(0, Math.min(innerHeight - 1, r.y + r.height / 2));
    const hit = document.elementFromPoint(x, y);
    const paintClip = { x: 0, y: 0, right: innerWidth, bottom: innerHeight };
    for (let p = e; p; p = p.parentElement) {
      const ps = getComputedStyle(p), pr = p.getBoundingClientRect();
      if (['hidden', 'clip', 'auto', 'scroll'].includes(ps.overflowX)) { paintClip.x = Math.max(paintClip.x, pr.left); paintClip.right = Math.min(paintClip.right, pr.right); }
      if (['hidden', 'clip', 'auto', 'scroll'].includes(ps.overflowY)) { paintClip.y = Math.max(paintClip.y, pr.top); paintClip.bottom = Math.min(paintClip.bottom, pr.bottom); }
    }
    paintClip.width = Math.max(0, paintClip.right - paintClip.x); paintClip.height = Math.max(0, paintClip.bottom - paintClip.y);
    const indicator = e.getAttribute('aria-checked') === 'true' ? e.querySelector('[data-state="checked"]') : null;
    const ir = (indicator?.lastElementChild ?? indicator)?.getBoundingClientRect();
    const checkBox = ir?.width && ir?.height ? { x: ir.x, y: ir.y, width: ir.width, height: ir.height } : null;
    return { runs, paintClip, checkBox, layer: e.closest('[role="menu"]') ? 'menu' : e.closest('[data-narrow-overlay]') ? 'drawer' : 'base', occludedAtCenter: !hit || !(e === hit || e.contains(hit) || hit.contains(e)), placeholder: e.getAttribute('placeholder') || e.getAttribute('data-placeholder') || '', checked: e.getAttribute('aria-checked'), fontWeight: s.fontWeight, paddingLeft: parseFloat(s.paddingLeft), paddingTop: parseFloat(s.paddingTop) };
  }), data.elements.map(e => e.selector));
  data.elements.forEach((e, i) => Object.assign(e, details[i]));
  data.layout = await page.evaluate(() => {
    const boxes = selector => [...document.querySelectorAll(selector)].map(e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e); return { selector, x: r.x, y: r.y, width: r.width, height: r.height, clientWidth: e.clientWidth, scrollWidth: e.scrollWidth, display: s.display, overflowX: s.overflowX }; }).filter(r => r.width && r.height && r.display !== 'none');
    const offscreen = [...document.querySelectorAll('body *')].flatMap(e => {
      const r = e.getBoundingClientRect(), s = getComputedStyle(e);
      const direct = [...e.childNodes].some(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim());
      if (!(direct || e.matches('button,a,input,textarea,[aria-label],[role],[data-slot],[data-testid],[data-tree-tab]')) || !r.width || !r.height || s.display === 'none' || s.visibility !== 'visible' || e.closest('[hidden],[inert]') || r.bottom <= 0 || r.top >= innerHeight || r.right <= innerWidth + 0.5) return [];
      for (let p = e; p; p = p.parentElement) if (Number(getComputedStyle(p).opacity) === 0) return [];
      return [{ name: e.getAttribute('aria-label') || e.innerText || e.getAttribute('placeholder') || '', slot: e.getAttribute('data-slot'), tag: e.localName, x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, region: e.closest('footer[data-slot="statusbar"]') ? 'statusbar' : e.closest('[data-zone-tabstrip],[data-titlebar-cluster]') ? 'tabstrip' : 'body' }];
    });
    return { documentClientWidth: document.documentElement.clientWidth, documentScrollWidth: document.documentElement.scrollWidth, tabstrips: boxes('[data-zone-tabstrip]'), statusbars: boxes('footer[data-slot="statusbar"]'), drawers: boxes('[data-narrow-overlay]'), rightControls: boxes('[data-titlebar-cluster="right"]'), offscreen };
  });
  json(path.join(dir, key + '.dom.json'), data);
  console.log(JSON.stringify({ state: key, boxes: data.elements.length, viewport: data.viewport }));
  return data;
}
const xml = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const n = value => Math.round(value * 1000) / 1000;
const rect = (b, attrs = '') => `<rect x="${n(b.x)}" y="${n(b.y)}" width="${n(b.width)}" height="${n(b.height)}" ${attrs}/>`;
const overlaps = (a, b) => a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
function linkSources(states, inputs) {
  const files = Object.keys(inputs).filter(p => /\.(tsx?|css)$/.test(p) && !/\.test\./.test(p)).map(file => ({ file, lines: fs.readFileSync(path.join(ROOT, file), 'utf8').split('\n') }));
  const byFile = new Map(files.map(f => [f.file, f]));
  const find = (file, term, kind) => {
    const row = file?.lines.findIndex(line => line.includes(term));
    return row >= 0 ? { file: file.file, line: row + 1, symbol: term, kind, status: 'VERIFIED' } : null;
  };
  for (const state of states) {
    for (const e of state.elements) {
      const hinted = byFile.get(e.sourceHint?.split(':')[0]);
      const terms = (e.codeHint ?? '').split(';').map(s => s.trim()).filter(Boolean);
      const declarations = terms.flatMap(t => [`function ${t}(`, `function ${t} `, `const ${t} =`, `<${t}`]);
      e.source = declarations.map(t => find(hinted, t, 'component')).find(Boolean) ?? terms.map(t => find(hinted, t, 'code hint')).find(Boolean);
      if (!e.source && e.slot) for (const file of files) { e.source = find(file, `data-slot="${e.slot}"`, 'DOM slot'); if (e.source) break; }
      if (!e.source && e.testId) for (const file of files) { e.source = find(file, `data-testid="${e.testId}"`, 'test ID'); if (e.source) break; }
      if (!e.source && e.ariaLabel) for (const file of files) { e.source = find(file, `aria-label="${e.ariaLabel}"`, 'aria label'); if (e.source) break; }
    }
    const keyed = new Map(state.elements.map(e => [e.selector, e]));
    for (const e of state.elements) {
      if (!e.source && e.ownerSelector && keyed.get(e.ownerSelector)?.source) e.source = { ...keyed.get(e.ownerSelector).source, kind: 'owning control' };
      if (!e.source && e.text.length > 3) for (const file of files) { e.source = find(file, e.text, 'text definition; not necessarily render callsite'); if (e.source) break; }
      e.source ??= { status: 'UNVERIFIED', reason: 'Measured from the app DOM, but an exact static component callsite was not resolved.' };
    }
  }
}
function fitNativeText(states, dir) {
  const unique = new Map();
  for (const state of states) for (const e of state.elements) for (const run of e.runs) {
    run.fontKey = JSON.stringify([run.text, e.style.fontSize || 12, Number(e.fontWeight) || 400]);
    if (!unique.has(run.fontKey)) unique.set(run.fontKey, { id: `measure-${unique.size}`, text: run.text, size: e.style.fontSize || 12, weight: Number(e.fontWeight) || 400 });
  }
  const svg = path.join(dir, 'font-metrics.svg'), output = path.join(dir, 'font-metrics.json');
  write(svg, `<svg xmlns="http://www.w3.org/2000/svg" width="540" height="1171">${[...unique.values()].map(t => `<text id="${t.id}" x="0" y="100" font-family="Inter" font-size="${t.size}" font-weight="${t.weight}">${xml(t.text)}</text>`).join('')}</svg>`);
  run(CLI, ['convert', svg, output, '--no-system-fonts']);
  const nodes = Object.values(JSON.parse(fs.readFileSync(output, 'utf8')).nodes);
  const widths = new Map(nodes.filter(n => n.type === 'text').map(n => [n.name, n.width]));
  for (const state of states) for (const e of state.elements) for (const text of e.runs) {
    const width = widths.get(unique.get(text.fontKey).id);
    check(width > 0, 'FigCraft did not measure text: ' + text.text);
    text.nativeWidth = width; text.scaleX = text.width / width;
  }
}
function svgFrame(state) {
  const { width, height, dpr } = state.viewport, defs = [], body = [], badges = [], occupied = [];
  const elements = [...state.elements].sort((a, b) => ['base', 'drawer', 'menu'].indexOf(a.layer) - ['base', 'drawer', 'menu'].indexOf(b.layer));
  const layers = new Map(elements.map(e => [e.selector, e]));
  for (const e of elements) {
    const b = e.visibleBox, clip = `clip-${e.id}`;
    defs.push(`<clipPath id="${clip}">${rect(e.paintClip)}</clipPath>`);
    const surface = ['sidebar', 'sidebar-content', 'composer-surface', 'composer-root', 'statusbar', 'dropdown-menu-content', 'pane-tab'].includes(e.slot) || e.role === 'menu';
    const control = e.interactive && !e.ownerSelector && e.box.width > 2 && e.box.height > 2;
    let content = '';
    if (surface || control || e.role === 'separator') content += rect(e.box, `fill="${e.layer === 'menu' ? '#f5f5f5' : '#ffffff'}" stroke="${control ? '#8a8a8a' : '#c5c5c5'}" stroke-width="${control ? '0.75' : '0.5'}" rx="${n(Math.min(e.style.borderRadius || 0, 5))}"`);
    const fs = e.style.fontSize || 12;
    for (const run of e.runs) {
      content += `<text transform="translate(${n(run.x)} ${n(run.y + Math.min(run.height * 0.82, fs))}) scale(${run.scaleX} 1)" x="0" y="0" font-family="Inter" font-size="${fs}" font-weight="${Number(e.fontWeight) || 400}" fill="#343434">${xml(run.text)}</text>`;
      if (!e.occludedAtCenter) occupied.push({ x: run.x, y: run.y, width: run.width, height: run.height });
    }
    if (e.placeholder && !e.runs.length) content += `<text x="${n(b.x + (e.paddingLeft || 0))}" y="${n(b.y + (e.paddingTop || 0) + fs)}" font-family="Inter" font-size="${n(fs)}" fill="#777777">${xml(e.placeholder)}</text>`;
    const childText = elements.some(c => c.ownerSelector === e.selector && c.runs.length);
    if (control && !e.runs.length && !childText && !e.placeholder) {
      const label = e.id === 'SB-1' ? 'CMD' : e.accessibleName || e.mappedName || 'Control';
      content += `<text x="${n(b.x + 2)}" y="${n(b.y + b.height / 2 + 2.5)}" font-family="Inter" font-size="7" fill="#666666">${xml(label.slice(0, Math.max(1, Math.floor((b.width - 4) / 4))))}</text>`;
    }
    if (e.checkBox) { const c = e.checkBox; content += `<path d="M ${n(c.x + c.width * 0.15)} ${n(c.y + c.height * 0.5)} L ${n(c.x + c.width * 0.4)} ${n(c.y + c.height * 0.75)} L ${n(c.x + c.width * 0.85)} ${n(c.y + c.height * 0.2)}" fill="none" stroke="#343434" stroke-width="1.3"/>`; }
    body.push(`<g id="${state.state}-${e.id}" data-selector="${xml(e.selector)}"><title>${xml(e.id + ': ' + (e.mappedName || e.accessibleName || e.slot || e.tag))}</title><g clip-path="url(#${clip})">${content}</g></g>`);
  }
  const labelBoxes = [];
  for (const e of elements) {
    const owner = layers.get(e.ownerSelector);
    if (e.occludedAtCenter || (owner && (owner.interactive || owner.role === 'tab')) || (e.id.startsWith('NEW-') && !(e.interactive && e.box.width > 2 && e.box.height > 2))) continue;
    const b = e.visibleBox, w = e.id.length * 4.6 + 5, h = 10;
    const candidates = [
      { x: b.x, y: b.y - h - 1 }, { x: b.x + b.width - w, y: b.y + b.height + 1 },
      { x: b.x + 1, y: b.y + 1 }, { x: b.x + b.width - w - 1, y: b.y + b.height - h - 1 },
      { x: b.x + b.width + 2, y: b.y }, { x: b.x - w - 2, y: b.y },
      ...[2, 3, 4, 5].flatMap(row => [{ x: b.x, y: b.y - row * (h + 2) }, { x: b.x + b.width - w, y: b.y - row * (h + 2) }, { x: b.x, y: b.y + b.height + row * (h + 2) }]),
    ].map(p => ({ x: Math.max(1, Math.min(width - w - 1, p.x)), y: Math.max(1, Math.min(height - h - 1, p.y)), width: w, height: h }));
    const score = p => labelBoxes.filter(q => overlaps(p, q)).length * 10000 + occupied.filter(q => overlaps(p, q)).length * 100 + Math.hypot(p.x - b.x, p.y - b.y) / 100;
    const chosen = candidates.sort((a, b) => score(a) - score(b))[0];
    labelBoxes.push(chosen);
    badges.push(`<g id="badge-${e.id}">${rect(chosen, 'fill="#2459A6" stroke="#2459A6" stroke-width="0.5" rx="1"')}<text x="${n(chosen.x + 2)}" y="${n(chosen.y + 7.5)}" font-family="Inter" font-size="7.5" fill="#ffffff">${xml(e.id)}</text></g>`);
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width * dpr}" height="${height * dpr}" viewBox="0 0 ${width} ${height}"><title>${state.state}: code-derived UI geometry; OS bars excluded</title><defs>${defs.join('')}</defs>${rect({ x: 0, y: 0, width, height }, 'fill="#ffffff"')}${body.join('')}${badges.join('')}</svg>\n`;
}
function metrics(state) {
  const truncated = state.elements.filter(e => (e.text || e.interactive) && !e.occludedAtCenter && e.box.width > 2 && (e.scrollWidth > e.clientWidth + 1 || e.textExtent.width > e.box.width + 1 && e.style.whiteSpace === 'nowrap')).map(e => ({ id: e.id, name: e.accessibleName, region: e.region, width: n(e.box.width), clientWidth: e.clientWidth, scrollWidth: e.scrollWidth, textWidth: n(e.textExtent.width), overflowX: e.style.overflowX, textOverflow: e.style.textOverflow, clipsText: ['hidden', 'clip', 'auto', 'scroll'].includes(e.style.overflowX) }));
  return { state: state.state, viewport: state.viewport, count: state.elements.length, ids: state.elements.map(e => e.id).sort(), layout: state.layout, truncated, profileRail: state.elements.some(e => e.slot === 'profile-rail'), dateGroups: state.elements.filter(e => e.text && /^(Today|Yesterday|Last week|This week|Older|Last month)$/i.test(e.text)).map(e => ({ text: e.text, box: e.box })), statusbar: state.elements.filter(e => e.region === 'statusbar' && e.interactive).map(e => ({ id: e.id, name: e.accessibleName, box: e.box, visibleBox: e.visibleBox })) };
}
function analyzeIssues(states) {
  const measurements = states.map(s => {
    const m = metrics(s), candidates = s.elements.filter(e => e.interactive && !e.ownerSelector && !e.occludedAtCenter && e.box.width > 2);
    const pairs = [];
    for (let i = 0; i < candidates.length; i++) for (let j = i + 1; j < candidates.length; j++) {
      const a = candidates[i], b = candidates[j];
      if (!['statusbar', 'tabstrip'].includes(a.region) || a.region !== b.region) continue;
      const w = Math.min(a.box.right, b.box.right) - Math.max(a.box.x, b.box.x), h = Math.min(a.box.bottom, b.box.bottom) - Math.max(a.box.y, b.box.y);
      if (w > 0.5 && h > 0.5) pairs.push({ a: a.id, b: b.id, region: a.region, overlapWidth: n(w), overlapHeight: n(h) });
    }
    const smart = s.elements.find(e => e.id === 'SB-5');
    const profile = s.elements.find(e => e.id === 'SB-2');
    return { state: s.state, viewport: s.viewport, offscreen: s.layout.offscreen, truncated: m.truncated, overlaps: pairs, smart: smart ? { box: smart.box, visibleBox: smart.visibleBox, clipped: smart.box.right > s.viewport.width + 0.5 || smart.box.width - smart.visibleBox.width > 1 || m.truncated.some(t => t.clipsText && (t.id === smart.id || s.elements.find(e => e.id === t.id)?.ownerSelector === smart.selector)) } : null, profile: profile ? { box: profile.box, label: profile.accessibleName, clipped: m.truncated.some(t => t.clipsText && (t.id === profile.id || s.elements.find(e => e.id === t.id)?.ownerSelector === profile.selector)) } : null, rightControls: candidates.filter(e => ['TB-4', 'TB-5'].includes(e.id)).map(e => e.id) };
  });
  const smart = measurements.filter(m => m.smart?.clipped || m.offscreen.some(e => e.name === 'Smart'));
  const profiles = measurements.filter(m => m.profile?.clipped);
  const landscape = measurements.find(m => m.state === 'LANDSCAPE'), unfolded = measurements.find(m => m.state === 'UNFOLDED');
  const missing = ['TB-4', 'TB-5'].filter(id => !landscape?.rightControls.includes(id));
  const crowded = measurements.find(m => m.state === 'CROWDED');
  const plus = crowded?.offscreen.filter(e => e.name === 'New session tab') ?? [];
  const legacy = [
    { id: 'KI-1', name: 'Clipped Smart', status: smart.length ? 'CONFIRMED' : 'UNVERIFIED', evidence: smart.length ? smart.map(m => `${m.state}: right=${n(m.smart?.box.right ?? m.offscreen.find(e => e.name === 'Smart').right)}, viewport=${m.viewport.width}`).join('; ') : 'Not reproduced in these synthetic states; this does NOT clear the old phone report.' },
    { id: 'KI-2', name: 'Squeezed profile name', status: profiles.length ? 'CONFIRMED' : 'UNVERIFIED', evidence: profiles.length ? `${profiles.length} states: ${profiles.map(m => m.state).join(', ')}. Profile-button widths: ${[...new Set(profiles.map(m => n(m.profile.box.width)))].join(', ')} CSS px. Descendant label text overflows a clipping/ellipsis box; raw clientWidth, scrollWidth and text width are in issues.json.` : 'No profile-label overflow reproduced with Profile A. Longer real names and native insets remain unverified.' },
    { id: 'KI-3', name: 'Controls hidden in landscape', status: landscape && missing.length ? 'CONFIRMED' : 'UNVERIFIED', evidence: `Landscape: ${landscape?.viewport.width}x${landscape?.viewport.height}; ${missing.length ? 'not visible: ' + missing.join(', ') : 'TB-4 and TB-5 visible'}. Unfolded: ${unfolded?.viewport.width}x${unfolded?.viewport.height}; visible: ${unfolded?.rightControls.join(', ')}. Responsive visibility is measured; whether intentional is not established.` },
    { id: 'KI-4', name: 'Crowded new-tab plus', status: plus.length || crowded?.overlaps.some(p => p.region === 'tabstrip' && [p.a, p.b].includes('TB-3')) ? 'CONFIRMED' : 'UNVERIFIED', evidence: plus.length ? `After creating tabs and selecting the first: plus right=${n(plus[0].right)}, viewport=${crowded.viewport.width} CSS px. Offscreen geometry, not a screenshot inference.` : 'Crowded tabs were rendered. New-tab-plus clipping was not reproduced in this state.' },
  ];
  return { method: 'Only DOM measurements; >0.5 CSS px for edge/overlap, >1 CSS px for scroll/text overflow. Nested controls are excluded from overlap pairs. Scrollable clipping can be intentional; CONFIRMED means the geometry occurred, not that its cause is proved.', legacy, measurements };
}
function issueSvg(issues) {
  const text = (value, x, y, size = 23, color = '#343434') => `<text x="${x}" y="${y}" font-family="Inter" font-size="${size}" fill="${color}">${xml(value)}</text>`;
  const wrap = value => String(value).split(/\s+/).reduce((lines, word) => { if (!lines.length || (lines.at(-1) + ' ' + word).length > 69) lines.push(word); else lines[lines.length - 1] += ' ' + word; return lines; }, []);
  const overlap = issues.measurements.reduce((n, m) => n + m.overlaps.length, 0), truncated = issues.measurements.reduce((n, m) => n + m.truncated.length, 0);
  const cards = [...issues.legacy, { id: 'MEASURE', name: 'All measured layouts', status: 'CONFIRMED', evidence: `${issues.measurements.length} rendered states. ${truncated} text/scroll overflow observations. ${overlap} statusbar/tabstrip overlap pairs. Raw values and selectors: issues.json. Scrollable clipping is not automatically a bug.` }, { id: 'LIMITS', name: 'Evidence limits', status: 'UNVERIFIED', evidence: 'No real phone, Android insets, keyboard, sign-in or live server was tested. F6 is a generated evidence sheet, not an app screenshot. Font widths are fitted to measured DOM text runs; control boxes are unchanged.' }];
  let body = text('F6 | KNOWN ISSUES FROM THE CODE RENDER', 40, 64, 31) + text('CONFIRMED = measured; UNVERIFIED = not established here', 40, 108, 22);
  cards.forEach((card, i) => { const y = 148 + i * 345; body += rect({ x: 36, y, width: 1008, height: 322 }, 'fill="#f5f5f5" stroke="#b5b5b5"') + text(card.id + ' | ' + card.name, 56, y + 42, 26, '#2459A6') + text(card.status, 56, y + 82, 23); wrap(card.evidence).slice(0, 7).forEach((line, j) => { body += text(line, 56, y + 124 + j * 25, 21); }); });
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="2342" viewBox="0 0 1080 2342">${rect({ x: 0, y: 0, width: 1080, height: 2342 }, 'fill="#ffffff"')}${body}</svg>\n`;
}
function writeDiff(states, inputs, issues) {
  const commands = JSON.parse(fs.readFileSync(path.join(ROOT, '.cache/wireframe/wireframe-final.commands.json'), 'utf8'));
  let next = 2; const frameNames = new Map(), old = [];
  for (const command of commands) {
    const p = command.params ?? {};
    if (command.command === 'frame.create') frameNames.set(next++, p.name);
    if (command.command === 'node.create') { old.push({ ...p, frame: frameNames.get(p.parent) }); next++; }
  }
  const compared = [];
  for (const state of states.filter(s => /^F[1-5]$/.test(s.state))) {
    const get = slot => state.elements.find(e => e.slot === slot)?.box;
    for (const [name, box] of [['Status bar', get('statusbar')], ['Composer surface', get('composer-root')], ['Sessions drawer', state.layout.drawers[0]], ['Profile rail', get('profile-rail')], ['Status profile list', state.state === 'F4' ? state.elements.find(e => e.role === 'menu')?.box : null], ['Drawer filter menu', state.state === 'F5' ? state.elements.find(e => e.role === 'menu')?.box : null]]) {
      const before = old.filter(p => p.frame === state.state && p.name === name && p.type === 'rectangle').at(-1);
      if (!before || !box) continue;
      const a = Object.fromEntries(['x', 'y', 'width', 'height'].map(k => [k, n(box[k] * state.viewport.dpr)]));
      compared.push({ state: state.state, name, v1: Object.fromEntries(['x', 'y', 'width', 'height'].map(k => [k, before[k]])), codeDevicePx: a, delta: Object.fromEntries(['x', 'y', 'width', 'height'].map(k => [k, n(a[k] - before[k])])) });
    }
  }
  const map = JSON.parse(fs.readFileSync(path.join(ROOT, 'scripts/wireframe-element-map.json'), 'utf8'));
  const phone = states.filter(s => /^F[1-5]$/.test(s.state));
  const elements = phone.flatMap(s => s.elements), ids = new Set(elements.map(e => e.id));
  const fresh = [...new Map(elements.filter(e => e.id.startsWith('NEW-')).map(e => [e.id, e])).values()];
  const missed = map.rules.filter(r => !ids.has(r.id));
  const v1Map = fs.readFileSync(path.join(ROOT, '.cache/wireframe/ELEMENT-MAP.md'), 'utf8');
  const changed = [...v1Map.matchAll(/^\| ([^|]+) \| ([a-f0-9]{64}) \|$/gm)].filter(m => inputs[m[1]] && inputs[m[1]] !== m[2]).map(m => m[1]);
  const pick = (state, name) => compared.find(c => c.state === state && c.name === name);
  const sizeLine = (state, name) => { const c = pick(state, name); return c ? `${name}: V1 ${c.v1.width}x${c.v1.height}; code ${c.codeDevicePx.width}x${c.codeDevicePx.height} px (width delta ${c.delta.width}, height delta ${c.delta.height}).` : `${name}: not observed; no size claim.`; };
  const biggest = [sizeLine('F2', 'Sessions drawer'), sizeLine('F4', 'Status profile list'), sizeLine('F5', 'Drawer filter menu'), sizeLine('F1', 'Status bar'), `${fresh.length} NEW DOM IDs; ${missed.length} V1 IDs not observed. NEW includes wrappers, not just independent controls. Collapse all / Mark all as read are ${elements.some(e => e.accessibleName === 'Collapse all') && elements.some(e => e.accessibleName === 'Mark all as read') ? 'present in the code render' : 'not both observed'}.`];
  const lines = ['# V1 screenshot wireframe vs current code', '', '## Comparison limits', '- V1 is an annotated reconstruction, not a DOM extract. Its callout rectangles are NOT control hitboxes and are never used as such here.', '- Compare named panel rectangles in V1 commands with measured current DOM panel rectangles, converted to output pixels. Coordinates retain each canvas origin. V1 includes its title/status/navigation artwork; current frames contain only the renderer, so absolute Y deltas do NOT isolate a screenshot error.', '- Synthetic labels, viewport assumptions and later source changes can all change layout. These differences are NOT proof that every old screenshot was wrong.', '- V1 fingerprinted sources changed: ' + (changed.join(', ') || 'none among the recorded fingerprints') + '. Unfingerprinted source changes cannot be ruled out.', '', '## Five biggest differences', ...biggest.map((s, i) => `${i + 1}. ${s}`), '', '## Panel measurements (output pixels)', '| State / panel | V1 x,y,w,h | Code x,y,w,h | Delta x,y,w,h |', '|---|---|---|---|', ...compared.map(c => `| ${c.state} ${c.name} | ${Object.values(c.v1).join(', ')} | ${Object.values(c.codeDevicePx).join(', ')} | ${Object.values(c.delta).join(', ')} |`), '', '## Present in the code extract, not mapped in V1', ...fresh.map(e => `- ${e.id}: ${e.accessibleName || e.slot || e.tag}; selector \`${e.selector}\``), '', '## V1 elements not observed', ...missed.map(r => `- ${r.id}: ${r.name}. Hidden/conditional/unmapped is possible; NOT claimed deleted from the source.`), '- OS-1 / OS-2: Android system areas outside this renderer; omitted rather than invented.', '', '## Known issues: old words replaced with measurements', ...issues.legacy.map(i => `- ${i.id}: ${i.status}. ${i.evidence}`), '', 'Full measured records: issues.json, drift.json and state DOM JSON.'];
  write(path.join(OUT, 'DIFF.md'), lines.join('\n') + '\n');
  json(path.join(OUT, 'diff.json'), { biggest, compared, changedFingerprintedSources: changed, newIds: fresh.map(e => e.id), v1IdsNotObserved: missed.map(r => r.id) });
  return biggest;
}
function exportFigcraft(states, dir, issues) {
  const frames = [...states.filter(s => /^F[1-5]$/.test(s.state)), { state: 'F6' }];
  fitNativeText(states, dir);
  for (const state of states) write(path.join(dir, state.state + '.svg'), svgFrame(state));
  write(path.join(dir, 'F6.svg'), issueSvg(issues));
  for (const state of [...states, { state: 'F6' }]) {
    const svg = path.join(dir, state.state + '.svg'), native = path.join(dir, state.state + '.figcraft');
    run(CLI, ['convert', svg, native, '--no-system-fonts']);
    run(CLI, ['convert', native, path.join(dir, state.state + '.png'), '--no-system-fonts']);
  }
  const native = path.join(dir, 'hermes-android-wireframe-code.figcraft');
  const ops = [];
  frames.forEach((state, index) => ops.push({ command: 'file.import', params: { path: path.join(dir, state.state + '.svg'), x: index % 3 * 1128, y: Math.floor(index / 3) * 2390 } }));
  const batch = path.join(dir, 'import-frames.json'); json(batch, ops);
  run(CLI, ['run', batch, '--out', native, '--no-system-fonts']);
  run(CLI, ['convert', native, path.join(dir, 'overview.png'), '--no-system-fonts']);
  json(path.join(dir, 'figcraft-info.json'), JSON.parse(run(CLI, ['info', native, '--json', '--no-system-fonts'])));
  const document = path.join(dir, 'figcraft-document.json');
  run(CLI, ['convert', native, document, '--no-system-fonts']);
  const nodes = Object.values(JSON.parse(fs.readFileSync(document, 'utf8')).nodes);
  check(!nodes.some(n => n.type === 'image'), 'FigCraft output must be editable vectors, not a bitmap.');
  check(nodes.filter(n => n.type === 'text').length > 50 && nodes.filter(n => n.type === 'frame').length >= 6, 'Six editable frames and text layers are required.');
}
function writeReports(states, dir, inputs, runtime) {
  const measured = states.map(metrics); json(path.join(dir, 'metrics.json'), measured);
  const previous = path.join(OUT, 'run-1', 'metrics.json');
  const repeat = dir.endsWith('run-2') && fs.existsSync(previous) ? measured.map((s, i) => { const old = JSON.parse(fs.readFileSync(previous, 'utf8'))[i]; return { state: s.state, count: s.count, sameCount: s.count === old.count, sameIds: JSON.stringify(s.ids) === JSON.stringify(old.ids), sameGeometry: JSON.stringify(states[i].elements.map(e => e.box)) === JSON.stringify(JSON.parse(fs.readFileSync(path.join(OUT, 'run-1', s.state + '.dom.json'), 'utf8')).elements.map(e => e.box)), sameSvg: hash(fs.readFileSync(path.join(dir, s.state + '.svg'))) === hash(fs.readFileSync(path.join(OUT, 'run-1', s.state + '.svg'))) }; }) : null;
  const map = JSON.parse(fs.readFileSync(path.join(ROOT, 'scripts/wireframe-element-map.json'), 'utf8'));
  const seen = new Set(states.filter(s => /^F/.test(s.state)).flatMap(s => s.elements.map(e => e.id)));
  const missing = map.rules.filter(r => !seen.has(r.id));
  const added = [...new Map(states.filter(s => /^F/.test(s.state)).flatMap(s => s.elements.filter(e => e.id.startsWith('NEW-')).map(e => [e.id, e]))).values()];
  const rows = ['# Code-derived element map', '', 'Coordinates are unmodified CSS getBoundingClientRect values; visibleBox is the viewport/ancestor-clip intersection. Native geometry comes from the source build, not screenshots. OS bars are outside the renderer and are NOT drawn.', '', 'Phone: 540x1171 CSS px / DPR 2 -> 1080x2342 output px, the requested canvas, NOT a physical-phone calibration. Additional mobile-layout harness sizes: 393x852 portrait / DPR 3; 852x393 landscape / DPR 3; 884x1104 fold-inner / DPR 2.2. CROWDED exercises seven extra tabs then selects the first.', '', 'NEW IDs are stable selector SHA-256 prefixes. Nested wrappers/text remain separate, named SVG layers; only independent controls and preserved IDs receive visible badges.', ''];
  for (const state of states) {
    rows.push(`## ${state.state}: ${state.elements.length} visible DOM records`, '', '| ID | Plain name | Accessible name | CSS box x,y,w,h | Source | Selector |', '|---|---|---|---|---|---|');
    for (const e of state.elements) rows.push(`| ${e.id} | ${String(e.mappedName || e.accessibleName || e.slot || e.tag).replaceAll('|', '/')} | ${String(e.accessibleName || '(none)').replaceAll('|', '/').replaceAll('\n', ' ')} | ${['x', 'y', 'width', 'height'].map(k => n(e.box[k])).join(', ')} | ${e.source.status === 'VERIFIED' ? e.source.file + ':' + e.source.line + ' (' + e.source.kind + ')' : 'UNVERIFIED static callsite'} | \`${e.selector.replaceAll('|', '/')}\` |`);
    rows.push('');
  }
  rows.push('## V1 IDs not observed in these states', ...missing.map(r => `- ${r.id}: ${r.name}. Hidden/not rendered or selector requires review; NOT assumed removed.`), '', '## Reserved OS / measured issue IDs', ...Object.entries(map.reserved).map(([id, r]) => '- ' + id + ': ' + r.name + (id.startsWith('OS-') ? '; outside the renderer; NOT synthesized.' : '; see measured F6 / issues.json.')), '', '## How to ask for a change', '', '1. "SB-2: show the full profile name on phone. Keep the FM-5 rail toggle."', '2. "TB-3: keep the new-tab plus visible when I return to an older tab."', '3. "CP-4: keep High visible in landscape. Do not change SB-5 approval mode."', '');
  write(path.join(OUT, 'ELEMENT-MAP.md'), rows.join('\n'));
  const drift = { missingPreservedIds: missing.map(r => ({ id: r.id, name: r.name })), newIds: added.map(e => ({ id: e.id, name: e.accessibleName || e.slot || e.tag, selector: e.selector, source: e.source })), reserved: map.reserved, measured };
  json(path.join(OUT, 'drift.json'), drift);
  json(path.join(OUT, 'verification.json'), { branch: run('git', ['branch', '--show-current']).trim(), head: run('git', ['rev-parse', 'HEAD']).trim(), sourceFiles: Object.keys(inputs).length, sourceInputHash: hash(JSON.stringify(inputs)), generatorHash: hash(fs.readFileSync(fileURLToPath(import.meta.url))), mappingHash: hash(fs.readFileSync(path.join(ROOT, 'scripts/wireframe-element-map.json'))), repeat, measured, runtime, figcraftCli: { version: '0.6.0', sha256: hash(fs.readFileSync(CLI)), sourceCheckout: '833f0d2c27f0acbae5394848930ae531fc89c724', sourceBuildIdentityNotEstablished: true } });
  const phone = measured.filter(s => /^F/.test(s.state));
  const result = ['# Code-derived wireframe result', '', '## Geometry and build', '- Real current app built with Vite and booted using the existing APK browser-fixture bootstrap. Only the bootstrap native handshake/REST/socket inputs are synthetic; application component/CSS sources are unchanged.', '- Phone: 540 × 1171 CSS px at DPR 2 = 1080 × 2342 output px. This is an app viewport, not a measured Android screen/inset calibration.', '- OS status/navigation bars are NOT drawn. V1 remains untouched.', '- Unfolded: representative 768 × 900 and 1024 × 900 CSS viewports, DPR 1; NOT a fresh physical Fold-device acceptance test.', '- Branch: native-gateways; HEAD: ' + run('git', ['rev-parse', '--short', 'HEAD']).trim(), '', '## Measured states', ...phone.map(s => `- ${s.state}: ${s.count} DOM records; rail ${s.profileRail ? 'ON' : 'OFF'}; ${s.truncated.length} clipping/truncation candidates.`), '', '## Repeatability', repeat ? JSON.stringify(repeat, null, 2) : 'First pass only. Repeatability is NOT YET VERIFIED.', '', '## Code/V1 drift', `- ${seen.size - added.length} preserved IDs observed; ${added.length} NEW IDs. Nested DOM wrappers are included; counts are not counts of independent UI controls.`, ...missing.map(r => '- Not observed: ' + r.id + ' ' + r.name), '- Sources not resolved to an exact static callsite are explicitly UNVERIFIED in ELEMENT-MAP.md and DOM JSON.', '- Drawer width, control bounds, profile-rail clipping, menu dimensions, header visibility and statusbar compression are measured rather than copied from V1; see drift.json and metrics.json.', '', '## Layout observations', ...measured.map(s => `- ${s.state} (${s.viewport.width}px): page overflow ${s.layout.documentScrollWidth > s.layout.documentClientWidth}; rail ${s.profileRail}; date groups ${s.dateGroups.map(g => g.text).join(', ') || 'none visible'}; truncation candidates: ${s.truncated.map(e => e.id + ' ' + e.name).join('; ') || 'none'}.`), '', '## Safety and limits', '- No app/native source edits, Git writes, branch switches, device/emulator access, shared browser, backend/server, tunnels or profile changes.', '- Browser requests outside the intercepted local fixture origin are aborted. No listening server is started.', '- Synthetic data only; no private sessions, tokens or server credentials.', '- No physical-device callback/auth/socket/reply/history/foreground-return gate was exercised.', '- Project-wide tests/linters were not run: visual approval comes first. This report covers actual build/render/export execution and the measured repeat comparison, not the application regression suite.', '', '## Open', 'overview.png', 'F1.png through F5.png', 'F1.svg through F5.svg', 'hermes-android-wireframe-code.figcraft', 'ELEMENT-MAP.md', 'verification.json', ''];
  const extra = ['', '## Artifact pipeline', '- F1-F5 are source-derived UI states; F6 is the measured known-issues evidence sheet, NOT an app screen.', '- Native FigCraft CLI 0.6.0 imports SVG into editable frame/text/vector layers; native reopen, JSON inspection and PNG rendering are exercised. GUI open/save is NOT claimed.', '- Native bundled Inter text is horizontally fitted to each measured browser text run. Control boxes are unchanged. The export does not assume textLength support or falsely clip every element to its own box.', '- Additional actual mobile-layout harness viewports: PORTRAIT393 393x852 / DPR 3; LANDSCAPE 852x393 / DPR 3; UNFOLDED 884x1104 / DPR 2.2. CROWDED creates seven extra tabs and returns to the first.', '- See DIFF.md for five quantified differences and V1/source-comparison limits; issues.json contains overflow, truncation and overlap measurements.', '', '## Reproduce from scratch', '- First pass: node.exe scripts/wireframe-from-code.mjs', '- Second fresh build/render: node.exe scripts/wireframe-from-code.mjs --pass=2', '- Do not use --reuse-build for acceptance. Each pass empties its isolated Vite build and run directory. No tests/linter: visual-approval gate remains.', '', '## Files', '- hermes-android-wireframe-code.figcraft; overview.png; F1.svg-F6.svg; F1.png-F6.png; ELEMENT-MAP.md; DIFF.md; RESULT.md; issues.json; drift.json; verification.json; run-1/ and run-2/ evidence.'];
  extra.push('', '## One-command rerun (both fresh passes)', 'From C:/example-projects/hermes android:', 'node.exe scripts/wireframe-from-code.mjs && node.exe scripts/wireframe-from-code.mjs --pass=2');
  write(path.join(OUT, 'RESULT.md'), result.filter(line => !line.startsWith('- Unfolded:')).map(line => line.replace('F1.png through F5.png', 'F1.png through F6.png').replace('F1.svg through F5.svg', 'F1.svg through F6.svg')).concat(extra).join('\n') + '\n');
  return repeat;
}
async function main() {
  process.chdir(ROOT); fs.mkdirSync(OUT, { recursive: true }); memoryGate();
  check(run('git', ['branch', '--show-current']).trim() === 'native-gateways', 'Wrong branch; no branch change is allowed.');
  const pass = process.argv.includes('--pass=2') ? 2 : 1;
  const v1dir = path.join(ROOT, '.cache/wireframe');
  const v1Hashes = () => Object.fromEntries(fs.readdirSync(v1dir, { recursive: true }).filter(f => fs.statSync(path.join(v1dir, f)).isFile()).sort().map(f => [f, hash(fs.readFileSync(path.join(v1dir, f)))]));
  const v1before = v1Hashes();
  if (pass === 1) json(path.join(OUT, 'v1-inputs.json'), v1before);
  else check(JSON.stringify(v1before) === JSON.stringify(JSON.parse(fs.readFileSync(path.join(OUT, 'v1-inputs.json'), 'utf8'))), 'V1 changed between passes.');
  const before = sourceSnapshot();
  if (!skipBuild) {
    console.log('Building current app source into the isolated output folder.');
    run(process.execPath, ['node_modules/vite/bin/vite.js', 'build', '--outDir', relative(BUILD), '--emptyOutDir', '--configLoader', 'runner'], 600000);
  }
  if (skipBuild) check(fs.existsSync(path.join(OUT, 'source-inputs.json')) && JSON.stringify(before) === JSON.stringify(JSON.parse(fs.readFileSync(path.join(OUT, 'source-inputs.json'), 'utf8'))), 'Cached build is not source-matched. Run without --reuse-build.');
  check(fs.existsSync(path.join(BUILD, 'index.html')), 'Fresh build missing.');
  const previousArg = process.argv[2]; process.argv[2] = OUT;
  const harness = await import('../tests/browser/mobile-layout.mjs');
  process.argv[2] = previousArg;
  memoryGate();
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const dir = path.join(OUT, probe ? 'probe' : `run-${pass}`);
  fs.rmSync(dir, { recursive: true, force: true }); fs.mkdirSync(dir, { recursive: true });
  const states = [], runtime = [];
  let app;
  try {
    app = await boot(browser, { width: 540, height: 1171, dpr: 2 }, harness, dir);
    states.push(...await captureStates(app, dir));
    runtime.push({ viewport: 'phone', errors: app.errors, calls: app.calls, blocked: app.blocked });
    check(app.errors.length === 0, 'Renderer page errors: ' + app.errors.join('; '));
    await app.context.close(); app = null;
    if (!probe) for (const vp of [{ name: 'PORTRAIT393', width: 393, height: 852, dpr: 3 }, { name: 'LANDSCAPE', width: 852, height: 393, dpr: 3 }, { name: 'UNFOLDED', width: 884, height: 1104, dpr: 2.2 }]) {
      memoryGate();
      app = await boot(browser, vp, harness, dir);
      states.push(await inspect(app.page, vp.name, dir));
      runtime.push({ viewport: vp.name, errors: app.errors, calls: app.calls, blocked: app.blocked });
      check(app.errors.length === 0, 'Unfolded renderer page errors: ' + app.errors.join('; '));
      await app.context.close(); app = null;
    }
  } finally { await app?.context.close(); await browser.close(); }
  json(path.join(dir, 'runtime.json'), runtime);
  const after = sourceSnapshot();
  check(JSON.stringify(before) === JSON.stringify(after), 'Shared source changed during generation. Output is not source-matched.');
  json(path.join(OUT, 'source-inputs.json'), before);
  if (probe) { console.log('PROBE_COMPLETE'); return; }
  linkSources(states, before);
  for (const state of states) json(path.join(dir, state.state + '.dom.json'), state);
  json(path.join(dir, 'source-inputs.json'), before);
  const issues = analyzeIssues(states); json(path.join(dir, 'issues.json'), issues);
  exportFigcraft(states, dir, issues);
  const repeat = writeReports(states, dir, before, runtime);
  const differences = writeDiff(states, before, issues);
  check(!repeat || repeat.every(s => s.sameCount && s.sameIds && s.sameGeometry && s.sameSvg), 'Clean repeat changed counts, IDs, geometry or SVG. See verification.json.');
  const outputs = fs.readdirSync(dir).filter(name => /^(F[1-6]|CROWDED|PORTRAIT393|LANDSCAPE|UNFOLDED)\.(svg|png)$/.test(name) || name === 'overview.png');
  const sameFiles = pass === 2 ? outputs.map(name => ({ file: name, sameBytes: hash(fs.readFileSync(path.join(dir, name))) === hash(fs.readFileSync(path.join(OUT, 'run-1', name))) })) : null;
  check(!sameFiles || sameFiles.every(f => f.sameBytes), 'Repeat exports differ in bytes. See per-run output.');
  if (pass === 2) check(fs.readFileSync(path.join(OUT, 'run-1/source-inputs.json'), 'utf8') === fs.readFileSync(path.join(dir, 'source-inputs.json'), 'utf8'), 'Source snapshots changed between fresh passes.');
  for (const name of fs.readdirSync(dir)) if (/^(F[1-6]|CROWDED|PORTRAIT393|LANDSCAPE|UNFOLDED)\.(svg|png|figcraft|dom\.json)$/.test(name) || /^(overview\.png|hermes-android-wireframe-code\.figcraft|metrics\.json|issues\.json)$/.test(name)) fs.copyFileSync(path.join(dir, name), path.join(OUT, name));
  check(JSON.stringify(before) === JSON.stringify(sourceSnapshot()), 'Shared source changed before final export.');
  check(JSON.stringify(v1before) === JSON.stringify(v1Hashes()), 'V1 changed during generation.');
  const verificationPath = path.join(OUT, 'verification.json');
  const verification = JSON.parse(fs.readFileSync(verificationPath, 'utf8'));
  Object.assign(verification, { freshBuild: !skipBuild, completedPass: pass, bothFreshPassesVerified: pass === 2 && !skipBuild, v1Preserved: true, v1Files: Object.keys(v1before).length, exportedFiles: sameFiles, knownIssues: issues.legacy, differences });
  json(verificationPath, verification); json(path.join(dir, 'verification.json'), verification);
  const resultPath = path.join(OUT, 'RESULT.md');
  write(resultPath, fs.readFileSync(resultPath, 'utf8') + `\n## Execution verification\n- Completed fresh pass ${pass}. Two fresh passes: ${pass === 2 ? 'VERIFIED' : 'pending'}.\n- V1 hashes unchanged (${Object.keys(v1before).length} files).\n- ${sameFiles ? 'Counts, IDs, geometry, SVG and PNG bytes match across both independent builds/renders.' : 'Second independent build/render still required.'}\n- Source snapshots unchanged during capture/export${pass === 2 ? ' and identical between passes' : ''}.\n- Final image review remains separate; this is NOT device acceptance or app-fix approval.\n`);
  fs.rmSync(path.join(OUT, 'failure.json'), { force: true });
  console.log(JSON.stringify({ completed: true, pass, states: states.map(s => ({ state: s.state, count: s.elements.length })), repeat, output: OUT }));
}
if (process.argv.includes('--self-test')) {
  memoryGate(); console.log('Self-test: memory gate passed.');
} else main().catch(error => { json(path.join(OUT, 'failure.json'), { message: error.message, stack: error.stack }); console.error(error.stack); process.exitCode = 1; });
