package us.pilipia.hermes.prototype;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;
/** Gateway-brokered RFC8252. Only the injected native store may retain refresh credentials. */
public final class NativeAuth {
 public interface Transport {
  Map<String,Object> post(String path,Map<String,String> body,String access) throws Exception;
  default Map<String,Object> dispatch(String path,Map<String,String> body,String access,Callable<Void> beforeDispatch)throws Exception {
   beforeDispatch.call();return post(path,body,access);
  }
  default Map<String,Object> refresh(Map<String,String> body,Callable<Void> beforeDispatch)throws Exception {
   beforeDispatch.call();return post("/auth/native/refresh",body,"");
  }
  /** Contract-built Hermes REST call (NativeApi) with the current Bearer token. */
  default Reply api(NativeApi.Call call,String access,Callable<Void> beforeDispatch)throws Exception {throw new IOException("Hermes REST unavailable");}
 }
 /** Status and raw JSON text of a Hermes REST call; never contains a credential. */
 public static final class Reply {
  public final int status;public final String body;
  public Reply(int status,String body){this.status=status;this.body=body;}
 }
 public interface Store {
  Credential load() throws IOException;
  void save(Credential credential) throws IOException;
  void clear() throws IOException;
 }
 public static final class Credential {
  public final String refreshToken,provider;
  public final boolean pending;
  public Credential(String refreshToken,String provider,boolean pending)throws IOException {
   this.refreshToken=text(Collections.singletonMap("value",refreshToken),"value");
   this.provider=text(Collections.singletonMap("value",provider),"value");this.pending=pending;
  }
 }
 public static final class AuthRequired extends IOException { public AuthRequired(){super("Sign in to this PC again");} }
 public static final class HttpFailure extends IOException {
  public final int status;
  public HttpFailure(int status){super("Gateway HTTP "+status);this.status=status;}
 }
 private final Transport http;
 private final String origin;
 private final Store store;
 private final Object refreshLock=new Object();
 private long generation;
 private Map<String,Object> tokens;
 private boolean restoreFailed;
 private ServerSocket listener;
 public NativeAuth(Transport http,String origin){this.http=http;this.store=null;this.origin=checked(origin);}
 public NativeAuth(Transport http,Store store,String origin)throws IOException {
  this.http=Objects.requireNonNull(http);this.store=Objects.requireNonNull(store);this.origin=checked(origin);
  try{Credential saved=store.load();if(saved!=null)tokens=restored(saved);}
  catch(IOException failure){restoreFailed=true;}
 }
 private static String checked(String origin){
  if(origin==null||!origin.equals(ServerOrigin.normalize(origin)))throw new IllegalArgumentException("Invalid server origin");
  return origin;
 }
 public String origin(){return origin;}
 private static Map<String,Object> restored(Credential saved){
  Map<String,Object> t=new HashMap<>();t.put("refresh_token",saved.refreshToken);t.put("provider",saved.provider);
  t.put("expires_at",0L);t.put("refresh_pending",saved.pending);return t;
 }
 private void publish(Map<String,Object> result,long gen)throws IOException {
  current(gen);
  if(store!=null)store.save(new Credential(text(result,"refresh_token"),text(result,"provider"),false));
  tokens=result;
 }
 public static String challenge(String verifier) throws Exception {
  return Base64.getUrlEncoder().withoutPadding().encodeToString(MessageDigest.getInstance("SHA-256").digest(verifier.getBytes(StandardCharsets.US_ASCII)));
 }
 private static String random(){byte[] b=new byte[32];new SecureRandom().nextBytes(b);return Base64.getUrlEncoder().withoutPadding().encodeToString(b);}
 private static String enc(String s)throws Exception{return URLEncoder.encode(s,"UTF-8");}
 private static Map<String,String> fields(String... pairs){Map<String,String> m=new HashMap<>();for(int i=0;i<pairs.length;i+=2)m.put(pairs[i],pairs[i+1]);return m;}
 private static String text(Map<String,?> m,String key)throws IOException {Object s=m.get(key);if(!(s instanceof String)||((String)s).isEmpty()||((String)s).length()>16384)throw new IOException("Invalid gateway authentication response");return (String)s;}
 private static Map<String,Object> validated(Map<String,Object> t)throws IOException {
  text(t,"access_token");text(t,"refresh_token");text(t,"provider");
  if(!(t.get("expires_at") instanceof Number)||((Number)t.get("expires_at")).longValue()<=0)throw new IOException("Invalid token expiry");return new HashMap<>(t);
 }
 private synchronized void current(long gen)throws IOException {if(gen!=generation)throw new IOException("PC sign-in cancelled");}
 private Map<String,Object> postCurrent(String path,Map<String,String> body,String access,long gen)throws Exception {
  return http.dispatch(path,body,access,()->{current(gen);return null;});
 }
 /** Cancels this lifecycle owner, without deleting the durable login. */
 public synchronized void close(){generation++;tokens=null;if(listener!=null){try{listener.close();}catch(IOException ignored){}listener=null;}}
 /** Explicit local logout; failure is surfaced, never reported as a successful deletion. */
 public synchronized void signOut()throws IOException {close();if(store!=null)store.clear();}
 public void signIn(Consumer<String> browser,int timeoutMs)throws Exception {
  final long gen;final ServerSocket server=new ServerSocket();
  synchronized(this){close();if(restoreFailed){store.clear();restoreFailed=false;}gen=generation;listener=server;}
  ExecutorService worker=Executors.newSingleThreadExecutor();
  try{
   server.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"),0),4);
   final String verifier=random(),state=random();final int port=server.getLocalPort();
   final long deadline=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(timeoutMs);
   Future<String> received=worker.submit(()->awaitCode(server,state,deadline));
   browser.accept(origin+"/auth/native/authorize?redirect_uri="+enc("http://127.0.0.1:"+port+"/callback")+"&code_challenge="+enc(challenge(verifier))+"&code_challenge_method=S256&state="+enc(state));
   String code=received.get(Math.max(1,TimeUnit.NANOSECONDS.toMillis(deadline-System.nanoTime())),TimeUnit.MILLISECONDS);
   current(gen);Map<String,Object> result=validated(postCurrent("/auth/native/token",fields("code",code,"code_verifier",verifier),"",gen));
   synchronized(this){publish(result,gen);}
  }catch(ExecutionException failure){
   // Report the actual stage failure, not an opaque executor wrapper. No values are logged.
   if(failure.getCause() instanceof Exception)throw (Exception)failure.getCause();
   throw failure;
  }finally{server.close();worker.shutdownNow();synchronized(this){if(listener==server)listener=null;}}
 }
 /** App link that only brings Hermes back to the front (the app ignores its data). */
 static final String RETURN_LINK="intent://signed-in#Intent;scheme=hermes-prototype;package=us.pilipia.hermes.prototype;end";
 /**
  * Fixed callback page: the browser returns to Hermes by itself where it allows that (meta refresh),
  * and the link does it with a tap where it does not. No script, no request data echoed.
  */
 static final String RETURN_PAGE="<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
  +"<meta http-equiv=\"refresh\" content=\"0;url="+RETURN_LINK+"\"><title>Hermes</title></head>"
  +"<body><p>Sign-in received.</p><p><a href=\""+RETURN_LINK+"\">Return to Hermes</a></p></body></html>";
 private static final class SignInDenied extends IOException {SignInDenied(){super("PC sign-in denied");}}
 private String awaitCode(ServerSocket server,String state,long deadline)throws Exception {
  while(System.nanoTime()<deadline){
   server.setSoTimeout((int)Math.min(1000,Math.max(1,TimeUnit.NANOSECONDS.toMillis(deadline-System.nanoTime()))));
   final Socket accepted;
   try{accepted=server.accept();}catch(SocketTimeoutException idle){continue;}
   try(Socket socket=accepted){
    socket.setSoTimeout(1000);String request=line(socket.getInputStream(),8192);String code=null;boolean valid=false,denied=false;
    try{
     String[] parts=request.split(" ");URI target=new URI(parts[1]);
     if(parts.length==3&&parts[0].equals("GET")&&!target.isAbsolute()&&target.getRawPath().equals("/callback")&&target.getRawFragment()==null){
      Map<String,String> q=new HashMap<>();for(String field:target.getRawQuery().split("&")){
       String[] kv=field.split("=",2);String key=URLDecoder.decode(kv[0],"UTF-8"),value=URLDecoder.decode(kv[1],"UTF-8");if(q.put(key,value)!=null)throw new IOException("Duplicate callback field");
      }
      valid=MessageDigest.isEqual(state.getBytes(StandardCharsets.US_ASCII),q.getOrDefault("state","").getBytes(StandardCharsets.US_ASCII));
      denied=valid&&q.containsKey("error");code=q.get("code");valid=valid&&(denied||(code!=null&&!code.isEmpty()&&code.length()<=4096));
     }
    }catch(Exception ignored){valid=false;}
    byte[] body=(valid?RETURN_PAGE:"Invalid sign-in callback.").getBytes(StandardCharsets.UTF_8);
    String headers="HTTP/1.1 "+(valid?"200 OK":"400 Bad Request")+"\r\nContent-Type: "+(valid?"text/html":"text/plain")+"; charset=utf-8\r\nCache-Control: no-store\r\nReferrer-Policy: no-referrer\r\nContent-Security-Policy: default-src 'none'\r\nConnection: close\r\nContent-Length: "+body.length+"\r\n\r\n";
    socket.getOutputStream().write(headers.getBytes(StandardCharsets.US_ASCII));socket.getOutputStream().write(body);socket.getOutputStream().flush();
    if(denied)throw new SignInDenied();if(valid)return code;
   }catch(SignInDenied denied){throw denied;}
   catch(SocketTimeoutException ignored){}
   catch(IOException abortedClient){
    // Browser preconnects, probes and reset client sockets are not a failed sign-in.
    // Cancellation closes the listener itself and must still abort immediately.
    if(server.isClosed())throw abortedClient;
   }
  }throw new IOException("PC sign-in timed out");
 }
 private static String line(InputStream in,int max)throws IOException {ByteArrayOutputStream b=new ByteArrayOutputStream();int c;while((c=in.read())!=-1&&c!='\n'){if(b.size()>=max)throw new IOException("Oversized callback");if(c!='\r')b.write(c);}return b.toString("US-ASCII");}
 private Map<String,Object> access(boolean force,long gen)throws Exception {
  synchronized(refreshLock){
   Map<String,Object> old;synchronized(this){current(gen);old=tokens;if(old==null)throw new AuthRequired();}
   // An interrupted rotating refresh may have consumed its one-time token.
   // Keep ciphertext, but never replay an unknown delivery automatically (even after restart).
   if(Boolean.TRUE.equals(old.get("refresh_pending")))throw new AuthRequired();
   if(!force&&((Number)old.get("expires_at")).longValue()>System.currentTimeMillis()/1000+60)return old;
   try{
    Map<String,Object> rotated=validated(http.refresh(fields("refresh_token",text(old,"refresh_token"),"provider",text(old,"provider")),()->{
     synchronized(this){
      current(gen);Credential pending=new Credential(text(old,"refresh_token"),text(old,"provider"),true);
      if(store!=null)store.save(pending);
      tokens=restored(pending);
     }
     return null;
    }));
    synchronized(this){publish(rotated,gen);return rotated;}
   }catch(HttpFailure failure){if(failure.status==400||failure.status==401||failure.status==403){synchronized(this){if(gen==generation)signOut();}throw new AuthRequired();}throw failure;}
  }
 }
 /** Stock-server REST: the same access/refresh path as tickets; one forced refresh on 401. */
 public Reply api(NativeApi.Call call)throws Exception {
  final long gen;synchronized(this){gen=generation;}
  Map<String,Object> active=access(false,gen);
  Reply reply=http.api(call,text(active,"access_token"),()->{current(gen);return null;});
  if(reply.status==401){active=access(true,gen);reply=http.api(call,text(active,"access_token"),()->{current(gen);return null;});}
  current(gen);return reply;
 }
 public String ticket()throws Exception {
  final long gen;synchronized(this){gen=generation;}
  Map<String,Object> active=access(false,gen),reply;
  try{reply=postCurrent("/api/auth/ws-ticket",Collections.emptyMap(),text(active,"access_token"),gen);}
  catch(HttpFailure failure){if(failure.status!=401)throw failure;active=access(true,gen);reply=postCurrent("/api/auth/ws-ticket",Collections.emptyMap(),text(active,"access_token"),gen);}
  current(gen);return text(reply,"ticket");
 }
}
