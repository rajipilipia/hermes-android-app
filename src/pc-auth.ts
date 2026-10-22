/** Deliberately no URL, header, fetch or token bridge. Native owns all credentials. */
import { foregroundRequired, isBackgrounded } from "./foreground";
export interface PcAuth { signIn(): Promise<void>; ticket(): Promise<string>; signOut(): Promise<void>; }
interface NativeBridge { request(id: string, operation: string): void; }
declare global { interface Window { HermesPc?: NativeBridge; __hermesPcResult?: (id:string,ok:boolean,value:string)=>void; } }
const pending=new Map<string,{resolve:(s:string)=>void;reject:(e:Error)=>void;timer:ReturnType<typeof setTimeout>}>();
let sequence=0;
function request(operation:string):Promise<string>{
 if(typeof window==="undefined" || !window.HermesPc) return Promise.reject(new Error("PC sign-in requires the Android APK and your system browser. Browser preview supports manual debug only."));
 if(operation==="ticket"&&isBackgrounded())return Promise.reject(foregroundRequired());
 window.__hermesPcResult=(id,ok,value)=>{const p=pending.get(id);if(!p)return;pending.delete(id);clearTimeout(p.timer);if(ok)p.resolve(value);else { const error=value === "PC_FOREGROUND_REQUIRED" ? foregroundRequired() : new Error(value === "PC_SIGN_IN_REQUIRED" ? "Sign in to this PC again." : value); if(value === "PC_SIGN_IN_REQUIRED")error.name="PcSignInRequired";p.reject(error); }};
 return new Promise((resolve,reject)=>{const id=String(++sequence);const timer=setTimeout(()=>{pending.delete(id);reject(new Error("PC sign-in timed out. Try again."));},operation==="signIn"?610000:60000);pending.set(id,{resolve,reject,timer});try{window.HermesPc!.request(id,operation);}catch{pending.delete(id);clearTimeout(timer);reject(new Error("Native PC connection unavailable."));}});
}
export const pcAuth:PcAuth={signIn:async()=>{await request("signIn");},ticket:()=>request("ticket"),signOut:async()=>{for(const [id,p] of pending){clearTimeout(p.timer);p.reject(new Error("PC sign-in cancelled."));pending.delete(id);}await request("signOut");}};
