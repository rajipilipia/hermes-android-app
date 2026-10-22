import org.json.JSONArray;
import org.json.JSONObject;
import us.pilipia.hermes.prototype.NativeAuth;
import us.pilipia.hermes.prototype.ServerProbe;
import java.io.IOException;
import java.util.*;

/** The real ServerProbe: Desktop's probe result from /api/status and /api/auth/providers. */
public final class ServerProbeHostTest {
 static final String SERVER="https://gateway.example.com";
 static void check(boolean b,String message){if(!b)throw new AssertionError(message);}
 static void pause(long ms){try{Thread.sleep(ms);}catch(InterruptedException e){throw new IllegalStateException(e);}}
 static long ms(long started){return (System.nanoTime()-started)/1000000;}
 static Map<String,Object> status(boolean gated,String... flows){
  Map<String,Object> m=new HashMap<>();m.put("auth_required",gated);m.put("version","0.22.0");m.put("auth_flows",new JSONArray(Arrays.asList(flows)));return m;
 }
 static Map<String,Object> providers(){
  Map<String,Object> m=new HashMap<>();
  m.put("providers",new JSONArray().put(new JSONObject().put("name","nous").put("display_name","Nous Research")).put(new JSONObject().put("name","")));
  return m;
 }
 public static void main(String[] args)throws Exception{
  JSONObject ok=new JSONObject(ServerProbe.run(path->"/api/status".equals(path)?status(true,"native_pkce"):providers(),SERVER));
  check(ok.getBoolean("reachable")&&"oauth".equals(ok.getString("authMode"))&&ok.isNull("error"),"gated native server: "+ok);
  check("0.22.0".equals(ok.getString("version"))&&ok.getJSONArray("providers").length()==1,"version/providers: "+ok);
  check("Nous Research".equals(ok.getJSONArray("providers").getJSONObject(0).getString("displayName")),"display name: "+ok);

  check(new JSONObject(ServerProbe.run(path->status(true),SERVER)).getString("error").contains("native_pkce"),"no native flow");
  check(new JSONObject(ServerProbe.run(path->status(false),SERVER)).getString("error").contains("no sign-in gate"),"ungated");

  JSONObject http=new JSONObject(ServerProbe.run(path->{throw new NativeAuth.HttpFailure(404);},SERVER));
  check(!http.getBoolean("reachable")&&http.getString("error").contains("HTTP 404"),"http failure: "+http);

  // One retry on a network failure while the typed address is still current; none once it is stale.
  int[] calls={0};
  ServerProbe.Reader flaky=path->{if("/api/status".equals(path)&&calls[0]++==0)throw new IOException("reset");return "/api/status".equals(path)?status(true,"native_pkce"):providers();};
  check(new JSONObject(ServerProbe.run(flaky,SERVER,()->true)).getBoolean("reachable")&&calls[0]==2,"retry once");
  calls[0]=0;
  JSONObject stale=new JSONObject(ServerProbe.run(flaky,SERVER,()->false));
  check(!stale.getBoolean("reachable")&&calls[0]==1&&stale.getString("error").contains("gateway.example.com"),"stale: no retry "+stale);
  // A timeout already used the whole wait (NG-2 G4): no second try.
  calls[0]=0;
  JSONObject slow=new JSONObject(ServerProbe.run(path->{calls[0]++;throw new java.net.SocketTimeoutException("Read timed out");},SERVER,()->true));
  check(!slow.getBoolean("reachable")&&calls[0]==1,"timeout: no retry "+slow);

  // The signed-in server (NG-2 G7): a working ticket answers; a failed one leaves the public probe.
  JSONObject live=new JSONObject(ServerProbe.session(()->"ticket",SERVER));
  check(live.getBoolean("reachable")&&"oauth".equals(live.getString("authMode"))&&live.isNull("error")&&SERVER.equals(live.getString("baseUrl")),"session: "+live);
  check(ServerProbe.session(()->{throw new NativeAuth.AuthRequired();},SERVER)==null,"signed out: public probe");
  check(ServerProbe.session(()->{throw new java.net.SocketTimeoutException("Read timed out");},SERVER)==null,"unreachable: public probe");
  check(!live.toString().contains("ticket"),"no ticket in the reply");
  // Both checks at once for the signed-in server (NG-2b H1): the waits overlap, the first reachable answer wins.
  java.util.concurrent.ExecutorService pool=java.util.concurrent.Executors.newCachedThreadPool();
  try{
   ServerProbe.Reader good=path->"/api/status".equals(path)?status(true,"native_pkce"):providers();
   java.util.function.Supplier<String> slowGood=()->{pause(400);return ServerProbe.run(good,SERVER);};
   java.util.function.Supplier<String> down=()->ServerProbe.run(path->{throw new java.net.SocketTimeoutException("Read timed out");},SERVER);
   long t=System.nanoTime();
   String[] won=ServerProbe.race(pool,()->"ticket",SERVER,slowGood);
   check("session".equals(won[1])&&new JSONObject(won[0]).getBoolean("reachable")&&ms(t)<300,"fast session wins: "+Arrays.toString(won)+" "+ms(t));
   t=System.nanoTime();
   won=ServerProbe.race(pool,()->{pause(400);throw new java.net.SocketTimeoutException("Read timed out");},SERVER,slowGood);
   check("public".equals(won[1])&&new JSONObject(won[0]).getBoolean("reachable")&&ms(t)<700,"slow ticket + slow status overlap: "+ms(t));
   won=ServerProbe.race(pool,()->{throw new NativeAuth.AuthRequired();},SERVER,()->ServerProbe.run(good,SERVER));
   check("public".equals(won[1])&&new JSONObject(won[0]).getBoolean("reachable"),"signed out: public answers");
   t=System.nanoTime();
   won=ServerProbe.race(pool,()->{pause(400);throw new java.net.SocketTimeoutException("Read timed out");},SERVER,down);
   JSONObject both=new JSONObject(won[0]);
   check("public".equals(won[1])&&!both.getBoolean("reachable")&&both.getString("error").contains("gateway.example.com")&&ms(t)>=350,"both fail: public error after the slower check "+both);
  }finally{pool.shutdownNow();}
  System.out.println("PASS server probe: gated/native, ungated, no native flow, HTTP failure, one retry only while current and fast, signed-in session, session and public checks in parallel");
 }
}
