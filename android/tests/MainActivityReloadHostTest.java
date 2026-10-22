package us.pilipia.hermes.prototype;

import android.net.Uri;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import java.lang.reflect.Field;
import java.util.*;
import java.util.concurrent.*;

/** Actual Activity/bridge under deterministic UI and HTTP plumbing; not WebView OS proof. */
public final class MainActivityReloadHostTest {
 private static final String PAGE="https://gateway.example.com/assets/index.html";
 private static Object field(Object target,String name)throws Exception{
  Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(target);
 }
 private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
 private static WebResourceRequest request(String url,String method,boolean main){return new WebResourceRequest(){
  public Uri getUrl(){return Uri.parse(url);}public String getMethod(){return method;}public boolean isForMainFrame(){return main;}
 };}
 private static MainActivity activity()throws Exception{
  MainActivity a=new MainActivity();a.onCreate(null);a.onResume();return a;
 }
 private static WebView web(MainActivity a)throws Exception{return (WebView)field(a,"web");}
 private static void startupFocus()throws Exception{
  MainActivity a=activity();WebView w=web(a);
  try{
   check(w.hasFocus(),"Cold-start WebView has no focus; Desktop readiness stays checking until a tap");
   int requested=w.focusRequests;
   w.clearFocus();a.onPause();a.onResume();
   check(w.focusRequests==requested,"Resume must not steal focus from a native guest or dialog");
   check(w.scripts.stream().noneMatch(script->script.contains(".focus(")),"Startup must not focus a text field from JavaScript");
   System.out.println("PASS actual Activity focuses WebView at startup only, without focusing an editor");
  }finally{a.onDestroy();a.drain();}
 }
 private static List<String> results(WebView w){
  List<String> result=new ArrayList<>();for(String script:w.scripts)if(script.startsWith("window.__hermesPcResult"))result.add(script);return result;
 }
 private static void navigation()throws Exception{
  MainActivity a=activity();WebView w=web(a);
  try{
   check(!w.client.shouldOverrideUrlLoading(w,request(PAGE,"GET",true)),"Trusted bundled main-document GET reload is blocked");
   for(String hash:Arrays.asList("#", "#/settings", "#session/A?tab=files", "#route%20name"))
    check(!w.client.shouldOverrideUrlLoading(w,request(PAGE+hash,"GET",true)),"Valid bundled hash route is blocked");
   for(String url:Arrays.asList(PAGE+"?",PAGE+"?q=x#route",PAGE+"/other",PAGE.replace("index.html","other.html"),
     PAGE.replace("index.html","%69ndex.html"),PAGE.replace("/assets/","/assets/./"),PAGE.replace("/assets/","/assets/x/../"),
     PAGE.replace("/assets/","/assets%2f"),PAGE.replace("https:","http:"),PAGE.replace(".com/",".com:443/"),
     PAGE.replace(".com/",".com.evil/"),PAGE.replace("https://","https://user@"),"file:///assets/index.html",
     "data:text/html,a","blob:"+PAGE,PAGE+"#%",PAGE+"#bad fragment"))
    check(w.client.shouldOverrideUrlLoading(w,request(url,"GET",true)),"Unsafe navigation admitted: "+url);
   check(w.client.shouldOverrideUrlLoading(w,request(PAGE,"POST",true)),"POST admitted");
   check(w.client.shouldOverrideUrlLoading(w,request(PAGE,"get",true)),"Non-exact GET admitted");
   check(w.client.shouldOverrideUrlLoading(w,request(PAGE,"GET",false)),"Frame navigation admitted");
   check(w.client.shouldOverrideUrlLoading(new WebView(a),request(PAGE,"GET",true)),"Foreign WebView admitted");
   w.url="https://example.com/";
   check(w.client.shouldOverrideUrlLoading(w,request(PAGE,"GET",true)),"Untrusted current document admitted navigation");
   System.out.println("PASS actual Activity exact bundled main-frame GET reload/hash allowlist");
  }finally{a.onDestroy();a.drain();}
 }
 private static Object seedNativeAuth(MainActivity a)throws Exception{
  NativeAuth auth=(NativeAuth)field(a,"auth");Field f=NativeAuth.class.getDeclaredField("tokens");f.setAccessible(true);
  Map<String,Object> tokens=new HashMap<>();tokens.put("access_token","synthetic-access");tokens.put("refresh_token","synthetic-refresh");
  tokens.put("provider","synthetic");tokens.put("expires_at",System.currentTimeMillis()/1000+3600);f.set(auth,tokens);return tokens;
 }
 private static void beginTicket(MainActivity a,String id)throws Exception{
  NativeHttp.entered=new CountDownLatch(1);NativeHttp.release=new CountDownLatch(1);NativeHttp.calls.set(0);
  a.new PcBridge().request(id,"ticket");a.drain();
  check(NativeHttp.entered.await(5,TimeUnit.SECONDS),"Native ticket request did not start");
 }
 private static void callbacks()throws Exception{
  MainActivity a=activity();WebView w=web(a);Object tokens=seedNativeAuth(a);
  try{
   beginTicket(a,"1");Object authEpoch=field(a,"authEpoch");
   // WebView onPageStarted is a true main-document start, unlike a hash change.
   w.client.onPageStarted(w,PAGE,null);
   check(tokens==field(field(a,"auth"),"tokens"),"Trusted reload cleared native credentials");
   check(authEpoch.equals(field(a,"authEpoch")),"Trusted reload changed auth cancellation epoch");
   a.new PcBridge().request("1","ticket");a.drain(); // JS sequence restarts at 1.
   NativeHttp.release.countDown();a.awaitQueued(2);a.drain();
   List<String> delivered=results(w);
   check(delivered.size()==1&&delivered.get(0).contains("synthetic-ticket-2"),
     "Old-document ticket resolved the new document's reused request id 1: deliveries="+delivered.size());
   System.out.println("PASS actual bridge old-document/new-id collision rejected; current result accepted; native auth preserved");
  }finally{NativeHttp.release.countDown();a.onDestroy();a.drain();}
 }
 private static void callbackBoundaries()throws Exception{
  // A same-document HashRouter transition must not cancel a valid pending result.
  MainActivity a=activity();WebView w=web(a);seedNativeAuth(a);
  try{
   beginTicket(a,"1");
   check(!w.client.shouldOverrideUrlLoading(w,request(PAGE+"#/settings","GET",true)),"Hash route blocked");
   w.url=PAGE+"#/settings"; // WebView does not emit onPageStarted for a fragment change.
   NativeHttp.release.countDown();a.awaitQueued(1);a.drain();
   check(results(w).size()==1,"Hash transition cancelled a current result");
  }finally{NativeHttp.release.countDown();a.onDestroy();a.drain();}
  // A bridge invocation queued on the old document cannot be admitted by the new one.
  a=activity();w=web(a);seedNativeAuth(a);
  try{
   NativeHttp.calls.set(0);final MainActivity owner=a;
   Thread invocation=new Thread(()->owner.new PcBridge().request("1","ticket"));invocation.start();invocation.join(5000);
   check(!invocation.isAlive(),"Bridge invocation did not queue");
   w.client.onPageStarted(w,PAGE,null);a.drain();
   ExecutorService worker=(ExecutorService)field(a,"authWorker");worker.submit(()->{}).get(5,TimeUnit.SECONDS);
   check(NativeHttp.calls.get()==0,"Old-document invocation was accepted after reload");
  }finally{a.onDestroy();a.drain();}
  // Reject already-queued delivery after navigation, signOut, or destruction.
  for(String transition:Arrays.asList("navigation","signOut","destroy")){
   a=activity();w=web(a);seedNativeAuth(a);
   try{
    beginTicket(a,"1");NativeHttp.release.countDown();a.awaitQueued(1);
    if(transition.equals("navigation"))w.client.onPageStarted(w,PAGE,null);
    if(transition.equals("signOut"))a.new PcBridge().request("2","signOut");
    if(transition.equals("destroy"))a.onDestroy();
    a.drain();
    List<String> delivered=results(w);
    if(transition.equals("signOut"))check(delivered.size()==1&&delivered.get(0).contains("\"2\",true,\"\""),"Logout was not acknowledged or stale ticket escaped logout");
    else check(delivered.isEmpty(),"Queued result escaped "+transition);
   }finally{NativeHttp.release.countDown();if(!transition.equals("destroy"))a.onDestroy();a.drain();}
  }
  System.out.println("PASS actual bridge hash continuity, queued invocation/delivery, auth cancellation and destroy fences");
 }
 public static void main(String[] args)throws Exception{
  if(args[0].equals("all")||args[0].equals("focus"))startupFocus();
  if(args[0].equals("all")||args[0].equals("navigation"))navigation();
  if(args[0].equals("all")||args[0].equals("callbacks")){callbacks();callbackBoundaries();}
  if(args[0].equals("all"))durableLifecycle();
  if(args[0].equals("all"))logoutFailure();
  if(args[0].equals("all"))diagnostics();
  if(args[0].equals("all"))backgroundRequests();
  if(args[0].equals("all"))staleForegroundRequests();
  if(args[0].equals("all"))foregroundDispatch();
  if(args[0].equals("all"))notifications();
 }
 private static void diagnostics()throws Exception{
  android.util.Log.messages.clear();
  MainActivity a=activity();WebView w=web(a);seedNativeAuth(a);
  try{
   beginTicket(a,"6");NativeHttp.release.countDown();a.awaitQueued(1);a.drain();
   a.onPause();a.onResume();
  }finally{NativeHttp.release.countDown();a.onDestroy();a.drain();}
  String logs=String.join("\n",android.util.Log.messages);
  check(logs.contains("event=activity_create")&&logs.contains("event=activity_pause")&&logs.contains("event=activity_resume")&&logs.contains("event=activity_destroy"),"Lifecycle diagnostics missing");
  check(logs.contains("event=auth_start operation=ticket")&&logs.contains("event=auth_result ok=true"),"Native auth stage diagnostics missing");
  check(!logs.contains("synthetic-access")&&!logs.contains("synthetic-refresh")&&!logs.contains("synthetic-ticket")&&!logs.contains("Bearer "),"Credential leaked into diagnostics");
  System.out.println("PASS native stage/lifecycle debug traces exclude access/refresh/ticket values");
 }
 private static void logoutFailure()throws Exception{
  MainActivity a=activity();WebView w=web(a);
  try{
   AndroidRefreshStore.failClear=true;
   a.new PcBridge().request("4","signOut");a.drain();
   check(results(w).size()==1&&results(w).get(0).contains("\"4\",false,"),"Native credential deletion failure was not acknowledged as failure");
  }finally{AndroidRefreshStore.failClear=false;a.onDestroy();a.drain();}
  System.out.println("PASS actual bridge acknowledges logout failure without successful reload signal");
 }
 private static void durableLifecycle()throws Exception{
  for(boolean renderer:new boolean[]{false,true}){
   AndroidRefreshStore.saved=new NativeAuth.Credential("synthetic-lifecycle-refresh","nous",false);
   MainActivity a=activity();WebView w=web(a);
   check(!((Map<?,?>)field(field(a,"auth"),"tokens")).containsKey("access_token"),"restart restored access token rather than refresh only");
   int clears=AndroidRefreshStore.clears;
   if(renderer)w.client.onRenderProcessGone(w,new android.webkit.RenderProcessGoneDetail());
   a.onDestroy();a.drain();
   check(AndroidRefreshStore.saved!=null&&AndroidRefreshStore.clears==clears,"Activity/renderer teardown erased durable login");
   MainActivity next=activity();
   try{check(field(field(next,"auth"),"tokens")!=null,"Activity recreation lost durable credential");next.new PcBridge().request("0","signOut");check(AndroidRefreshStore.saved==null,"explicit bridge signout did not clear durable login");}
   finally{next.onDestroy();next.drain();}
  }
  System.out.println("PASS actual Activity encrypted-store composition/refresh-only recreation/destroy/renderer preserve/explicit logout");
 }
 private static void backgroundRequests()throws Exception{
  MainActivity a=activity();seedNativeAuth(a);a.onPause();
  NativeAuth.Transport transport=(NativeAuth.Transport)field(field(a,"auth"),"http");
  ExecutorService worker=Executors.newSingleThreadExecutor();
  NativeHttp.calls.set(0);
  try{
   for(String kind:Arrays.asList("ticket","refresh","read","write")){
   Future<?> result=worker.submit(()->{
    try{
     Callable<Void> guard=()->{throw new AssertionError("Background dispatch guard executed");};
     if(kind.equals("ticket"))transport.dispatch("/api/auth/ws-ticket",new HashMap<>(),"synthetic",guard);
     else if(kind.equals("refresh"))transport.refresh(new HashMap<>(),guard);
     else transport.api(new NativeApi.Call(kind.equals("read")?"GET":"POST","/api/sessions",null),"synthetic",guard);
     throw new AssertionError("Background request succeeded");
    }catch(java.io.IOException expected){check("PC_FOREGROUND_REQUIRED".equals(expected.getMessage()),"Background deferral misclassified as login failure");}
    catch(Exception e){throw new RuntimeException(e);}
   });
   result.get(1,TimeUnit.SECONDS);
   }
   check(NativeHttp.calls.get()==0,"Background ticket reached HTTP");
   System.out.println("PASS background ticket fails promptly with foreground deferral, no HTTP or queue wait");
   Object tokens=field(field(a,"auth"),"tokens");
   ((Map<String,Object>)tokens).put("expires_at",0L);
   NativeAuth.Credential saved=AndroidRefreshStore.saved;
   try{((NativeAuth)field(a,"auth")).ticket();throw new AssertionError("Background refresh succeeded");}
   catch(java.io.IOException expected){check("PC_FOREGROUND_REQUIRED".equals(expected.getMessage()),"Refresh deferral misclassified");}
   check(tokens==field(field(a,"auth"),"tokens")&&saved==AndroidRefreshStore.saved,"Unsent refresh marked pending or changed credentials");
   System.out.println("PASS background REST read/write and refresh blocked; unsent rotating credential unchanged");
  }finally{worker.shutdownNow();a.onDestroy();a.drain();}
 }
 private static void staleForegroundRequests()throws Exception{
  for(String kind:Arrays.asList("ticket","synthetic-read","synthetic-write")){
   MainActivity a=activity();WebView w=web(a);seedNativeAuth(a);
   boolean ticket=kind.equals("ticket");
   ExecutorService worker=(ExecutorService)field(a,ticket?"authWorker":"apiWorker");
   CountDownLatch blocked=new CountDownLatch(ticket?1:4),release=new CountDownLatch(1);
   NativeHttp.calls.set(0);NativeHttp.apiCalls.set(0);
   try{
    for(int i=0;i<(ticket?1:4);i++)worker.execute(()->{blocked.countDown();try{release.await();}catch(InterruptedException e){Thread.currentThread().interrupt();}});
    check(blocked.await(5,TimeUnit.SECONDS),"Worker blockers did not start");
    if(ticket)a.new PcBridge().request("81","ticket");else a.new ApiBridge().call("81",kind);
    a.drain();a.onPause();a.onResume();release.countDown();a.awaitQueued(1);a.drain();
    check(NativeHttp.calls.get()==0&&NativeHttp.apiCalls.get()==0,"Old foreground work dispatched after return");
    check(w.scripts.stream().anyMatch(s->s.contains("PC_FOREGROUND_REQUIRED")),"Stale foreground work did not return typed deferral");
   }finally{release.countDown();a.onDestroy();a.drain();}
  }
  System.out.println("PASS queued ticket/REST read/write from an old foreground never dispatch after return");
 }
 private static void foregroundDispatch()throws Exception{
  for(String path:Arrays.asList("/auth/native/token")){
   MainActivity a=activity();a.onPause();
   NativeAuth.Transport transport=(NativeAuth.Transport)field(field(a,"auth"),"http");
   java.util.concurrent.atomic.AtomicInteger guard=new java.util.concurrent.atomic.AtomicInteger();
   NativeHttp.calls.set(0);
   ExecutorService worker=Executors.newSingleThreadExecutor();
   try{
    CountDownLatch started=new CountDownLatch(1);
    Future<?> pending=worker.submit(()->{started.countDown();try{
     transport.dispatch(path,new HashMap<>(),"synthetic",()->{guard.incrementAndGet();throw new java.io.IOException("synthetic cancelled after readiness");});
     throw new AssertionError("cancelled guard reached HTTP");
    }catch(java.io.IOException expected){}catch(Exception e){throw new RuntimeException(e);}});
    check(started.await(5,TimeUnit.SECONDS),"dispatch test worker start");
    Thread.sleep(50);
    check(guard.get()==0,"token/ticket dispatch guard ran before foreground readiness");
    a.onResume();pending.get(5,TimeUnit.SECONDS);
    check(guard.get()==1&&NativeHttp.calls.get()==0,"cancelled post-readiness guard dispatched HTTP");
   }finally{worker.shutdownNow();a.onDestroy();a.drain();}
  }
  for(boolean signOut:new boolean[]{false,true}){
   MainActivity a=activity();seedNativeAuth(a);a.onPause();
   NativeAuth auth=(NativeAuth)field(a,"auth");ExecutorService worker=Executors.newSingleThreadExecutor();
   NativeHttp.calls.set(0);NativeHttp.entered=new CountDownLatch(1);NativeHttp.release=new CountDownLatch(0);
   try{
    CountDownLatch start=new CountDownLatch(1);
    Future<?> pending=worker.submit(()->{start.countDown();try{auth.ticket();throw new AssertionError("cancelled ticket succeeded");}catch(java.io.IOException expected){}catch(Exception e){throw new RuntimeException(e);}});
    check(start.await(5,TimeUnit.SECONDS),"ticket worker start");Thread.sleep(50);
    if(signOut)auth.signOut();else auth.close();
    a.onResume();pending.get(5,TimeUnit.SECONDS);
    check(NativeHttp.calls.get()==0,"cancelled ticket dispatched HTTP after Activity foreground wait");
   }finally{worker.shutdownNow();a.onDestroy();a.drain();}
  }
  System.out.println("PASS actual Activity token/ticket readiness-before-dispatch guard and close/signOut cancellation; no HTTP escaped");
 }
 private static void notifications()throws Exception{
  MainActivity a=activity();
  try{
   NativeNotifications n;
   try{n=(NativeNotifications)field(a,"notifications");}catch(NoSuchFieldException absent){throw new AssertionError("Activity native notification controller absent");}
   check(n!=null&&n.resumes>0,"native notification lifecycle missing");int invalid=n.invalidations;
   web(a).client.onPageStarted(web(a),PAGE,null);
   check(n.invalidations==invalid+1,"reload did not fence old notification routes");
   invalid=n.invalidations;a.new PcBridge().request("9","signOut");
   check(n.invalidations==invalid+1,"logout did not invalidate notifications");
   int intents=n.intents;java.lang.reflect.Method incoming;
   try{incoming=MainActivity.class.getDeclaredMethod("onNewIntent",android.content.Intent.class);}catch(NoSuchMethodException absent){throw new AssertionError("singleTask notification override absent");}
   incoming.setAccessible(true);incoming.invoke(a,new android.content.Intent("fixture",Uri.parse("fixture:opaque")));
   check(n.intents==intents+1,"singleTask new intent not forwarded");
   a.onDestroy();check(n.destroys==1,"Activity destruction did not invalidate native notifications");
  }finally{if(!(Boolean)field(a,"destroyed"))a.onDestroy();a.drain();}
  System.out.println("PASS actual Activity native notification document/auth/intent/lifecycle composition");
 }
}
