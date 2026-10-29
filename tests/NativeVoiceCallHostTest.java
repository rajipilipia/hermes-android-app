import us.pilipia.hermes.prototype.NativeVoiceCall;
public final class NativeVoiceCallHostTest {
 static int starts,stops;static boolean allowed=true;
 static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
 public static void main(String[] args){
  NativeVoiceCall call=new NativeVoiceCall(new NativeVoiceCall.Driver(){public boolean start(){starts++;return allowed;}public void stop(){stops++;}});
  check(!call.set(true,false)&&starts==0&&!call.active(),"background page started the microphone service");
  allowed=false;check(!call.set(true,true)&&!call.active()&&starts==1,"failed service was reported active");
  allowed=true;check(call.set(true,true)&&call.active()&&starts==2,"failed start latched future attempts");
  check(call.set(true,true)&&starts==2,"same call started a second service");
  check(call.set(true,false)&&starts==2&&call.active(),"background repeat dropped the running call");
  check(call.set(false,false)&&!call.active()&&stops==1,"call end did not stop the service");
  check(call.set(false,true)&&stops==1,"second end stopped the service twice");
  check(call.set(true,true)&&call.active()&&starts==3,"new call after end did not start");
  call.reset();check(!call.active()&&stops==2,"reset did not stop the service");
  check(call.set(true,true),"reset closed the owner");
  call.close();check(!call.active()&&stops==3,"close did not stop the service");
  check(!call.set(true,true)&&starts==4,"closed owner restarted the service");
  System.out.println("PASS native voice call service demand: foreground start, one service per call, stop on end/reset/close, failure recovery");
 }
}
