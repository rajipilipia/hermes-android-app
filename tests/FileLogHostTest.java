import java.io.ByteArrayInputStream;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
public final class FileLogHostTest {
 static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
 public static void main(String[] args)throws Exception{
  String red=us.pilipia.hermes.prototype.FileLog.redact("{\"text\":\"hello my chat\",\"access_token\":\"abcd1234efgh\",\"api_key\":\"sk-xyz98765\"} Authorization: Bearer abcdefghijklmnop ticket=zz99yy88 eyJhbGciOiJI.eyJzdWIiOiIx.c2lnbmF0dXJl");
  check(red.contains("hello my chat"),"chat text was removed");
  check(!red.contains("abcd1234efgh")&&!red.contains("sk-xyz98765")&&!red.contains("abcdefghijklmnop")&&!red.contains("zz99yy88")&&!red.contains("c2lnbmF0dXJl"),"secret kept: "+red);
  File dir=Files.createTempDirectory("filelog").toFile();
  us.pilipia.hermes.prototype.FileLog.writeAll(dir,new ByteArrayInputStream("one line here\nsecond line here\nthird line here\nfourth line here\n".getBytes(StandardCharsets.UTF_8)),20,2);
  String[] names=dir.list();java.util.Arrays.sort(names);
  check(names.length==2,"rotation did not keep the newest 2 files: "+names.length);
  check(new String(Files.readAllBytes(new File(dir,names[1]).toPath()),StandardCharsets.UTF_8).contains("fourth line here"),"newest line missing");
  System.out.println("PASS dev file log: chat kept, secrets masked, rotation keeps newest files");
 }
}
