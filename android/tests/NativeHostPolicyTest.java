import java.lang.reflect.*;
import java.util.*;

public final class NativeHostPolicyTest {
 private static Class<?> policy;
 private static Object invoke(String name, Class<?>[] types, Object... args) throws Exception {
  return policy.getMethod(name, types).invoke(null, args);
 }
 private static String path(String url, String method) throws Exception {
  return (String)invoke("assetPath", new Class<?>[]{String.class,String.class},url,method);
 }
 private static void eq(Object expected, Object actual) {
  if (!Objects.equals(expected,actual)) throw new AssertionError("expected="+expected+" actual="+actual);
 }
 public static void main(String[] args)throws Exception {
  try { policy=Class.forName("us.pilipia.hermes.prototype.NativeHostPolicy"); }
  catch(ClassNotFoundException failure){throw new AssertionError("Missing strict bundled-asset policy");}
  // Before setup the page lives at the setup origin; a server is never trusted until chosen natively.
  eq(true,invoke("setup",new Class<?>[]{}));
  eq("https://setup.hermes-android.invalid/assets/index.html",invoke("appUrl",new Class<?>[]{}));
  eq(false,invoke("isAppPage",new Class<?>[]{String.class},"https://gateway.example.com/assets/index.html"));
  for(String bad:Arrays.asList("https://gateway.example.com/","http://gateway.example.com","https://gateway.example.com:443","https://10.0.0.1",null)){
   try{invoke("useOrigin",new Class<?>[]{String.class},bad);throw new AssertionError("accepted page origin "+bad);}catch(java.lang.reflect.InvocationTargetException expected){}
  }
  invoke("useOrigin",new Class<?>[]{String.class},"https://gateway.example.com:8443");
  eq("index.html",path("https://gateway.example.com:8443/assets/index.html","GET"));
  eq(null,path("https://gateway.example.com/assets/index.html","GET"));
  invoke("useOrigin",new Class<?>[]{String.class},"https://gateway.example.com");
  eq(false,invoke("setup",new Class<?>[]{}));
  String root="https://gateway.example.com/assets/";
  eq("index.html",path(root+"index.html","GET"));
  eq("assets/main-abc.js",path(root+"assets/main-abc.js","GET"));
  eq("fonts/Newsreader.woff2",path(root+"fonts/Newsreader.woff2","GET"));
  for(String invalid:Arrays.asList("http://gateway.example.com/assets/a.js",
    "https://gateway.example.com:444/assets/a.js", "https://user@gateway.example.com/assets/a.js",
    "https://gateway.example.com.evil/assets/a.js",root+"../secret",root+"%2e%2e/a.js",
    root+"x/%2e%2e/a.js",root+"%2f/a.js",root+"a%5cb.js",root+"a.js?x=1",root+"a.js#x",
    root+"a//b.js",root+"",root+"a%252ejs","file:///assets/a.js","content://files/index.html")) eq(null,path(invalid,"GET"));
  eq(null,path(root+"a.js","POST")); eq(null,path(null,"GET"));
  String[][] mimes={{"a.html","text/html"},{"a.js","application/javascript"},{"a.mjs","application/javascript"},
    {"a.css","text/css"},{"a.json","application/json"},{"a.wasm","application/wasm"},
    {"a.woff2","font/woff2"},{"a.woff","font/woff"},{"a.ttf","font/ttf"},{"a.otf","font/otf"},
    {"a.svg","image/svg+xml"},{"a.png","image/png"},{"a.webp","image/webp"},{"a.jpeg","image/jpeg"},
    {"a.gif","image/gif"},{"a.ico","image/x-icon"},{"a.avif","image/avif"},{"a.mp3","audio/mpeg"},
    {"a.ogg","audio/ogg"},{"a.wav","audio/wav"},{"a.mp4","video/mp4"},{"a.webm","video/webm"},
    {"a.bin","application/octet-stream"}};
  for(String[] m:mimes)eq(m[1],invoke("mimeType",new Class<?>[]{String.class},m[0]));
  eq(null,invoke("encoding",new Class<?>[]{String.class},"image/png"));
  eq("UTF-8",invoke("encoding",new Class<?>[]{String.class},"application/javascript"));
  for(String link:Arrays.asList("https://example.com/a?b=c#d","http://example.com","https://accounts.google.com/x","https://gateway.example.com/assets/index.html","https://host.example.com:8443/p"))
   eq(true,invoke("allowExternal",new Class<?>[]{String.class},link));
  for(String link:Arrays.asList("javascript:alert(1)","file:///sdcard/a","content://x/y","intent://x#Intent;end","data:text/html,a",
    "https://user:pw@example.com/","mailto:a@example.com","https:/no-host","https://exa mple.com","about:blank","",null))
   eq(false,invoke("allowExternal",new Class<?>[]{String.class},link));
  System.out.println("PASS strict origin/path/method bundle routing and Desktop MIME types");
  // In-app browser pane (R1 stage 1): the current page origin is https://gateway.example.com here.
  for(String link:Arrays.asList("https://example.com/a?b=c#d","http://example.com","https://docs.example.org:8443/p","https://gateway.example.com:8443/","http://gateway.example.com/","https://8.8.8.8/"))
   eq(true,invoke("allowGuest",new Class<?>[]{String.class},link));
  for(String link:Arrays.asList("https://gateway.example.com/","https://GATEWAY.example.com/assets/index.html","https://gateway.example.com:443/x",
    "http://localhost:5173","https://127.0.0.1/","https://10.1.2.3/","https://192.168.1.10/","https://172.20.0.1/","https://169.254.1.1/","https://100.100.1.1/",
    "https://[::1]/","https://printer.local/","https://app.localhost/","https://intranet/","https://user:pw@example.com/","javascript:alert(1)",
    "file:///sdcard/a","content://x/y","intent://x#Intent;end","data:text/html,a","about:blank","",null))
   eq(false,invoke("allowGuest",new Class<?>[]{String.class},link));
  System.out.println("PASS browser pane: http/https public hosts only, never the Hermes server, loopback, private or local names");
  String page=root+"index.html", origin="https://gateway.example.com";
  String audio="android.webkit.resource.AUDIO_CAPTURE";
  eq(true,invoke("allowAudio",new Class<?>[]{String.class,String.class,String[].class},page,origin,new String[]{audio}));
  eq(true,invoke("allowAudio",new Class<?>[]{String.class,String.class,String[].class},page,origin+"/",new String[]{audio}));
  for(String other:Arrays.asList(origin+":443",origin+".evil",origin+"/path","https://user@gateway.example.com","file:///", "null"))
   eq(false,invoke("allowAudio",new Class<?>[]{String.class,String.class,String[].class},page,other,new String[]{audio}));
  for(String fragment:Arrays.asList("#settings", "#/settings/voice", "#session/stored-A?tab=files", "#preview", "#")) {
   eq(true,invoke("isAppPage",new Class<?>[]{String.class},page+fragment));
   eq(true,invoke("allowAudio",new Class<?>[]{String.class,String.class,String[].class},page+fragment,origin,new String[]{audio}));
   eq(null,path(page+fragment,"GET")); // Current-document identity is NOT asset-fetch policy.
  }
  for(String other:Arrays.asList(page+"?q=x#settings",page+"?#settings",origin+":443/assets/index.html#settings",
    "https://user@gateway.example.com/assets/index.html#settings", origin+".evil/assets/index.html#settings",
    origin+"/assets/%69ndex.html#settings", origin+"/assets/./index.html#settings",origin+"/assets/index.html/other#settings",
    "http://gateway.example.com/assets/index.html#settings",page+"#bad fragment",page+"#%", "", null))
   eq(false,invoke("isAppPage",new Class<?>[]{String.class},other));
  System.out.println("PASS exact bundled-document identity across hash routes without relaxing asset requests");
  Class<?>[] navigation={String.class,String.class,String.class,boolean.class};
  eq(true,invoke("allowNavigation",navigation,page,page,"GET",true));
  eq(true,invoke("allowNavigation",navigation,page+"#/settings",page+"#session/A?tab=files","GET",true));
  for(String target:Arrays.asList(page+"?",page+"?q=x#route",root+"other.html",root+"%69ndex.html",root+"./index.html",
    origin+":443/assets/index.html",origin+".evil/assets/index.html","https://user@gateway.example.com/assets/index.html",
    "http://gateway.example.com/assets/index.html","file:///assets/index.html","data:text/html,a","blob:"+page,
    page+"#%",page+"#bad fragment",null))eq(false,invoke("allowNavigation",navigation,page,target,"GET",true));
  eq(false,invoke("allowNavigation",navigation,page,page,"POST",true));
  eq(false,invoke("allowNavigation",navigation,page,page,"get",true));
  eq(false,invoke("allowNavigation",navigation,page,page,"GET",false));
  eq(false,invoke("allowNavigation",navigation,origin+"/other.html",page,"GET",true));
  eq(false,invoke("allowNavigation",navigation,null,page,"GET",true));
  System.out.println("PASS pure exact bundled GET/main-frame navigation policy");
  eq(false,invoke("allowAudio",new Class<?>[]{String.class,String.class,String[].class},page,origin,new String[]{audio,"android.webkit.resource.VIDEO_CAPTURE"}));
  eq(false,invoke("allowAudio",new Class<?>[]{String.class,String.class,String[].class},page,origin,new String[]{}));
  for(String op:Arrays.asList("clipboard.write","browser.open","document.save","document.share","screen.keepAwake","notification.show"))
   eq(true,invoke("allowDevice",new Class<?>[]{String.class,String.class,String.class},page,page,op));
  for(String op:Arrays.asList("fetch","api","readFile","ticket","signIn","openUrl","document.read"))
   eq(false,invoke("allowDevice",new Class<?>[]{String.class,String.class,String.class},page,page,op));
  eq(false,invoke("allowDevice",new Class<?>[]{String.class,String.class,String.class},page,"blob:"+origin+"/uuid","document.save"));
  eq(false,invoke("allowDevice",new Class<?>[]{String.class,String.class,String.class},page,"data:text/html,preview","clipboard.write"));
  eq(true,invoke("allowBrowser",new Class<?>[]{String.class},"https://example.com/a?q=b#c"));
  for(String link:Arrays.asList("javascript:alert(1)","intent://example.com/", "file:///etc/a","content://docs/a",
    "https://user:pass@example.com/","http://127.0.0.1/","http://localhost/","https://10.0.2.2/","https://[::1]/","https://example.com:444/"))
   eq(false,invoke("allowBrowser",new Class<?>[]{String.class},link));
  System.out.println("PASS audio resource/origin allowlist and frame-scoped finite device operations");
 }
}
