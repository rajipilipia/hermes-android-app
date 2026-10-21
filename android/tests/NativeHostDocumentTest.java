import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;

/** Actual document-byte preparation, not Android parser/runtime proof. */
public final class NativeHostDocumentTest {
 private static Class<?> document;
 private static int checks;
 private static byte[] prepare(byte[] html)throws Exception {
  try{return (byte[])document.getMethod("prepare",InputStream.class).invoke(null,new ByteArrayInputStream(html));}
  catch(InvocationTargetException failure){throw (Exception)failure.getCause();}
 }
 private static String prepare(String html)throws Exception{return new String(prepare(html.getBytes(StandardCharsets.UTF_8)),StandardCharsets.UTF_8);}
 private static void check(boolean condition,String label){checks++;if(!condition)throw new AssertionError(label);}
 private static void reject(byte[] html)throws Exception {
  try{prepare(html);throw new AssertionError("Expected rejected document");}catch(IOException expected){checks++;}
 }
 public static void main(String[] args)throws Exception {
  try{document=Class.forName("us.pilipia.hermes.prototype.BundledDocument");}
  catch(ClassNotFoundException missing){throw new AssertionError("Missing parser-before-renderer bundled-document bootstrap");}
  String source=new String(Files.readAllBytes(Paths.get("dist/index.html")),StandardCharsets.UTF_8);
  String prepared=prepare(source);
  String tag="<script src=\"/assets/native-lifecycle.js\"></script>";
  check(prepared.contains(tag),"fixed same-origin parser-blocking hook exists");
  check(prepared.indexOf(tag)==prepared.indexOf("<head>")+6,"hook is first head content before every renderer script");
  check(prepared.replace(tag,"").equals(source),"preserve all original document/CSP bytes");
  check(prepared.indexOf(tag)==prepared.lastIndexOf(tag),"exactly one hook");
  check(!tag.contains("defer")&&!tag.contains("async")&&!tag.contains("type="),"classic script blocks parser");
  for(String bad:new String[]{"<html><head></head></html>","<!doctype html><script>renderer()</script><html lang=\"en\"><head></head></html>",
   source.replace("<head>","<head><head>"),source.replace("<head>","<HEAD>"),source+tag})reject(bad.getBytes(StandardCharsets.UTF_8));
  reject(new byte[]{(byte)0xff});
  reject(new byte[1024*1024+1]);
  System.out.println("PASS bundled document bootstrap checks: "+checks);
  if(args.length==1)Files.write(Paths.get(args[0]),prepared.getBytes(StandardCharsets.UTF_8));
 }
}
