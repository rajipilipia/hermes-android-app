package us.pilipia.hermes.prototype;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.drawable.Icon;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

/**
 * Keeps the microphone (and the process) alive only while a Codex Live call that the user started
 * is running. The ongoing notification has an End action. Never restarts itself.
 */
public final class VoiceCallService extends Service {
 static final String END="us.pilipia.hermes.prototype.VOICE_CALL_END";
 // v2: the first channel was IMPORTANCE_LOW, so Android filed the call card under "Silent", folded with
 // its End button hidden. A channel's importance cannot be raised after creation, hence a new id.
 private static final String CHANNEL="hermes-voice-call-v2";
 private static final String OLD_CHANNEL="hermes-voice-call";
 private static final int ID=7302;
 /** Set by the Activity (UI thread). The End action calls it, then the service stops itself. */
 private static volatile Runnable onEnd;
 static void setOnEnd(Runnable action){onEnd=action;}
 @Override public void onCreate(){
  super.onCreate();
  NotificationManager manager=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);
  // DEFAULT keeps the card (and End) in the main list; no sound, no vibration. The card shows no chat text.
  NotificationChannel channel=new NotificationChannel(CHANNEL,"Hermes call",NotificationManager.IMPORTANCE_DEFAULT);
  channel.setSound(null,null);channel.enableVibration(false);channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
  manager.deleteNotificationChannel(OLD_CHANNEL);
  manager.createNotificationChannel(channel);
  Intent open=new Intent(this,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP);
  PendingIntent target=PendingIntent.getActivity(this,ID,open,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
  PendingIntent end=PendingIntent.getService(this,ID,new Intent(this,VoiceCallService.class).setAction(END),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
  Notification.Action stop=new Notification.Action.Builder(Icon.createWithResource(this,android.R.drawable.ic_menu_close_clear_cancel),"End",end).build();
  Notification card=new Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.ic_btn_speak_now)
   .setContentTitle("Hermes call").setContentText("Voice call is on. Tap to return to Hermes.")
   .setContentIntent(target).addAction(stop).setOngoing(true).setLocalOnly(true).setOnlyAlertOnce(true)
   .setVisibility(Notification.VISIBILITY_PUBLIC).setCategory(Notification.CATEGORY_CALL).build();
  if(Build.VERSION.SDK_INT>=30)startForeground(ID,card,ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
  else startForeground(ID,card);
  android.util.Log.i("HermesDiag","event=voice_call_service_start");
 }
 @Override public int onStartCommand(Intent intent,int flags,int startId){
  if(intent!=null&&END.equals(intent.getAction())){
   android.util.Log.i("HermesDiag","event=voice_call_service_end source=notification");
   Runnable action=onEnd;
   if(action!=null)new Handler(Looper.getMainLooper()).post(action);
   stopSelf();
  }
  return START_NOT_STICKY;
 }
 @Override public IBinder onBind(Intent intent){return null;}
 @Override public void onTaskRemoved(Intent rootIntent){stopSelf();}
 @Override public void onTimeout(int startId,int fgsType){android.util.Log.i("HermesDiag","event=voice_call_service_timeout");stopSelf();}
 @Override public void onDestroy(){
  stopForeground(STOP_FOREGROUND_REMOVE);
  android.util.Log.i("HermesDiag","event=voice_call_service_stop");super.onDestroy();
 }
}
