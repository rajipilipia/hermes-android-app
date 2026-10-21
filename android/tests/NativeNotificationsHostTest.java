package us.pilipia.hermes.prototype;

import android.app.*;
import android.content.Intent;
import android.os.Build;
import org.json.*;
import java.lang.reflect.*;

/** Actual controller with framework fixtures: not notification OS/device proof. */
public final class NativeNotificationsHostTest {
 private static int checks;
 private static Class<?> type;
 private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
 private static Object controller(Activity a)throws Exception{return type.getConstructor(Activity.class).newInstance(a);}
 private static Object call(Object c,String method,Class<?>[] args,Object... values)throws Exception{return type.getMethod(method,args).invoke(c,values);}
 private static JSONObject request(Object c,String operation,JSONObject payload,boolean active)throws Exception{
  return new JSONObject((String)call(c,"request",new Class<?>[]{String.class,JSONObject.class,boolean.class},operation,payload,active));
 }
 private static JSONObject request(Object c,String operation,boolean active)throws Exception{return request(c,operation,new JSONObject(),active);}
 private static void permission()throws Exception {
  Build.VERSION.SDK_INT=36;Activity a=new Activity();Object c=controller(a);
  check(request(c,"status",false).getString("permission").equals("not-requested"),"initial permission must not be requested");
  check(a.requests==0,"status never opens permission prompt");
  check(!request(c,"request",false).getBoolean("ok"),"background permission request refused");
  check(a.requests==0,"background cannot prompt");
  JSONObject pending=request(c,"request",true);
  check(pending.getBoolean("ok")&&pending.getString("permission").equals("requested"),"explicit foreground request opens runtime consent");
  check(a.requests==1&&a.requested.length==1&&a.requested[0].equals("android.permission.POST_NOTIFICATIONS"),"only notification consent requested");
  check(request(c,"status",true).getString("permission").equals("requested"),"pending status reported truthfully");
  request(c,"request",true);check(a.requests==1,"pending prompt not duplicated");
  check(!(Boolean)call(c,"onRequestPermissionsResult",new Class<?>[]{int.class,String[].class,int[].class},a.requestCode+1,new String[]{"android.permission.POST_NOTIFICATIONS"},new int[]{-1}),"foreign permission result not consumed");
  a.rationale=true;
  check((Boolean)call(c,"onRequestPermissionsResult",new Class<?>[]{int.class,String[].class,int[].class},a.requestCode,a.requested,new int[]{-1}),"owned denial result consumed");
  check(request(c,"status",true).getString("permission").equals("denied"),"denial status");
  request(c,"request",true);check(a.requests==1,"denial never automatically re-prompts, even after explicit re-entry");
  Object replacement=controller(a);
  check(request(replacement,"status",false).getString("permission").equals("denied"),"asked flag survives controller replacement");
  request(replacement,"request",true);check(a.requests==1,"asked flag prevents repeat prompt after recreation");
  a.rationale=false;check(request(c,"status",true).getString("permission").equals("blocked"),"no-rationale denial is blocked");
  a.permission=0;check(request(c,"status",true).getString("permission").equals("granted"),"OS grant is authoritative");
  a.notifications.enabled=false;check(request(c,"status",true).getString("permission").equals("blocked"),"OS master disabled is blocked");
  Activity failure=new Activity();failure.failSave=true;Object f=controller(failure);
  check(!request(f,"request",true).getBoolean("ok")&&failure.requests==0,"failed asked persistence refuses prompt");
  Build.VERSION.SDK_INT=32;Activity legacy=new Activity();Object old=controller(legacy);
  check(request(old,"status",false).getString("permission").equals("granted"),"pre-33 uses OS notification setting");
  request(old,"request",true);check(legacy.requests==0,"pre-33 never requests runtime notification permission");
  Build.VERSION.SDK_INT=36;
 }
 private static JSONObject notification(String session)throws Exception {
  return new JSONObject().put("kind","approval").put("title","Private fixture title").put("body","Private fixture body")
   .put("sessionId",session).put("focusSessionId","stored-1").put("notifyId","notify-1").put("tag","fixture")
   .put("icon","/untrusted/private/icon.png").put("route",new JSONObject().put("profile","example-profile").put("sessionId",session).put("storedSessionId","stored-1"));
 }
 private static Notification only(Activity a){check(a.notifications.shown.size()==1,"exactly one OS notification");return a.notifications.shown.values().iterator().next();}
 private static void show()throws Exception {
  Activity a=new Activity();a.permission=0;Object c=controller(a);
  JSONObject n=notification("runtime-1").put("silent",true).put("actions",new JSONArray()
   .put(new JSONObject().put("id","approve:request-1").put("text","Approve"))
   .put(new JSONObject().put("id","reject:request-1").put("text","Reject")));
  check(request(c,"show",n,false).getBoolean("ok"),"background notification must be handed to OS");
  Notification posted=only(a);
  check(posted.title.equals("Private fixture title")&&posted.body.equals("Private fixture body"),"original Desktop text is used");
  check(posted.visibility==Notification.VISIBILITY_SECRET,"lock screen secret visibility");
  check(posted.publicVersion!=null&&!posted.publicVersion.title.contains("Private")&&!posted.publicVersion.body.contains("Private"),"generic public notification contains no chat text");
  check(posted.icon==android.R.drawable.ic_dialog_info,"arbitrary absolute icon path is discarded");
  check(posted.actions.size()==1&&posted.actions.get(0).title.equals("Review"),"approval actions become one navigation-only Review");
  check(posted.actions.get(0).intent==posted.contentIntent,"review uses same navigation capability, no action identifier");
  check(posted.autoCancel&&posted.localOnly&&posted.timeout==86400000L,"notification has auto-cancel, local-only and 24h OS timeout");
  PendingIntent pi=posted.contentIntent;
  check((pi.flags&PendingIntent.FLAG_IMMUTABLE)!=0,"pending intent immutable");
  check(pi.intent.getComponent().getClassName().equals("us.pilipia.hermes.prototype.MainActivity"),"pending intent explicitly targets MainActivity");
  check(pi.intent.getAction().equals("us.pilipia.hermes.prototype.NOTIFICATION_OPEN"),"fixed private action");
  check(pi.intent.getExtras().size()==0,"intent carries no owner/session/text extras");
  check(pi.intent.getData()!=null&&!pi.intent.getData().toString().contains("example-profile")&&!pi.intent.getData().toString().contains("runtime"),"unique data is opaque capability, not owner/session");
  android.app.NotificationChannel quiet=a.notifications.getNotificationChannel(posted.channel);
  check(quiet!=null&&quiet.sound==null&&!quiet.vibration,"silent channel has neither sound nor vibration");
  String quietId=posted.channel;
  check(request(c,"show",notification("runtime-1").put("silent",false),false).getBoolean("ok"),"replacement show accepted");
  posted=only(a);check(!posted.channel.equals(quietId),"audible and silent channels are separate immutable IDs");
  check(pi.cancelled,"dedup replacement revokes old pending intent");
  int count=a.notifications.posts;
  a.notifications.enabled=false;check(!request(c,"show",notification("other"),false).getBoolean("ok"),"master-disabled show refused");
  a.notifications.enabled=true;a.permission=-1;
  check(!request(c,"show",notification("other"),false).getBoolean("ok")&&a.requests==0,"show without consent refuses without prompting");
  a.permission=0;a.notifications.failNotify=true;
  check(!request(c,"show",notification("other"),false).getBoolean("ok"),"OS notification rejection returned honestly");
  check(a.notifications.posts==count,"refused notifications not reported as OS posts");
 }
 private static void invalidShow()throws Exception {
  Activity a=new Activity();a.permission=0;Object c=controller(a);
  JSONObject[] invalid={
   notification("s").put("unknown",true),notification("s").put("kind","other"),
   notification("s").put("title",new String(new char[257]).replace('\0','x')),
   notification("s").put("body",new String(new char[4097]).replace('\0','x')),
   notification("s").put("silent","true"),notification("s").put("title",42),
   notification("s").put("route",new JSONObject().put("profile","../example-profile")),
   notification("s").put("route",new JSONObject().put("profile","example-profile").put("sessionId","../secret")),
   notification("s").put("route",new JSONObject().put("profile","example-profile").put("token","credential")),
   notification("s").put("activate","https://foreign.invalid"),
   notification("s").put("route",new JSONObject().put("profile","example-profile").put("activate","//evil.invalid")),
   notification("s").put("activate","/%2e%2e/private"),notification("s").put("activate","/%2f%2fevil.invalid"),
   notification("s").put("activate","/ok%0aevil"),notification("s").put("activate","/ok\\evil"),
   notification("s").put("actions",new JSONArray().put(new JSONObject().put("id","approve").put("text","Yes").put("execute",true))),
   notification("s").put("actions",new JSONArray().put(new JSONObject().put("id","approve").put("text","Yes").put("activate","javascript:evil")))
  };
  for(JSONObject n:invalid)check(!request(c,"show",n,false).getBoolean("ok"),"malformed notification refused: "+n.keySet());
  check(a.notifications.posts==0&&a.requests==0,"invalid input never reaches notification manager or permission prompt");
 }
 private static void accept(Object c,Intent intent)throws Exception{call(c,"acceptIntent",new Class<?>[]{Intent.class},intent);}
 private static void tap()throws Exception {
  Activity a=new Activity();a.permission=0;Object c=controller(a);JSONObject original=notification("runtime-tap");
  original.getJSONObject("route").put("activate","/index-network/intent/1?source=notification");
  check(request(c,"show",original,false).getBoolean("ok"),"tap fixture posted");
  Notification posted=only(a);Intent intent=posted.contentIntent.intent;
  String action=intent.getAction(),token=intent.getData().toString();
  original.getJSONObject("route").put("profile","attacker");
  intent.putExtra("profile","forged").putExtra("sessionId","forged").putExtra("actionId","approve:arbitrary");
  accept(c,intent);
  check(intent.getData()==null&&intent.getAction()==null&&intent.getExtras().size()==0,"recognized tap intent scrubbed");
  check(a.notifications.shown.isEmpty()&&posted.contentIntent.cancelled,"tap consumes token and cancels OS notification");
  check(!request(c,"take",false).getBoolean("ok"),"background page cannot consume route");
  a.keyguard.locked=true;check(!request(c,"take",true).getBoolean("ok"),"locked device cannot consume route");
  call(c,"resume",new Class<?>[]{});
  a.keyguard.locked=false;call(c,"resume",new Class<?>[]{});
  JSONObject taken=request(c,"take",true);
  check(taken.getBoolean("ok")&&taken.getJSONObject("route").getString("profile").equals("example-profile"),"route captured before mutation; intent extras not trusted");
  JSONObject route=taken.getJSONObject("route");
  check(route.getString("sessionId").equals("runtime-tap")&&route.getString("storedSessionId").equals("stored-1"),"live and stored session identities remain separate");
  check(route.getString("activate").equals("/index-network/intent/1?source=notification"),"safe local plugin navigation survives");
  check(route.length()==4&&!taken.has("actionId")&&!taken.toString().contains("Private"),"only navigation route returned, never action execution or chat text");
  check(!request(c,"take",true).getBoolean("ok"),"route delivered only once");
  accept(c,new Intent().setAction(action).setData(android.net.Uri.parse(token)));
  check(!request(c,"take",true).getBoolean("ok"),"token replay fails closed");
  Intent forged=new Intent().setAction(action).setData(android.net.Uri.parse("hermes-notification:"+new String(new char[64]).replace('\0','0'))).putExtra("sessionId","forged");
  accept(c,forged);check(!request(c,"take",true).getBoolean("ok"),"unknown opaque token cannot route");
  check(request(c,"show",notification("process-old"),false).getBoolean("ok"),"old process fixture posted");
  Intent old=only(a).contentIntent.intent;Object replacement=controller(a);accept(replacement,old);
  check(!request(replacement,"take",true).getBoolean("ok"),"process/controller restart cannot reconstruct route from intent");
 }
 private static void lifecycle()throws Exception {
  Activity a=new Activity();a.permission=0;Object c=controller(a);
  check(request(c,"show",notification("stale"),false).getBoolean("ok"),"stale fixture posted");
  Notification stale=only(a);Intent staleIntent=stale.contentIntent.intent;
  call(c,"invalidate",new Class<?>[]{});
  check(a.notifications.shown.isEmpty()&&stale.contentIntent.cancelled,"document/account invalidate cancels OS notification and pending capability");
  accept(c,staleIntent);check(!request(c,"take",true).getBoolean("ok"),"stale owner cannot route after invalidate");
  request(c,"show",notification("tap-before-change"),false);accept(c,only(a).contentIntent.intent);
  call(c,"invalidate",new Class<?>[]{});check(!request(c,"take",true).getBoolean("ok"),"invalidate drops queued route too");
  request(c,"show",notification("first"),false);Notification first=only(a);
  String firstToken=first.contentIntent.intent.getData().toString();String action=first.contentIntent.intent.getAction();
  for(int i=1;i<=32;i++)check(request(c,"show",notification("cap-"+i),false).getBoolean("ok"),"bounded show admitted");
  check(a.notifications.shown.size()==32&&first.contentIntent.cancelled,"cap32 evicts and cancels oldest");
  accept(c,new Intent().setAction(action).setData(android.net.Uri.parse(firstToken)));
  check(!request(c,"take",true).getBoolean("ok"),"evicted token cannot route");
  call(c,"invalidate",new Class<?>[]{});
  request(c,"show",notification("expiry"),false);Notification expiring=only(a);
  android.os.SystemClock.now+=86400000L;call(c,"resume",new Class<?>[]{});
  check(a.notifications.shown.isEmpty()&&expiring.contentIntent.cancelled,"resume prunes elapsed 24h notifications");
  accept(c,expiring.contentIntent.intent);check(!request(c,"take",true).getBoolean("ok"),"expired token cannot route");
  request(c,"show",notification("pending-expiry"),false);accept(c,only(a).contentIntent.intent);
  android.os.SystemClock.now+=86400000L;
  check(!request(c,"take",true).getBoolean("ok"),"pending route also expires at original deadline");
  request(c,"show",notification("cancel-1").put("notifyId","id-1"),false);
  request(c,"show",notification("cancel-2").put("notifyId","id-2"),false);
  check(request(c,"cancel",new JSONObject().put("notifyId","id-1"),false).getBoolean("ok")&&a.notifications.shown.size()==1,"cancel by notifyId targets own notification");
  check(request(c,"cancel",new JSONObject().put("tag","fixture"),false).getBoolean("ok")&&a.notifications.shown.isEmpty(),"cancel by tag");
  request(c,"show",notification("cancel-all"),false);
  check(request(c,"cancel",false).getBoolean("ok")&&a.notifications.shown.isEmpty(),"empty cancel clears owned notifications");
  request(c,"show",notification("destroy"),false);Notification destroyed=only(a);accept(c,destroyed.contentIntent.intent);
  request(c,"show",notification("destroy-2"),false);
  call(c,"destroy",new Class<?>[]{});call(c,"destroy",new Class<?>[]{});call(c,"resume",new Class<?>[]{});
  check(a.notifications.shown.isEmpty(),"destroy idempotently cancels owned notifications");
  check(!request(c,"show",notification("after-destroy"),false).getBoolean("ok")&&!request(c,"take",true).getBoolean("ok"),"destroy is terminal");
  Activity consent=new Activity();Object old=controller(consent);request(old,"request",true);int code=consent.requestCode;
  call(old,"invalidate",new Class<?>[]{});
  check(!(Boolean)call(old,"onRequestPermissionsResult",new Class<?>[]{int.class,String[].class,int[].class},code,consent.requested,new int[]{0}),"late permission result invalidated with owner");
  // Permission callback arrays are untrusted: only a later OS permission read can grant.
  Activity liar=new Activity();Object liarOwner=controller(liar);request(liarOwner,"request",true);
  call(liarOwner,"onRequestPermissionsResult",new Class<?>[]{int.class,String[].class,int[].class},liar.requestCode,new String[]{"android.permission.POST_NOTIFICATIONS"},new int[]{0});
  check(!request(liarOwner,"status",true).getString("permission").equals("granted"),"callback grant cannot override missing OS consent");
 }
 private static void requestShape()throws Exception {
  Activity a=new Activity();a.permission=0;Object c=controller(a);
  check(!request(c,"unknown",true).getBoolean("ok"),"unknown operation refused");
  check(!request(c,"status",new JSONObject().put("extra",true),true).getBoolean("ok"),"status requires empty payload");
  check(!request(c,"request",new JSONObject().put("extra",true),true).getBoolean("ok")&&a.requests==0,"invalid permission payload cannot prompt");
  check(!request(c,"cancel",new JSONObject().put("unknown",true),true).getBoolean("ok"),"cancel rejects unknown fields");
  check(!request(c,"cancel",new JSONObject().put("notifyId",42),true).getBoolean("ok"),"cancel rejects non-string notifyId");
  check(!request(c,"show",new JSONObject().put("kind","turnDone"),false).getBoolean("ok"),"show requires native route, never infers owner from session/title");
  JSONObject malformed=notification("bad-null").put("route",JSONObject.NULL);
  check(!request(c,"show",malformed,false).getBoolean("ok"),"JSON null route refused");
  check(request(c,"show",notification("channel"),false).getBoolean("ok"),"channel fixture posted");
  Notification posted=only(a);a.notifications.channels.put(posted.channel,new NotificationChannel(posted.channel,"disabled",0));
  check(!request(c,"show",notification("blocked-channel"),false).getBoolean("ok"),"disabled channel refuses show despite granted runtime consent");
 }
 public static void main(String[] args)throws Exception {
  try{type=Class.forName("us.pilipia.hermes.prototype.NativeNotifications");}
  catch(ClassNotFoundException missing){throw new AssertionError("NativeNotifications controller API is absent",missing);}
  permission();show();invalidShow();tap();lifecycle();requestShape();
  System.out.println("PASS NativeNotifications JVM fixture assertions: "+checks);
 }
}
