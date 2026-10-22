import {it,expect,vi} from "vitest";
import {ChatController} from "../src/chat";
import {Peer} from "./fixture";
import {pcAuth} from "../src/pc-auth";
it("native logout stays pending until its own acknowledgement and surfaces deletion failure",async()=>{
 const calls:Array<[string,string]>=[];
 (globalThis as any).window={HermesPc:{request:(id:string,operation:string)=>calls.push([id,operation])}};
 try{
  let settled=false;
  const result=Promise.resolve(pcAuth.signOut()).then(()=>{settled=true;},error=>{settled=true;throw error;});
  await Promise.resolve();await Promise.resolve();
  expect(settled).toBe(false);
  expect(calls).toHaveLength(1);expect(calls[0][1]).toBe("signOut");expect(calls[0][0]).not.toBe("0");
  const rejected=expect(result).rejects.toThrow("Local sign-out cleanup failed");
  window.__hermesPcResult!(calls[0][0],false,"Local sign-out cleanup failed");
  await rejected;
 }finally{delete (globalThis as any).window;}
});
it("PC sign-in obtains fresh single-use tickets; disconnect preserves login, explicit sign-out clears",async()=>{
 const p=new Peer(),c=new ChatController(p.client(),5);
 const auth={signIn:vi.fn(async()=>{}),ticket:vi.fn(async()=>"ticket-"+Math.random()),signOut:vi.fn()};
 expect(typeof (c as any).connectPc).toBe("function");
 await (c as any).connectPc(auth);expect(auth.signIn).toHaveBeenCalledTimes(1);
 expect(p.sockets[0].url).toMatch(/^wss:\/\/gateway\.example\.com\/api\/ws\?ticket=/);
 p.sockets[0].close();await vi.waitFor(()=>expect(p.sockets.length).toBe(2));
 expect(auth.ticket).toHaveBeenCalledTimes(2);expect(p.sockets[1].url).not.toBe(p.sockets[0].url);
 c.disconnect();expect(auth.signOut).not.toHaveBeenCalled();
 await c.connectPc(auth);c.signOut();expect(auth.signOut).toHaveBeenCalledTimes(1);
});
it("terminal native expiry stops reconnect and asks for fresh sign-in",async()=>{
 const p=new Peer(),c=new ChatController(p.client(),5);let count=0;
 const auth={signIn:async()=>{},ticket:async()=>{if(count++) {const e=new Error("Sign in again");e.name="PcSignInRequired";throw e;}return "first";},signOut:vi.fn()};
 await c.connectPc(auth);p.sockets[0].close();await vi.waitFor(()=>expect(c.state.status).toBe("offline"));
 expect(c.state.error).toContain("Sign in");await new Promise(r=>setTimeout(r,30));expect(count).toBe(2);c.disconnect();
});
