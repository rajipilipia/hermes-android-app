import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import us.pilipia.hermes.prototype.NativeApi;

/** The stock-server REST allowlist: contract operations only, native-built path/query, adapter owner rules. */
public final class NativeApiHostTest {
 static void check(boolean b,String message){if(!b)throw new AssertionError(message);}
 static void rejects(NativeApi api,String request){
  try{api.prepare(request);throw new AssertionError("accepted "+request);}catch(java.io.IOException expected){}
 }
 public static void main(String[] args)throws Exception{
  NativeApi api=new NativeApi(new String(Files.readAllBytes(Paths.get(args[0])),StandardCharsets.UTF_8));
  NativeApi.Call c=api.prepare("{\"operation\":\"GET /api/sessions/{session_id}/messages\",\"profile\":\"work\",\"pathParams\":{\"session_id\":\"a b/c\"},\"query\":{}}");
  check("GET".equals(c.method)&&c.body==null,"method/body");
  check("/api/sessions/a%20b%2Fc/messages?profile=work".equals(c.pathAndQuery),"path+profile: "+c.pathAndQuery);
  c=api.prepare("{\"operation\":\"GET /api/profiles\",\"profile\":\"work\",\"pathParams\":{},\"query\":{}}");
  check("/api/profiles".equals(c.pathAndQuery),"profile added to a non-profile route: "+c.pathAndQuery);
  c=api.prepare("{\"operation\":\"GET /api/config\",\"profile\":\"default\",\"pathParams\":{},\"query\":{\"include_defaults\":true}}");
  check(c.pathAndQuery.contains("include_defaults=false")&&!c.pathAndQuery.contains("include_defaults=true"),"config defaults not forced off: "+c.pathAndQuery);
  c=api.prepare("{\"operation\":\"PATCH /api/sessions/{session_id}\",\"profile\":\"work\",\"pathParams\":{\"session_id\":\"s1\"},\"query\":{},\"body\":{\"title\":\"x\",\"profile\":\"other\"}}");
  String body=new String(c.body,StandardCharsets.UTF_8);
  check("PATCH".equals(c.method)&&body.contains("\"profile\":\"work\"")&&!body.contains("other"),"owner not forced into body: "+body);
  // Hermes's own JSON routes for voice and workspace uploads (Desktop's remote mode uses them).
  c=api.prepare("{\"operation\":\"POST /api/audio/transcribe\",\"profile\":\"work\",\"pathParams\":{},\"query\":{},\"body\":{\"data_url\":\"data:audio/webm;base64,AAAA\",\"mime_type\":\"audio/webm\"}}");
  check("POST".equals(c.method)&&c.pathAndQuery.startsWith("/api/audio/transcribe"),"transcribe: "+c.pathAndQuery);
  c=api.prepare("{\"operation\":\"POST /api/audio/speak\",\"profile\":\"work\",\"pathParams\":{},\"query\":{},\"body\":{\"text\":\"hi\"}}");
  check(c.pathAndQuery.startsWith("/api/audio/speak"),"speak: "+c.pathAndQuery);
  StringBuilder big=new StringBuilder("data:image/png;base64,");for(int i=0;i<3000000;i++)big.append('A');
  c=api.prepare("{\"operation\":\"POST /api/files/upload\",\"profile\":\"work\",\"pathParams\":{},\"query\":{},\"body\":{\"path\":\"a.png\",\"data_url\":\""+big+"\"}}");
  check(c.body.length>3000000,"3 MB upload refused");
  // Unknown, withheld, binary or relay-only operations, foreign fields and bad profiles never become a request.
  for(String bad:new String[]{
   "{\"operation\":\"GET /api/secrets\",\"profile\":\"work\",\"pathParams\":{},\"query\":{}}",
   "{\"operation\":\"POST /api/audio/stt-lease\",\"profile\":\"work\",\"pathParams\":{},\"query\":{},\"body\":{}}",
   "{\"operation\":\"GET /api/fs/download\",\"profile\":\"work\",\"pathParams\":{},\"query\":{\"path\":\"/x\"}}",
   "{\"operation\":\"GET /api/profiles\",\"profile\":\"root\",\"pathParams\":{},\"query\":{}}",
   "{\"operation\":\"GET /api/profiles\",\"profile\":\"Work\",\"pathParams\":{},\"query\":{}}",
   "{\"operation\":\"GET /api/profiles\",\"profile\":\"work\",\"pathParams\":{},\"query\":{\"x\":\"1\"}}",
   "{\"operation\":\"GET /api/profiles\",\"profile\":\"work\",\"pathParams\":{},\"query\":{},\"url\":\"https://evil.example.com\"}",
   "{\"operation\":\"GET /api/profiles\",\"profile\":\"work\",\"pathParams\":{},\"query\":{},\"body\":{\"a\":1}}",
   "{\"operation\":\"GET /api/sessions/{session_id}\",\"profile\":\"work\",\"pathParams\":{},\"query\":{}}",
   "{\"operation\":\"GET /api/sessions/{session_id}\",\"profile\":\"work\",\"pathParams\":{\"session_id\":\"s\",\"x\":\"y\"},\"query\":{}}",
   "{\"operation\":\"PUT /api/config\",\"profile\":\"work\",\"pathParams\":{},\"query\":{}}",
   "not json",null})rejects(api,bad);
  System.out.println("PASS stock-server REST: contract-only operations, native path/query/profile, owner rules, voice and uploads as JSON, no URL/header/withheld/binary download");
 }
}
