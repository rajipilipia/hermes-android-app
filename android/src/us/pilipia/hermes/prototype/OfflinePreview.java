package us.pilipia.hermes.prototype;

import java.nio.charset.StandardCharsets;

/** Offline guest documents. No server URL, header, path or native interface is accepted. */
final class OfflinePreview {
 static final int MAX_BYTES=2*1024*1024;
 static final String ORIGIN="https://hermes-offline-preview.invalid/";
 static final String HEIGHT_PREFIX="HERMES_OFFLINE_HEIGHT:";
 static final String CSP="default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; frame-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'";
 static String document(String html){
  if(html==null||html.getBytes(StandardCharsets.UTF_8).length>MAX_BYTES)throw new IllegalArgumentException("HTML preview exceeds the 2 MiB limit.");
  // This first policy cannot be relaxed by a later policy in the supplied document.
  return "<!doctype html><meta http-equiv=\"Content-Security-Policy\" content=\""+CSP+"\"><meta name=\"referrer\" content=\"no-referrer\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
   +"<style>html,body{margin:0;background:transparent;overflow-wrap:anywhere}img,svg,canvas{max-width:100%}</style>"+html
   +"<script>(function(){var last=0;function size(){var b=document.body;if(!b)return;var h=Math.max(120,Math.min(8192,Math.ceil(b.scrollHeight)));if(h!==last){last=h;console.log('"+HEIGHT_PREFIX+"'+h)}};new ResizeObserver(size).observe(document.documentElement);addEventListener('load',size);size()})()</script>";
 }
 static int height(String message){
  if(message==null||!message.startsWith(HEIGHT_PREFIX))return -1;
  String value=message.substring(HEIGHT_PREFIX.length());
  if(!value.matches("[0-9]{1,4}"))return -1;
  int height=Integer.parseInt(value);return height>=120&&height<=8192?height:-1;
 }

 /** Bounded trailing delivery: startup's final size must not vanish inside a throttle window. */
 static final class Heights {
  private final java.util.function.Consumer<Runnable> later;
  private final java.util.function.IntConsumer receiver;
  private int latest=-1,sent=-1,generation;
  private boolean queued;
  Heights(java.util.function.Consumer<Runnable> later,java.util.function.IntConsumer receiver){this.later=later;this.receiver=receiver;}
  void offer(int height){
   if(height<120||height>8192)return;
   latest=height;if(queued||height==sent)return;
   queued=true;final int version=generation;
   later.accept(()->{
    if(version!=generation)return;
    queued=false;
    if(latest!=sent){sent=latest;receiver.accept(sent);}
   });
  }
  void reset(){generation++;queued=false;latest=-1;sent=-1;}
 }
}
