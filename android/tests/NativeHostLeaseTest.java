import java.lang.reflect.*;

public final class NativeHostLeaseTest {
 static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
 public static void main(String[] args)throws Exception{
  Class<?> type;
  try{type=Class.forName("us.pilipia.hermes.prototype.CallbackLease");}
  catch(ClassNotFoundException e){throw new AssertionError("Missing lifecycle-fenced callback lease");}
  Object lease=type.getConstructor().newInstance();
  Method start=type.getMethod("start",Object.class),take=type.getMethod("take",long.class),current=type.getMethod("current",long.class),invalidate=type.getMethod("invalidate"),close=type.getMethod("close");
  Object first=new Object(),second=new Object();long id=(Long)start.invoke(lease,first);
  check((Boolean)current.invoke(lease,id),"pending not current");
  check(take.invoke(lease,id+1)==null,"stale result took current callback");
  check(take.invoke(lease,id)==first,"current callback lost");
  check(take.invoke(lease,id)==null,"callback completed twice");
  long replaced=(Long)start.invoke(lease,second);
  check(replaced>id,"lease token reused");check(invalidate.invoke(lease)==second,"cancel lost callback");
  check(!(Boolean)current.invoke(lease,replaced),"cancelled callback remains current");
  long latest=(Long)start.invoke(lease,first);
  check(take.invoke(lease,replaced)==null,"late picker or runtime permission accepted");
  check(close.invoke(lease)==first,"destroy lost pending callback");
  check(close.invoke(lease)==null,"double destruction cancelled twice");
  check(take.invoke(lease,latest)==null,"destroyed callback escaped");
  try{start.invoke(lease,second);throw new AssertionError("destroyed owner admitted new callback");}
  catch(InvocationTargetException expected){check(expected.getCause() instanceof IllegalStateException,"wrong closed error");}
  System.out.println("PASS callback exactly-once/cancel/replacement/stale-result/destruction fences");
 }
}
