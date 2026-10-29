package us.pilipia.hermes.prototype;

/** UI-thread owned. One user-started Codex Live call at a time keeps the microphone service alive. */
public final class NativeVoiceCall {
 public interface Driver {boolean start();void stop();}
 private final Driver driver;
 private boolean on,closed;
 public NativeVoiceCall(Driver driver){this.driver=driver;}
 /** Start only while Hermes is on screen (Android rule); stopping is always allowed. */
 public boolean set(boolean active,boolean foreground){
  if(closed)return false;
  if(!active){if(on){on=false;driver.stop();}return true;}
  if(on)return true;
  if(!foreground||!driver.start())return false;
  on=true;return true;
 }
 public boolean active(){return on&&!closed;}
 public void reset(){set(false,false);}
 public void close(){reset();closed=true;}
}
