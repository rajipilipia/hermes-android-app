package us.pilipia.hermes.prototype;

import android.app.Activity;
import android.content.Intent;
import android.webkit.JavascriptInterface;
import org.json.JSONObject;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import android.os.Bundle;
import android.os.Build;
import android.view.WindowInsets;
import android.widget.FrameLayout;
import android.net.Uri;
import android.net.http.SslError;
import android.graphics.Color;
import android.webkit.WebView;
import android.webkit.WebSettings;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.SslErrorHandler;
import java.io.IOException;
import java.io.ByteArrayInputStream;
import java.util.HashMap;
import java.util.Map;

/** Bundled local UI. Only auth actions and native-validated server setup cross the bridge; tokens stay native. */
public final class MainActivity extends Activity {
 private WebView web;
 private FrameLayout container;
 private DesktopChromeClient chrome;
 private BrowserPane browser;
 private NativeNotifications notifications;
 private NativeWork work;
 private android.window.OnBackInvokedCallback backCallback;
 private byte[] lifecycleScript;
 private boolean currentPage(){return !destroyed&&web!=null&&NativeHostPolicy.isAppPage(web.getUrl());}
 private boolean activePage(){return foreground&&currentPage();}
 private ServerStore servers;
 /** Saved server origin, or null while the user has not set one up. UI thread only. */
 private String server;
 private final Object foregroundLock=new Object();
 private boolean foreground=false;
 private long foregroundEpoch=0;
 private final ThreadLocal<Long> requestForegroundEpoch=new ThreadLocal<>();
 private static final class ForegroundRequired extends IOException {
  ForegroundRequired(){super("PC_FOREGROUND_REQUIRED");}
 }
 /** Reconnect/REST work must not occupy workers while Android has paused the app. */
 private void requireForeground()throws IOException {
  synchronized(foregroundLock){
   if(destroyed)throw new IOException("Activity closed");
   Long admitted=requestForegroundEpoch.get();
   if(!foreground||(admitted!=null&&admitted.longValue()!=foregroundEpoch))throw new ForegroundRequired();
  }
 }
 private void authForeground(String path)throws IOException,InterruptedException {
  // Explicit browser sign-in is the only operation that must wait for the browser to return.
  if("/auth/native/token".equals(path))awaitForeground();else requireForeground();
 }
 private volatile NativeAuth auth;
 // Probes run in parallel: the Hermes card probes while the address is typed, and a stale partial
 // host must never queue the real one behind its DNS/connect timeout.
 private final ExecutorService probeWorker=Executors.newCachedThreadPool();
 private final java.util.concurrent.atomic.AtomicLong probeGeneration=new java.util.concurrent.atomic.AtomicLong();
 /** Stock-server REST allowlist from the bundled capability contract; null if the asset is unusable. */
 private NativeApi api;
 private final ExecutorService apiWorker=Executors.newFixedThreadPool(4);
 private void awaitForeground()throws IOException,InterruptedException {
  long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(120);
  synchronized(foregroundLock){
   while(!foreground&&!destroyed){
    long remaining=TimeUnit.NANOSECONDS.toMillis(deadline-System.nanoTime());
    if(remaining<=0)throw new IOException("Return to Hermes to finish connecting");
    foregroundLock.wait(Math.max(1,remaining));
   }
   if(destroyed)throw new IOException("Activity closed");
  }
 }
 private final ExecutorService authWorker=Executors.newSingleThreadExecutor();
 private volatile long authEpoch=0;
 private volatile long documentEpoch=0;
 private volatile boolean destroyed=false;
 public final class PcBridge {
  @JavascriptInterface public void request(String id,String operation){
   if(id==null||!id.matches("[0-9]{1,12}")||!("signIn".equals(operation)||"ticket".equals(operation)||"signOut".equals(operation)))return;
   final long document=documentEpoch;
   runOnUiThread(()->{
    if(!currentPage())return;
    if(document!=documentEpoch)return;
    if(!"signOut".equals(operation)&&!foreground){result(authEpoch,document,id,false,"PC_FOREGROUND_REQUIRED");return;}
    android.util.Log.d("HermesPrototype","event=auth_start operation="+operation+" epoch="+authEpoch+" document="+document);
    if(auth==null){result(authEpoch,document,id,"signOut".equals(operation),"signOut".equals(operation)?"":"PC_SERVER_REQUIRED");return;}
    if("signOut".equals(operation)){
     if(work!=null)work.reset();
     if(notifications!=null)notifications.invalidate();
     authEpoch++;
     try{auth.signOut();result(authEpoch,document,id,true,"");}catch(IOException failure){
      result(authEpoch,document,id,false,"Local sign-out cleanup failed. Try again.");
     }
     return;
    }
    if("signIn".equals(operation)){if(notifications!=null)notifications.invalidate();authEpoch++;auth.close();}
    final long epoch=authEpoch;final NativeAuth owner=auth;final long admittedForeground=foregroundEpoch;
    authWorker.execute(()->{
     try{
      if(destroyed||epoch!=authEpoch||document!=documentEpoch)return;
      String value="";
      if("signIn".equals(operation))browserSignIn(owner,epoch);
      else {requestForegroundEpoch.set(admittedForeground);requireForeground();value=owner.ticket();}
      result(epoch,document,id,true,value);
     }catch(ForegroundRequired e){result(epoch,document,id,false,"PC_FOREGROUND_REQUIRED");}
     catch(NativeAuth.AuthRequired e){result(epoch,document,id,false,"PC_SIGN_IN_REQUIRED");}
     catch(NativeAuth.HttpFailure e){result(epoch,document,id,false,"Gateway HTTP "+e.status);}
     catch(Exception e){android.util.Log.w("HermesPrototype","Native auth stage="+operation+" exception="+e.getClass().getSimpleName());result(epoch,document,id,false,"PC sign-in/connection failed or expired. Sign in again; check your system browser and network.");}
     finally{requestForegroundEpoch.remove();}
    });
   });
  }
 }
 private void browserSignIn(NativeAuth owner,long epoch)throws Exception {
  AtomicReference<NativeWork.Lease> lease=new AtomicReference<>();
  try{owner.signIn(url->{
   CountDownLatch launched=new CountDownLatch(1);AtomicReference<RuntimeException> failed=new AtomicReference<>();
   runOnUiThread(()->{try{
    if(destroyed||epoch!=authEpoch||!activePage())throw new IllegalStateException("Cancelled");
    lease.set(work==null?null:work.signIn(true));
    if(lease.get()==null)throw new IllegalStateException("Foreground sign-in service unavailable");
    startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(url)).addCategory(Intent.CATEGORY_BROWSABLE));
   }catch(RuntimeException e){failed.set(e);}finally{launched.countDown();}});
   try{if(!launched.await(5,TimeUnit.SECONDS)||failed.get()!=null)throw new IllegalStateException("Browser unavailable");}catch(InterruptedException e){Thread.currentThread().interrupt();throw new IllegalStateException("Cancelled");}
  },600000);}finally{runOnUiThread(()->{if(lease.get()!=null)lease.get().close();});}
 }
 private NativeAuth newAuth(String origin)throws IOException {
  final NativeHttp http=new NativeHttp(origin);
  return new NativeAuth(new NativeAuth.Transport(){
   public java.util.Map<String,Object> post(String path,java.util.Map<String,String> body,String access)throws Exception {
    authForeground(path);return http.post(path,body,access);
   }
   public java.util.Map<String,Object> dispatch(String path,java.util.Map<String,String> body,String access,java.util.concurrent.Callable<Void> beforeDispatch)throws Exception {
    authForeground(path);beforeDispatch.call();return http.post(path,body,access);
   }
   public java.util.Map<String,Object> refresh(java.util.Map<String,String> body,java.util.concurrent.Callable<Void> beforeDispatch)throws Exception {
    // Deferral happens before marking the rotating credential pending: no refresh was sent.
    requireForeground();beforeDispatch.call();return http.post("/auth/native/refresh",body,"");
   }
   public NativeAuth.Reply api(NativeApi.Call call,String access,java.util.concurrent.Callable<Void> beforeDispatch)throws Exception {
    requireForeground();beforeDispatch.call();return http.api(call,access);
   }
  },new AndroidRefreshStore(this,origin),origin);
 }
 /**
  * Server setup for the Hermes connection cards. The value is only ever a typed server address:
  * native normalizes it (https host, optional port, nothing else) and asks before switching servers.
  * Results never contain tokens or tickets.
  */
 public final class ServerBridge {
  @JavascriptInterface public void request(String id,String operation,String value){
   if(id==null||!id.matches("[0-9]{1,12}")||!java.util.Arrays.asList("probe","signIn","cloudSignIn","test","apply","reset","portal").contains(operation))return;
   final long document=documentEpoch;
   runOnUiThread(()->{
    if(!currentPage()||document!=documentEpoch)return;
    if("reset".equals(operation)){confirmReset(id,document);return;}
    if("portal".equals(operation)){openPortal(document,id);return;}
    String target=ServerOrigin.normalize(value);
    if(target==null){serverResult(document,id,false,"Enter the https:// address of your Hermes server: a host name with an optional port, no path.");return;}
    switch(operation){
     case "probe":probe(document,id,target);return;
     case "cloudSignIn":
      // Hermes Cloud agent sign-in: same native flow, only for agent dashboards.
      if(!ServerOrigin.cloudAgent(target)){serverResult(document,id,false,"That is not a Hermes Cloud agent address (it ends in agents.nousresearch.com).");return;}
      if(target.equals(server))serverSignIn(document,id);
      else confirmSwitch(document,id,target);
      return;
     case "signIn":
      if(target.equals(server))serverSignIn(document,id);
      else confirmSwitch(document,id,target);
      return;
     case "test":
      if(!target.equals(server)||auth==null){serverResult(document,id,false,"Sign in to "+ServerOrigin.label(target)+" first.");return;}
      testServer(document,id);return;
     default:
      if(!target.equals(server)){serverResult(document,id,false,"Sign in to "+ServerOrigin.label(target)+" first.");return;}
      if(!server.equals(NativeHostPolicy.origin())){NativeHostPolicy.useOrigin(server);}
      serverResult(document,id,true,server);
      // Native navigation to the exact new page; the old document and its callbacks are fenced by documentEpoch.
      web.loadUrl(NativeHostPolicy.appUrl());
    }
   });
  }
 }
 private void probe(long document,String id,String target){
  final long generation=probeGeneration.incrementAndGet();
  // Settings re-checks the server the app is already using; the live sign-in races the public check.
  final NativeAuth owner=target.equals(server)?auth:null;
  probeWorker.execute(()->{
   // A newer address superseded this one: answer at once (the card ignores stale results).
   if(generation!=probeGeneration.get()){serverResult(document,id,false,"Superseded.");return;}
   try{awaitForeground();}catch(Exception e){serverResult(document,id,false,"Return to Hermes to check the server.");return;}
   final long started=System.nanoTime();
   final java.util.function.Supplier<String> open=()->ServerProbe.run(new NativeHttp(target)::getPublic,target,()->generation==probeGeneration.get());
   final String[] answer=owner==null?new String[]{open.get(),"public"}:ServerProbe.race(probeWorker,owner::ticket,target,open);
   android.util.Log.d("HermesPrototype","event=server_probe source="+answer[1]+" elapsed_ms="+((System.nanoTime()-started)/1000000)+" current="+(generation==probeGeneration.get()));
   serverResult(document,id,true,answer[0]);
  });
 }
 /** Opens the fixed Nous Portal in the system browser; the page passes no address. */
 private void openPortal(long document,String id){
  try{startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(ServerOrigin.PORTAL)).addCategory(Intent.CATEGORY_BROWSABLE));serverResult(document,id,true,ServerOrigin.PORTAL);}
  catch(RuntimeException unavailable){serverResult(document,id,false,"No browser is available to open the Nous Portal.");}
 }
 private void confirmSwitch(long document,String id,String target){
  String message=server==null
   ?"Hermes will sign in to "+ServerOrigin.label(target)+" in your browser. Only continue if this is your own Hermes server."
   :"Hermes will sign out of "+ServerOrigin.label(server)+" on this phone and sign in to "+ServerOrigin.label(target)+". Only continue if this is your own Hermes server.";
  ServerDialogs.confirm(this,"Connect to "+ServerOrigin.label(target)+"?",message,"Connect",()->{
   if(!currentPage()||document!=documentEpoch)return;
   try{switchServer(target);}catch(IOException failure){serverResult(document,id,false,"Could not sign out of the previous server. Try again.");return;}
   serverSignIn(document,id);
  },()->serverResult(document,id,false,"Cancelled."));
 }
 private void confirmReset(String id,long document){
  if(server==null){serverResult(document,id,true,"");return;}
  ServerDialogs.confirm(this,"Disconnect from "+ServerOrigin.label(server)+"?",
   "Hermes will sign out on this phone and forget this server. Your chats stay on the server.","Disconnect",()->{
    if(!currentPage()||document!=documentEpoch)return;
    try{
     if(notifications!=null)notifications.invalidate();
     authEpoch++;if(auth!=null)auth.signOut();auth=null;
     servers.clear();server=null;
    }catch(IOException failure){serverResult(document,id,false,"Local sign-out cleanup failed. Try again.");return;}
    serverResult(document,id,true,"");
    NativeHostPolicy.useOrigin(ServerOrigin.SETUP);web.loadUrl(NativeHostPolicy.appUrl());
   },()->serverResult(document,id,false,"Cancelled."));
 }
 /** Old credential is deleted (acknowledged) before the new server is saved. The page moves on apply. */
 private void switchServer(String target)throws IOException {
  if(notifications!=null)notifications.invalidate();
  authEpoch++;
  if(auth!=null){auth.signOut();auth=null;}
  NativeAuth next=newAuth(target);
  servers.save(target);
  server=target;auth=next;
 }
 /** Like Desktop: every Sign in press runs the system-browser native sign-in (RFC 8252). */
 private void serverSignIn(long document,String id){
  if(notifications!=null)notifications.invalidate();
  final long epoch=authEpoch;final NativeAuth owner=auth;
  authWorker.execute(()->{
   try{
    if(destroyed||epoch!=authEpoch)return;
    browserSignIn(owner,epoch);
    if(epoch==authEpoch)serverResult(document,id,true,owner.origin());
   }catch(Exception e){
    android.util.Log.w("HermesPrototype","Server sign-in exception="+e.getClass().getSimpleName());
    if(epoch==authEpoch)serverResult(document,id,false,"If your browser showed your account page instead of \u201cSign-in received\u201d, tap Sign in again.");
   }
  });
 }
 private void testServer(long document,String id){
  final long epoch=authEpoch;final NativeAuth owner=auth;
  authWorker.execute(()->{
   try{owner.ticket();if(epoch==authEpoch)serverResult(document,id,true,owner.origin());}
   catch(NativeAuth.AuthRequired e){serverResult(document,id,false,"Sign in to "+ServerOrigin.label(owner.origin())+" first.");}
   catch(NativeAuth.HttpFailure e){serverResult(document,id,false,"Server answered HTTP "+e.status+".");}
   catch(Exception e){serverResult(document,id,false,"Could not reach "+ServerOrigin.label(owner.origin())+".");}
  });
 }
 /**
  * Hermes REST on a server without the PC adapter (Desktop talks REST to such a server directly).
  * The page sends a capabilityCall() result; NativeApi admits only contract operations and builds the
  * request itself. Replies carry the HTTP status and JSON text, never a credential.
  */
 public final class ApiBridge {
  @JavascriptInterface public void call(String id,String request){
   if(id==null||!id.matches("[0-9]{1,12}"))return;
   final long document=documentEpoch;
   runOnUiThread(()->{
    if(!currentPage()||document!=documentEpoch)return;
    if(auth==null||api==null){apiResult(document,id,false,auth==null?"PC_SERVER_REQUIRED":"Hermes REST is unavailable in this build.");return;}
    final NativeApi.Call call;
    try{call=api.prepare(request);}catch(IOException invalid){apiResult(document,id,false,invalid.getMessage());return;}
    if(!foreground){apiResult(document,id,false,"PC_FOREGROUND_REQUIRED");return;}
    final long epoch=authEpoch;final NativeAuth owner=auth;final long admittedForeground=foregroundEpoch;
    apiWorker.execute(()->{
     try{
      if(destroyed||epoch!=authEpoch||document!=documentEpoch)return;
      requestForegroundEpoch.set(admittedForeground);requireForeground();
      NativeAuth.Reply reply=owner.api(call);
      if(epoch==authEpoch)apiResult(document,id,true,"{\"status\":"+reply.status+",\"body\":"+JSONObject.quote(reply.body)+"}");
     }catch(ForegroundRequired e){apiResult(document,id,false,"PC_FOREGROUND_REQUIRED");}
     catch(NativeAuth.AuthRequired e){apiResult(document,id,false,"PC_SIGN_IN_REQUIRED");}
     catch(Exception e){android.util.Log.w("HermesPrototype","Hermes REST exception="+e.getClass().getSimpleName());apiResult(document,id,false,"Could not reach the Hermes server.");}
     finally{requestForegroundEpoch.remove();}
    });
   });
  }
 }
 /**
  * Desktop's in-app browser contract (R1, approved staged). "external": open an http/https link in
  * the system browser (Desktop's openExternal). "guest" (stage 1): one BrowserPane request (create,
  * load, back, forward, reload, stop, bounds, destroy); BrowserPane validates every URL natively.
  */
 public final class BrowserBridge {
  @JavascriptInterface public void request(String id,String operation,String value){
   if(id==null||!id.matches("[0-9]{1,12}")||!("external".equals(operation)||"guest".equals(operation))||value==null||value.length()>8192)return;
   final long document=documentEpoch;
   runOnUiThread(()->{
    if(!currentPage()||document!=documentEpoch)return;
    if("guest".equals(operation)){
     String error=browser==null?"The Hermes browser is unavailable.":browser.request(value);
     browserResult(document,id,error==null,error==null?"":error);
     return;
    }
    if(!NativeHostPolicy.allowExternal(value)){browserResult(document,id,false,"This link cannot be opened.");return;}
    try{startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(value)).addCategory(Intent.CATEGORY_BROWSABLE));browserResult(document,id,true,"");}
    catch(RuntimeException unavailable){browserResult(document,id,false,"No browser is available to open this link.");}
   });
  }
 }
 private void browserResult(long document,String id,boolean ok,String value){runOnUiThread(()->{
  if(currentPage()&&!destroyed&&document==documentEpoch)web.evaluateJavascript("window.__hermesBrowserResult&&window.__hermesBrowserResult("+JSONObject.quote(id)+","+ok+","+JSONObject.quote(value)+")",null);
 });}
 private void guestEvent(int guest,String type,String detail){
  // Called on the UI thread by BrowserPane; guests are destroyed whenever the app document changes.
  if(currentPage()&&!destroyed)web.evaluateJavascript("window.__hermesGuestEvent&&window.__hermesGuestEvent("+guest+","+JSONObject.quote(type)+","+JSONObject.quote(detail)+")",null);
 }
 private void apiResult(long document,String id,boolean ok,String value){runOnUiThread(()->{
  if(currentPage()&&!destroyed&&document==documentEpoch)web.evaluateJavascript("window.__hermesApiResult&&window.__hermesApiResult("+JSONObject.quote(id)+","+ok+","+JSONObject.quote(value)+")",null);
 });}
 private void serverResult(long document,String id,boolean ok,String value){runOnUiThread(()->{
  if(currentPage()&&!destroyed&&document==documentEpoch)web.evaluateJavascript("window.__hermesServerResult&&window.__hermesServerResult("+JSONObject.quote(id)+","+ok+","+JSONObject.quote(value)+")",null);
 });}
 private void result(long epoch,long document,String id,boolean ok,String value){runOnUiThread(()->{
  // Never log callback values: successful ticket responses contain a credential.
  if(!ok&&"PC_FOREGROUND_REQUIRED".equals(value))android.util.Log.d("HermesPrototype","event=auth_deferred reason=foreground");
  else android.util.Log.d("HermesPrototype","event=auth_result ok="+ok+" current="+NativeHostPolicy.allowAuthCallback(epoch,authEpoch,document,documentEpoch,destroyed)+" epoch="+epoch+" document="+document);
  if(currentPage()&&NativeHostPolicy.allowAuthCallback(epoch,authEpoch,document,documentEpoch,destroyed))web.evaluateJavascript("window.__hermesPcResult&&window.__hermesPcResult("+JSONObject.quote(id)+","+ok+","+JSONObject.quote(value)+")",null);
 });}
 @Override public void onCreate(Bundle state) {
  super.onCreate(state);
  work=new NativeWork(new NativeWork.Driver(){
   public boolean start(){
    try{return startForegroundService(new Intent(MainActivity.this,ConnectionWorkService.class))!=null;}
    catch(RuntimeException denied){android.util.Log.w("HermesPrototype","event=work_service_rejected exception="+denied.getClass().getSimpleName());return false;}
   }
   public void stop(){stopService(new Intent(MainActivity.this,ConnectionWorkService.class));}
  });
  android.util.Log.d("HermesPrototype","event=activity_create");
  servers=new ServerStore(this);server=servers.load();
  NativeHostPolicy.useOrigin(server!=null?server:ServerOrigin.SETUP);
  // Always the real native encrypted store. Never degrade to memory-only success.
  try{auth=server!=null?newAuth(server):null;}
  catch(IOException failure){finish();return;}
  notifications=new NativeNotifications(this);
  notifications.acceptIntent(getIntent());
  // Load the fixed script before allowing any bundled document to render.
  try(java.io.InputStream input=getAssets().open("native-lifecycle.js");java.io.ByteArrayOutputStream script=new java.io.ByteArrayOutputStream()){
   BoundedStreams.copy(input,script,65536);lifecycleScript=script.toByteArray();
   if(lifecycleScript.length==0)throw new IOException("Missing lifecycle fence");
  }catch(IOException failure){finish();return;}
  try(java.io.InputStream input=getAssets().open("capability-contract.json");java.io.ByteArrayOutputStream contract=new java.io.ByteArrayOutputStream()){
   BoundedStreams.copy(input,contract,1<<20);api=new NativeApi(contract.toString("UTF-8"));
  }catch(Exception unavailable){api=null;}
  web=new WebView(this);
  WebSettings settings=web.getSettings();
  settings.setJavaScriptEnabled(true);
  // UI settings (profile rail, layout, drafts) live in localStorage; without DOM
  // storage every change is lost on exit. Storage stays app-private and no-backup.
  settings.setDomStorageEnabled(true);
  android.util.Log.i("HermesPrototype","event=webview_config dom_storage=true verbose_logging=true");
  settings.setAllowFileAccess(false);
  settings.setAllowContentAccess(false);
  settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
  settings.setSaveFormData(false);
  settings.setSupportMultipleWindows(false);
  settings.setMediaPlaybackRequiresUserGesture(true);
  web.addJavascriptInterface(new PcBridge(),"HermesPc");
  web.addJavascriptInterface(new ServerBridge(),"HermesServer");
  web.addJavascriptInterface(new ApiBridge(),"HermesApi");
  web.addJavascriptInterface(new BrowserBridge(),"HermesBrowser");
  // DEBUG APK ONLY: HTTPS asset origin may dial explicitly opted-in local WS.
  // Android network-security-config + JS validator + CSP deny remote cleartext.
  settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
  WebView.setWebContentsDebuggingEnabled(true);
  web.setWebViewClient(new WebViewClient(){
   @Override public void onPageStarted(WebView view,String url,android.graphics.Bitmap favicon){
    // WebView emits this for main-document starts, not same-document hash routes.
    // Fence callbacks only: a trusted reload must retain native login credentials.
    if(view==web&&!destroyed){documentEpoch++;android.util.Log.d("HermesPrototype","event=document_start document="+documentEpoch);if(work!=null)work.turn(false,false);if(notifications!=null)notifications.invalidate();if(chrome!=null)chrome.documentChanged();if(browser!=null)browser.destroyAll();}
   }
   @Override public void onPageFinished(WebView view,String url){
    if(view==web&&NativeHostPolicy.isAppPage(url)&&currentPage())lifecycle(foreground?"resume":"pause");
   }
   @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){
    return view!=web||destroyed||!NativeHostPolicy.allowNavigation(view.getUrl(),request.getUrl().toString(),request.getMethod(),request.isForMainFrame());
   }
   @Override public void onReceivedSslError(WebView view,SslErrorHandler handler,SslError error){handler.cancel();}
   @Override public boolean onRenderProcessGone(WebView view,android.webkit.RenderProcessGoneDetail detail){
    android.util.Log.d("HermesPrototype","event=renderer_gone");
    authEpoch++;if(auth!=null)auth.close();if(browser!=null)browser.destroyAll();view.destroy();web=null;finish();return true;
   }
   @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request){
    // A main-frame reload can carry the renderer's hash route (#/settings?...); it is still the one
    // exact bundled document. Every other request keeps the strict fragment-free asset policy.
    String url=request.getUrl().toString();
    String path=request.isForMainFrame()&&"GET".equals(request.getMethod())&&NativeHostPolicy.isAppPage(url)?"index.html"
     :NativeHostPolicy.assetPath(url,request.getMethod());
    if(path==null)return blocked();
    String mime=NativeHostPolicy.mimeType(path);
    try {
     Map<String,String> headers=new HashMap<>();headers.put("Cache-Control","no-store");headers.put("X-Content-Type-Options","nosniff");headers.put("Referrer-Policy","no-referrer");
     // No untrusted HTML/preview frame may inherit the auth-privileged JavaScript interface.
     headers.put("Content-Security-Policy","default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data: blob:; media-src 'self' blob: data:; worker-src 'self' blob:; connect-src 'self' wss: ws://localhost:* ws://127.0.0.1:* ws://10.0.2.2:*; frame-src 'none'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'none'");
     headers.put("X-Frame-Options","DENY");
     headers.put("Permissions-Policy","microphone=(self), camera=(), geolocation=()");
     java.io.InputStream asset;
     if("native-lifecycle.js".equals(path)){
      if(lifecycleScript==null)return blocked();
      asset=new ByteArrayInputStream(lifecycleScript);
     }else if("index.html".equals(path)){
      if(lifecycleScript==null)return blocked();
      try(java.io.InputStream index=getAssets().open("www/"+path)){
       asset=new ByteArrayInputStream(BundledDocument.prepare(index));
      }
     }else asset=getAssets().open("www/"+path);
     return new WebResourceResponse(mime,NativeHostPolicy.encoding(mime),200,"OK",headers,asset);
    }catch(IOException error){return blocked();}
   }
  });
  container=new FrameLayout(this);
  chrome=new DesktopChromeClient(this,new DesktopChromeClient.Host(){
   public boolean active(){return activePage();}
   public boolean page(){return currentPage();}
   public WebView web(){return web;}
   public android.view.ViewGroup container(){return container;}
   public String notification(String operation,JSONObject payload){return currentPage()&&notifications!=null?notifications.request(operation,payload,activePage()):"{\"ok\":false}";}
   public boolean work(boolean active){return currentPage()&&work!=null&&work.turn(active,activePage());}
  });
  web.setWebChromeClient(chrome);
  container.addView(web,new FrameLayout.LayoutParams(-1,-1));
  browser=new BrowserPane(this,container,this::guestEvent);
  container.setOnApplyWindowInsetsListener((view,insets)->{
   if(Build.VERSION.SDK_INT>=30){
    android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
    container.setPadding(bars.left,bars.top,bars.right,bars.bottom);
    return WindowInsets.CONSUMED;
   }else{
    container.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());
   }
   return insets;
  });
  setContentView(container);
  applySystemBars();
  // Desktop's readiness check requires document.hasFocus(). A cold WebView can be
  // visible but unfocused until the first tap. Focus the view, not an editor; do
  // this only at creation so returning from a guest or dialog never steals focus.
  web.requestFocus();
  container.requestApplyInsets();
  if(Build.VERSION.SDK_INT>=33){backCallback=this::handleBack;getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,backCallback);}
  // Bundled page at the server origin (or the setup origin): assets are app-local, never downloaded.
  // The temporary loopback listener is the OAuth callback only.
  web.loadUrl(NativeHostPolicy.appUrl());
 }
 private void lifecycle(String state){
  if(currentPage())web.evaluateJavascript("window.__hermesNativeLifecycle&&window.__hermesNativeLifecycle("+JSONObject.quote(state)+")",null);
 }
 @Override protected void onNewIntent(Intent intent){
  super.onNewIntent(intent);
  if(notifications!=null)notifications.acceptIntent(intent);
  setIntent(intent);
  if(activePage())web.evaluateJavascript("window.dispatchEvent(new Event('hermes:notification-tap'))",null);
 }
 // System bars and the strips behind them follow the system light/dark mode and match the page
 // chrome (light #F6F8FA, dark #010409), so a light page has no dark band above or below it.
 private void applySystemBars(){
  boolean night=(getResources().getConfiguration().uiMode&android.content.res.Configuration.UI_MODE_NIGHT_MASK)==android.content.res.Configuration.UI_MODE_NIGHT_YES;
  int chromeColor=night?Color.rgb(1,4,9):Color.rgb(246,248,250);
  getWindow().setStatusBarColor(chromeColor);
  getWindow().setNavigationBarColor(chromeColor);
  if(web!=null)web.setBackgroundColor(chromeColor);
  if(container==null)return;
  container.setBackgroundColor(chromeColor);
  if(Build.VERSION.SDK_INT>=30){
   android.view.WindowInsetsController controller=container.getWindowInsetsController();
   int light=android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS|android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
   if(controller!=null)controller.setSystemBarsAppearance(night?0:light,light);
  }else{
   int light=android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR|android.view.View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
   int flags=container.getSystemUiVisibility();
   container.setSystemUiVisibility(night?flags&~light:flags|light);
  }
 }
 @Override public void onConfigurationChanged(android.content.res.Configuration configuration){
  super.onConfigurationChanged(configuration);
  applySystemBars();
  if(container!=null)container.requestApplyInsets();
  if(web!=null){web.requestLayout();if(activePage())web.evaluateJavascript("window.dispatchEvent(new Event('resize'))",null);}
 }
 @Override public void onBackPressed(){handleBack();}
 private void handleBack(){
  if(chrome!=null&&chrome.hideCustomView())return;
  if(!activePage()){moveTaskToBack(true);return;}
  if(Build.VERSION.SDK_INT>=30){
   WindowInsets insets=web.getRootWindowInsets();
   if(insets!=null&&insets.isVisible(WindowInsets.Type.ime())){android.view.WindowInsetsController controller=web.getWindowInsetsController();if(controller!=null)controller.hide(WindowInsets.Type.ime());return;}
  }
  // A visible in-app browser page goes back in its own history first.
  if(browser!=null&&browser.back())return;
  final WebView owner=web;
  // The renderer may preventDefault() to close its current sheet/pane. Never navigate to an untrusted history URL.
  web.evaluateJavascript("(function(){var e=new Event('hermes:native-back',{cancelable:true});if(!window.dispatchEvent(e))return true;var k=new KeyboardEvent('keydown',{key:'Escape',code:'Escape',bubbles:true,cancelable:true});if(!document.dispatchEvent(k))return true;var a=document.activeElement;if(a&&(a.tagName==='INPUT'||a.tagName==='TEXTAREA'||a.isContentEditable)){a.blur();return true;}return false;})()",handled->{
   if(web==owner&&activePage()&&!"true".equals(handled))moveTaskToBack(true);
  });
 }
 private static WebResourceResponse blocked(){return new WebResourceResponse("text/plain","UTF-8",403,"Forbidden",new HashMap<>(),new ByteArrayInputStream(new byte[0]));}
 @Override protected void onActivityResult(int requestCode,int resultCode,Intent data){
  if(chrome!=null&&chrome.onActivityResult(requestCode,resultCode,data))return;
  super.onActivityResult(requestCode,resultCode,data);
 }
 @Override public void onRequestPermissionsResult(int requestCode,String[] permissions,int[] grants){
  if(notifications!=null&&notifications.onRequestPermissionsResult(requestCode,permissions,grants))return;
  if(chrome!=null&&chrome.onRequestPermissionsResult(requestCode,permissions,grants))return;
  super.onRequestPermissionsResult(requestCode,permissions,grants);
 }
 @Override protected void onPause(){android.util.Log.d("HermesPrototype","event=activity_pause");synchronized(foregroundLock){foreground=false;foregroundEpoch++;}lifecycle("pause");if(chrome!=null)chrome.pause();super.onPause();if(web!=null)web.onPause();if(browser!=null)browser.pause();}
 @Override protected void onResume(){super.onResume();android.util.Log.d("HermesPrototype","event=activity_resume");if(web!=null)web.onResume();if(browser!=null)browser.resume();synchronized(foregroundLock){foreground=true;foregroundLock.notifyAll();}if(work!=null)work.resume();if(chrome!=null)chrome.resume();if(notifications!=null)notifications.resume();lifecycle("resume");if(activePage())web.evaluateJavascript("window.dispatchEvent(new Event('hermes:notification-tap'))",null);}
 @Override protected void onDestroy(){android.util.Log.d("HermesPrototype","event=activity_destroy");lifecycle("pause");destroyed=true;synchronized(foregroundLock){foregroundLock.notifyAll();}if(work!=null)work.close();if(notifications!=null)notifications.destroy();if(chrome!=null)chrome.destroy();if(browser!=null)browser.destroyAll();if(Build.VERSION.SDK_INT>=33&&backCallback!=null)getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback(backCallback);authEpoch++;if(auth!=null)auth.close();authWorker.shutdownNow();probeWorker.shutdownNow();apiWorker.shutdownNow();if(web!=null){web.removeJavascriptInterface("HermesPc");web.removeJavascriptInterface("HermesServer");web.removeJavascriptInterface("HermesApi");web.removeJavascriptInterface("HermesBrowser");web.stopLoading();web.clearCache(true);web.destroy();web=null;}super.onDestroy();}
}
