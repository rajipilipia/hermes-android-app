import {it,expect} from "vitest";import {readFileSync,existsSync} from "node:fs";
import {spawnSync} from "node:child_process";
const read=(s:string)=>existsSync(s)?readFileSync(s,"utf8"):"";
it("Android opens external system browser with a constrained credential-free native bridge and normal TLS",()=>{
 const main=read("android/src/us/pilipia/hermes/prototype/MainActivity.java"),http=read("android/src/us/pilipia/hermes/prototype/NativeHttp.java");
 expect(main).toContain("Intent.ACTION_VIEW");expect(main).toContain("@JavascriptInterface");expect(main).toContain('NativeHostPolicy.isAppPage(web.getUrl())');expect(main).toContain('if(!currentPage())return;');expect(main).toContain('if(currentPage()&&NativeHostPolicy.allowAuthCallback(epoch,authEpoch,document,documentEpoch,destroyed))');
 expect(main).toContain('"signIn"');expect(main).toContain('"ticket"');expect(main).toContain('"signOut"');expect(main).toContain("auth.signOut()");
 expect(http).toContain('setInstanceFollowRedirects(false)');expect(http).toContain('"Authorization", "Bearer " + access');expect(http).toContain("new URL(origin+path)");expect(http).toContain("ServerOrigin.normalize(origin)");expect(http).not.toMatch(/setSSLSocketFactory|setHostnameVerifier|CookieManager/);
});
it("executes actual Activity reload admission and independent native auth/document callback fences",()=>{
 const run=spawnSync(process.env.PYTHON??"python",["-B","android/tests/test-main-activity-reload.py"],{encoding:"utf8",timeout:60000});
 expect(run.status,run.stdout+run.stderr).toBe(0);
 expect(run.stdout).toContain("PASS actual Activity exact bundled main-frame GET reload/hash allowlist");
 expect(run.stdout).toContain("PASS actual bridge old-document/new-id collision rejected; current result accepted; native auth preserved");
 expect(run.stdout).toContain("PASS actual bridge hash continuity, queued invocation/delivery, auth cancellation and destroy fences");
},60000);
