import { it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import vm from 'node:vm';
const main = () => readFileSync('android/src/us/pilipia/hermes/prototype/MainActivity.java', 'utf8');

it('executes strict native host policy and callback lifecycle tests', async () => {
  const run = spawnSync(process.env.PYTHON ?? 'python', ['android/tests/test-native-host.py'], { encoding: 'utf8', timeout: 60000 });
  expect(run.status, run.stdout + run.stderr).toBe(0);
  expect(run.stdout).toContain('PASS callback exactly-once');
  expect(run.stdout).toContain('PASS strict origin/path/method');
  const prepared=readFileSync('build/native-host-tests/prepared-index.html','utf8');
  const scripts=[...prepared.matchAll(/<script\b([^>]*)>/g)];
  expect(scripts[0][1]).toBe(' src="/assets/native-lifecycle.js"');
  expect(scripts.slice(1).some(s=>s[1].includes('type="module"'))).toBe(true);
  let stops=0,captures=0;
  const window:any={navigator:{mediaDevices:{getUserMedia:()=>{captures++;return Promise.resolve({getTracks:()=>[{stop:()=>{stops++;},addEventListener:()=>{}}]});}}},
    document:{visibilityState:'visible',querySelectorAll:()=>[],addEventListener:()=>{}},dispatchEvent:()=>{},CustomEvent:class{},DOMException};
  window.window=window;window.top=window;
  // Execute actual first parser-blocking asset, then simulate the renderer's
  // earliest possible cache. This is document/JS proof, not a WebView OS pass.
  vm.runInNewContext(readFileSync('android/assets/native-lifecycle.js','utf8'),window);
  const rendererCached=window.navigator.mediaDevices.getUserMedia.bind(window.navigator.mediaDevices);
  await expect(rendererCached({audio:true})).rejects.toMatchObject({name:'NotAllowedError'});
  expect(captures).toBe(0);
  window.__hermesNativeLifecycle('resume');
  await rendererCached({audio:true});
  window.__hermesNativeLifecycle('pause');
  expect(stops).toBe(1);
});
it('executes actual Chrome callback cancellation with bounded workers/queues', () => {
  const run=spawnSync(process.env.PYTHON ?? 'python',['android/tests/test-chrome-client.py'],{encoding:'utf8',timeout:60000});
  expect(run.status,run.stdout+run.stderr).toBe(0);
  expect(run.stdout).toContain('PASS DesktopChromeClient bounded executor/callback checks:');
});
it('wires exact asset routing, correct MIME/encoding and non-privileged frame boundary', () => {
  const java = main();
  expect(java).toContain('NativeHostPolicy.assetPath(');
  expect(java).toContain('NativeHostPolicy.mimeType(');
  expect(java).toContain('NativeHostPolicy.encoding(');
  expect(java).toContain('Content-Security-Policy');
  expect(java).toContain("frame-src 'none'");
  expect(java).toContain('Permissions-Policy');
  expect(java).toContain('settings.setMediaPlaybackRequiresUserGesture(true)');
  expect(java).toContain('onRenderProcessGone(');
});
it('installs the fixed parser-blocking hook from bundled assets and shares hash-safe page identity everywhere', () => {
  const java=main();
  expect(java).toContain('BundledDocument.prepare(');
  expect(java).toContain('"native-lifecycle.js".equals(path)');
  expect(java).toContain('new ByteArrayInputStream(lifecycleScript)');
  expect(java).toContain('"index.html".equals(path)');
  expect(java).toContain('NativeHostPolicy.isAppPage(web.getUrl())');
  expect(java).not.toContain('APP_URL.equals(web.getUrl())');
  const finished=java.slice(java.indexOf('void onPageFinished('),java.indexOf('boolean shouldOverrideUrlLoading('));
  expect(finished).not.toContain('getAssets().open(');
  expect(finished).not.toContain('evaluateJavascript(');
  expect(finished).toContain('lifecycle(foreground?"resume":"pause")');
  const bridge=java.slice(java.indexOf('class PcBridge'),java.indexOf('private void browserSignIn('));
  const result=java.slice(java.indexOf('private void result('),java.indexOf('@Override public void onCreate'));
  expect(bridge.match(/currentPage\(\)/g)?.length).toBe(1); // admission
  expect(result.match(/currentPage\(\)/g)?.length).toBe(1); // AND result
  expect(java).toContain('public boolean page(){return currentPage();}');
});
it('wires standard bounded picker and runtime microphone consent with stale callback cancellation', () => {
  const java = main();
  const chrome = (() => { try { return readFileSync('android/src/us/pilipia/hermes/prototype/DesktopChromeClient.java','utf8'); } catch { return ''; } })();
  expect(java).toContain('web.setWebChromeClient(chrome)');
  for (const method of ['onShowFileChooser(', 'onPermissionRequest(', 'onPermissionRequestCanceled(', 'onRequestPermissionsResult(', 'onActivityResult(', 'onShowCustomView(', 'onHideCustomView(']) expect(chrome).toContain(method);
  expect(chrome).toContain('Intent.ACTION_OPEN_DOCUMENT');
  expect(chrome).toContain('Intent.CATEGORY_OPENABLE');
  expect(chrome).toContain('documents.stage(');
  expect(chrome).toContain('NativeHostPolicy.allowAudio(');
  expect(chrome).toContain('Manifest.permission.RECORD_AUDIO');
  expect(chrome).toContain('new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE}');
  expect(chrome).not.toContain('.grant(request.getResources())');
  expect(chrome).toContain('CallbackLease<');
  expect(chrome).toContain('shutdownNow()');
  expect(chrome).toContain('static final java.util.concurrent.atomic.AtomicInteger NEXT_CODE');
  const manifest=readFileSync('android/AndroidManifest.xml','utf8');
  expect(manifest).toContain('android.permission.RECORD_AUDIO');
  expect(manifest).toContain('android:exported="false" android:grantUriPermissions="true"');
  expect(manifest).not.toMatch(/READ_EXTERNAL_STORAGE|WRITE_EXTERNAL_STORAGE|MANAGE_EXTERNAL_STORAGE|android.permission.CAMERA/);
});
