package us.pilipia.hermes.prototype;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.system.Os;
import android.system.OsConstants;
import java.io.*;
import java.security.*;
import javax.crypto.*;

/** Production composition: app-private no-backup location and nonexportable native key, bound to one server. */
public final class AndroidRefreshStore implements NativeAuth.Store {
 private static final String ALIAS="us.pilipia.hermes.prototype.native-refresh.v1";
 private final File directory;
 private final EncryptedRefreshStore encrypted;
 public AndroidRefreshStore(Context context,String origin){
  directory=new File(context.getNoBackupFilesDir(),"native-auth");
  encrypted=new EncryptedRefreshStore(directory,new EncryptedRefreshStore.Keys(){
   private KeyStore store()throws GeneralSecurityException {
    try{KeyStore result=KeyStore.getInstance("AndroidKeyStore");result.load(null);return result;}
    catch(IOException e){throw new GeneralSecurityException("Native keystore unavailable");}
   }
   public SecretKey get(boolean create)throws GeneralSecurityException {
    KeyStore ks=store();Key existing=ks.getKey(ALIAS,null);
    if(existing instanceof SecretKey)return (SecretKey)existing;
    if(existing!=null||!create)throw new KeyStoreException("Native credential key unavailable");
    KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
    generator.init(new KeyGenParameterSpec.Builder(ALIAS,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
     .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
     .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setRandomizedEncryptionRequired(true).build());
    return generator.generateKey();
   }
   public void delete()throws GeneralSecurityException {store().deleteEntry(ALIAS);}
  },origin);
 }
 public NativeAuth.Credential load()throws IOException{return encrypted.load();}
 public void save(NativeAuth.Credential credential)throws IOException{encrypted.save(credential);syncDirectory();}
 public void clear()throws IOException{encrypted.clear();if(directory.exists())syncDirectory();}
 private void syncDirectory()throws IOException {
  java.io.FileDescriptor fd=null;
  try{fd=Os.open(directory.getPath(),OsConstants.O_RDONLY,0);Os.fsync(fd);}
  catch(android.system.ErrnoException e){throw new IOException("Credential directory sync unavailable");}
  finally{if(fd!=null)try{Os.close(fd);}catch(android.system.ErrnoException e){throw new IOException("Credential directory close unavailable");}}
 }
}
