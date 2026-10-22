package us.pilipia.hermes.prototype;

import java.util.HashSet;
import java.util.Set;

/** UI-thread owned, bounded service demand. No network, credentials, or persisted state. */
public final class NativeWork {
 public interface Driver {boolean start();void stop();}
 private final Driver driver;
 private final Set<Object> signIns=new HashSet<>();
 private boolean turn,running,closed;
 public NativeWork(Driver driver){this.driver=driver;}
 private boolean sync(){
  boolean wanted=!closed&&(turn||!signIns.isEmpty());
  if(wanted&&!running){if(!driver.start())return false;running=true;}
  else if(!wanted&&running){running=false;driver.stop();}
  return true;
 }
 public boolean turn(boolean active,boolean foreground){
  if(closed||active&&!turn&&!foreground)return false;
  boolean before=turn;turn=active;
  if(!sync()){turn=before;return false;}
  return true;
 }
 public final class Lease implements AutoCloseable {
  private final Object key;
  private Lease(Object key){this.key=key;}
  @Override public void close(){if(signIns.remove(key))sync();}
 }
 public Lease signIn(boolean foreground){
  if(closed||!foreground)return null;
  Object key=new Object();signIns.add(key);
  if(!sync()){signIns.remove(key);return null;}
  return new Lease(key);
 }
 public void resume(){if(!closed&&running&&!driver.start()){running=false;}}
 public void reset(){turn=false;signIns.clear();sync();}
 public void close(){closed=true;reset();}
}
