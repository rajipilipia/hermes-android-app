import {it,expect} from "vitest";
import {ChatController} from "../src/chat";
import {Peer} from "./fixture";
it("captures completion BEFORE resume RPC response and ignores unrelated runtime events",async()=>{
 const p=new Peer(),base=p.respond.bind(p);
 p.respond=(method,params)=>{
  if(method==="session.resume"){
   p.emit("message.complete",{text:"wrong"},"unrelated");
   p.emit("message.complete",{text:"Part two"});
   return {session_id:"runtime-1",stored_session_id:"stored-1",messages:[],message_count:0,info:{},running:true,inflight:{user:"Question",assistant:"Part ",streaming:true}};
  }
  if(method==="session.history")return {count:2,messages:[{role:"user",text:"Question"},{role:"assistant",text:"Part two"}]};
  return base(method,params);
 };
 const c=new ChatController(p.client());await c.connect("wss://example.test/ws","");await c.open("stored-1");
 expect(c.state.busy).toBe(false);expect(c.state.messages.map(m=>m.text)).toEqual(["Question","Part two"]);
 await c.send("Next");expect(p.calls.filter(x=>x.method==="prompt.submit")).toHaveLength(1);c.disconnect();
});
