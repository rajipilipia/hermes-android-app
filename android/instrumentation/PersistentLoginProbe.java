package us.pilipia.hermes.prototype.persistenceprobe;

import android.app.Instrumentation;
import android.content.Context;
import android.os.Bundle;
import android.os.Build;
import android.provider.Settings;
import android.security.keystore.KeyInfo;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.*;
import java.util.*;
import javax.crypto.SecretKey;
import javax.crypto.SecretKeyFactory;
import us.pilipia.hermes.prototype.AndroidRefreshStore;
import us.pilipia.hermes.prototype.NativeAuth;

/** Self-targeting test APK/UID only. No production context, live HTTP or real credentials. */
public final class PersistentLoginProbe extends Instrumentation {
 private static final String FIRST="SYNTHETIC_PERSISTENCE_PROBE_REFRESH_V1_NOT_A_CREDENTIAL";
 private static final String NEXT="SYNTHETIC_PERSISTENCE_PROBE_REFRESH_V2_NOT_A_CREDENTIAL";
 private static final String OWNER="hermes-isolated-persistence-probe-v1";
 private Bundle args;
 @Override public void onCreate(Bundle args){this.args=args;start();}
 private static void require(boolean condition)throws IOException{if(!condition)throw new IOException("Probe safety or acceptance gate failed");}
 private static String hash(File file)throws Exception {
  require(file.length()>0&&file.length()<=20000);
  byte[] bytes=MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file.toPath()));StringBuilder result=new StringBuilder();
  for(byte b:bytes)result.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return result.toString();
 }
 private static Properties marker(File owner)throws Exception {
  require(owner.isFile()&&owner.length()<1024);Properties result=new Properties();try(InputStream in=new FileInputStream(owner)){result.load(in);}
  require(OWNER.equals(result.getProperty("owner")));return result;
 }
 private static void own(File owner,File record,Properties data)throws Exception {
  data.setProperty("recordSha256",hash(record));File tmp=new File(owner.getPath()+".tmp");
  try(FileOutputStream out=new FileOutputStream(tmp)){data.store(out,null);out.getFD().sync();}
  Files.move(tmp.toPath(),owner.toPath(),java.nio.file.StandardCopyOption.ATOMIC_MOVE,java.nio.file.StandardCopyOption.REPLACE_EXISTING);
 }
 private static boolean lacks(File file,String text)throws Exception {return !new String(Files.readAllBytes(file.toPath()),StandardCharsets.ISO_8859_1).contains(text);}
 @Override public void onStart(){
  Bundle result=new Bundle();String phase=args==null?"":args.getString("phase","");
  try{
   // Self-targeting gives the test a DIFFERENT UID/Keystore namespace from Hermes.
   // Even interleaved production sign-in/logout cannot read or overwrite its state.
   require(("ranchu".equals(Build.HARDWARE)||"goldfish".equals(Build.HARDWARE))&&"us.pilipia.hermes.prototype.persistenceprobe".equals(getTargetContext().getPackageName())&&"us.pilipia.hermes.prototype.persistenceprobe".equals(getContext().getPackageName()));
   Context target=getContext();require(target.getApplicationInfo().uid==android.os.Process.myUid());
   File record=new File(target.getNoBackupFilesDir(),"native-auth/refresh.v1.enc");
   File partial=new File(target.getNoBackupFilesDir(),"native-auth/refresh.v1.tmp");
   File owner=new File(target.getNoBackupFilesDir(),"persistent-probe-owner.v1");
   AndroidRefreshStore store=new AndroidRefreshStore(target);
   int boot=Settings.Global.getInt(target.getContentResolver(),Settings.Global.BOOT_COUNT,-1);require(boot>=0);
   if("seed".equals(phase)){
    // Never decrypt, overwrite or delete a pre-existing production credential.
    require(!record.exists()&&!partial.exists()&&!owner.exists());
    Properties data=new Properties();data.setProperty("owner",OWNER);data.setProperty("boot",String.valueOf(boot));data.setProperty("pid",String.valueOf(android.os.Process.myPid()));
    store.save(new NativeAuth.Credential(FIRST,"nous",false));own(owner,record,data);
    require(lacks(record,FIRST));result.putBoolean("seeded_synthetic_only",true);
   }else if("verify-process".equals(phase)||"verify-reboot".equals(phase)||"cleanup".equals(phase)){
    Properties data=marker(owner);
    // Check the fixture-owned ciphertext hash BEFORE any decryption/key access.
    require(data.getProperty("recordSha256","").equals(hash(record)));
    NativeAuth.Credential saved=store.load();require(saved!=null&&(FIRST.equals(saved.refreshToken)||NEXT.equals(saved.refreshToken))&&"nous".equals(saved.provider)&&!saved.pending);
    if("cleanup".equals(phase)){
     NativeAuth auth=new NativeAuth((path,body,access)->{throw new AssertionError("Logout performed HTTP");},store);auth.signOut();
     require(!record.exists()&&!partial.exists()&&store.load()==null);Files.delete(owner.toPath());result.putBoolean("fixture_only_cleanup",true);
    }else{
     boolean processChanged=!String.valueOf(android.os.Process.myPid()).equals(data.getProperty("pid"));
     boolean rebootChanged=boot!=Integer.parseInt(data.getProperty("boot"));
     require(processChanged);if("verify-reboot".equals(phase))require(rebootChanged);
     final int[] calls={0,0};final String fixture=saved.refreshToken;
     NativeAuth auth=new NativeAuth((path,body,access)->{
      if("/auth/native/refresh".equals(path)){
       require(fixture.equals(body.get("refresh_token"))&&"nous".equals(body.get("provider"))&&access.isEmpty());calls[0]++;
       Map<String,Object> tokens=new HashMap<>();tokens.put("access_token","SYNTHETIC_RAM_ONLY_ACCESS");tokens.put("refresh_token",NEXT);tokens.put("provider","nous");tokens.put("expires_at",System.currentTimeMillis()/1000+3600);return tokens;
      }
      require("/api/auth/ws-ticket".equals(path)&&"SYNTHETIC_RAM_ONLY_ACCESS".equals(access));
      // Actual production store must contain rotation before a fresh ticket can be minted.
      require(NEXT.equals(store.load().refreshToken));Map<String,Object> reply=new HashMap<>();reply.put("ticket","SYNTHETIC_RAM_ONLY_TICKET_"+(++calls[1]));return reply;
     },store);
     require(calls[0]==0);String a=auth.ticket(),b=auth.ticket();require(!a.equals(b)&&calls[0]==1&&calls[1]==2);auth.close();
     require(NEXT.equals(store.load().refreshToken));own(owner,record,data);
     require(lacks(record,FIRST)&&lacks(record,NEXT)&&lacks(record,"SYNTHETIC_RAM_ONLY_ACCESS")&&lacks(record,"SYNTHETIC_RAM_ONLY_TICKET"));
     // Hardware backing is measured, never assumed from an emulator/JVM result.
     KeyStore ks=KeyStore.getInstance("AndroidKeyStore");ks.load(null);
     SecretKey key=(SecretKey)ks.getKey("us.pilipia.hermes.prototype.native-refresh.v1",null);
     KeyInfo info=(KeyInfo)SecretKeyFactory.getInstance(key.getAlgorithm(),"AndroidKeyStore").getKeySpec(key,KeyInfo.class);
     result.putBoolean("hardware_backed",info.isInsideSecureHardware());
     result.putBoolean("process_changed",processChanged);result.putBoolean("boot_changed",rebootChanged);
     result.putBoolean("restored_refresh_only",true);result.putBoolean("renewed_once_fresh_tickets",true);result.putBoolean("ciphertext_only",true);
    }
   }else if("check-cleared".equals(phase)){
    // Metadata absence only. Never load a record another user may have created.
    require(!record.exists()&&!partial.exists()&&!owner.exists());result.putBoolean("still_signed_out_after_restart",true);
   }else throw new IOException("Unknown probe phase");
   result.putBoolean("passed",true);finish(android.app.Activity.RESULT_OK,result);
  }catch(Throwable failure){
   // No throwable messages, tokens, keys, record bytes or account information leave the probe.
   result.clear();result.putBoolean("passed",false);result.putString("failure_class",failure.getClass().getSimpleName());finish(android.app.Activity.RESULT_CANCELED,result);
  }
 }
}
