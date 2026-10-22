package us.pilipia.hermes.prototype;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

/** Executable policy shared by native callbacks. No credentials. The page origin is the chosen
 * server (or the setup origin), set only by MainActivity from a native-validated value. */
public final class NativeHostPolicy {
 private static volatile String origin=ServerOrigin.SETUP;
 private NativeHostPolicy(){}
 /** Exact page origin for every check below; only the setup origin or a normalized server origin. */
 public static void useOrigin(String value){
  if(!ServerOrigin.SETUP.equals(value)&&(value==null||!value.equals(ServerOrigin.normalize(value))))throw new IllegalArgumentException("Invalid page origin");
  origin=value;
 }
 public static String origin(){return origin;}
 public static String appUrl(){return origin+"/assets/index.html";}
 public static boolean setup(){return ServerOrigin.SETUP.equals(origin);}
 public static boolean isAppPage(String page){
  if(page==null)return false;
  try{
   URI uri=new URI(page);
   // HashRouter changes only the same bundled document's fragment. Never normalize
   // authority/path, accept a query, or reuse this predicate for asset requests.
   return origin(uri)&&"/assets/index.html".equals(uri.getRawPath())&&uri.getRawQuery()==null;
  }catch(URISyntaxException e){return false;}
 }
 /** Only the same exact bundled document may reload or change its hash route. */
 public static boolean allowNavigation(String page,String target,String method,boolean mainFrame){
  return mainFrame&&"GET".equals(method)&&isAppPage(page)&&isAppPage(target);
 }
 /** JS request IDs restart on reload; neither epoch alone identifies their owner. */
 public static boolean allowAuthCallback(long requestedAuth,long currentAuth,long requestedDocument,long currentDocument,boolean destroyed){
  return !destroyed&&requestedAuth==currentAuth&&requestedDocument==currentDocument;
 }
 public static boolean allowAudio(String page,String requestOrigin,String[] resources){
  String current=origin;
  return isAppPage(page)&&(current.equals(requestOrigin)||(current+"/").equals(requestOrigin))
   &&resources!=null&&resources.length==1&&"android.webkit.resource.AUDIO_CAPTURE".equals(resources[0]);
 }
 public static boolean allowDevice(String page,String frameUrl,String operation){
  if(!isAppPage(page)||!isAppPage(frameUrl)||operation==null)return false;
  switch(operation){
   case "clipboard.write":case "browser.open":case "document.save":case "document.share":
   case "screen.keepAwake":case "notification.show":return true;
   default:return false;
  }
 }
 public static boolean allowBrowser(String value){
  if(value==null||value.length()>4096||value.matches(".*[\\x00-\\x20\\x7f].*"))return false;
  try{
   URI uri=new URI(value);String host=uri.getHost();
   if(!("https".equals(uri.getScheme())||"http".equals(uri.getScheme()))||uri.getUserInfo()!=null
      ||uri.getPort()!=-1||host==null||!host.contains(".")||host.contains(":"))return false;
   String lower=host.toLowerCase(Locale.ROOT);
   return !(lower.endsWith(".localhost")||lower.endsWith(".local")||lower.matches("[0-9.]+"));
  }catch(URISyntaxException e){return false;}
 }
 /** Desktop's openExternal for the system browser: http/https with a host, no userinfo, bounded. */
 public static boolean allowExternal(String value){
  if(value==null||value.length()>4096||value.matches(".*[\\x00-\\x20\\x7f].*"))return false;
  try{
   URI uri=new URI(value);String scheme=uri.getScheme()==null?"":uri.getScheme().toLowerCase(Locale.ROOT);
   return ("https".equals(scheme)||"http".equals(scheme))&&uri.getHost()!=null&&uri.getRawUserInfo()==null;
  }catch(URISyntaxException e){return false;}
 }
 /**
  * The in-app browser pane (R1 stage 1): http/https with a host, any port, no userinfo, bounded,
  * never the Hermes server the app uses (its pages would share the app's storage), never loopback,
  * link-local or private IP literals or local names.
  */
 public static boolean allowGuest(String value){
  if(!allowExternal(value))return false;
  try{
   URI uri=new URI(value);String scheme=uri.getScheme().toLowerCase(Locale.ROOT);
   String host=uri.getHost().toLowerCase(Locale.ROOT);
   if(host.startsWith("[")||host.contains(":"))return false;
   if(host.equals("localhost")||host.endsWith(".localhost")||host.endsWith(".local")||host.endsWith(".internal")||!host.contains("."))return false;
   if(host.matches("[0-9.]+")){
    String[] p=host.split("\\.");
    if(p.length!=4)return false;
    int a=Integer.parseInt(p[0]),b=Integer.parseInt(p[1]);
    if(a==0||a==10||a==127||a>=224||(a==169&&b==254)||(a==172&&b>=16&&b<=31)||(a==192&&b==168)||(a==100&&b>=64&&b<=127))return false;
   }
   int port=uri.getPort()==-1?("https".equals(scheme)?443:80):uri.getPort();
   String current=origin;
   URI server=new URI(current);
   int serverPort=server.getPort()==-1?443:server.getPort();
   return !(host.equals(server.getHost().toLowerCase(Locale.ROOT))&&port==serverPort&&"https".equals(scheme));
  }catch(URISyntaxException|NumberFormatException e){return false;}
 }
 private static boolean origin(URI uri){
  // Exact authority string: the setup or server host, plus its non-default port if it has one.
  return "https".equals(uri.getScheme())&&origin.substring(8).equals(uri.getRawAuthority())&&uri.getUserInfo()==null;
 }
 public static String assetPath(String url,String method){
  if(url==null||!"GET".equals(method))return null;
  try{
   URI uri=new URI(url);
   if(!origin(uri)||uri.getRawQuery()!=null||uri.getRawFragment()!=null)return null;
   String raw=uri.getRawPath();
   if(raw==null||!raw.startsWith("/assets/"))return null;
   String path=raw.substring(8);
   // Packaged Vite output uses literal safe filenames. Reject escaped/double-escaped paths.
   if(path.isEmpty()||path.contains("%")||path.contains("\\")||path.contains("//"))return null;
   for(String part:path.split("/",-1))if(part.isEmpty()||part.equals(".")||part.equals("..")||!part.matches("[A-Za-z0-9_.@+ -]+"))return null;
   return path;
  }catch(URISyntaxException e){return null;}
 }
 public static String mimeType(String path){
  String suffix=path.substring(path.lastIndexOf('.')+1).toLowerCase(Locale.ROOT);
  switch(suffix){
   case "html":return "text/html";
   case "js":case "mjs":return "application/javascript";
   case "css":return "text/css";
   case "json":case "map":return "application/json";
   case "wasm":return "application/wasm";
   case "woff":return "font/woff";case "woff2":return "font/woff2";
   case "ttf":return "font/ttf";case "otf":return "font/otf";
   case "svg":return "image/svg+xml";case "png":return "image/png";
   case "jpg":case "jpeg":return "image/jpeg";case "webp":return "image/webp";
   case "gif":return "image/gif";case "ico":return "image/x-icon";case "avif":return "image/avif";
   case "mp3":return "audio/mpeg";case "ogg":return "audio/ogg";case "wav":return "audio/wav";
   case "mp4":return "video/mp4";case "webm":return "video/webm";
   case "txt":case "md":return "text/plain";case "pdf":return "application/pdf";
   default:return "application/octet-stream";
  }
 }
 public static String encoding(String mime){
  return mime.startsWith("text/")||mime.equals("application/javascript")||mime.equals("application/json")||mime.equals("image/svg+xml")?"UTF-8":null;
 }
}
