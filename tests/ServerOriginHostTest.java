import us.pilipia.hermes.prototype.ServerOrigin;

/** The only gate for a user-typed server: https host (+port) or nothing. */
public final class ServerOriginHostTest {
 static void check(boolean b,String message){if(!b)throw new AssertionError(message);}
 static void same(String input,String expected){
  String got=ServerOrigin.normalize(input);
  check(expected.equals(got),input+" -> "+got+" (expected "+expected+")");
 }
 public static void main(String[] args){
  same("https://gateway.example.com","https://gateway.example.com");
  same("  https://Gateway.Example.COM/  ","https://gateway.example.com");
  same("gateway.example.com","https://gateway.example.com");
  same("http://gateway.example.com","https://gateway.example.com");
  same("https://gateway.example.com:443","https://gateway.example.com");
  same("https://gateway.example.com:8443","https://gateway.example.com:8443");
  same("pc.tailnet-1234.ts.net","https://pc.tailnet-1234.ts.net");
  for(String bad:new String[]{null,"","   ","https://","ftp://gateway.example.com","wss://gateway.example.com",
    "https://gateway.example.com/path","https://gateway.example.com/assets/index.html","https://gateway.example.com?x=1",
    "https://gateway.example.com#x","https://user@gateway.example.com","https://user:pw@gateway.example.com",
    "https://192.168.1.10","https://100.64.0.1:9119","https://[::1]","https://localhost","https://pc.local",
    "https://pc.localhost","https://setup.hermes-android.invalid","https://intranet","https://gateway.example.com:0",
    "https://gateway.example.com:70000","https://gate way.example.com","https://-bad.example.com",
    "https://gate\tway.example.com","https://gäteway.example.com","javascript:alert(1)"})
   check(ServerOrigin.normalize(bad)==null,"accepted "+bad);
  check(ServerOrigin.normalize(ServerOrigin.SETUP)==null,"setup origin accepted as a server");
  check("gateway.example.com:8443".equals(ServerOrigin.label("https://gateway.example.com:8443")),"label");
  check(ServerOrigin.cloudAgent("https://my-agent.agents.nousresearch.com"),"cloud agent rejected");
  for(String other:new String[]{"https://gateway.example.com","https://agents.nousresearch.com","https://x.agents.nousresearch.com:8443",
    "https://x.agents.nousresearch.com.evil.example","https://xagents.nousresearch.com","http://x.agents.nousresearch.com",null})
   check(!ServerOrigin.cloudAgent(other),"accepted as cloud agent: "+other);
  System.out.println("PASS server origin: https host/port only; no path, query, userinfo, IP, local name or setup origin; exact cloud-agent suffix");
 }
}
