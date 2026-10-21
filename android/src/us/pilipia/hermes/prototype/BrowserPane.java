package us.pilipia.hermes.prototype;

import android.app.Activity;
import android.graphics.Color;
import android.net.http.SslError;
import android.view.Gravity;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.GeolocationPermissions;
import android.webkit.PermissionRequest;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import org.json.JSONException;
import org.json.JSONObject;
import java.io.ByteArrayInputStream;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Desktop's in-app browser pane on a phone (R1 stage 1, approved; see AGENTS.md). Desktop draws an
 * Electron &lt;webview&gt; in the pane; here each pane gets a separate native WebView laid over the
 * rectangle the page reports. Guests have no JavaScript interface, no file or content access,
 * platform TLS, no popups, downloads, file picker or permissions, and load only the pages
 * NativeHostPolicy.allowGuest admits. Requests to the Hermes server itself are refused, because its
 * pages would share the app's storage. UI thread only.
 */
final class BrowserPane {
 /** Delivers one guest event (Electron webview event name plus JSON detail) to the current page. */
 interface Host { void emit(int guest,String type,String detail); }
 /** Live guests; the oldest hidden one is closed first (the page reopens it when shown again). */
 static final int LIVE_LIMIT=3;
 private final Activity activity;
 private final FrameLayout container;
 private final Host host;
 // Access order: the eldest entry is the least recently used guest.
 private final LinkedHashMap<Integer,WebView> guests=new LinkedHashMap<>(8,0.75f,true);
 private final Map<Integer,Boolean> shown=new HashMap<>();

 BrowserPane(Activity activity,FrameLayout container,Host host){this.activity=activity;this.container=container;this.host=host;}

 /** One page request (JSON). Returns null when done, or a short message for the page. */
 String request(String json){
  final JSONObject request;
  try{request=new JSONObject(json);}catch(JSONException|RuntimeException invalid){return "Invalid browser request.";}
  String op=request.optString("op","");
  int id=request.optInt("guest",0);
  if(id<1||id>999999)return "Unknown browser tab.";
  if("create".equals(op)){create(id);return null;}
  WebView view=guests.get(id);
  if(view==null)return "destroy".equals(op)?null:"This browser tab is closed.";
  switch(op){
   case "load":
    String url=request.optString("url","");
    if(!NativeHostPolicy.allowGuest(url))return "Hermes does not open this address in its browser.";
    view.loadUrl(url);return null;
   case "back":if(view.canGoBack())view.goBack();return null;
   case "forward":if(view.canGoForward())view.goForward();return null;
   case "reload":view.reload();return null;
   case "stop":view.stopLoading();return null;
   case "bounds":place(id,view,request);return null;
   case "destroy":destroy(id,false);return null;
   default:return "Unknown browser operation.";
  }
 }

 /** Back goes to the visible browser page's history first, like a browser. */
 boolean back(){
  for(Map.Entry<Integer,WebView> entry:new ArrayList<>(guests.entrySet())){
   WebView view=entry.getValue();
   if(Boolean.TRUE.equals(shown.get(entry.getKey()))&&view.getVisibility()==View.VISIBLE&&view.canGoBack()){view.goBack();return true;}
  }
  return false;
 }
 void pause(){for(WebView view:guests.values())view.onPause();}
 void resume(){for(WebView view:guests.values())view.onResume();}
 /** A new app document (reload or server switch) or the end of the Activity: every guest goes. */
 void destroyAll(){for(Integer id:new ArrayList<>(guests.keySet()))destroy(id,false);}

 private void create(int id){
  if(guests.containsKey(id))return;
  if(guests.size()>=LIVE_LIMIT){
   Integer victim=null;
   for(Integer candidate:guests.keySet())if(!Boolean.TRUE.equals(shown.get(candidate))){victim=candidate;break;}
   if(victim==null)victim=guests.keySet().iterator().next();
   destroy(victim,true);
  }
  final WebView view=new WebView(activity);
  WebSettings settings=view.getSettings();
  settings.setJavaScriptEnabled(true);
  settings.setDomStorageEnabled(true);
  settings.setAllowFileAccess(false);
  settings.setAllowContentAccess(false);
  settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
  settings.setSaveFormData(false);
  settings.setSupportMultipleWindows(false);
  settings.setJavaScriptCanOpenWindowsAutomatically(false);
  settings.setGeolocationEnabled(false);
  settings.setMediaPlaybackRequiresUserGesture(true);
  CookieManager.getInstance().setAcceptThirdPartyCookies(view,false);
  view.setBackgroundColor(Color.WHITE);
  view.setWebViewClient(new GuestClient(id));
  view.setWebChromeClient(new GuestChrome(id));
  FrameLayout.LayoutParams params=new FrameLayout.LayoutParams(0,0,Gravity.TOP|Gravity.START);
  view.setVisibility(View.GONE);
  // Added after the app page, so it draws on top of the pane's placeholder.
  container.addView(view,params);
  guests.put(id,view);
  shown.put(id,false);
 }
 private void destroy(int id,boolean evicted){
  WebView view=guests.remove(id);
  shown.remove(id);
  if(view==null)return;
  container.removeView(view);
  view.stopLoading();
  view.destroy();
  if(evicted)host.emit(id,"evicted","{}");
 }
 private void place(int id,WebView view,JSONObject request){
  double x=request.optDouble("x",0),y=request.optDouble("y",0),w=request.optDouble("w",0),h=request.optDouble("h",0);
  boolean visible=request.optBoolean("visible",false)&&finite(x,y,w,h)&&w>=1&&h>=1;
  shown.put(id,visible);
  if(!visible){
   if(view.hasFocus())view.clearFocus();
   view.setVisibility(View.GONE);
   return;
  }
  // CSS px of the app page to device px (the page renders at device-width, scale = density).
  float density=activity.getResources().getDisplayMetrics().density;
  FrameLayout.LayoutParams params=new FrameLayout.LayoutParams(px(w,density),px(h,density),Gravity.TOP|Gravity.START);
  params.leftMargin=px(x,density);params.topMargin=px(y,density);
  view.setLayoutParams(params);
  view.setVisibility(View.VISIBLE);
 }
 private static boolean finite(double... values){for(double v:values)if(Double.isNaN(v)||Double.isInfinite(v)||v<0||v>10000)return false;return true;}
 private static int px(double css,float density){return (int)Math.round(css*density);}

 /** Event detail: the page's synchronous getters (getURL, getTitle, canGoBack/Forward) read these. */
 private void emit(int id,WebView view,String type,JSONObject extra){
  if(guests.get(id)!=view)return;
  try{
   JSONObject detail=extra==null?new JSONObject():extra;
   String url=view.getUrl();
   detail.put("pageUrl",url==null?"":url);
   String title=view.getTitle();
   detail.put("pageTitle",title==null?"":title);
   detail.put("canGoBack",view.canGoBack());
   detail.put("canGoForward",view.canGoForward());
   host.emit(id,type,detail.toString());
  }catch(JSONException ignored){/* Never fails for these values. */}
 }
 private void fail(int id,WebView view,int code,String description,String url){
  try{emit(id,view,"did-fail-load",new JSONObject().put("errorCode",code).put("errorDescription",description).put("validatedURL",url==null?"":url).put("isMainFrame",true));}
  catch(JSONException ignored){/* Never fails for these values. */}
 }
 /** WebView error codes to Chromium net error codes Desktop shows (never -3, which Desktop ignores). */
 static int netError(int code){
  switch(code){
   case WebViewClient.ERROR_HOST_LOOKUP:return -105;
   case WebViewClient.ERROR_CONNECT:return -102;
   case WebViewClient.ERROR_TIMEOUT:return -118;
   case WebViewClient.ERROR_FAILED_SSL_HANDSHAKE:return -107;
   case WebViewClient.ERROR_BAD_URL:return -300;
   case WebViewClient.ERROR_UNSUPPORTED_SCHEME:return -301;
   default:return -2;
  }
 }

 private final class GuestClient extends WebViewClient {
  private final int id;
  private String loading="";
  GuestClient(int id){this.id=id;}
  @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){
   if(!request.isForMainFrame())return false;
   String url=request.getUrl().toString();
   if(NativeHostPolicy.allowGuest(url))return false;
   // An http/https page Hermes will not show (its own server, a private address) says so;
   // other schemes (mailto:, tel:, intent:, app links) do nothing, as in Desktop's pane.
   if(NativeHostPolicy.allowExternal(url))fail(id,view,-20,"Hermes does not open this address in its browser.",url);
   return true;
  }
  @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request){
   // No guest page, frame or fetch may reach the Hermes server: it would share the app's storage.
   String url=request.getUrl().toString();
   if(sameServer(url))
    return new WebResourceResponse("text/plain","UTF-8",403,"Forbidden",new HashMap<String,String>(),new ByteArrayInputStream(new byte[0]));
   return null;
  }
  @Override public void onPageStarted(WebView view,String url,android.graphics.Bitmap favicon){loading=url==null?"":url;emit(id,view,"did-start-loading",null);}
  @Override public void onPageFinished(WebView view,String url){emit(id,view,"dom-ready",null);emit(id,view,"did-stop-loading",null);}
  @Override public void doUpdateVisitedHistory(WebView view,String url,boolean reload){
   try{emit(id,view,"did-navigate",new JSONObject().put("url",url==null?"":url));}catch(JSONException ignored){/* Never fails. */}
  }
  @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error){
   if(request.isForMainFrame())fail(id,view,netError(error.getErrorCode()),String.valueOf(error.getDescription()),request.getUrl().toString());
  }
  @Override public void onReceivedSslError(WebView view,SslErrorHandler handler,SslError error){
   // Platform TLS only: never proceed past a certificate error.
   handler.cancel();
   String url=error==null?"":error.getUrl();
   if(url!=null&&url.equals(loading))fail(id,view,-202,"The site's security certificate is not trusted.",url);
  }
  @Override public boolean onRenderProcessGone(WebView view,RenderProcessGoneDetail detail){
   if(guests.get(id)==view){
    fail(id,view,-2,"The page stopped working. Reload to try again.",view.getUrl());
    destroy(id,true);
   }
   return true;
  }
 }
 private static boolean sameServer(String url){
  try{
   java.net.URI target=new java.net.URI(url),server=new java.net.URI(NativeHostPolicy.origin());
   int port=target.getPort()==-1?("https".equalsIgnoreCase(target.getScheme())?443:80):target.getPort();
   int serverPort=server.getPort()==-1?443:server.getPort();
   return target.getHost()!=null&&target.getHost().equalsIgnoreCase(server.getHost())&&port==serverPort;
  }catch(java.net.URISyntaxException e){return false;}
 }

 private final class GuestChrome extends WebChromeClient {
  private final int id;
  GuestChrome(int id){this.id=id;}
  @Override public void onReceivedTitle(WebView view,String title){emit(id,view,"page-title-updated",null);}
  @Override public void onPermissionRequest(PermissionRequest request){request.deny();}
  @Override public void onGeolocationPermissionsShowPrompt(String origin,GeolocationPermissions.Callback callback){callback.invoke(origin,false,false);}
  @Override public boolean onShowFileChooser(WebView view,ValueCallback<android.net.Uri[]> callback,FileChooserParams params){callback.onReceiveValue(null);return true;}
  @Override public boolean onCreateWindow(WebView view,boolean dialog,boolean userGesture,android.os.Message resultMsg){return false;}
 }
}
