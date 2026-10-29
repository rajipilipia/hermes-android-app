package us.pilipia.hermes.prototype;
import java.util.Arrays;
public final class OfflinePreviewHostTest {
 public static void main(String[] args)throws Exception{
  String document=OfflinePreview.document("<button onclick=\"this.textContent='OK'\">Test</button>");
  if(!document.contains("connect-src 'none'")||!document.contains("frame-src 'none'")||!document.contains("onclick=")||!document.contains("no-referrer"))throw new AssertionError("Missing offline containment or interactive content");
  if(OfflinePreview.height("HERMES_OFFLINE_HEIGHT:240")!=240||OfflinePreview.height("HERMES_OFFLINE_HEIGHT:1200")!=1200)throw new AssertionError("Height");
  if(OfflinePreview.height("HERMES_OFFLINE_HEIGHT:1847")!=1847||OfflinePreview.height("HERMES_OFFLINE_HEIGHT:8192")!=8192)throw new AssertionError("Tall inline content is truncated");
  for(String value:new String[]{"secret", "HERMES_OFFLINE_HEIGHT:8193", "HERMES_OFFLINE_HEIGHT:99999", "HERMES_OFFLINE_HEIGHT:0", "HERMES_OFFLINE_HEIGHT:NaN", "HERMES_OFFLINE_HEIGHT:120;fetch('x')"})if(OfflinePreview.height(value)!=-1)throw new AssertionError("Unbounded height");
  java.util.ArrayDeque<Runnable> jobs=new java.util.ArrayDeque<>();
  java.util.List<Integer> emitted=new java.util.ArrayList<>();
  OfflinePreview.Heights reporter=new OfflinePreview.Heights(jobs::add,emitted::add);
  reporter.offer(120);reporter.offer(1847);
  if(jobs.size()!=1||!emitted.isEmpty())throw new AssertionError("Resize storm must be coalesced");
  jobs.remove().run();
  if(!emitted.equals(java.util.Arrays.asList(1847)))throw new AssertionError("Final startup height was lost");
  reporter.offer(1847);if(!jobs.isEmpty())throw new AssertionError("Duplicate height");
  reporter.offer(2000);reporter.reset();jobs.remove().run();
  if(emitted.size()!=1)throw new AssertionError("Stale document height");
  reporter.offer(1900);jobs.remove().run();
  if(!emitted.equals(java.util.Arrays.asList(1847,1900)))throw new AssertionError("New document height");
  char[] large=new char[OfflinePreview.MAX_BYTES/2+1];Arrays.fill(large,'汉');
  try{OfflinePreview.document(new String(large));throw new AssertionError("UTF-8 byte bound");}catch(IllegalArgumentException expected){}
  if(!NativeHostPolicy.requiresExternalAuthentication("https://accounts.google.com/gsi/transform"))throw new AssertionError("Google helper");
  if(!NativeHostPolicy.requiresExternalAuthentication("https://ACCOUNTS.GOOGLE.COM/o/oauth2/v2/auth"))throw new AssertionError("Google OAuth");
  for(String url:new String[]{"https://accounts.google.com.evil.test/gsi/transform","https://example.com/","file:///x",null})if(NativeHostPolicy.requiresExternalAuthentication(url))throw new AssertionError("Overbroad auth match");
  if(args.length==1)java.nio.file.Files.write(java.nio.file.Paths.get(args[0]),OfflinePreview.document("<button id='counter' onclick='this.textContent=Number(this.textContent)+1'>0</button><label>Filter<input id='filter'></label>").getBytes(java.nio.charset.StandardCharsets.UTF_8));
  System.out.println("PASS offline document policy, byte bounds, bounded height channel and exact Google-account host detection");
 }
}
