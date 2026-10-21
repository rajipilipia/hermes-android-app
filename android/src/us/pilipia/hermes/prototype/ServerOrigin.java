package us.pilipia.hermes.prototype;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

/** The user-chosen Hermes server. Native is the only place that accepts one; JS never passes paths or headers. */
public final class ServerOrigin {
 /** Page origin while no server is set up. Never a server: normalize() rejects .invalid. */
 public static final String SETUP="https://setup.hermes-android.invalid";
 /** Nous Portal, where Hermes Cloud users find their agents (Desktop's default portal base). */
 public static final String PORTAL="https://portal.nousresearch.com/";
 private static final String CLOUD_AGENT_SUFFIX=".agents.nousresearch.com";
 private static final String LABEL="[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?";
 private ServerOrigin(){}
 /**
  * Returns the canonical {@code https://host[:port]} origin, or null. A missing scheme or http:// is
  * upgraded to https (never downgraded). Rejects paths, query, fragment, userinfo, IP literals and
  * local-only names: the server needs a real HTTPS name (Cloudflare Tunnel, Tailscale Serve, a proxy).
  */
 public static String normalize(String value){
  if(value==null)return null;
  String text=value.trim();
  if(text.isEmpty()||text.length()>2048||text.matches(".*[\\x00-\\x20\\x7f].*"))return null;
  String lower=text.toLowerCase(Locale.ROOT);
  if(lower.startsWith("http://"))text="https://"+text.substring(7);
  else if(!lower.contains("://"))text="https://"+text;
  try{
   URI uri=new URI(text);
   if(!"https".equalsIgnoreCase(uri.getScheme())||uri.getRawUserInfo()!=null||uri.getRawQuery()!=null||uri.getRawFragment()!=null)return null;
   String path=uri.getRawPath();
   if(path!=null&&!path.isEmpty()&&!"/".equals(path))return null;
   String host=uri.getHost();
   if(host==null)return null;
   host=host.toLowerCase(Locale.ROOT);
   if(host.length()>253||!host.matches(LABEL+"(?:\\."+LABEL+")+")||host.matches("[0-9.]+"))return null;
   for(String local:new String[]{".localhost",".local",".invalid",".test",".example",".internal",".lan",".home.arpa"})
    if(host.endsWith(local))return null;
   int port=uri.getPort();
   String authority=uri.getRawAuthority();
   if(port==-1&&!host.equals(authority.toLowerCase(Locale.ROOT)))return null;
   if(port!=-1&&(port<1||port>65535||!(host+":"+port).equals(authority.toLowerCase(Locale.ROOT))))return null;
   return "https://"+host+(port==-1||port==443?"":":"+port);
  }catch(URISyntaxException failure){return null;}
 }
 /** A Hermes Cloud agent dashboard (Desktop's own host check: the agents.nousresearch.com suffix). */
 public static boolean cloudAgent(String origin){
  return origin!=null&&origin.equals(normalize(origin))&&origin.indexOf(':',8)<0&&origin.endsWith(CLOUD_AGENT_SUFFIX);
 }
 /** Host (and port) for user-facing confirmation text. */
 public static String label(String origin){return origin==null?"":origin.substring("https://".length());}
}
