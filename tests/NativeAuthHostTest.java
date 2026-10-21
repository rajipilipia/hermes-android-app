import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.Consumer;
import java.net.*;

public final class NativeAuthHostTest {
 public static void main(String[] args)throws Exception {
  Class<?> core;
  try{core=Class.forName("us.pilipia.hermes.prototype.NativeAuth");}catch(ClassNotFoundException e){throw new AssertionError("Missing real native PKCE core");}
  String actual=(String)core.getMethod("challenge",String.class).invoke(null,"dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk");
  if(!"E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM".equals(actual))throw new AssertionError("RFC7636 S256 mismatch");
  System.out.println("PASS RFC7636 S256");
  Class<?> transport;
  try{transport=Class.forName("us.pilipia.hermes.prototype.NativeAuth$Transport");}catch(ClassNotFoundException e){throw new AssertionError("Missing executable loopback broker and token lifecycle");}
  flow(core,transport);
  failurePaths(core,transport);
  abortedCallbackClient(core,transport);

 }
 static void failurePaths(Class<?> core,Class<?> transport)throws Exception {
  AtomicReference<Object> owner=new AtomicReference<>();AtomicBoolean cancelRefresh=new AtomicBoolean();AtomicInteger calls=new AtomicInteger();
  Object http=http(core,transport,(o,m,a)->{
   calls.incrementAndGet();if(a[0].equals("/auth/native/token"))return token("initial",1);
   if(a[0].equals("/auth/native/refresh")){if(cancelRefresh.get())core.getMethod("signOut").invoke(owner.get());return token("late",System.currentTimeMillis()/1000+3600);}throw new AssertionError("stale refresh minted ticket");
  });
  Object auth=core.getConstructor(transport,String.class).newInstance(http,"https://gateway.example.com");owner.set(auth);AtomicReference<String> url=new AtomicReference<>();
  try{core.getMethod("signIn",Consumer.class,int.class).invoke(auth,(Consumer<String>)url::set,70);throw new AssertionError("timeout did not abort");}catch(InvocationTargetException expected){}
  check(calls.get()==0,"timed out flow exchanged code");try{get(callback(url.get(),null));throw new AssertionError("timeout listener survived");}catch(java.io.IOException expected){}
  try{
   core.getMethod("signIn",Consumer.class,int.class).invoke(auth,(Consumer<String>)(s)->{try{get(callback(s,null).replace("code=one-time-code","error=access_denied"));}catch(Exception e){throw new RuntimeException(e);}},1000);
   throw new AssertionError("denied callback accepted");
  }catch(InvocationTargetException expected){check(expected.getCause().getClass().getSimpleName().equals("SignInDenied"),"denial was swallowed or wrapped");}
  check(calls.get()==0,"denied callback exchanged code");
  try{core.getMethod("signIn",Consumer.class,int.class).invoke(auth,(Consumer<String>)(s)->{url.set(s);try{core.getMethod("signOut").invoke(auth);}catch(Exception e){throw new RuntimeException(e);}},1000);throw new AssertionError("cancel accepted");}catch(InvocationTargetException expected){}
  check(calls.get()==0,"cancel exchanged code");
  core.getMethod("signIn",Consumer.class,int.class).invoke(auth,(Consumer<String>)(s)->{try{get(callback(s,null));}catch(Exception e){throw new RuntimeException(e);}},1000);
  cancelRefresh.set(true);try{core.getMethod("ticket").invoke(auth);throw new AssertionError("late refresh escaped identity fence");}catch(InvocationTargetException expected){}
  try{core.getMethod("ticket").invoke(auth);throw new AssertionError("late refresh restored tokens");}catch(InvocationTargetException expected){}
  System.out.println("PASS timeout/cancel/stale-refresh identity fence");
 }
 static void check(boolean b,String m){if(!b)throw new AssertionError(m);}
 static void abortedCallbackClient(Class<?> core,Class<?> transport)throws Exception {
  Object auth=core.getConstructor(transport,String.class).newInstance(http(core,transport,(o,m,a)->{throw new AssertionError("unexpected auth HTTP");}),"https://gateway.example.com");
  AtomicInteger accepted=new AtomicInteger();
  try(ServerSocket server=new ServerSocket(){
   @Override public Socket accept(){
    if(accepted.getAndIncrement()==0)return new Socket(){
     @Override public java.io.InputStream getInputStream()throws java.io.IOException {throw new SocketException("synthetic browser preconnect reset");}
    };
    return new Socket(){
     @Override public java.io.InputStream getInputStream(){return new java.io.ByteArrayInputStream("GET /callback?code=synthetic-code&state=expected HTTP/1.1\r\n\r\n".getBytes(java.nio.charset.StandardCharsets.US_ASCII));}
     @Override public java.io.OutputStream getOutputStream(){return new java.io.ByteArrayOutputStream();}
    };
   }
  }){
   Method await=core.getDeclaredMethod("awaitCode",ServerSocket.class,String.class,long.class);await.setAccessible(true);
   Object code=await.invoke(auth,server,"expected",System.nanoTime()+TimeUnit.SECONDS.toNanos(2));
   check("synthetic-code".equals(code)&&accepted.get()==2,"aborted browser connection killed the sign-in listener");
  }
  System.out.println("PASS aborted browser connection does not cancel valid callback");
 }
 static Object http(Class<?> core,Class<?> transport,InvocationHandler handler){
  return java.lang.reflect.Proxy.newProxyInstance(core.getClassLoader(),new Class[]{transport},(o,m,a)->{
   if(m.getName().equals("dispatch")){
    ((Callable<?>)a[3]).call();
    return handler.invoke(o,transport.getMethod("post",String.class,Map.class,String.class),Arrays.copyOf(a,3));
   }
   if(m.getName().equals("refresh")){
    ((Callable<?>)a[1]).call();
    return handler.invoke(o,transport.getMethod("post",String.class,Map.class,String.class),new Object[]{"/auth/native/refresh",a[0],""});
   }
   return handler.invoke(o,m,a);
  });
 }
 static Map<String,Object> token(String access,long expiry){Map<String,Object> m=new HashMap<>();m.put("access_token",access);m.put("refresh_token","rotating-refresh");m.put("expires_at",expiry);m.put("provider","nous");return m;}
 static String callback(String auth,String stateOverride)throws Exception{
  URI u=new URI(auth);Map<String,String> q=new HashMap<>();for(String part:u.getRawQuery().split("&")){String[] kv=part.split("=",2);q.put(kv[0],URLDecoder.decode(kv[1],"UTF-8"));}
  check(u.getScheme().equals("https")&&u.getHost().equals("gateway.example.com")&&u.getPath().equals("/auth/native/authorize"),"wrong broker");
  check(q.get("code_challenge_method").equals("S256"),"no S256");check(q.get("code_challenge").length()==43,"challenge entropy");
  return q.get("redirect_uri")+"?code=one-time-code&state="+URLEncoder.encode(stateOverride==null?q.get("state"):stateOverride,"UTF-8");
 }
 static int get(String target)throws Exception{HttpURLConnection c=(HttpURLConnection)new URL(target).openConnection();c.setConnectTimeout(1000);c.setReadTimeout(1000);try{return c.getResponseCode();}finally{c.disconnect();}}
 static String[] fetch(String target)throws Exception{HttpURLConnection c=(HttpURLConnection)new URL(target).openConnection();c.setConnectTimeout(1000);c.setReadTimeout(1000);try{int code=c.getResponseCode();java.io.InputStream in=code<400?c.getInputStream():c.getErrorStream();java.io.ByteArrayOutputStream b=new java.io.ByteArrayOutputStream();if(in!=null){int n;byte[] buf=new byte[4096];while((n=in.read(buf))!=-1)b.write(buf,0,n);}String body=new String(b.toByteArray(),java.nio.charset.StandardCharsets.UTF_8);return new String[]{String.valueOf(code),String.valueOf(c.getContentType()),body};}finally{c.disconnect();}}
 static void flow(Class<?> core,Class<?> transport)throws Exception{
  AtomicInteger exchanged=new AtomicInteger(),refreshed=new AtomicInteger(),tickets=new AtomicInteger();AtomicReference<String> verifier=new AtomicReference<>(),authorize=new AtomicReference<>();
  Object http=http(core,transport,(o,m,a)->{
   String path=(String)a[0];Map<String,String> body=(Map<String,String>)a[1];String access=(String)a[2];
   if(path.equals("/auth/native/token")){check(body.keySet().equals(new HashSet<>(Arrays.asList("code","code_verifier"))),"wrong token schema");check(body.get("code").equals("one-time-code"),"wrong code");verifier.set(body.get("code_verifier"));exchanged.incrementAndGet();return token("initial",1);}
   if(path.equals("/auth/native/refresh")){check(body.get("provider").equals("nous"),"provider dropped");refreshed.incrementAndGet();Thread.sleep(40);return token("fresh",System.currentTimeMillis()/1000+3600);}
   if(path.equals("/api/auth/ws-ticket")){check("fresh".equals(access),"not current Bearer");Map<String,Object> r=new HashMap<>();r.put("ticket","single-use-"+tickets.incrementAndGet());return r;}
   throw new AssertionError("unapproved route "+path);
  });
  Object auth=core.getConstructor(transport,String.class).newInstance(http,"https://gateway.example.com");
  Consumer<String> browser=url->{try{authorize.set(url);check(get(callback(url,"wrong-state"))==400,"state mismatch accepted");check(exchanged.get()==0,"bad state reached exchange");String[] page=fetch(callback(url,null));check("200".equals(page[0]),"valid callback rejected");check(page[1].startsWith("text/html")&&page[2].contains("intent://signed-in#Intent;scheme=hermes-prototype;package=us.pilipia.hermes.prototype;end")&&page[2].contains("Return to Hermes")&&!page[2].contains("one-time-code")&&!page[2].contains("<script"),"callback page does not offer the return link or echoes request data");}catch(Exception e){throw new RuntimeException(e);}};
  core.getMethod("signIn",Consumer.class,int.class).invoke(auth,browser,3000);
  check(exchanged.get()==1,"exchange count");check(verifier.get().length()>=43,"weak verifier");check(authorize.get().contains((String)core.getMethod("challenge",String.class).invoke(null,verifier.get())),"challenge not bound to verifier");
  ExecutorService pool=Executors.newFixedThreadPool(2);
  try{Future<Object> t1=pool.submit(()->core.getMethod("ticket").invoke(auth));Future<Object> t2=pool.submit(()->core.getMethod("ticket").invoke(auth));check(!t1.get().equals(t2.get()),"ticket reuse");check(refreshed.get()==1,"refresh not single flight");}finally{pool.shutdownNow();}
  core.getMethod("signOut").invoke(auth);try{core.getMethod("ticket").invoke(auth);throw new AssertionError("credentials survived signout");}catch(InvocationTargetException expected){}
  try{get(callback(authorize.get(),null));throw new AssertionError("listener survived login");}catch(java.io.IOException expected){}
  System.out.println("PASS broker/loopback/state/PKCE binding/exchange/refresh single-flight/fresh tickets/signout/listener cleanup/return-to-app page");
 }
}
