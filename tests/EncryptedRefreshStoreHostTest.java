import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import javax.crypto.*;
import javax.crypto.spec.*;
import us.pilipia.hermes.prototype.NativeAuth;

/** Actual bounded codec/AES-GCM/files, injected JVM key only. Not Android Keystore proof. */
public final class EncryptedRefreshStoreHostTest {
 static void check(boolean b,String message){if(!b)throw new AssertionError(message);}
 static void rejects(NativeAuth.Store s)throws Exception{try{s.load();throw new AssertionError("bad stored credential accepted");}catch(IOException expected){}}
 public static void main(String[] args)throws Exception{
  Class<?> implementation,keys;
  try{implementation=Class.forName("us.pilipia.hermes.prototype.EncryptedRefreshStore");keys=Class.forName(implementation.getName()+"$Keys");}catch(ClassNotFoundException e){throw new AssertionError("No encrypted bounded refresh store exists",e);}
  Path dir=Paths.get(args[0]);Files.createDirectories(dir);for(File f:dir.toFile().listFiles())Files.delete(f.toPath());
  AtomicReference<SecretKey> key=new AtomicReference<>();
  Object source=Proxy.newProxyInstance(keys.getClassLoader(),new Class[]{keys},(o,m,a)->{
   if(m.getName().equals("delete")){key.set(null);return null;}
   if(key.get()==null && (Boolean)a[0]){KeyGenerator g=KeyGenerator.getInstance("AES");g.init(256);key.set(g.generateKey());}
   if(key.get()==null)throw new java.security.KeyStoreException("synthetic missing key");return key.get();
  });
  NativeAuth.Store s=(NativeAuth.Store)implementation.getConstructor(File.class,keys,String.class).newInstance(dir.toFile(),source,"https://gateway.example.com");
  check(s.load()==null,"empty not absent");
  NativeAuth.Credential fixture=new NativeAuth.Credential("synthetic-only-refresh-secret","nous",false);s.save(fixture);
  Path file=dir.resolve("refresh.v1.enc");byte[] first=Files.readAllBytes(file);
  check(!new String(first,StandardCharsets.ISO_8859_1).contains(fixture.refreshToken),"plaintext refresh on disk");
  NativeAuth.Credential loaded=s.load();check(loaded.refreshToken.equals(fixture.refreshToken)&&loaded.provider.equals("nous")&&!loaded.pending,"encrypted restore changed fields");
  s.save(fixture);check(!Arrays.equals(first,Files.readAllBytes(file)),"GCM nonce reused");
  // The server origin is authenticated data: the same record never restores for another server.
  rejects((NativeAuth.Store)implementation.getConstructor(File.class,keys,String.class).newInstance(dir.toFile(),source,"https://other.example.com"));
  byte[] good=Files.readAllBytes(file);good[good.length-1]^=1;Files.write(file,good);rejects(s);
  s.save(fixture);good=Files.readAllBytes(file);good[7]=99;Files.write(file,good);rejects(s);
  s.save(fixture);Files.write(file,new byte[100000]);rejects(s);
  s.save(fixture);key.set(null);rejects(s);
  check(Files.exists(file),"key invalidation silently overwrote/deleted record");
  s.clear();check(s.load()==null,"explicit clear retained credential");
  Object broken=Proxy.newProxyInstance(keys.getClassLoader(),new Class[]{keys},(o,m,a)->{throw new java.security.KeyStoreException("synthetic crypto unavailable");});
  NativeAuth.Store unavailable=(NativeAuth.Store)implementation.getConstructor(File.class,keys,String.class).newInstance(dir.toFile(),broken,"https://gateway.example.com");
  try{unavailable.save(fixture);throw new AssertionError("crypto failure pretended to save");}catch(IOException expected){}
  check(!Files.exists(file),"crypto failure created plaintext fallback");
  System.out.println("PASS real JVM AES-GCM encrypted-only/fresh nonce/bounded version/tamper/other-server/key-loss/fail-closed/clear (NOT Android Keystore)");
 }
}
