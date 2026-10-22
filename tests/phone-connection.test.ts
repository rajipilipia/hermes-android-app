import {it,expect} from "vitest";
import {readFileSync} from "node:fs";
import {ChatController} from "../src/chat";
import {Peer} from "./fixture";
it("native browser sign-in waits but background ticket/REST work is rejected before HTTP",()=>{
 const main=readFileSync("android/src/us/pilipia/hermes/prototype/MainActivity.java","utf8");
 expect(main).toContain("authForeground(path);return http.post(path,body,access)");
 expect(main).toContain('if("/auth/native/token".equals(path))awaitForeground();else requireForeground();');
 expect(main).toContain("requireForeground();beforeDispatch.call();return http.api(call,access)");
 expect(main).toContain('super("PC_FOREGROUND_REQUIRED")');
 expect(main).toContain("admitted.longValue()!=foregroundEpoch");
 expect(main).toContain("while(!foreground&&!destroyed)");
 expect(main).toContain("foreground=true;foregroundLock.notifyAll()");
 expect(main).toContain("foreground=false;");
});
it("launcher reuses the authenticated Android activity",()=>{
 expect(readFileSync("android/AndroidManifest.xml","utf8")).toContain('android:launchMode="singleTask"');
});
it("connection error identifies native login failure without leaking native error text",async()=>{
 const c=new ChatController(new Peer().client());
 await expect(c.connectPc({signIn:async()=>{throw new Error("private-credential");},ticket:async()=>"unused",signOut:async()=>{}})).rejects.toThrow("PC sign-in");
 expect(c.state.error).not.toContain("private-credential");
});
it("ticket failure is distinct from socket connection and never exposes ticket text",async()=>{
 const c=new ChatController(new Peer().client());
 await expect(c.connectPc({signIn:async()=>{},ticket:async()=>{throw new Error("secret-ticket");},signOut:async()=>{}})).rejects.toThrow("connection ticket");
 expect(c.state.error).not.toContain("secret-ticket");
});
