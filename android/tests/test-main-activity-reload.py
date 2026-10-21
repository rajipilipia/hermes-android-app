"""Run actual MainActivity with deterministic framework/HTTP plumbing, no APK or network.

The production Activity, NativeAuth and policy execute unchanged. The fakes supply
only Android UI scheduling/views and a latch-controlled ticket HTTP response.
"""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.cache/port-checkpoints/native-reload-host'
JDK = Path(os.environ.get('JAVA_HOME', 'C:/Program Files/Microsoft/jdk-21.0.8.9-hotspot')) / 'bin'
SRC = ROOT / 'android/src/us/pilipia/hermes/prototype'
STUBS = {
'android/content/Context.java':'package android.content; public class Context {}',
'android/widget/Toast.java':'package android.widget; public class Toast {public static final int LENGTH_LONG=1;public static Toast makeText(android.content.Context c,String s,int length){return new Toast();}public void show(){}}',
'us/pilipia/hermes/prototype/AndroidRefreshStore.java':'''package us.pilipia.hermes.prototype;
public class AndroidRefreshStore implements NativeAuth.Store {
 public static NativeAuth.Credential saved; public static int loads,clears; public static boolean failClear;
 public AndroidRefreshStore(android.content.Context c,String origin){}
 public NativeAuth.Credential load(){loads++;return saved;}
 public void save(NativeAuth.Credential c){saved=c;}
 public void clear()throws java.io.IOException{if(failClear)throw new java.io.IOException("synthetic deletion failure");clears++;saved=null;}
}''',
'android/app/Activity.java': '''package android.app;
public class Activity extends android.content.Context {
 private final Thread uiThread=Thread.currentThread();
 private final java.util.Queue<Runnable> ui=new java.util.concurrent.ConcurrentLinkedQueue<>();
 public void runOnUiThread(Runnable r){if(Thread.currentThread()==uiThread)r.run();else ui.add(r);}
 public void drain(){Runnable r;while((r=ui.poll())!=null)r.run();}
 public void awaitQueued(int count)throws Exception{long end=System.nanoTime()+java.util.concurrent.TimeUnit.SECONDS.toNanos(5);while(ui.size()<count){if(System.nanoTime()>end)throw new AssertionError("UI callback not queued");Thread.sleep(1);}}
 public android.content.res.AssetManager getAssets(){return new android.content.res.AssetManager();}
 public android.content.res.Resources getResources(){return new android.content.res.Resources();}
 public android.view.Window getWindow(){return new android.view.Window();}
 public android.window.OnBackInvokedDispatcher getOnBackInvokedDispatcher(){return new android.window.OnBackInvokedDispatcher();}
 public void startActivity(android.content.Intent i){} public void finish(){} public boolean moveTaskToBack(boolean value){return true;}
 public Object startForegroundService(android.content.Intent i){return new Object();} public boolean stopService(android.content.Intent i){return true;}
 public void setContentView(android.view.View v){} public void onCreate(android.os.Bundle b){}
 public void onConfigurationChanged(android.content.res.Configuration c){} public void onBackPressed(){}
 protected void onActivityResult(int a,int b,android.content.Intent i){} public void onRequestPermissionsResult(int r,String[] p,int[] g){}
 protected void onNewIntent(android.content.Intent i){} public android.content.Intent getIntent(){return null;} public void setIntent(android.content.Intent i){}
 protected void onPause(){} protected void onResume(){} protected void onDestroy(){}
}''',
'android/content/res/AssetManager.java':'package android.content.res; public class AssetManager { public java.io.InputStream open(String path)throws java.io.IOException{return new java.io.ByteArrayInputStream("/* lifecycle test plumbing */".getBytes("UTF-8"));} }',
'android/content/res/Configuration.java':'package android.content.res; public class Configuration { public static final int UI_MODE_NIGHT_MASK=48,UI_MODE_NIGHT_YES=32; public int uiMode=16; }',
'android/content/res/Resources.java':'package android.content.res; public class Resources { public Configuration getConfiguration(){return new Configuration();} }',
'android/content/Intent.java':'package android.content; public class Intent { public static final String ACTION_VIEW="view",CATEGORY_BROWSABLE="browsable"; public Intent(String action,android.net.Uri uri){} public Intent(Context c,Class<?> type){} public Intent addCategory(String value){return this;} }',
'android/net/Uri.java':'package android.net; public class Uri { private String value; private Uri(String s){value=s;} public static Uri parse(String s){return new Uri(s);} public String toString(){return value;} }',
'android/net/http/SslError.java':'package android.net.http; public class SslError {}',
'android/os/Bundle.java':'package android.os; public class Bundle {}',
'android/os/Build.java':'package android.os; public class Build { public static class VERSION {public static final int SDK_INT=36;} }',
'android/graphics/Bitmap.java':'package android.graphics; public class Bitmap {}',
'android/graphics/Color.java':'package android.graphics; public class Color { public static int rgb(int a,int b,int c){return 0;} }',
'android/graphics/Insets.java':'package android.graphics; public class Insets { public int left,top,right,bottom; }',
'android/util/Log.java':'package android.util; public class Log {public static final java.util.List<String> messages=new java.util.ArrayList<>(); public static int w(String a,String b){messages.add(b);return 0;} public static int d(String a,String b){messages.add(b);return 0;} public static int i(String a,String b){messages.add(b);return 0;} }',
'android/view/View.java':'''package android.view; public class View {
 public int focusRequests; private boolean focused;
 public boolean requestFocus(){focusRequests++;focused=true;return true;}
 public boolean hasFocus(){return focused;} public void clearFocus(){focused=false;}
 public interface OnApplyWindowInsetsListener{WindowInsets onApplyWindowInsets(View view,WindowInsets insets);}
 public void setOnApplyWindowInsetsListener(OnApplyWindowInsetsListener l){} public void setPadding(int l,int t,int r,int b){}
 public void requestApplyInsets(){} public void requestLayout(){} public WindowInsets getRootWindowInsets(){return new WindowInsets();}
 public WindowInsetsController getWindowInsetsController(){return new WindowInsetsController();}
 public static final int SYSTEM_UI_FLAG_LIGHT_STATUS_BAR=8192,SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR=16;
 public void setBackgroundColor(int c){} public int getSystemUiVisibility(){return 0;} public void setSystemUiVisibility(int v){}
}''',
'android/view/ViewGroup.java':'package android.view; public class ViewGroup extends View { public static class LayoutParams { public LayoutParams(int w,int h){} } public void addView(View v,LayoutParams p){} }',
'android/view/Window.java':'package android.view; public class Window { public void setStatusBarColor(int c){} public void setNavigationBarColor(int c){} }',
'android/view/WindowInsets.java':'''package android.view; public class WindowInsets {
 public static final WindowInsets CONSUMED=new WindowInsets(); public static class Type {public static int systemBars(){return 1;} public static int displayCutout(){return 2;} public static int ime(){return 4;}}
 public android.graphics.Insets getInsets(int type){return new android.graphics.Insets();} public boolean isVisible(int type){return false;}
 public int getSystemWindowInsetLeft(){return 0;} public int getSystemWindowInsetTop(){return 0;} public int getSystemWindowInsetRight(){return 0;} public int getSystemWindowInsetBottom(){return 0;}
}''',
'android/view/WindowInsetsController.java':'package android.view; public class WindowInsetsController { public static final int APPEARANCE_LIGHT_STATUS_BARS=8,APPEARANCE_LIGHT_NAVIGATION_BARS=16; public void hide(int type){} public void setSystemBarsAppearance(int appearance,int mask){} }',
'android/window/OnBackInvokedCallback.java':'package android.window; public interface OnBackInvokedCallback { void onBackInvoked(); }',
'android/window/OnBackInvokedDispatcher.java':'package android.window; public class OnBackInvokedDispatcher { public static final int PRIORITY_DEFAULT=0; public void registerOnBackInvokedCallback(int p,OnBackInvokedCallback c){} public void unregisterOnBackInvokedCallback(OnBackInvokedCallback c){} }',
'android/widget/FrameLayout.java':'package android.widget; public class FrameLayout extends android.view.ViewGroup { public FrameLayout(android.app.Activity a){} }',
'android/webkit/JavascriptInterface.java':'package android.webkit; @java.lang.annotation.Retention(java.lang.annotation.RetentionPolicy.RUNTIME) public @interface JavascriptInterface {}',
'android/webkit/ValueCallback.java':'package android.webkit; public interface ValueCallback<T>{void onReceiveValue(T value);}',
'android/webkit/WebSettings.java':'''package android.webkit; public class WebSettings {
 public static final int LOAD_NO_CACHE=2,MIXED_CONTENT_ALWAYS_ALLOW=0;
 public void setJavaScriptEnabled(boolean v){} public void setDomStorageEnabled(boolean v){} public void setAllowFileAccess(boolean v){} public void setAllowContentAccess(boolean v){}
 public void setCacheMode(int v){} public void setSaveFormData(boolean v){} public void setSupportMultipleWindows(boolean v){} public void setMediaPlaybackRequiresUserGesture(boolean v){} public void setMixedContentMode(int v){}
}''',
'android/webkit/WebView.java':'''package android.webkit; public class WebView extends android.view.View {
 public String url; public WebViewClient client; public final java.util.List<String> scripts=new java.util.ArrayList<>();
 public WebView(android.app.Activity a){} public String getUrl(){return url;} public void loadUrl(String s){url=s;client.onPageStarted(this,s,null);}
 public void setBackgroundColor(int c){} public WebSettings getSettings(){return new WebSettings();} public void addJavascriptInterface(Object o,String n){}
 public void removeJavascriptInterface(String n){} public static void setWebContentsDebuggingEnabled(boolean v){}
 public void setWebViewClient(WebViewClient c){client=c;} public void setWebChromeClient(Object c){}
 public void evaluateJavascript(String script,ValueCallback<String> callback){scripts.add(script);}
 public void onPause(){} public void onResume(){} public void stopLoading(){} public void clearCache(boolean v){} public void destroy(){}
}''',
'android/webkit/WebResourceRequest.java':'package android.webkit; public interface WebResourceRequest { android.net.Uri getUrl(); String getMethod(); boolean isForMainFrame(); }',
'android/webkit/WebResourceResponse.java':'package android.webkit; public class WebResourceResponse { public WebResourceResponse(String m,String e,int s,String r,java.util.Map<String,String> h,java.io.InputStream i){} }',
'android/webkit/SslErrorHandler.java':'package android.webkit; public class SslErrorHandler { public void cancel(){} }',
'android/webkit/RenderProcessGoneDetail.java':'package android.webkit; public class RenderProcessGoneDetail {}',
'android/webkit/WebViewClient.java':'''package android.webkit; public class WebViewClient {
 public void onPageStarted(WebView v,String u,android.graphics.Bitmap b){} public void onPageFinished(WebView v,String u){}
 public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest r){return false;}
 public void onReceivedSslError(WebView v,SslErrorHandler h,android.net.http.SslError e){}
 public boolean onRenderProcessGone(WebView v,RenderProcessGoneDetail d){return false;}
 public WebResourceResponse shouldInterceptRequest(WebView v,WebResourceRequest r){return null;}
}''',
'org/json/JSONObject.java':'package org.json; public class JSONObject { public static String quote(String s){return "\\\""+s.replace("\\\\","\\\\\\\\").replace("\\\"","\\\\\\\"")+"\\\"";} }',
'us/pilipia/hermes/prototype/DesktopChromeClient.java':'''package us.pilipia.hermes.prototype; public class DesktopChromeClient {
 public interface Host{boolean active();boolean page();android.webkit.WebView web();android.view.ViewGroup container();}
 public int changes; public DesktopChromeClient(android.app.Activity a,Host h){} public void documentChanged(){changes++;}
 public boolean hideCustomView(){return false;} public boolean onActivityResult(int a,int b,android.content.Intent i){return false;}
 public boolean onRequestPermissionsResult(int r,String[] p,int[] g){return false;}
 public void pause(){} public void resume(){} public void destroy(){}
}''',
'us/pilipia/hermes/prototype/NativeNotifications.java': '''package us.pilipia.hermes.prototype; public class NativeNotifications {
 public int invalidations,intents,resumes,destroys; public NativeNotifications(android.app.Activity a){}
 public String request(String op,org.json.JSONObject payload,boolean active){return "false";}
 public void acceptIntent(android.content.Intent i){intents++;} public void invalidate(){invalidations++;}
 public void resume(){resumes++;} public void destroy(){destroys++;} public boolean onRequestPermissionsResult(int c,String[] p,int[] g){return false;}
}''',
'us/pilipia/hermes/prototype/NativeHttp.java':'''package us.pilipia.hermes.prototype; public class NativeHttp {
 public NativeHttp(String origin){}
 public static final java.util.concurrent.atomic.AtomicInteger apiCalls=new java.util.concurrent.atomic.AtomicInteger();
 public NativeAuth.Reply api(NativeApi.Call call,String access){apiCalls.incrementAndGet();return new NativeAuth.Reply(200,"{}");}
 public java.util.Map<String,Object> getPublic(String path){throw new AssertionError("Unexpected probe");}
 public static volatile java.util.concurrent.CountDownLatch entered,release; public static final java.util.concurrent.atomic.AtomicInteger calls=new java.util.concurrent.atomic.AtomicInteger();
 public java.util.Map<String,Object> post(String path,java.util.Map<String,String> body,String access)throws Exception{
  if(!"/api/auth/ws-ticket".equals(path))throw new AssertionError("Unexpected HTTP operation");
  int call=calls.incrementAndGet();entered.countDown();if(!release.await(5,java.util.concurrent.TimeUnit.SECONDS))throw new AssertionError("HTTP test latch expired");
  java.util.Map<String,Object> result=new java.util.HashMap<>();result.put("ticket","synthetic-ticket-"+call);return result;
 }
}''',
'us/pilipia/hermes/prototype/ServerStore.java':'''package us.pilipia.hermes.prototype; public class ServerStore {
 public static String saved="https://gateway.example.com"; public ServerStore(android.content.Context c){}
 public String load(){return saved;} public void save(String o){saved=o;} public void clear(){saved=null;}
}''',
'us/pilipia/hermes/prototype/NativeApi.java':'''package us.pilipia.hermes.prototype; public final class NativeApi {
 public static final class Call { public final String method,pathAndQuery; public final byte[] body; Call(String m,String p,byte[] b){method=m;pathAndQuery=p;body=b;} }
 public NativeApi(String contract){} public Call prepare(String request)throws java.io.IOException{
  if("synthetic-read".equals(request))return new Call("GET","/api/profiles/active",null);
  if("synthetic-write".equals(request))return new Call("POST","/api/sessions",new byte[]{123,125});
  throw new java.io.IOException("stub");
 }
}''',
'us/pilipia/hermes/prototype/ServerProbe.java':'''package us.pilipia.hermes.prototype; public class ServerProbe { public interface Reader{java.util.Map<String,Object> getPublic(String p)throws Exception;} public static String session(java.util.concurrent.Callable<?> p,String o){return null;} public static String[] race(java.util.concurrent.ExecutorService e,java.util.concurrent.Callable<?> p,String o,java.util.function.Supplier<String> s){return new String[]{s.get(),"public"};} public static String run(Reader h,String o,java.util.function.BooleanSupplier c){return "{}";} }''',
'us/pilipia/hermes/prototype/BrowserPane.java':'''package us.pilipia.hermes.prototype; class BrowserPane {
 interface Host{void emit(int guest,String type,String detail);} static int destroys;
 BrowserPane(android.app.Activity a,android.widget.FrameLayout c,Host h){} String request(String json){return null;}
 boolean back(){return false;} void pause(){} void resume(){} void destroyAll(){destroys++;}
}''',
'us/pilipia/hermes/prototype/ServerDialogs.java':'''package us.pilipia.hermes.prototype; class ServerDialogs { static void confirm(android.app.Activity a,String t,String m,String act,Runnable ok,Runnable cancel){cancel.run();} }''',
'us/pilipia/hermes/prototype/ConnectionWorkService.java':'package us.pilipia.hermes.prototype; public class ConnectionWorkService {}',
}


def run(args, name):
    result = subprocess.run(list(map(str, args)), cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    (OUT / (name + '.log')).write_text(result.stdout, encoding='utf-8')
    print(result.stdout, end='')
    if result.returncode:
        raise SystemExit(result.returncode)


def main():
    mode = sys.argv[1:] or ['all']
    if len(mode) != 1 or mode[0] not in ['all', 'navigation', 'callbacks']:
        raise SystemExit('Usage: test-main-activity-reload.py [all|navigation|callbacks]')
    classes = OUT / 'classes'
    classes.mkdir(parents=True, exist_ok=True)
    for name, content in STUBS.items():
        target = OUT / 'fakes' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.strip() + '\n', encoding='utf-8')
    sources = [SRC / name for name in ['MainActivity.java', 'NativeHostPolicy.java', 'NativeAuth.java', 'NativeWork.java', 'ServerOrigin.java', 'BoundedStreams.java', 'BundledDocument.java']]
    sources += [ROOT / 'android/tests/MainActivityReloadHostTest.java']
    run([JDK / 'javac.exe', '--release', '8', '-Xlint:-options', '-d', classes,
         *sorted((OUT / 'fakes').rglob('*.java')), *sources], 'compile')
    run([JDK / 'java.exe', '-cp', classes, 'us.pilipia.hermes.prototype.MainActivityReloadHostTest', *mode], mode[0])


if __name__ == '__main__':
    main()
