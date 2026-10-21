package us.pilipia.hermes.prototype;

/** One callback at a time, monotonic identity, terminal Activity destruction. */
public final class CallbackLease<T> {
 private long generation;
 private T pending;
 private boolean closed;
 public synchronized long start(T value){
  if(closed||pending!=null||value==null)throw new IllegalStateException("Callback owner unavailable");
  pending=value;return ++generation;
 }
 public synchronized boolean current(long token){return !closed&&pending!=null&&generation==token;}
 public synchronized T take(long token){
  if(!current(token))return null;T value=pending;pending=null;return value;
 }
 public synchronized T invalidate(){T value=pending;pending=null;generation++;return value;}
 public synchronized T close(){closed=true;return invalidate();}
}
