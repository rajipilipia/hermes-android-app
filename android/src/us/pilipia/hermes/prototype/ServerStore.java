package us.pilipia.hermes.prototype;

import android.content.Context;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;

/** The chosen server origin. Not a secret, but app-private and no-backup like the credential. */
public final class ServerStore {
 private final File directory,file,temporary;
 public ServerStore(Context context){this(new File(context.getNoBackupFilesDir(),"server"));}
 ServerStore(File directory){this.directory=directory;file=new File(directory,"origin.v1");temporary=new File(directory,"origin.v1.tmp");}
 /** The saved origin, or null when none is set up (or the record is not a valid origin). */
 public synchronized String load(){
  try{
   if(!file.isFile()||file.length()>2048)return null;
   String saved=new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8);
   String origin=ServerOrigin.normalize(saved);
   return saved.equals(origin)?origin:null;
  }catch(IOException failure){return null;}
 }
 public synchronized void save(String origin)throws IOException {
  if(origin==null||!origin.equals(ServerOrigin.normalize(origin)))throw new IOException("Invalid server origin");
  if(!directory.isDirectory()&&!directory.mkdirs())throw new IOException("Server directory unavailable");
  try(FileOutputStream output=new FileOutputStream(temporary)){output.write(origin.getBytes(StandardCharsets.UTF_8));output.getFD().sync();}
  Files.move(temporary.toPath(),file.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
 }
 public synchronized void clear()throws IOException {Files.deleteIfExists(file.toPath());Files.deleteIfExists(temporary.toPath());}
}
