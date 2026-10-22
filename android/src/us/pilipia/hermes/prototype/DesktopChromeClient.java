package us.pilipia.hermes.prototype;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebView;
import android.webkit.MimeTypeMap;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.Future;

/** Standard Android browser callbacks, never an authenticated network or filesystem bridge. */
public final class DesktopChromeClient extends WebChromeClient {
 public interface Host {
  boolean active(); boolean page(); WebView web(); ViewGroup container();
  default String notification(String operation,org.json.JSONObject payload){return "{\"ok\":false}";}
  default boolean work(boolean active){return false;}
 }
 private final Activity activity;
 private final Host host;
 private final LocalDocuments documents;
 private final Handler ui=new Handler(Looper.getMainLooper());
 private final ThreadPoolExecutor files=fileExecutor();
 private static ThreadPoolExecutor fileExecutor(){
  ThreadPoolExecutor executor=new ThreadPoolExecutor(1,1,30,TimeUnit.SECONDS,new ArrayBlockingQueue<Runnable>(1),task->{
   Thread thread=new Thread(task,"desktop-file-picker");thread.setDaemon(true);return thread;
  });
  executor.allowCoreThreadTimeOut(true);return executor;
 }
 private final CallbackLease<Picker> pickers=new CallbackLease<>();
 private final CallbackLease<Microphone> microphones=new CallbackLease<>();
 private Picker picker;
 private Microphone microphone;
 private boolean closed;
 private static final java.util.concurrent.atomic.AtomicInteger NEXT_CODE=new java.util.concurrent.atomic.AtomicInteger(1024);
 private View customView;
 private CustomViewCallback customCallback;
 private static final long CALLBACK_TIMEOUT=120000;
 private static final class Picker {
  final ValueCallback<Uri[]> callback;final boolean multiple;final int code;
  long lease;Future<?> task;Uri[] result;boolean ready;Runnable timeout;
  Picker(ValueCallback<Uri[]> callback,boolean multiple,int code){this.callback=callback;this.multiple=multiple;this.code=code;}
 }
 private static final class Microphone {
  final PermissionRequest request;final int code;long lease;
  Microphone(PermissionRequest request,int code){this.request=request;this.code=code;}
 }
 public DesktopChromeClient(Activity activity,Host host){this.activity=activity;this.host=host;documents=new LocalDocuments(activity);}
 @Override public boolean onJsPrompt(WebView view,String url,String message,String value,android.webkit.JsPromptResult result){
  // All prompts are consumed, never an arbitrary native operation or a system dialog.
  String reply="{\"ok\":false}";
  if(!closed&&view==host.web()&&host.page()&&NativeHostPolicy.isAppPage(url)
    &&value!=null&&value.length()<=20000){
   try{
    org.json.JSONObject envelope=new org.json.JSONObject(value);
    if("hermes.android.work.v1".equals(message)){
     if(envelope.length()==1&&envelope.opt("active") instanceof Boolean)
      reply=host.work(envelope.getBoolean("active"))?"{\"ok\":true}":"{\"ok\":false}";
    }else if("hermes.android.notifications.v1".equals(message)){
     String operation=envelope.getString("operation");
     if(envelope.length()==2&&envelope.has("payload")&&java.util.Arrays.asList("show","cancel","status","request","take").contains(operation))
      reply=host.notification(operation,envelope.getJSONObject("payload"));
    }
   }catch(Exception invalid){/* Fail closed; no raw payload logging. */}
  }
  result.confirm(reply);return true;
 }
 private int code(){int value=NEXT_CODE.getAndIncrement();if(value>=32767)throw new IllegalStateException("Native request capacity reached");return value;}
 // Verbose, structural-only logging for phone debugging: never URIs, names or content.
 private static void log(String line){android.util.Log.i("HermesDiag",line);}
 @Override public boolean onConsoleMessage(android.webkit.ConsoleMessage message){
  if(message==null)return false;
  String text=message.message();
  if(text==null)return false;
  // Page-side structural diagnostics and errors are copied to logcat (bounded, one line).
  if(text.startsWith("[hermes-diag]")||message.messageLevel()==android.webkit.ConsoleMessage.MessageLevel.ERROR||message.messageLevel()==android.webkit.ConsoleMessage.MessageLevel.WARNING){
    String line=text.replaceAll("[\\r\\n]+"," ").replaceAll("[A-Za-z0-9_\\-+/=]{40,}","[redacted]");
    if(line.length()>400)line=line.substring(0,400);
    log("js level="+message.messageLevel()+" "+line);
  }
  return false;
 }
 @Override public boolean onShowFileChooser(WebView view,ValueCallback<Uri[]> callback,FileChooserParams params){
  log("event=picker_request mode="+(params==null?-1:params.getMode())+" closed="+closed+" active="+host.active());
  cancelPicker();
  if(closed||view!=host.web()||!host.active()||params==null||
    (params.getMode()!=FileChooserParams.MODE_OPEN&&params.getMode()!=FileChooserParams.MODE_OPEN_MULTIPLE)){
   callback.onReceiveValue(null);return true;
  }
  try{
   final Picker current=new Picker(callback,params.getMode()==FileChooserParams.MODE_OPEN_MULTIPLE,code());
   current.lease=pickers.start(current);picker=current;
   // Never honor camera/capture intents or broad filesystem paths. Only explicit per-item documents.
   Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE);
   List<String> types=acceptedTypes(params.getAcceptTypes());
   intent.setType(types.size()==1?types.get(0):"*/*");
   if(types.size()>1)intent.putExtra(Intent.EXTRA_MIME_TYPES,types.toArray(new String[0]));
   intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,current.multiple);
   intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
   activity.startActivityForResult(intent,current.code);
   current.timeout=()->{if(picker==current)cancelPicker();};
   ui.postDelayed(current.timeout,CALLBACK_TIMEOUT);
  }catch(RuntimeException failure){if(picker!=null)cancelPicker();else callback.onReceiveValue(null);}
  return true;
 }
 private static List<String> acceptedTypes(String[] values){
  List<String> result=new ArrayList<>();
  if(values!=null)for(String value:values){
   if(result.size()>=16)break;
   if(value==null)continue;
   for(String token:value.split(",")){
    String type=token.trim().toLowerCase(java.util.Locale.ROOT);
    if(type.startsWith("."))type=MimeTypeMap.getSingleton().getMimeTypeFromExtension(type.substring(1));
    if(type!=null&&type.length()<=127&&type.matches("(?:[a-z0-9!#$&^_.+\\-]+|\\*)/(?:[a-z0-9!#$&^_.+\\-]+|\\*)")&&!result.contains(type))result.add(type);
    if(result.size()>=16)break;
   }
  }
  if(result.isEmpty())result.add("*/*");return result;
 }
 public boolean onActivityResult(int requestCode,int resultCode,Intent data){
  final Picker current=picker;
  if(current==null||current.code!=requestCode)return false;
  if(current.task!=null||current.ready)return true; // Each result owner admits work only once.
  log("event=picker_result result_ok="+(resultCode==Activity.RESULT_OK)+" has_data="+(data!=null)+" closed="+closed+" page="+host.page());
  if(resultCode!=Activity.RESULT_OK||data==null||closed||!host.page()){cancelPicker();return true;}
  try{
   current.task=files.submit(()->{
    Uri[] selected=null;
    try{selected=documents.stage(data,current.multiple);}catch(Exception failure){/* No URI/content/filename in logs: class name only. */log("event=picker_stage_failed error="+failure.getClass().getSimpleName());}
    log("event=picker_staged count="+(selected==null?0:selected.length));
    final Uri[] safe=selected;
    ui.post(()->{if(picker==current&&pickers.current(current.lease)){current.result=safe;current.ready=true;deliverPicker();}});
   });
  }catch(RuntimeException failure){cancelPicker();}
  return true;
 }
 private void deliverPicker(){
  Picker current=picker;
  // Activity results can precede onResume. Do not deliver to a background/different document.
  if(current==null||!current.ready||!host.active())return;
  if(pickers.take(current.lease)!=current)return;
  picker=null;ui.removeCallbacks(current.timeout);
  log("event=picker_deliver count="+(current.result==null?0:current.result.length));
  current.callback.onReceiveValue(current.result);
 }
 private void cancelPicker(){
  Picker old=pickers.invalidate();picker=null;
  if(old!=null)log("event=picker_cancel");
  if(old!=null){ui.removeCallbacks(old.timeout);if(old.task!=null){old.task.cancel(true);files.remove((Runnable)old.task);}old.callback.onReceiveValue(null);}
 }
 @Override public void onPermissionRequest(PermissionRequest request){
  denyMicrophone();
  if(closed||!host.active()||!NativeHostPolicy.allowAudio(host.web().getUrl(),request.getOrigin().toString(),request.getResources())){
   request.deny();return;
  }
  try{
   final Microphone current=new Microphone(request,code());
   current.lease=microphones.start(current);microphone=current;
   if(activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED){completeMicrophone(current,true);return;}
   activity.requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO},current.code);
   ui.postDelayed(()->{if(microphone==current)denyMicrophone();},CALLBACK_TIMEOUT);
  }catch(RuntimeException failure){if(microphone!=null)denyMicrophone();else request.deny();}
 }
 public boolean onRequestPermissionsResult(int requestCode,String[] permissions,int[] grants){
  Microphone current=microphone;
  if(current==null||current.code!=requestCode)return false;
  boolean granted=permissions.length==1&&grants.length==1&&Manifest.permission.RECORD_AUDIO.equals(permissions[0])
    &&grants[0]==PackageManager.PERMISSION_GRANTED&&activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED;
  completeMicrophone(current,granted);return true;
 }
 private void completeMicrophone(Microphone current,boolean granted){
  if(microphones.take(current.lease)!=current)return;microphone=null;
  if(granted&&!closed&&host.active()&&NativeHostPolicy.allowAudio(host.web().getUrl(),current.request.getOrigin().toString(),current.request.getResources()))
   current.request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
  else current.request.deny();
 }
 private void denyMicrophone(){Microphone old=microphones.invalidate();microphone=null;if(old!=null)old.request.deny();}
 @Override public void onPermissionRequestCanceled(PermissionRequest request){
  if(microphone!=null&&microphone.request==request){microphones.invalidate();microphone=null;}
 }
 @Override public void onGeolocationPermissionsShowPrompt(String origin,android.webkit.GeolocationPermissions.Callback callback){callback.invoke(origin,false,false);}
 @Override public void onShowCustomView(View view,CustomViewCallback callback){
  if(closed||customView!=null||!host.active()){callback.onCustomViewHidden();return;}
  customView=view;customCallback=callback;
  host.container().addView(view,new ViewGroup.LayoutParams(-1,-1));host.web().setVisibility(View.INVISIBLE);
 }
 @Override public void onHideCustomView(){hideCustomView();}
 public boolean hideCustomView(){
  if(customView==null)return false;
  host.container().removeView(customView);customView=null;
  if(host.web()!=null)host.web().setVisibility(View.VISIBLE);
  CustomViewCallback old=customCallback;customCallback=null;if(old!=null)old.onCustomViewHidden();return true;
 }
 public void resume(){if(!closed){deliverPicker();LocalDocuments.cleanup(activity);}}
 public void pause(){denyMicrophone();hideCustomView();}
 public void documentChanged(){cancelPicker();denyMicrophone();hideCustomView();}
 public void destroy(){
  if(closed)return;closed=true;cancelPicker();denyMicrophone();hideCustomView();
  pickers.close();microphones.close();files.shutdownNow();ui.removeCallbacksAndMessages(null);
 }
}
