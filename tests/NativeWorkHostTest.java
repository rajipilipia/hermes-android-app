import us.pilipia.hermes.prototype.NativeWork;
public final class NativeWorkHostTest {
 static int starts,stops;static boolean allowed=true;
 static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
 public static void main(String[] args){
  NativeWork work=new NativeWork(new NativeWork.Driver(){public boolean start(){starts++;return allowed;}public void stop(){stops++;}});
  check(!work.turn(true,false)&&starts==0,"background page started work");
  check(work.turn(true,true)&&starts==1,"visible turn not protected");
  check(work.turn(true,false)&&starts==1,"same active turn restarted service");
  NativeWork.Lease first=work.signIn(true),second=work.signIn(true);
  check(first!=null&&second!=null&&starts==1,"leases started duplicate service");
  work.turn(false,false);first.close();first.close();check(stops==0,"one lease stopped another sign-in");
  second.close();check(stops==1,"last lease did not stop");
  check(work.signIn(false)==null,"background sign-in admitted");
  allowed=false;check(!work.turn(true,true),"failed service was reported active");
  allowed=true;check(work.turn(true,true),"failed start latched future attempts");
  NativeWork.Lease stale=work.signIn(true);work.reset();
  check(work.turn(true,true),"reset permanently closed demand");int before=stops;stale.close();check(stops==before,"stale sign-in stopped new work");
  work.close();check(!work.turn(true,true)&&work.signIn(true)==null,"destroyed owner restarted service");
  System.out.println("PASS bounded native work demand: foreground admission, overlapping leases, failure recovery, stale fences, cleanup");
 }
}
