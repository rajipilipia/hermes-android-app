import java.lang.reflect.Method;

/** Pure delivery policy: document ownership is independent from native auth ownership. */
public final class NativeHostAuthEpochTest {
 private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
 public static void main(String[] args)throws Exception{
  Method policy=Class.forName("us.pilipia.hermes.prototype.NativeHostPolicy").getMethod("allowAuthCallback",
    long.class,long.class,long.class,long.class,boolean.class);
  check((Boolean)policy.invoke(null,7L,7L,1L,1L,false),"Current callback rejected");
  check(!(Boolean)policy.invoke(null,7L,7L,1L,2L,false),"Reload allowed stale-document response with the same JS id");
  check((Boolean)policy.invoke(null,7L,7L,2L,2L,false),"New-document callback rejected after reload");
  check(!(Boolean)policy.invoke(null,7L,8L,2L,2L,false),"Auth cancellation allowed stale response");
  check(!(Boolean)policy.invoke(null,7L,7L,2L,2L,true),"Destroyed Activity allowed response");
  System.out.println("PASS pure independent auth/document epochs and destruction delivery policy");
 }
}
