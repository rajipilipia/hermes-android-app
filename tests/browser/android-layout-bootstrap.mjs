// Emulator layout fixtures only. Does not alter the installed APK, native login,
// server configuration, TLS or CSP. Boot the real bundled renderer through CDP
// with synthetic bridges, since a fresh emulator has no connected account.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { parse } from '@babel/parser';

export async function bootApkLayoutFixture(page, assetRoot) {
  const html = readFileSync(path.join(assetRoot, 'index.html'), 'utf8');
  const entry = /<script[^>]+src="([^"]+\.js)"/.exec(html)?.[1];
  if (!entry) throw new Error('APK entry module missing');
  const url = new URL(entry, page.url()).href;
  const original = readFileSync(path.join(assetRoot, entry), 'utf8');
  if (!original.includes('https://setup.hermes-android.invalid')) throw new Error('APK setup branch changed');
  const source = original.replaceAll('https://setup.hermes-android.invalid', 'https://layout-fixture.invalid');
  const ast = parse(source, { sourceType: 'module', createImportExpressions: true });
  const edits = [];
  const absolute = value => new URL(value, url).href;
  const walk = node => {
    if (!node || typeof node !== 'object') return;
    if (node.type === 'ImportDeclaration') {
      const specifiers = node.specifiers;
      const target = JSON.stringify(absolute(node.source.value));
      const named = specifiers.filter(s => s.type !== 'ImportNamespaceSpecifier').map(s =>
        `${JSON.stringify(s.type === 'ImportDefaultSpecifier' ? 'default' : s.imported.name ?? s.imported.value)}:${s.local.name}`);
      const namespace = specifiers.find(s => s.type === 'ImportNamespaceSpecifier');
      const code = namespace ? `const ${namespace.local.name}=await import(${target});`
        : named.length ? `const {${named.join(',')}}=await import(${target});` : `await import(${target});`;
      edits.push([node.start, node.end, code]);
      return;
    }
    if (node.type === 'ImportExpression') {
      const value = node.source.type === 'StringLiteral' ? node.source.value
        : node.source.type === 'TemplateLiteral' && node.source.expressions.length === 0 ? node.source.quasis[0].value.cooked : null;
      if (value?.startsWith('.')) edits.push([node.source.start, node.source.end, JSON.stringify(absolute(value))]);
    }
    if (node.type === 'MemberExpression' && node.object?.type === 'MetaProperty' && node.object.meta.name === 'import' && node.property?.name === 'url') {
      edits.push([node.start, node.end, JSON.stringify(url)]);
      return;
    }
    for (const [key, child] of Object.entries(node)) {
      if (['loc','start','end','extra'].includes(key)) continue;
      if (Array.isArray(child)) child.forEach(walk); else if (child && typeof child === 'object') walk(child);
    }
  };
  walk(ast.program);
  let code = source;
  for (const [start,end,value] of edits.sort((a,b)=>b[0]-a[0])) code = code.slice(0,start) + value + code.slice(end);

  // The real CSP stays intact. Imports still use the exact installed local assets.
  // Debugger evaluation is confined to this synthetic test; nothing is persisted.
  const existingStyles = await page.locator('link[rel="stylesheet"]').evaluateAll(nodes => nodes.map(n => n.href));
  const shell = html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace('</head>',
    existingStyles.map(href => `<link rel="stylesheet" href="${href}">`).join('') + '</head>');
  await page.setContent(shell, { waitUntil:'domcontentloaded' });
  await page.evaluate(() => {
    // Android reinstalls Java bridge properties during document.open(); apply
    // fixtures after setContent, not only in the browser's init-script hook.
    window.HermesServer = undefined;
    window.__layoutFixtureOnly = true;
    window.HermesApi = { call(id, request) {
      window.__hermesRestFixture(request).then(reply => window.__hermesApiResult?.(id, true,
        JSON.stringify({status:reply.status,body:JSON.stringify(reply.body)})));
    }};
    window.HermesPc = { request(id, operation) {
      queueMicrotask(() => window.__hermesPcResult?.(id,true,operation==='ticket'?'synthetic-test-ticket':''));
    }};
    window.HermesBrowser = { request(id,operation,value) {
      const payload=operation==='guest'?JSON.parse(value):{op:operation,url:value};
      queueMicrotask(()=>{
        window.__hermesBrowserResult?.(id,true,'');
        if(payload.op==='load') {
          const detail=JSON.stringify({pageUrl:payload.url,pageTitle:'Layout fixture',canGoBack:false,canGoForward:false});
          for(const event of ['did-start-loading','dom-ready','did-stop-loading']) window.__hermesGuestEvent?.(payload.guest,event,detail);
        }
      });
    }};
    if (String(window.HermesPc.request).includes('[native code]')) throw new Error('Native bridge fixture did not take effect');
  });
  await page.evaluate(`(async()=>{${code}\n})()`);
  await page.locator('[data-contrib-shell]').waitFor({timeout:45000});
}
