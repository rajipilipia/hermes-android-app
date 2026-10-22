import { it, expect } from 'vitest';
import { readFileSync, existsSync } from 'node:fs';
import vm from 'node:vm';

it('stops captured audio, cancels late capture and pauses playback on native background', async () => {
  const file='android/assets/native-lifecycle.js';
  expect(existsSync(file), 'real packaged lifecycle hook is missing').toBe(true);
  let resolve: (stream: unknown) => void=()=>{};
  let stops=0, pauses=0, ttsCancels=0;
  const events: unknown[]=[];
  const callbacks: Record<string,()=>void>={};
  const window: any={
    navigator:{mediaDevices:{getUserMedia:()=>new Promise(r=>{resolve=r;})}},
    document:{visibilityState:'visible', querySelectorAll:()=>[{pause:()=>{pauses++;}}], addEventListener:(type:string,fn:()=>void)=>{callbacks[type]=fn;}},
    speechSynthesis:{cancel:()=>{ttsCancels++;}},
    dispatchEvent:(e:unknown)=>{events.push(e);},
    CustomEvent:class {constructor(public type:string,public options:unknown){}},
    DOMException,
  };
  window.window=window;window.top=window;
  vm.runInNewContext(readFileSync(file,'utf8'),window);
  // The native foreground signal (not initial visibility) admits capture.
  window.__hermesNativeLifecycle('resume');
  const late=window.navigator.mediaDevices.getUserMedia({audio:true});
  window.__hermesNativeLifecycle('pause');
  resolve({getTracks:()=>[{stop:()=>{stops++;}}]});
  await expect(late).rejects.toMatchObject({name:'AbortError'});
  expect(stops).toBe(1);expect(pauses).toBe(1);expect(ttsCancels).toBe(1);
  await expect(window.navigator.mediaDevices.getUserMedia({audio:true})).rejects.toMatchObject({name:'NotAllowedError'});
  window.__hermesNativeLifecycle('resume');
  const live=window.navigator.mediaDevices.getUserMedia({audio:true});
  resolve({getTracks:()=>[{stop:()=>{stops++;},addEventListener:()=>{}}]});
  await live;
  window.__hermesNativeLifecycle('pause');
  expect(stops).toBe(2);
  expect(events.length).toBe(4);
});
it('starts capture fenced and visibility cannot overrule the latest native pause', async () => {
  let captures=0;
  let resolve: (stream: unknown)=>void=()=>{};
  let stops=0;
  const callbacks: Record<string,()=>void>={};
  const window: any={
    navigator:{mediaDevices:{getUserMedia:()=>{captures++;return new Promise(r=>{resolve=r;});}}},
    document:{visibilityState:'visible',querySelectorAll:()=>[],addEventListener:(name:string,fn:()=>void)=>{callbacks[name]=fn;}},
    dispatchEvent:()=>{},CustomEvent:class {},DOMException,
  };
  window.window=window;window.top=window;
  vm.runInNewContext(readFileSync('android/assets/native-lifecycle.js','utf8'),window);
  // A renderer-cached reference must already be the fenced wrapper.
  const cachedCapture=window.navigator.mediaDevices.getUserMedia.bind(window.navigator.mediaDevices);
  const cold=cachedCapture({audio:true});
  expect(captures, 'cold visible document must not invoke platform capture before native resume').toBe(0);
  await expect(cold).rejects.toMatchObject({name:'NotAllowedError'});
  callbacks.visibilitychange();
  await expect(cachedCapture({audio:true})).rejects.toMatchObject({name:'NotAllowedError'});
  window.__hermesNativeLifecycle('resume');
  const late=cachedCapture({audio:true});
  window.__hermesNativeLifecycle('pause');
  callbacks.visibilitychange(); // visible may arrive after onPause; still denied.
  await expect(cachedCapture({audio:true})).rejects.toMatchObject({name:'NotAllowedError'});
  // Even pause -> resume before fulfillment must invalidate the earlier capture.
  window.__hermesNativeLifecycle('resume');
  resolve({getTracks:()=>[{stop:()=>{stops++;}}]});
  await expect(late).rejects.toMatchObject({name:'AbortError'});
  expect(stops).toBe(1);expect(captures).toBe(1);
  window.document.visibilityState='hidden';callbacks.visibilitychange();
  await expect(cachedCapture({audio:true})).rejects.toMatchObject({name:'NotAllowedError'});
  window.document.visibilityState='visible';callbacks.visibilitychange();
  const live=cachedCapture({audio:true});
  resolve({getTracks:()=>[{stop:()=>{stops++;},addEventListener:()=>{}}]});
  await live;
  window.__hermesNativeLifecycle('pause');
  expect(stops).toBe(2);
});
it('wires IME, Android back, fold resize and packaged lifecycle hook without persisting auth', () => {
  const java=readFileSync('android/src/us/pilipia/hermes/prototype/MainActivity.java','utf8');
  for(const token of ['WindowInsets.Type.ime()', 'onConfigurationChanged(', 'onBackPressed(', 'OnBackInvokedCallback', 'hermes:native-back', '__hermesNativeLifecycle', 'native-lifecycle.js'])expect(java).toContain(token);
  // Packaging moved into an importable byte-bound helper; preserve the native
  // asset assertion here, while builder behavior is owned by its dedicated suite.
  const builder=readFileSync('scripts/apk_build.py','utf8');
  expect(builder).toContain("native = source / 'android/assets'");
  expect(builder).toContain("add('assets/' + relative, file)");
  expect(java).not.toContain('web.saveState(');
});
