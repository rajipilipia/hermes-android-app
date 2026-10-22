"""Notification-only framework fixtures. These are not Android OS implementations."""
STUBS = {
'android/Manifest.java': '''package android; public final class Manifest { public static final class permission { public static final String POST_NOTIFICATIONS="android.permission.POST_NOTIFICATIONS"; } }''',
'android/R.java': '''package android; public final class R { public static final class drawable { public static final int ic_dialog_info=17301659; } }''',
'android/content/pm/PackageManager.java': '''package android.content.pm; public class PackageManager { public static final int PERMISSION_GRANTED=0,PERMISSION_DENIED=-1; }''',
'android/content/Context.java': '''package android.content;
public class Context { public static final String NOTIFICATION_SERVICE="notification",KEYGUARD_SERVICE="keyguard"; public static final int MODE_PRIVATE=0; }
''',
'android/content/SharedPreferences.java': '''package android.content;
public interface SharedPreferences { boolean getBoolean(String k,boolean d); Editor edit(); interface Editor { Editor putBoolean(String k,boolean v); boolean commit(); } }
''',
'android/app/Activity.java': '''package android.app;
public class Activity extends android.content.Context {
 public final NotificationManager notifications=new NotificationManager(); public final KeyguardManager keyguard=new KeyguardManager();
 public int permission=-1,requests,requestCode; public String[] requested; public boolean rationale,failRequest,failSave;
 public final java.util.Map<String,Boolean> saved=new java.util.HashMap<>();
 public Object getSystemService(String name){return NOTIFICATION_SERVICE.equals(name)?notifications:KEYGUARD_SERVICE.equals(name)?keyguard:null;}
 public String getPackageName(){return "us.pilipia.hermes.prototype";}
 public int checkSelfPermission(String name){return permission;}
 public boolean shouldShowRequestPermissionRationale(String name){return rationale;}
 public void requestPermissions(String[] names,int code){if(failRequest)throw new IllegalStateException();requests++;requested=names;requestCode=code;}
 public android.content.SharedPreferences getSharedPreferences(String name,int mode){return new android.content.SharedPreferences(){
  public boolean getBoolean(String k,boolean d){return saved.getOrDefault(k,d);}
  public Editor edit(){return new Editor(){String key;boolean value;public Editor putBoolean(String k,boolean v){key=k;value=v;return this;} public boolean commit(){if(failSave)return false;saved.put(key,value);return true;}};}
 };}
}
''',
'android/app/KeyguardManager.java': '''package android.app; public class KeyguardManager { public boolean locked; public boolean isKeyguardLocked(){return locked;} }''',
'android/os/Build.java': '''package android.os; public class Build { public static final class VERSION { public static int SDK_INT=36; } }''',
'android/os/SystemClock.java': '''package android.os; public class SystemClock { public static long now=1000; public static long elapsedRealtime(){return now;} }''',
'android/os/Looper.java': '''package android.os; public class Looper { private static final Looper MAIN=new Looper(); public static Looper getMainLooper(){return MAIN;} public static Looper myLooper(){return MAIN;} }''',
'android/os/Handler.java': '''package android.os; public class Handler { public Handler(Looper l){} public boolean postDelayed(Runnable r,long ms){return true;} public void removeCallbacks(Runnable r){} public void removeCallbacksAndMessages(Object t){} }''',
'android/os/Bundle.java': '''package android.os; public class Bundle { public final java.util.Map<String,Object> values=new java.util.HashMap<>(); public java.util.Set<String> keySet(){return values.keySet();} public int size(){return values.size();} }''',
'android/content/ComponentName.java': '''package android.content; public class ComponentName { public final String name; public ComponentName(String n){name=n;} public String getClassName(){return name;} }''',
'android/net/Uri.java': '''package android.net; public class Uri { private final String value; private Uri(String v){value=v;} public static Uri parse(String v){return new Uri(v);} public String toString(){return value;} public String getSchemeSpecificPart(){return value.substring(value.indexOf(':')+1);} }''',
'android/content/Intent.java': '''package android.content;
public class Intent {
 public static final int FLAG_ACTIVITY_CLEAR_TOP=0x04000000,FLAG_ACTIVITY_SINGLE_TOP=0x20000000;
 private String action; private android.net.Uri data; private ComponentName component; private final android.os.Bundle extras=new android.os.Bundle(); public int flags;
 public Intent(){} public Intent(Context c,Class<?> cls){component=new ComponentName(cls.getName());}
 public Intent setAction(String a){action=a;return this;} public String getAction(){return action;}
 public Intent setData(android.net.Uri u){data=u;return this;} public android.net.Uri getData(){return data;}
 public Intent addFlags(int f){flags|=f;return this;} public ComponentName getComponent(){return component;}
 public Intent putExtra(String k,String v){extras.values.put(k,v);return this;} public String getStringExtra(String k){Object v=extras.values.get(k);return v instanceof String?(String)v:null;}
 public Intent removeExtra(String k){extras.values.remove(k);return this;} public android.os.Bundle getExtras(){return extras;}
 public Intent replaceExtras(android.os.Bundle b){extras.values.clear();if(b!=null)extras.values.putAll(b.values);return this;}
}
''',
'android/app/PendingIntent.java': '''package android.app;
public class PendingIntent {
 public static final int FLAG_IMMUTABLE=0x04000000,FLAG_CANCEL_CURRENT=0x10000000,FLAG_UPDATE_CURRENT=0x08000000;
 public android.content.Intent intent; public int flags,code; public boolean cancelled;
 public static PendingIntent getActivity(android.content.Context c,int code,android.content.Intent i,int flags){PendingIntent p=new PendingIntent();p.intent=i;p.flags=flags;p.code=code;return p;}
 public void cancel(){cancelled=true;}
}
''',
'android/app/NotificationChannel.java': '''package android.app;
public class NotificationChannel {
 private final String id;private final int importance; public Object sound="default";public boolean vibration=true;public int visibility;
 public NotificationChannel(String id,CharSequence name,int importance){this.id=id;this.importance=importance;}
 public String getId(){return id;} public int getImportance(){return importance;}
 public void setSound(android.net.Uri uri,android.media.AudioAttributes attrs){sound=uri;} public void enableVibration(boolean v){vibration=v;} public void setLockscreenVisibility(int v){visibility=v;}
}
''',
'android/media/AudioAttributes.java': '''package android.media; public class AudioAttributes {}''',
'android/app/NotificationManager.java': '''package android.app;
public class NotificationManager {
 public static final int IMPORTANCE_NONE=0,IMPORTANCE_LOW=2,IMPORTANCE_DEFAULT=3;
 public boolean enabled=true,failNotify;public int posts,cancels;
 public final java.util.LinkedHashMap<Integer,Notification> shown=new java.util.LinkedHashMap<>();public final java.util.Map<String,NotificationChannel> channels=new java.util.HashMap<>();
 public boolean areNotificationsEnabled(){return enabled;}
 public void createNotificationChannel(NotificationChannel c){channels.putIfAbsent(c.getId(),c);}
 public NotificationChannel getNotificationChannel(String id){return channels.get(id);}
 public void notify(String tag,int id,Notification n){if(failNotify)throw new SecurityException();posts++;shown.put(id,n);}
 public void cancel(String tag,int id){cancels++;shown.remove(id);}
}
''',
'android/app/Notification.java': '''package android.app;
public class Notification {
 public static final int VISIBILITY_SECRET=-1;public static final String CATEGORY_STATUS="status",CATEGORY_MESSAGE="msg",CATEGORY_ERROR="err";
 public String title,body,channel,category;public int icon,visibility;public long timeout;public boolean autoCancel,onlyOnce,localOnly;public Notification publicVersion;public PendingIntent contentIntent;
 public final java.util.List<Action> actions=new java.util.ArrayList<>();
 public static class Action {public String title;public PendingIntent intent;}
 public static class BigTextStyle {String text;public BigTextStyle bigText(CharSequence t){text=t.toString();return this;}}
 public static class Builder {
  private final Notification n=new Notification();public Builder(android.content.Context c,String channel){n.channel=channel;}
  public Builder setContentTitle(CharSequence v){n.title=v.toString();return this;} public Builder setContentText(CharSequence v){n.body=v.toString();return this;}
  public Builder setSmallIcon(int v){n.icon=v;return this;} public Builder setVisibility(int v){n.visibility=v;return this;}
  public Builder setPublicVersion(Notification v){n.publicVersion=v;return this;} public Builder setContentIntent(PendingIntent v){n.contentIntent=v;return this;}
  public Builder setAutoCancel(boolean v){n.autoCancel=v;return this;} public Builder setOnlyAlertOnce(boolean v){n.onlyOnce=v;return this;} public Builder setLocalOnly(boolean v){n.localOnly=v;return this;}
  public Builder setTimeoutAfter(long v){n.timeout=v;return this;} public Builder setCategory(String v){n.category=v;return this;}
  public Builder setStyle(BigTextStyle v){return this;}
  public Builder addAction(int icon,CharSequence title,PendingIntent intent){Action a=new Action();a.title=title.toString();a.intent=intent;n.actions.add(a);return this;}
  public Notification build(){return n;}
 }
}
''',
'us/pilipia/hermes/prototype/MainActivity.java': '''package us.pilipia.hermes.prototype; public final class MainActivity extends android.app.Activity {}''',
}
