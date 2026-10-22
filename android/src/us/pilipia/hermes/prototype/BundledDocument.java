package us.pilipia.hermes.prototype;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Only for the exact index.html read from app-packaged www assets, never model HTML. */
public final class BundledDocument {
 private static final Pattern PREFIX=Pattern.compile("\\A<!doctype html>\\s*<html lang=\"en\">\\s*<head>");
 private static final String HOOK="<script src=\"/assets/native-lifecycle.js\"></script>";
 private BundledDocument(){}
 public static byte[] prepare(InputStream input)throws IOException {
  ByteArrayOutputStream bytes=new ByteArrayOutputStream();
  BoundedStreams.copy(input,bytes,1024*1024);
  String html=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
   .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes.toByteArray())).toString();
  Matcher prefix=PREFIX.matcher(html);
  // Fail closed on a changed document envelope instead of guessing where renderer
  // execution starts. This fixed classic external script blocks HTML parsing;
  // module/deferred renderer scripts cannot acquire/cache media before it runs.
  if(!prefix.find()||html.indexOf("<head>",prefix.end())!=-1||html.contains("native-lifecycle.js"))
   throw new IOException("Unrecognized bundled document bootstrap");
  return (html.substring(0,prefix.end())+HOOK+html.substring(prefix.end())).getBytes(StandardCharsets.UTF_8);
 }
}
