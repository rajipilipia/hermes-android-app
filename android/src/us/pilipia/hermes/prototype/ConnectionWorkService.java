package us.pilipia.hermes.prototype;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

/** Keeps only user-initiated sign-in/reply transport alive. Never restarts itself. */
public final class ConnectionWorkService extends Service {
 private static final String CHANNEL="hermes-active-work";
 private static final int ID=7301;
 private static final long LIMIT_MS=30*60*1000L;
 private final Handler timer=new Handler(Looper.getMainLooper());
 private final Runnable expire=()->{android.util.Log.i("HermesDiag","event=work_service_timeout");stopSelf();};
 @Override public void onCreate(){
  super.onCreate();
  NotificationManager manager=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);
  NotificationChannel channel=new NotificationChannel(CHANNEL,"Active Hermes connection",NotificationManager.IMPORTANCE_LOW);
  channel.setSound(null,null);channel.enableVibration(false);channel.setLockscreenVisibility(Notification.VISIBILITY_SECRET);
  manager.createNotificationChannel(channel);
  Intent open=new Intent(this,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP);
  PendingIntent target=PendingIntent.getActivity(this,ID,open,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
  Notification card=new Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.ic_dialog_info)
   .setContentTitle("Hermes connection active").setContentText("Finishing sign-in or a reply. Tap to return to Hermes.")
   .setContentIntent(target).setOngoing(true).setLocalOnly(true).setOnlyAlertOnce(true)
   .setVisibility(Notification.VISIBILITY_SECRET).setCategory(Notification.CATEGORY_SERVICE).build();
  if(Build.VERSION.SDK_INT>=29)startForeground(ID,card,ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
  else startForeground(ID,card);
  android.util.Log.i("HermesDiag","event=work_service_start");
 }
 @Override public int onStartCommand(Intent intent,int flags,int startId){
  timer.removeCallbacks(expire);timer.postDelayed(expire,LIMIT_MS);
  return START_NOT_STICKY;
 }
 @Override public IBinder onBind(Intent intent){return null;}
 @Override public void onTaskRemoved(Intent rootIntent){stopSelf();}
 @Override public void onTimeout(int startId,int fgsType){stopSelf();}
 @Override public void onDestroy(){
  timer.removeCallbacks(expire);stopForeground(STOP_FOREGROUND_REMOVE);
  android.util.Log.i("HermesDiag","event=work_service_stop");super.onDestroy();
 }
}
