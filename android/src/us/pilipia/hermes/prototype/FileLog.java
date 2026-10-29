package us.pilipia.hermes.prototype;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Arrays;
import java.util.Collections;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.Pattern;

/** DEV PHONE ONLY (the author, 2026-10-28: "save all on the phone no matter what"). Saves this app's
 *  whole log (native lines, every WebView console line, crashes) to rotating files in the app's
 *  external files folder: Android/data/us.pilipia.hermes.prototype/files/logs/. Chat text is kept;
 *  passwords, tokens and keys are masked. The app reads only its own log (no permission). */
public final class FileLog {
 static final long MAX_FILE=8L<<20;
 static final int KEEP=20;
 private static final AtomicBoolean STARTED=new AtomicBoolean();
 // Values after secret-looking names, Bearer values and JWTs.
 private static final Pattern SECRET_FIELD=Pattern.compile("(?i)(\"?[a-z_]*(?:token|secret|password|passwd|api_?key|authorization|cookie|ticket|refresh)[a-z_]*\"?\\s*[:=]\\s*\"?)[^\\s\",;&}]{4,}");
 private static final Pattern BEARER=Pattern.compile("(?i)(bearer\\s+)[A-Za-z0-9._~+/=-]{8,}");
 private static final Pattern JWT=Pattern.compile("eyJ[A-Za-z0-9_-]{8,}\\.[A-Za-z0-9_-]{8,}\\.[A-Za-z0-9_-]{8,}");

 private FileLog(){}

 /** Host tests: write a stream through the same redaction and rotation. */
 public static void writeAll(File dir,InputStream input,long maxBytes,int keep)throws IOException{copy(input,new Sink(dir,maxBytes,keep),"");}

 public static String redact(String line){
  // Bearer first: "Authorization: Bearer x" would otherwise mask only the word "Bearer".
  String out=BEARER.matcher(line).replaceAll("$1[redacted]");
  out=SECRET_FIELD.matcher(out).replaceAll("$1[redacted]");
  return JWT.matcher(out).replaceAll("[redacted-jwt]");
 }

 /** Starts once per process: earlier crash lines, then this process's live log. */
 static void start(final File dir,final int pid){
  if(dir==null||!STARTED.compareAndSet(false,true))return;
  Thread thread=new Thread(new Runnable(){public void run(){
   try{
    Sink sink=new Sink(dir,MAX_FILE,KEEP);
    sink.line("=== hermes file log start pid="+pid+" "+stamp("yyyy-MM-dd HH:mm:ss Z"));
    copy(new ProcessBuilder("logcat","-d","-b","crash","-v","threadtime").redirectErrorStream(true).start().getInputStream(),sink,"[earlier crash] ");
    copy(new ProcessBuilder("logcat","-b","main,system,crash","-v","threadtime","--pid="+pid).redirectErrorStream(true).start().getInputStream(),sink,"");
   }catch(Throwable failure){System.err.println("HermesDiag event=file_log_failed error="+failure.getClass().getSimpleName());}
  }},"hermes-file-log");
  thread.setDaemon(true);
  thread.start();
 }

 static void copy(InputStream input,Sink sink,String prefix)throws IOException{
  try(BufferedReader reader=new BufferedReader(new InputStreamReader(input,StandardCharsets.UTF_8))){
   for(String line;(line=reader.readLine())!=null;)sink.line(prefix+redact(line));
  }
 }

 static String stamp(String format){return new SimpleDateFormat(format,Locale.US).format(new Date());}

 /** Appends lines to hermes-<start time>-<part>.log, opens the next part past maxBytes and
  *  keeps the newest `keep` files (names sort by time, then part). */
 static final class Sink{
  private final File dir;private final long maxBytes;private final int keep;private final String started=stamp("yyyyMMdd-HHmmss");
  private OutputStream out;private long size;private int part;
  Sink(File dir,long maxBytes,int keep)throws IOException{
   this.dir=dir;this.maxBytes=maxBytes;this.keep=keep;
   if(!dir.isDirectory()&&!dir.mkdirs())throw new IOException("log folder");
   open();
  }
  private void open()throws IOException{
   if(out!=null)out.close();
   out=new FileOutputStream(new File(dir,String.format(Locale.US,"hermes-%s-%03d.log",started,part++)));size=0;
   prune(dir,keep);
  }
  synchronized void line(String text)throws IOException{
   byte[] bytes=(text+"\n").getBytes(StandardCharsets.UTF_8);
   if(size>0&&size+bytes.length>maxBytes)open();
   out.write(bytes);out.flush();size+=bytes.length;
  }
 }

 static void prune(File dir,int keep){
  String[] names=dir.list((parent,name)->name.startsWith("hermes-")&&name.endsWith(".log"));
  if(names==null||names.length<=keep)return;
  Arrays.sort(names,Collections.reverseOrder());
  for(int i=keep;i<names.length;i++)new File(dir,names[i]).delete();
 }
}
