// Exercise the installed Radix implementation and the real Android guard, not a menu mock.
// Node strips the project's TypeScript; all temporary modules stay in ignored .cache.
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { JSDOM } from 'jsdom';

const root = fileURLToPath(new URL('../../', import.meta.url));
const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  url: 'https://qa.invalid/', pretendToBeVisual: true,
});
const win = dom.window;
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'Element', 'Node',
  'NodeFilter', 'DOMRect', 'MutationObserver', 'CustomEvent', 'Event', 'MouseEvent', 'PointerEvent', 'KeyboardEvent']) {
  Object.defineProperty(globalThis, key, { configurable: true, value: key === 'window' ? win : win[key] });
}
globalThis.getComputedStyle = win.getComputedStyle.bind(win);
globalThis.requestAnimationFrame = win.requestAnimationFrame.bind(win);
globalThis.cancelAnimationFrame = win.cancelAnimationFrame.bind(win);
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = await import('react');
const { createRoot } = await import('react-dom/client');
const { installNativeTextSelection } = await import('../../src/desktop/mobile.ts');
const sourcePath = fileURLToPath(import.meta.resolve('@radix-ui/react-context-menu'));
let source = readFileSync(sourcePath, 'utf8');
let transformed = false;
if (!process.argv.includes('--unpatched')) {
  const { default: config } = await import('../../vite.config.ts');
  const plugin = config.plugins.flat(Infinity).find(item => item?.name === 'android-native-text-selection');
  if (plugin) {
    const result = plugin.transform(source, sourcePath);
    source = typeof result === 'string' ? result : result?.code ?? source;
    transformed = true;
  }
}
// The build uses Vite's root-relative import. Resolve only that import for this Node harness.
source = source.replaceAll('"/src/desktop/mobile"', JSON.stringify(pathToFileURL(path.join(root, 'src/desktop/mobile.ts')).href));
mkdirSync(path.join(root, '.cache'), { recursive: true });
const temp = mkdtempSync(path.join(root, '.cache/native-selection-test-'));
const modulePath = path.join(temp, 'radix.mjs');
writeFileSync(modulePath, source);
const results = [];
try {
  const Menu = await import(pathToFileURL(modulePath).href);
  const dispose = installNativeTextSelection(win);
  const renderer = createRoot(document.getElementById('root'));
  try {
    for (const kind of ['composer', 'input', 'text', 'link', 'row', 'reaction', 'mouse', 'composer-pointer', 'link-pointer']) {
      const props = { id: 'target' };
      let tag = 'p';
      if (kind.startsWith('composer')) { tag = 'div'; props.contentEditable = true; props.suppressContentEditableWarning = true; }
      if (kind === 'input') { tag = 'input'; props.defaultValue = 'synthetic QA'; }
      if (kind.startsWith('link')) { tag = 'a'; props.href = 'https://example.org'; }
      if (kind === 'row') { tag = 'div'; props['data-hermes-context-menu-trigger'] = ''; }
      if (kind === 'reaction') { tag = 'button'; props['data-context-menu-skip'] = ''; }
      await React.act(async () => renderer.render(React.createElement(Menu.Root, { key: kind },
        React.createElement(Menu.Trigger, { asChild: true },
          React.createElement('div', { 'data-zone-body': 'qa', 'data-hermes-context-menu-trigger': '' },
            React.createElement(tag, props, tag === 'input' ? undefined : 'synthetic QA'))),
        React.createElement(Menu.Portal, null,
          React.createElement(Menu.Content, null, React.createElement(Menu.Item, null, 'QA_ZONE_MENU'))))));
      const target = document.getElementById('target');
      const pointerType = kind === 'mouse' ? 'mouse' : 'touch';
      let pointerDefaultAllowed;
      let contextDefaultAllowed;
      await React.act(async () => {
        if (pointerType === 'touch') target.dispatchEvent(new win.Event('touchstart', { bubbles: true }));
        const down = new win.PointerEvent('pointerdown', { bubbles: true, cancelable: true, pointerType, button: 0, clientX: 20, clientY: 20 });
        target.dispatchEvent(down);
        pointerDefaultAllowed = !down.defaultPrevented;
        const menu = new win.PointerEvent('contextmenu', { bubbles: true, cancelable: true, pointerType, button: 2 });
        if (!kind.endsWith('-pointer')) target.dispatchEvent(menu);
        contextDefaultAllowed = !menu.defaultPrevented;
        await new Promise(resolve => setTimeout(resolve, 760));
      });
      results.push({ kind, menuOpened: !!document.querySelector('[role=menu]'), pointerDefaultAllowed, contextDefaultAllowed });
      await React.act(async () => {
        target.dispatchEvent(new win.PointerEvent('pointerup', { bubbles: true, pointerType }));
        target.dispatchEvent(new win.Event('touchend', { bubbles: true }));
      });
    }
  } finally {
    await React.act(async () => renderer.unmount());
    dispose();
  }
  console.log(JSON.stringify({ transformed, results }));
} finally {
  win.close();
  rmSync(temp, { recursive: true, force: true });
}
