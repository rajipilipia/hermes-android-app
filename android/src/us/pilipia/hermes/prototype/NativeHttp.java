package us.pilipia.hermes.prototype;
import javax.net.ssl.HttpsURLConnection;
import java.net.URL;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.JSONObject;
/** Native-validated server origin + exact auth paths only. Platform TLS, no redirects/cookie scraping. */
public final class NativeHttp implements NativeAuth.Transport {
 private final String origin;
 public NativeHttp(String origin){
  if(origin==null||!origin.equals(ServerOrigin.normalize(origin)))throw new IllegalArgumentException("Invalid server origin");
  this.origin=origin;
 }
 /** A NativeApi-built call: fixed origin, contract method/path, Bearer only, no redirects, bounded. */
 public NativeAuth.Reply api(NativeApi.Call call,String access)throws Exception {
  HttpsURLConnection c=(HttpsURLConnection)new URL(origin+call.pathAndQuery).openConnection();
  try{
   c.setInstanceFollowRedirects(false);c.setConnectTimeout(10000);c.setUseCaches(false);
   // Speech and transcription wait for the provider (Desktop allows minutes for long replies).
   c.setReadTimeout(call.pathAndQuery.startsWith("/api/audio/")?120000:60000);
   c.setRequestMethod(call.method); // Android's HttpURLConnection accepts PATCH (desktop session rename).
   c.setRequestProperty("Accept","application/json");c.setRequestProperty("Cache-Control","no-store");
   c.setRequestProperty("Authorization","Bearer "+access);
   if(call.body!=null){c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json");c.setFixedLengthStreamingMode(call.body.length);try(OutputStream out=c.getOutputStream()){out.write(call.body);}}
   int status=c.getResponseCode();
   InputStream in=status>=400?c.getErrorStream():c.getInputStream();
   ByteArrayOutputStream bytes=new ByteArrayOutputStream();
   if(in!=null)try(InputStream stream=in){byte[] chunk=new byte[8192];int n;while((n=stream.read(chunk))!=-1){if(bytes.size()+n>(8<<20))throw new IOException("Oversized Hermes response");bytes.write(chunk,0,n);}}
   return new NativeAuth.Reply(status,new String(bytes.toByteArray(),StandardCharsets.UTF_8));
  }finally{c.disconnect();}
 }
 /** Public, credential-free reads used to probe a server before sign-in. */
 public Map<String,Object> getPublic(String path)throws Exception {
  if(!Arrays.asList("/api/status","/api/auth/providers").contains(path))throw new IOException("Unsupported public server read");
  HttpsURLConnection c=(HttpsURLConnection)new URL(origin+path).openConnection();
  try{
   // Desktop allows 8 s; a busy PC answered /api/status in up to 22 s (NG-2), so status gets 30 s.
   c.setInstanceFollowRedirects(false);c.setConnectTimeout(15000);c.setReadTimeout("/api/status".equals(path)?30000:15000);c.setUseCaches(false);c.setRequestMethod("GET");
   c.setRequestProperty("Accept","application/json");c.setRequestProperty("Cache-Control","no-store");
   int status=c.getResponseCode();if(status!=200)throw new NativeAuth.HttpFailure(status);
   return json(c);
  }finally{c.disconnect();}
 }
 private static Map<String,Object> json(HttpsURLConnection c)throws Exception {
   ByteArrayOutputStream bytes=new ByteArrayOutputStream();try(InputStream in=c.getInputStream()){byte[] chunk=new byte[4096];int n;while((n=in.read(chunk))!=-1){if(bytes.size()+n>65536)throw new IOException("Oversized PC auth response");bytes.write(chunk,0,n);}}
   JSONObject json=new JSONObject(new String(bytes.toByteArray(),StandardCharsets.UTF_8));Map<String,Object> result=new HashMap<>();Iterator<String> keys=json.keys();while(keys.hasNext()){String key=keys.next();result.put(key,json.get(key));}return result;
 }
 @Override public Map<String,Object> post(String path,Map<String,String> body,String access)throws Exception {
  if(!Arrays.asList("/auth/native/token","/auth/native/refresh","/api/auth/ws-ticket").contains(path))throw new IOException("Unsupported PC auth operation");
  final long started=System.nanoTime();
  android.util.Log.d("HermesPrototype","event=auth_http_start operation="+path);
  HttpsURLConnection c=(HttpsURLConnection)new URL(origin+path).openConnection();
  try{
   c.setInstanceFollowRedirects(false);c.setConnectTimeout(10000);c.setReadTimeout(15000);c.setUseCaches(false);c.setRequestMethod("POST");c.setDoOutput(true);
   c.setRequestProperty("Content-Type","application/json");c.setRequestProperty("Accept","application/json");c.setRequestProperty("Cache-Control","no-store");
   if(!access.isEmpty())c.setRequestProperty("Authorization", "Bearer " + access);
   byte[] data=new JSONObject(body).toString().getBytes(StandardCharsets.UTF_8);c.setFixedLengthStreamingMode(data.length);
   try(OutputStream out=c.getOutputStream()){out.write(data);}
   int status=c.getResponseCode();android.util.Log.d("HermesPrototype","event=auth_http_status operation="+path+" status="+status+" elapsed_ms="+((System.nanoTime()-started)/1000000));if(status!=200)throw new NativeAuth.HttpFailure(status);
   return json(c);
  }finally{c.disconnect();android.util.Log.d("HermesPrototype","event=auth_http_end operation="+path+" elapsed_ms="+((System.nanoTime()-started)/1000000));}
 }
}
