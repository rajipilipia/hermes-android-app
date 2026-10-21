package us.pilipia.hermes.prototype;

import android.Manifest;
import android.app.Activity;
import android.app.NotificationManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.PendingIntent;
import android.content.Intent;
import android.net.Uri;
import android.os.SystemClock;
import org.json.JSONArray;
import java.net.URI;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import java.util.LinkedHashMap;
import java.util.Iterator;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import org.json.JSONObject;
import java.util.concurrent.atomic.AtomicInteger;

/** UI-thread only; the caller must authenticate the exact bundled document.
 * No auth/network bridge, persisted routes, chat logging or approval execution.
 */
public final class NativeNotifications {
 private static final String PERMISSION=Manifest.permission.POST_NOTIFICATIONS;
 private static final AtomicInteger NEXT_PERMISSION=new AtomicInteger(40000);
 private static final AtomicInteger NEXT_NOTIFICATION=new AtomicInteger(1);
 private static final String OS_TAG="hermes.native.notifications.v1";
 private static final String OPEN_ACTION="us.pilipia.hermes.prototype.NOTIFICATION_OPEN";
 private static final String TOKEN_PREFIX="hermes-notification:";
 private static final String NORMAL_CHANNEL="hermes.notifications.v1",QUIET_CHANNEL="hermes.notifications.quiet.v1";
 private static final long TTL=86400000L;
 private static final Set<String> FIELDS=names("kind","title","body","silent","sessionId","focusSessionId","tag","notifyId","actions","icon","activate","route");
 private static final Set<String> ROUTE_FIELDS=names("profile","sessionId","storedSessionId","activate");
 private static final Set<String> ACTION_FIELDS=names("id","text","activate");
 private static final Set<String> KINDS=names("approval","input","turnDone","turnError","backgroundDone","credits","plugin");
 private final SecureRandom random=new SecureRandom();
 private final LinkedHashMap<String,Entry> entries=new LinkedHashMap<>();
 private static final class Entry {
  final int id;final String route,key,notifyId,tag;final long expires;final PendingIntent intent;
  Entry(int id,String route,String key,String notifyId,String tag,long expires,PendingIntent intent){this.id=id;this.route=route;this.key=key;this.notifyId=notifyId;this.tag=tag;this.expires=expires;this.intent=intent;}
 }
 private final Activity activity;
 private final NotificationManager manager;
 // Manifest disables backup. This nonsecret flag is the only persistent state.
 private final SharedPreferences preferences;
 private int pendingPermission;
 private Entry pendingTap;
 private boolean closed;
 public NativeNotifications(Activity activity){
  this.activity=activity;
  manager=(NotificationManager)activity.getSystemService(Context.NOTIFICATION_SERVICE);
  preferences=activity.getSharedPreferences("native-notifications",Context.MODE_PRIVATE);
 }
 public String request(String operation,JSONObject payload,boolean active){
  try{
   if(closed||payload==null)return result(false,null);
   prune();
   if("show".equals(operation))return result(show(payload),null);
   if("cancel".equals(operation))return result(cancelMatching(payload),null);
   if(payload.length()!=0)return result(false,null);
   if("take".equals(operation))return take(active);
   if("status".equals(operation))return result(true,permission());
   if("request".equals(operation)){
    if(!active)return result(false,permission());
    String status=permission();
    if(!"not-requested".equals(status))return result("granted".equals(status)||"requested".equals(status),status);
    int code=NEXT_PERMISSION.getAndIncrement();
    if(code>65534||!preferences.edit().putBoolean("asked",true).commit())return result(false,permission());
    pendingPermission=code;
    try{activity.requestPermissions(new String[]{PERMISSION},code);}
    catch(RuntimeException failure){pendingPermission=0;return result(false,permission());}
    return result(true,"requested");
   }
  }catch(RuntimeException failure){return result(false,null);}
  return result(false,null);
 }
 /** The JS host polls take after focus/resume; this controller never evaluates script. */
 public void resume(){if(!closed)prune();}
 /** Must be called on every main-document replacement and account/owner change. */
 public void invalidate(){
  pendingTap=null;pendingPermission=0;
  for(Entry entry:entries.values())cancel(entry);
  entries.clear();
 }
 public void destroy(){if(closed)return;invalidate();closed=true;}
 private void prune(){
  long now=SystemClock.elapsedRealtime();
  Iterator<Entry> it=entries.values().iterator();
  while(it.hasNext()){Entry e=it.next();if(e.expires<=now){it.remove();cancel(e);}}
  if(pendingTap!=null&&pendingTap.expires<=now)pendingTap=null;
 }
 private boolean cancelMatching(JSONObject payload){
  if(!fields(payload,names("notifyId","tag"))||!text(payload,"notifyId",256,payload.has("notifyId"))
   ||!text(payload,"tag",256,payload.has("tag")))return false;
  Iterator<Entry> it=entries.values().iterator();
  while(it.hasNext()){Entry e=it.next();if(matches(e,payload)){it.remove();cancel(e);}}
  if(pendingTap!=null&&matches(pendingTap,payload))pendingTap=null;
  return true;
 }
 private static boolean matches(Entry entry,JSONObject p){return (!p.has("notifyId")||entry.notifyId.equals(p.optString("notifyId")))&&(!p.has("tag")||entry.tag.equals(p.optString("tag")));}
 public void acceptIntent(Intent intent){
  if(intent==null||!OPEN_ACTION.equals(intent.getAction()))return;
  try{
   if(closed)return;
   prune();
   Uri data=intent.getData();String raw=data==null?"":data.toString();
   if(!raw.matches("hermes-notification:[a-f0-9]{64}"))return;
   Entry entry=entries.remove(raw.substring(TOKEN_PREFIX.length()));
   if(entry!=null){cancel(entry);pendingTap=entry;}
  }finally{
   // Never leave a replayable capability or foreign owner/action extras on Activity.getIntent().
   intent.setAction(null);intent.setData(null);intent.replaceExtras((android.os.Bundle)null);
  }
 }
 private String take(boolean active){
  android.app.KeyguardManager keyguard=(android.app.KeyguardManager)activity.getSystemService(Context.KEYGUARD_SERVICE);
  if(!active||pendingTap==null||keyguard==null||keyguard.isKeyguardLocked())return result(false,null);
  Entry entry=pendingTap;pendingTap=null;
  try{return new JSONObject().put("ok",true).put("route",new JSONObject(entry.route)).toString();}
  catch(org.json.JSONException invalid){return result(false,null);}
 }
 private boolean show(JSONObject payload){
  if(!validNotification(payload)||!"granted".equals(permission()))return false;
  PendingIntent capability=null;
  try{
   String kind=payload.getString("kind"),title=payload.optString("title","Hermes"),body=payload.optString("body","");
   JSONObject route=payload.getJSONObject("route");
   String key=new JSONArray().put(payload.optString("tag","")).put(route.getString("profile"))
    .put(route.optString("sessionId","")).put(route.optString("storedSessionId","")).put(kind).toString();
   boolean silent=payload.optBoolean("silent",false);
   String channel=silent?QUIET_CHANNEL:NORMAL_CHANNEL;
   NotificationChannel normal=new NotificationChannel(NORMAL_CHANNEL,"Hermes notifications",NotificationManager.IMPORTANCE_DEFAULT);
   normal.setLockscreenVisibility(Notification.VISIBILITY_SECRET);
   NotificationChannel quiet=new NotificationChannel(QUIET_CHANNEL,"Hermes quiet notifications",NotificationManager.IMPORTANCE_LOW);
   quiet.setSound(null,null);quiet.enableVibration(false);quiet.setLockscreenVisibility(Notification.VISIBILITY_SECRET);
   manager.createNotificationChannel(normal);manager.createNotificationChannel(quiet);
   NotificationChannel current=manager.getNotificationChannel(channel);
   if(current==null||current.getImportance()==NotificationManager.IMPORTANCE_NONE)return false;
   String token=token();int id=NEXT_NOTIFICATION.getAndIncrement();if(id<=0)return false;
   Intent open=new Intent(activity,MainActivity.class).setAction(OPEN_ACTION).setData(Uri.parse(TOKEN_PREFIX+token))
    .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP);
   capability=PendingIntent.getActivity(activity,id,open,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_CANCEL_CURRENT);
   Notification generic=new Notification.Builder(activity,channel).setSmallIcon(android.R.drawable.ic_dialog_info)
    .setContentTitle("Hermes").setContentText("Open Hermes to review an update.").setVisibility(Notification.VISIBILITY_SECRET).build();
   Notification.Builder builder=new Notification.Builder(activity,channel).setSmallIcon(android.R.drawable.ic_dialog_info)
    .setContentTitle(title).setContentText(body).setVisibility(Notification.VISIBILITY_SECRET).setPublicVersion(generic)
    .setContentIntent(capability).setAutoCancel(true).setOnlyAlertOnce(true).setLocalOnly(true).setTimeoutAfter(TTL)
    .setCategory("turnError".equals(kind)?Notification.CATEGORY_ERROR:Notification.CATEGORY_STATUS);
   if(payload.has("actions")&&payload.getJSONArray("actions").length()>0)
    builder.addAction(android.R.drawable.ic_dialog_info,"Review",capability);
   // The only button is navigation. Never retain/echo action IDs or callbacks.
   manager.notify(OS_TAG,id,builder.build());
   Iterator<Entry> old=entries.values().iterator();
   while(old.hasNext()){Entry e=old.next();if(e.key.equals(key)){old.remove();cancel(e);}}
   entries.put(token,new Entry(id,route.toString(),key,payload.optString("notifyId",""),payload.optString("tag",""),SystemClock.elapsedRealtime()+TTL,capability));
   while(entries.size()>32){Iterator<Entry> oldest=entries.values().iterator();Entry e=oldest.next();oldest.remove();cancel(e);}
   return true;
  }catch(Exception failure){if(capability!=null)capability.cancel();return false;}
 }
 private void cancel(Entry entry){
  entry.intent.cancel();
  try{if(manager!=null)manager.cancel(OS_TAG,entry.id);}catch(RuntimeException ignored){/* Revoked route stays inert even if OS cancellation fails. */}
 }
 private String token(){byte[] bytes=new byte[32];random.nextBytes(bytes);StringBuilder out=new StringBuilder(64);for(byte b:bytes){out.append(Character.forDigit((b>>>4)&15,16));out.append(Character.forDigit(b&15,16));}return out.toString();}
 private static Set<String> names(String... values){return new HashSet<>(Arrays.asList(values));}
 private static boolean fields(JSONObject object,Set<String> allowed){
  Iterator<String> keys=object.keys();while(keys.hasNext())if(!allowed.contains(keys.next()))return false;return true;
 }
 private static boolean text(JSONObject object,String key,int limit,boolean required){
  if(!object.has(key))return !required;Object value=object.opt(key);
  return value instanceof String&&((String)value).length()<=limit&&(!required||!((String)value).isEmpty())&&((String)value).indexOf('\0')<0;
 }
 private static boolean identifier(JSONObject object,String key,int limit,boolean required){
  if(!object.has(key))return !required;
  return text(object,key,limit,true)&&object.optString(key).matches("[A-Za-z0-9][A-Za-z0-9._:@-]*");
 }
 private static boolean target(JSONObject object,String key){
  if(!object.has(key))return true;
  if(!text(object,key,1024,true))return false;
  String raw=object.optString(key);
  try{
   URI uri=new URI(raw);String path=uri.getPath(),query=uri.getQuery();
   if(uri.isAbsolute()||uri.getRawAuthority()!=null||uri.getRawFragment()!=null||path==null||!path.startsWith("/")||path.startsWith("//"))return false;
   String decoded=path+(query==null?"":query);
   for(int i=0;i<decoded.length();i++)if(decoded.charAt(i)<32||decoded.charAt(i)==127||decoded.charAt(i)=='\\')return false;
   for(String part:path.split("/"))if(part.equals(".")||part.equals(".."))return false;
   // Do not permit nested URL decoding to turn a local route into a URL/path escape.
   return decoded.indexOf('%')<0;
  }catch(Exception invalid){return false;}
 }
 private static boolean validNotification(JSONObject p){
  try{
   if(p.toString().length()>16384||!fields(p,FIELDS)||!text(p,"kind",32,true)||!KINDS.contains(p.getString("kind"))
    ||!text(p,"title",256,false)||!text(p,"body",4096,false)||!text(p,"icon",1024,false)
    ||!text(p,"notifyId",256,false)||!text(p,"tag",256,false)||!identifier(p,"sessionId",256,false)
    ||!identifier(p,"focusSessionId",256,false)||!target(p,"activate")
    ||p.has("silent")&&!(p.opt("silent") instanceof Boolean))return false;
   Object value=p.opt("route");if(!(value instanceof JSONObject))return false;JSONObject route=(JSONObject)value;
   if(!fields(route,ROUTE_FIELDS)||!identifier(route,"profile",128,true)||!identifier(route,"sessionId",256,false)
    ||!identifier(route,"storedSessionId",256,false)||!target(route,"activate"))return false;
   if(p.has("actions")){
    Object actions=p.opt("actions");if(!(actions instanceof JSONArray)||((JSONArray)actions).length()>4)return false;
    for(int i=0;i<((JSONArray)actions).length();i++){
     Object action=((JSONArray)actions).opt(i);if(!(action instanceof JSONObject))return false;JSONObject a=(JSONObject)action;
     if(!fields(a,ACTION_FIELDS)||!text(a,"id",256,true)||!text(a,"text",80,true)||!target(a,"activate"))return false;
    }
   }
   return true;
  }catch(Exception invalid){return false;}
 }
 private String permission(){
  if(manager==null)return "blocked";
  if(Build.VERSION.SDK_INT>=33&&activity.checkSelfPermission(PERMISSION)!=PackageManager.PERMISSION_GRANTED){
   if(pendingPermission!=0)return "requested";
   if(!preferences.getBoolean("asked",false))return "not-requested";
   return activity.shouldShowRequestPermissionRationale(PERMISSION)?"denied":"blocked";
  }
  return manager.areNotificationsEnabled()?"granted":"blocked";
 }
 public boolean onRequestPermissionsResult(int code,String[] permissions,int[] grants){
  if(pendingPermission==0||code!=pendingPermission)return false;
  pendingPermission=0;return true; // Re-read OS permission on the next status; never trust intent/callback data.
 }
 private static String result(boolean ok,String permission){
  try{JSONObject out=new JSONObject().put("ok",ok);if(permission!=null)out.put("permission",permission);return out.toString();}
  catch(org.json.JSONException impossible){return "{\"ok\":false}";}
 }
}
