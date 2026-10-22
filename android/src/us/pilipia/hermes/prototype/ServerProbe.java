package us.pilipia.hermes.prototype;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.util.Map;

/** Desktop's probeConnectionConfig: credential-free reads of /api/status and /api/auth/providers. */
public final class ServerProbe {
 private ServerProbe(){}
 /** The two public reads (NativeHttp.getPublic). */
 public interface Reader{Map<String,Object> getPublic(String path)throws Exception;}
 /** DesktopConnectionProbeResult JSON. Never throws; failures are reachable:false with a message. */
 public static String run(Reader http,String target){return run(http,target,()->true);}
 /**
  * The server this phone is signed in to: a working authenticated request ({@code proof}, a socket
  * ticket) answers the probe, so a slow /api/status cannot report a live server as unreachable.
  * Null when the proof fails (signed out or unreachable): the caller runs the public probe.
  */
 public static String session(java.util.concurrent.Callable<?> proof,String target){
  try{
   proof.call();
   return new JSONObject().put("baseUrl",target).put("reachable",true).put("authMode","oauth")
    .put("providers",new JSONArray()).put("version",JSONObject.NULL).put("error",JSONObject.NULL).toString();
  }catch(Exception notProven){return null;}
 }
 /**
  * The signed-in server (NG-2b H1): the session proof and the public probe ({@code open}) run
  * together and the first reachable answer wins, so a slow ticket (15 s) and a slow status (30 s)
  * no longer add up to 45 s. When neither proves the server, the public reply (with its error)
  * answers. The losing check is not interrupted (a ticket may be rotating the stored refresh
  * credential); its late result is ignored. Returns {reply, source}.
  */
 public static String[] race(java.util.concurrent.ExecutorService pool,java.util.concurrent.Callable<?> proof,String target,java.util.function.Supplier<String> open){
  java.util.concurrent.CompletionService<String[]> done=new java.util.concurrent.ExecutorCompletionService<>(pool);
  String[] fallback=null;
  try{
   done.submit(()->new String[]{session(proof,target),"session"});
   done.submit(()->new String[]{open.get(),"public"});
   for(int i=0;i<2;i++){
    String[] answer;
    try{answer=done.take().get();}catch(java.util.concurrent.ExecutionException failed){continue;}
    if(answer[0]==null)continue;
    if(new JSONObject(answer[0]).optBoolean("reachable"))return answer;
    fallback=answer;
   }
  }catch(InterruptedException stopped){Thread.currentThread().interrupt();}
  catch(JSONException|java.util.concurrent.RejectedExecutionException unexpected){/* Answered below. */}
  return fallback!=null?fallback:new String[]{failed(target),"public"};
 }
 /** Retries the status read once on a fast network failure while {@code current} still holds. */
 public static String run(Reader http,String target,java.util.function.BooleanSupplier current){
  JSONObject reply=new JSONObject();
  try{
   reply.put("baseUrl",target);reply.put("providers",new JSONArray());reply.put("version",JSONObject.NULL);
   try{
    Map<String,Object> status;
    try{status=http.getPublic("/api/status");}
    catch(NativeAuth.HttpFailure failure){throw failure;}
    // A timeout already spent the whole wait on a slow server; only a fast failure is retried.
    catch(java.net.SocketTimeoutException slow){throw slow;}
    catch(java.io.IOException retryable){if(!current.getAsBoolean())throw retryable;status=http.getPublic("/api/status");}
    boolean gated=Boolean.TRUE.equals(status.get("auth_required"));
    reply.put("reachable",true);reply.put("authMode",gated?"oauth":"token");
    Object version=status.get("version");if(version instanceof String&&((String)version).length()<=64)reply.put("version",version);
    if(gated)try{
     Object list=http.getPublic("/api/auth/providers").get("providers");
     if(list instanceof JSONArray){
      JSONArray providers=new JSONArray();
      for(int i=0;i<((JSONArray)list).length()&&i<16;i++){
       JSONObject p=((JSONArray)list).optJSONObject(i);if(p==null)continue;
       String name=p.optString("name","");if(name.isEmpty()||name.length()>64)continue;
       String display=p.optString("display_name",name);if(display.length()>64)display=name;
       providers.put(new JSONObject().put("name",name).put("displayName",display).put("supportsPassword",p.optBoolean("supports_password",false)));
      }
      reply.put("providers",providers);
     }
    }catch(Exception optional){/* Provider names only label the button. */}
    Object flows=status.get("auth_flows");
    boolean nativeFlow=false;
    if(flows instanceof JSONArray)for(int i=0;i<((JSONArray)flows).length();i++)nativeFlow|="native_pkce".equals(((JSONArray)flows).opt(i));
    reply.put("error",!gated?"This server has no sign-in gate. Hermes Android needs a gated server: set dashboard.public_url and an auth provider."
     :nativeFlow?JSONObject.NULL:"This Hermes server does not offer native sign-in (native_pkce). Update Hermes on the server.");
   }catch(NativeAuth.HttpFailure failure){
    reply.put("reachable",false).put("authMode","unknown").put("error","Server answered HTTP "+failure.status+". Check the address.");
   }catch(Exception failure){
    reply.put("reachable",false).put("authMode","unknown").put("error","Could not reach "+ServerOrigin.label(target)+" over HTTPS.");
   }
  }catch(JSONException impossible){return failed(target);}
  return reply.toString();
 }
 private static String failed(String target){
  return "{\"baseUrl\":"+JSONObject.quote(target)+",\"reachable\":false,\"authMode\":\"unknown\",\"providers\":[],\"version\":null,\"error\":\"Probe failed.\"}";
 }
}
