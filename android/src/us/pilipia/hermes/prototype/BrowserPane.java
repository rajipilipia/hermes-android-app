package us.pilipia.hermes.prototype;

import android.app.Activity;
import android.graphics.Color;
import android.net.http.SslError;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.webkit.CookieManager;
import android.webkit.ConsoleMessage;
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
 static final String EXTERNAL_AUTH="Google sign-in needs the system browser. Open the original website externally, then sign in there.";
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
 private final Map<Integer,FrameLayout> frames=new HashMap<>();
 private final Map<Integer,String> offline=new java.util.concurrent.ConcurrentHashMap<>();

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
   case "html":
    if(OfflinePreview.ORIGIN.equals(NativeHostPolicy.origin()+"/"))return "The offline preview origin cannot be the Hermes server.";
    final String document;
    try{document=OfflinePreview.document(request.getString("html"));}
    catch(JSONException|IllegalArgumentException invalid){return "Invalid or oversized offline HTML preview.";}
    offline.put(id,document);
    view.getSettings().setDomStorageEnabled(false);
    view.getSettings().setBlockNetworkLoads(true);
    view.getSettings().setCacheMode(WebSettings.LOAD_NO_CACHE);
    view.setBackgroundColor(android.graphics.Color.TRANSPARENT);
    ((GuestChrome)view.getWebChromeClient()).heights.reset();
    view.loadUrl(OfflinePreview.ORIGIN);
    return null;
   case "load":
    if(offline.containsKey(id))return "An offline preview cannot navigate to the network.";
    String url=request.optString("url","");
    if(!NativeHostPolicy.allowGuest(url))return "Hermes does not open this address in its browser.";
    if(NativeHostPolicy.requiresExternalAuthentication(url))return EXTERNAL_AUTH;
    view.loadUrl(url);return null;
   case "back":if(!offline.containsKey(id)&&view.canGoBack())view.goBack();return null;
   case "forward":if(!offline.containsKey(id)&&view.canGoForward())view.goForward();return null;
   case "reload":
    if(offline.containsKey(id)){((GuestChrome)view.getWebChromeClient()).heights.reset();view.loadUrl(OfflinePreview.ORIGIN);}
    else view.reload();
    return null;
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
   if(!offline.containsKey(entry.getKey())&&Boolean.TRUE.equals(shown.get(entry.getKey()))&&view.getVisibility()==View.VISIBLE&&view.canGoBack()){view.goBack();return true;}
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
  settings.setSupportMultipleWindows(true); // Refused explicitly by onCreateWindow below; never create a popup.
  settings.setJavaScriptCanOpenWindowsAutomatically(false);
  settings.setGeolocationEnabled(false);
  settings.setMediaPlaybackRequiresUserGesture(true);
  CookieManager.getInstance().setAcceptThirdPartyCookies(view,false);
  view.setBackgroundColor(Color.WHITE);
  view.setWebViewClient(new GuestClient(id));
  view.setWebChromeClient(new GuestChrome(id));
  view.setOnTouchListener(new View.OnTouchListener(){
   private float downX,downY,lastY;
   private boolean dragging;
   public boolean onTouch(View ignored,MotionEvent event){
    if(!offline.containsKey(id))return false;
    int action=event.getActionMasked();
    if(action==MotionEvent.ACTION_DOWN){downX=event.getRawX();downY=lastY=event.getRawY();dragging=false;return false;}
    if(action==MotionEvent.ACTION_MOVE){
     float dx=event.getRawX()-downX,dy=downY-event.getRawY();
     if(!dragging&&Math.abs(dy)>ViewConfiguration.get(activity).getScaledTouchSlop()&&Math.abs(dy)>Math.abs(dx)&&!view.canScrollVertically(dy>0?1:-1)){
      dragging=true;
      MotionEvent cancel=MotionEvent.obtain(event);cancel.setAction(MotionEvent.ACTION_CANCEL);view.onTouchEvent(cancel);cancel.recycle();
     }
     if(dragging){
      float delta=(lastY-event.getRawY())/activity.getResources().getDisplayMetrics().density;lastY=event.getRawY();
      try{emit(id,view,"preview-scroll",new JSONObject().put("dy",Math.max(-500,Math.min(500,delta))));}catch(JSONException ignoredError){}
      return true;
     }
    }
    if(action==MotionEvent.ACTION_UP||action==MotionEvent.ACTION_CANCEL){boolean wasDragging=dragging;dragging=false;return wasDragging;}
    return false;
   }
  });
  FrameLayout.LayoutParams params=new FrameLayout.LayoutParams(0,0,Gravity.TOP|Gravity.START);
  FrameLayout frame=new FrameLayout(activity);
  frame.setClipChildren(true);frame.setClipToPadding(true);
  view.setVisibility(View.GONE);
  frame.setVisibility(View.GONE);
  frame.addView(view,new FrameLayout.LayoutParams(0,0,Gravity.TOP|Gravity.START));
  // Clip the full-sized guest, rather than reflowing it into each visible slice.
  container.addView(frame,params);
  frames.put(id,frame);
  guests.put(id,view);
  shown.put(id,false);
 }
 private void destroy(int id,boolean evicted){
  WebView view=guests.remove(id);
  offline.remove(id);
  shown.remove(id);
  if(view==null)return;
  FrameLayout frame=frames.remove(id);
  if(frame!=null){frame.removeView(view);container.removeView(frame);}
  ((GuestChrome)view.getWebChromeClient()).heights.reset();
  view.stopLoading();
  view.destroy();
  if(evicted)host.emit(id,"evicted","{}");
 }
 private void place(int id,WebView view,JSONObject request){
  double x=request.optDouble("x",0),y=request.optDouble("y",0),w=request.optDouble("w",0),h=request.optDouble("h",0);
  double cw=request.optDouble("contentW",w),ch=request.optDouble("contentH",h),ox=request.optDouble("offsetX",0),oy=request.optDouble("offsetY",0);
  FrameLayout frame=frames.get(id);if(frame==null)return;
  boolean visible=request.optBoolean("visible",false)&&finite(x,y,w,h)&&w>=1&&h>=1;
  visible=visible&&finite(cw,ch,ox,oy)&&cw>=1&&ch>=1&&ch<=8192&&ox+w<=cw+2&&oy+h<=ch+2;
  shown.put(id,visible);
  if(!visible){
   if(view.hasFocus())view.clearFocus();
   view.setVisibility(View.GONE);
   frame.setVisibility(View.GONE);
   return;
  }
  // CSS px of the app page to device px (the page renders at device-width, scale = density).
  float density=activity.getResources().getDisplayMetrics().density;
  FrameLayout.LayoutParams params=new FrameLayout.LayoutParams(px(w,density),px(h,density),Gravity.TOP|Gravity.START);
  params.leftMargin=px(x,density);params.topMargin=px(y,density);
  frame.setLayoutParams(params);
  FrameLayout.LayoutParams content=new FrameLayout.LayoutParams(px(cw,density),px(ch,density),Gravity.TOP|Gravity.START);
  content.leftMargin=-px(ox,density);content.topMargin=-px(oy,density);
  view.setLayoutParams(content);
  frame.setVisibility(View.VISIBLE);
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
  private long loadVersion=0;
  GuestClient(int id){this.id=id;}
  @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){
   if(offline.containsKey(id))return true;
   if(!request.isForMainFrame())return false;
   String url=request.getUrl().toString();
   if(NativeHostPolicy.requiresExternalAuthentication(url)){loading="";fail(id,view,-20,EXTERNAL_AUTH,url);return true;}
   if(NativeHostPolicy.allowGuest(url))return false;
   // An http/https page Hermes will not show (its own server, a private address) says so;
   // other schemes (mailto:, tel:, intent:, app links) do nothing, as in Desktop's pane.
   if(NativeHostPolicy.allowExternal(url))fail(id,view,-20,"Hermes does not open this address in its browser.",url);
   return true;
  }
  @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request){
   // No guest page, frame or fetch may reach the Hermes server: it would share the app's storage.
   String url=request.getUrl().toString();
   String document=offline.get(id);
   if(document==null&&request.isForMainFrame()&&NativeHostPolicy.requiresExternalAuthentication(url)){
    view.post(()->{loading="";fail(id,view,-20,EXTERNAL_AUTH,url);});
    return new WebResourceResponse("text/plain","UTF-8",403,"Forbidden",new HashMap<String,String>(),new ByteArrayInputStream(new byte[0]));
   }
   if(document!=null&&request.isForMainFrame()&&"GET".equals(request.getMethod())&&OfflinePreview.ORIGIN.equals(url)){
    Map<String,String> headers=new HashMap<>();
    headers.put("Content-Security-Policy","sandbox allow-scripts; "+OfflinePreview.CSP);
    headers.put("Cache-Control","no-store");headers.put("Referrer-Policy","no-referrer");
    return new WebResourceResponse("text/html","UTF-8",200,"OK",headers,new ByteArrayInputStream(document.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
   }
   if(document!=null||sameServer(url))
    return new WebResourceResponse("text/plain","UTF-8",403,"Forbidden",new HashMap<String,String>(),new ByteArrayInputStream(new byte[0]));
   return null;
  }
  @Override public void onPageStarted(WebView view,String url,android.graphics.Bitmap favicon){
   loading=url==null?"":url;final long version=++loadVersion;
   emit(id,view,"did-start-loading",null);
   view.postDelayed(()->{
    if(version==loadVersion&&!loading.isEmpty()&&guests.get(id)==view){
     loading="";view.stopLoading();fail(id,view,-7,"This page did not finish loading. Retry or open the original website externally.",url);
    }
   },20000);
  }
  @Override public void onPageFinished(WebView view,String url){
   if(url==null||!url.equals(loading))return;
   loading="";emit(id,view,"dom-ready",null);emit(id,view,"did-stop-loading",null);
  }
  @Override public void doUpdateVisitedHistory(WebView view,String url,boolean reload){
   try{emit(id,view,"did-navigate",new JSONObject().put("url",url==null?"":url));}catch(JSONException ignored){/* Never fails. */}
  }
  @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error){
   if(request.isForMainFrame()){loading="";fail(id,view,netError(error.getErrorCode()),String.valueOf(error.getDescription()),request.getUrl().toString());}
  }
  @Override public void onReceivedSslError(WebView view,SslErrorHandler handler,SslError error){
   // Platform TLS only: never proceed past a certificate error.
   handler.cancel();
   String url=error==null?"":error.getUrl();
   if(url!=null&&url.equals(loading)){loading="";fail(id,view,-202,"The site's security certificate is not trusted.",url);}
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
  private final OfflinePreview.Heights heights;
  GuestChrome(int id){
   this.id=id;
   heights=new OfflinePreview.Heights(task->{WebView view=guests.get(id);if(view!=null)view.postDelayed(task,80);},height->{
    WebView view=guests.get(id);
    if(view!=null&&offline.containsKey(id))try{emit(id,view,"content-height",new JSONObject().put("height",height));}catch(JSONException ignored){}
   });
  }
  @Override public boolean onConsoleMessage(ConsoleMessage message){
   if(!offline.containsKey(id))return true;
   int height=OfflinePreview.height(message.message());
   heights.offer(height);
   return true; // Never forward arbitrary guest console text or private file contents.
  }
  @Override public void onReceivedTitle(WebView view,String title){emit(id,view,"page-title-updated",null);}
  @Override public void onPermissionRequest(PermissionRequest request){request.deny();}
  @Override public void onGeolocationPermissionsShowPrompt(String origin,GeolocationPermissions.Callback callback){callback.invoke(origin,false,false);}
  @Override public boolean onShowFileChooser(WebView view,ValueCallback<android.net.Uri[]> callback,FileChooserParams params){callback.onReceiveValue(null);return true;}
  @Override public boolean onCreateWindow(WebView view,boolean dialog,boolean userGesture,android.os.Message resultMsg){
   if(!offline.containsKey(id)&&userGesture){
    if(view.getWebViewClient() instanceof GuestClient)((GuestClient)view.getWebViewClient()).loading="";
    fail(id,view,-20,"This site requested a pop-up. Open the original website externally to continue sign-in.",view.getUrl());
   }
   return false;
  }
 }
}
