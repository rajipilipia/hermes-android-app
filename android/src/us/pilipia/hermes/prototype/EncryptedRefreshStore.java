package us.pilipia.hermes.prototype;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.charset.*;
import java.nio.file.*;
import java.security.*;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;

/** Bounded refresh-only codec. Production Keys are nonexportable AndroidKeyStore keys.
 * No credential logging, backup, access token, ticket, PKCE material or plaintext fallback.
 */
public final class EncryptedRefreshStore implements NativeAuth.Store {
 public interface Keys { SecretKey get(boolean create)throws GeneralSecurityException; void delete()throws GeneralSecurityException; }
 private static final Object LOCK=new Object();
 private static final int MAGIC=0x48524631,VERSION=1,MAX=20000;
 private final byte[] aad;
 private final File directory,file,temporary;
 private final Keys keys;
 /** The server origin is bound into the AAD: a record never decrypts for another server. */
 public EncryptedRefreshStore(File directory,Keys keys,String origin){
  aad=("us.pilipia.hermes.prototype\n"+origin+"\nrefresh-only\n1").getBytes(StandardCharsets.UTF_8);
  this.directory=directory;this.keys=keys;file=new File(directory,"refresh.v1.enc");temporary=new File(directory,"refresh.v1.tmp");
 }
 public NativeAuth.Credential load()throws IOException {
  synchronized(LOCK){
   if(!file.exists())return null;
   try{
    long length=file.length();if(length<40||length>MAX)throw new IOException("Invalid credential record");
    byte[] record=new byte[(int)length];
    try(DataInputStream in=new DataInputStream(new FileInputStream(file))){in.readFully(record);if(in.read()!=-1)throw new IOException("Invalid credential record");}
    DataInputStream in=new DataInputStream(new ByteArrayInputStream(record));
    if(in.readInt()!=MAGIC||in.readInt()!=VERSION)throw new IOException("Unsupported credential record");
    byte[] nonce=new byte[12];in.readFully(nonce);byte[] encrypted=new byte[record.length-20];in.readFully(encrypted);
    Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,keys.get(false),new GCMParameterSpec(128,nonce));cipher.updateAAD(aad);
    byte[] plain=cipher.doFinal(encrypted);
    try{
     DataInputStream fields=new DataInputStream(new ByteArrayInputStream(plain));String refresh=readText(fields,16384),provider=readText(fields,64);
     int pending=fields.readUnsignedByte();if(pending>1||fields.read()!=-1)throw new IOException("Invalid credential fields");
     return new NativeAuth.Credential(refresh,provider,pending==1);
    }finally{java.util.Arrays.fill(plain,(byte)0);}
   }catch(GeneralSecurityException|RuntimeException failure){throw new IOException("Credential decryption unavailable");}
  }
 }
 public void save(NativeAuth.Credential credential)throws IOException {
  synchronized(LOCK){
   byte[] plain=null;
   try{
    ByteArrayOutputStream bytes=new ByteArrayOutputStream();DataOutputStream fields=new DataOutputStream(bytes);
    writeText(fields,credential.refreshToken,16384);writeText(fields,credential.provider,64);fields.writeByte(credential.pending?1:0);fields.flush();plain=bytes.toByteArray();
    Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,keys.get(true));cipher.updateAAD(aad);
    byte[] nonce=cipher.getIV();if(nonce==null||nonce.length!=12)throw new IOException("Invalid credential nonce");
    byte[] encrypted=cipher.doFinal(plain);
    if(!directory.isDirectory()&&!directory.mkdirs())throw new IOException("Credential directory unavailable");
    try(FileOutputStream output=new FileOutputStream(temporary);DataOutputStream record=new DataOutputStream(output)){
     record.writeInt(MAGIC);record.writeInt(VERSION);record.write(nonce);record.write(encrypted);record.flush();output.getFD().sync();
    }
    // Same-directory atomic replacement: a crash leaves old READY (before delivery),
    // PENDING (uncertain delivery), or the complete rotated record; never partial plaintext.
    Files.move(temporary.toPath(),file.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
   }catch(GeneralSecurityException|RuntimeException failure){throw new IOException("Credential encryption unavailable");}
   finally{if(plain!=null)java.util.Arrays.fill(plain,(byte)0);Files.deleteIfExists(temporary.toPath());}
  }
 }
 public void clear()throws IOException {
  synchronized(LOCK){
   // Delete the wrapping key first: even a subsequent filesystem failure cannot restore login.
   try{keys.delete();}catch(GeneralSecurityException|RuntimeException failure){throw new IOException("Credential deletion unavailable");}
   Files.deleteIfExists(file.toPath());Files.deleteIfExists(temporary.toPath());
  }
 }
 private static void writeText(DataOutputStream out,String text,int max)throws IOException {
  byte[] bytes=text.getBytes(StandardCharsets.UTF_8);if(bytes.length==0||bytes.length>max)throw new IOException("Invalid credential fields");out.writeInt(bytes.length);out.write(bytes);
 }
 private static String readText(DataInputStream in,int max)throws IOException {
  int length=in.readInt();if(length<=0||length>max||length>in.available())throw new IOException("Invalid credential fields");
  byte[] bytes=new byte[length];in.readFully(bytes);
  return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
 }
}
