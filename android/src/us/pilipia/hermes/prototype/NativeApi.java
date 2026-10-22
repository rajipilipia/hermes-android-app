package us.pilipia.hermes.prototype;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Hermes's own REST API (what Desktop's remote mode calls), limited to the bundled capability
 * contract. The page names an operation id and typed values; native builds the method, path and
 * query itself and scopes profile-aware routes to the captured owner. Never a raw URL, method or header.
 */
public final class NativeApi {
 /** Uploads and recordings travel as data URLs (the contract allows 3 MiB) inside a JSON body. */
 private static final int MAX_REQUEST=(9<<19);
 /** Raw binary replies (file downloads) are not JSON; Desktop saves them through its own bridge. */
 private static final Set<String> BINARY=new HashSet<>(Arrays.asList("GET /api/fs/download"));
 /** Contract "download" operations whose reply is still JSON (speech comes back as a data URL). */
 private static final Set<String> JSON_DOWNLOADS=new HashSet<>(Arrays.asList("POST /api/audio/speak"));
 private static final class Op {
  String id,method,template;boolean profileQuery,body;Set<String> query=new HashSet<>();List<String> path=new ArrayList<>();
 }
 public static final class Call {
  public final String method,pathAndQuery;public final byte[] body;
  Call(String method,String pathAndQuery,byte[] body){this.method=method;this.pathAndQuery=pathAndQuery;this.body=body;}
 }
 private final Map<String,Op> ops=new HashMap<>();
 private final Pattern profile;
 public NativeApi(String contract)throws JSONException {
  JSONObject root=new JSONObject(contract);
  profile=Pattern.compile(root.getJSONObject("profileSchema").getString("pattern"));
  JSONArray list=root.getJSONArray("operations");
  for(int i=0;i<list.length();i++){
   JSONObject o=list.getJSONObject(i);
   String id=o.getString("id");
   if(!"implemented".equals(o.getString("availability"))||BINARY.contains(id)||!("json".equals(o.getString("output"))||JSON_DOWNLOADS.contains(id)))continue;
   Op op=new Op();op.id=o.getString("id");op.method=o.getString("method");op.template=o.getString("pathTemplate");
   op.profileQuery=o.getBoolean("profileQuery");op.body=!o.isNull("body");
   JSONObject props=o.getJSONObject("query").optJSONObject("properties");
   if(props!=null)for(Iterator<String> k=props.keys();k.hasNext();)op.query.add(k.next());
   Matcher m=Pattern.compile("\\{(\\w+)\\}").matcher(op.template);while(m.find())op.path.add(m.group(1));
   ops.put(op.id,op);
  }
 }
 public boolean supports(String id){return ops.containsKey(id);}
 /** Validates a capabilityCall() result ({operation, profile, pathParams, query[, body]}) into one HTTPS request. */
 public Call prepare(String request)throws IOException {
  try{
   if(request==null||request.length()>MAX_REQUEST)throw new IOException("Request too large");
   JSONObject call=new JSONObject(request);
   for(Iterator<String> k=call.keys();k.hasNext();)
    if(!Arrays.asList("operation","profile","pathParams","query","body").contains(k.next()))throw new IOException("Unknown request field");
   Op op=ops.get(call.getString("operation"));
   if(op==null)throw new IOException("This Desktop feature is not available on this server.");
   String owner=call.getString("profile");
   if(owner.length()>64||!profile.matcher(owner).matches())throw new IOException("Invalid profile");
   JSONObject pathParams=call.getJSONObject("pathParams"),query=call.getJSONObject("query");
   if(pathParams.length()!=op.path.size())throw new IOException("Invalid path parameters");
   String path=op.template;
   for(String key:op.path){
    String value=pathParams.getString(key);
    if(value.isEmpty()||value.length()>1024)throw new IOException("Invalid path parameter");
    path=path.replace("{"+key+"}",encode(value));
   }
   TreeMap<String,String> fields=new TreeMap<>();
   for(Iterator<String> k=query.keys();k.hasNext();){
    String key=k.next();Object value=query.get(key);
    if(!op.query.contains(key)||!(value instanceof String||value instanceof Number||value instanceof Boolean))throw new IOException("Invalid query field");
    String text=String.valueOf(value);if(text.length()>4096)throw new IOException("Invalid query value");
    fields.put(key,text);
   }
   // The captured profile scopes every profile-aware route.
   if(op.profileQuery)fields.put("profile",owner);
   if("GET /api/config".equals(op.id))fields.put("include_defaults","false");
   StringBuilder target=new StringBuilder(path);char separator='?';
   for(Map.Entry<String,String> field:fields.entrySet()){target.append(separator).append(encode(field.getKey())).append('=').append(encode(field.getValue()));separator='&';}
   byte[] body=null;
   if(op.body){
    if(!call.has("body")||call.isNull("body"))throw new IOException("Missing request body");
    Object value=call.get("body");
    if(value instanceof JSONObject&&("PATCH /api/sessions/{session_id}".equals(op.id)||"PUT /api/config".equals(op.id)))((JSONObject)value).put("profile",owner);
    body=String.valueOf(value).getBytes(StandardCharsets.UTF_8);
    if(body.length>MAX_REQUEST)throw new IOException("Request too large");
   }else if(call.has("body")&&!call.isNull("body"))throw new IOException("Unexpected request body");
   return new Call(op.method,target.toString(),body);
  }catch(JSONException invalid){throw new IOException("Invalid Desktop request");}
 }
 private static String encode(String value){
  try{return URLEncoder.encode(value,"UTF-8").replace("+","%20");}catch(java.io.UnsupportedEncodingException impossible){throw new IllegalStateException(impossible);}
 }
}
