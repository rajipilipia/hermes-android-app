package us.pilipia.hermes.prototype;

import android.app.Activity;
import android.app.AlertDialog;

/** Native confirmation before the app connects to, or forgets, a server. Page JS cannot answer it. */
final class ServerDialogs {
 private ServerDialogs(){}
 static void confirm(Activity activity,String title,String message,String action,Runnable accepted,Runnable cancelled){
  new AlertDialog.Builder(activity).setTitle(title).setMessage(message)
   .setPositiveButton(action,(dialog,which)->accepted.run())
   .setNegativeButton("Cancel",(dialog,which)->cancelled.run())
   .setOnCancelListener(dialog->cancelled.run())
   .show();
 }
}
