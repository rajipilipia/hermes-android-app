import { it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
const read = (p: string) => existsSync(p) ? readFileSync(p, "utf8") : "";
it("Keystore acceptance probe has its own app UID and contains the exact production store classes", () => {
 const manifest=read("android/instrumentation/AndroidManifest.xml");
 const probe=read("android/instrumentation/PersistentLoginProbe.java");
 const builder=read("scripts/build-persistence-probe.py");
 expect(manifest).toContain('android:targetPackage="us.pilipia.hermes.prototype.persistenceprobe"');
 expect(manifest).not.toContain('android:sharedUserId');
 expect(probe).toContain('Context target=getContext()');
 expect(probe).toContain('"us.pilipia.hermes.prototype.persistenceprobe".equals(getTargetContext().getPackageName())');
 expect(probe).not.toContain('"us.pilipia.hermes.prototype".equals(getTargetContext().getPackageName())');
 expect(builder).toContain("sorted(production.rglob('*.class')) + sorted(tests.rglob('*.class'))");
});
it("production Activity always wires Android Keystore no-backup refresh store, never lifecycle logout", () => {
 const main=read("android/src/us/pilipia/hermes/prototype/MainActivity.java");
 const store=read("android/src/us/pilipia/hermes/prototype/AndroidRefreshStore.java");
 expect(store,"real Android Keystore store is missing").toContain('KeyStore.getInstance("AndroidKeyStore")');
 expect(store).toContain("getNoBackupFilesDir()");
 expect(store).toContain("KeyGenParameterSpec.Builder");
 expect(store).toContain("BLOCK_MODE_GCM");
 expect(store).toContain("setRandomizedEncryptionRequired(true)");
 expect(store).not.toMatch(/getEncoded\(|SharedPreferences|Environment\.|getExternal|localStorage/);
 expect(main).toContain("new AndroidRefreshStore(this,origin)");
 expect(main).not.toContain("private final NativeAuth auth=new NativeAuth");
 // Only explicit user actions delete the login: Sign out, Disconnect, and a confirmed server switch.
 expect(main.match(/auth\.signOut\(/g)).toHaveLength(3);
 const between=(start:string,end:string)=>main.slice(main.indexOf(start),main.indexOf(end,main.indexOf(start)));
 expect(between('"signOut".equals(operation)){','return;')).toContain("auth.signOut()");
 expect(between("private void confirmReset(","private void switchServer(")).toContain("auth.signOut()");
 expect(between("private void switchServer(","private void serverSignIn(")).toContain("auth.signOut()");
 for(const lifecycle of ["protected void onPause(","protected void onDestroy(","onRenderProcessGone("])
  expect(between(lifecycle,"\n")).not.toContain("signOut");
 expect(main).toContain("auth.close()");
 expect(main).toContain("authForeground(path);return http.post");
 expect(main).toContain('if("/auth/native/token".equals(path))awaitForeground();else requireForeground();');
 expect(main).toContain('requireForeground();beforeDispatch.call();return http.post("/auth/native/refresh"');
 expect(read("src/desktop/auth-control.ts")).not.toContain("Login stays in Android memory");
});
