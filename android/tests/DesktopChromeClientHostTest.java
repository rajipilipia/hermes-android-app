package us.pilipia.hermes.prototype;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Handler;
import android.view.ViewGroup;
import android.webkit.*;
import java.lang.reflect.Field;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

/** Real callback/executor code with fake Activity/Handler, not Android runtime proof. */
public final class DesktopChromeClientHostTest {
 private static int checks;
 private static void check(boolean value,String label){checks++;if(!value)throw new AssertionError(label);}
 private static void await(CountDownLatch latch)throws Exception{check(latch.await(5,TimeUnit.SECONDS),"bounded latch progress");}
 private static void uninterruptibly(CountDownLatch latch){boolean interrupted=false;while(true){try{latch.await();break;}catch(InterruptedException ignored){interrupted=true;}}if(interrupted)Thread.currentThread().interrupt();}
 private static final class Host implements DesktopChromeClient.Host {
  final WebView web=new WebView();final ViewGroup container=new ViewGroup();boolean foreground=true,page=true;
  public boolean active(){return foreground&&page&&NativeHostPolicy.isAppPage(web.getUrl());}
  public boolean page(){return page&&NativeHostPolicy.isAppPage(web.getUrl());}
  public WebView web(){return web;}public ViewGroup container(){return container;}
  int notifications;
  int workCalls;
  public boolean work(boolean active){workCalls++;return !active||foreground;}
  public String notification(String operation,org.json.JSONObject payload){notifications++;return "{\"ok\":true}";}
 }
 private static ExecutorService files(DesktopChromeClient client)throws Exception{Field f=DesktopChromeClient.class.getDeclaredField("files");f.setAccessible(true);return (ExecutorService)f.get(client);}
 private static void queueBound()throws Exception {
  DesktopChromeClient client=new DesktopChromeClient(new Activity(),new Host());ExecutorService files=files(client);
  CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
  try {
   files.submit(()->{entered.countDown();uninterruptibly(release);});await(entered);
   Future<?> queued=files.submit(()->{});
   boolean rejected=false;try{files.submit(()->{});}catch(RejectedExecutionException expected){rejected=true;}
   check(rejected,"outer picker executor must reject beyond one worker and one queue slot");
   check(((ThreadPoolExecutor)files).getMaximumPoolSize()==1,"one outer worker");
   queued.cancel(true);
  } finally {release.countDown();client.destroy();check(files.awaitTermination(5,TimeUnit.SECONDS),"executor terminates");}
 }
 private static void cancellationReclaimsQueueAndCallbacks()throws Exception {
  Activity activity=new Activity();Host host=new Host();DesktopChromeClient client=new DesktopChromeClient(activity,host);ExecutorService files=files(client);
  CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
  AtomicInteger calls=new AtomicInteger();
  try {
   files.submit(()->{entered.countDown();uninterruptibly(release);});await(entered);
   for(int i=0;i<100;i++) {
    AtomicInteger once=new AtomicInteger();
    client.onShowFileChooser(host.web,value->{check(value==null,"cancellation is null");check(once.incrementAndGet()==1,"exactly-once cancellation");calls.incrementAndGet();},new WebChromeClient.FileChooserParams());
    int request=activity.requestCode;
    check(client.onActivityResult(request,Activity.RESULT_OK,new Intent().setData(Uri.parse("content://selected/item"))),"owned picker result");
    check(((ThreadPoolExecutor)files).getQueue().size()==1,"current staging task queued");
    check(client.onActivityResult(request,Activity.RESULT_OK,new Intent()),"duplicate owned result consumed inertly");
    check(((ThreadPoolExecutor)files).getQueue().size()==1,"duplicate result must not enqueue work or cancel owner");
    check(once.get()==0,"duplicate result cannot complete current callback early");
    client.documentChanged();
    check(((ThreadPoolExecutor)files).getQueue().isEmpty(),"cancel removes queued FutureTask immediately");
    check(Handler.delayedCount()==0,"cancel removes callback timeout retention");
    check(!client.onActivityResult(request,Activity.RESULT_OK,new Intent()),"stale request inert");
   }
   check(calls.get()==100,"every cancelled owner completed once");
   // Occupied queue: rejection still completes the active callback once.
   Future<?> occupied=files.submit(()->{});
   AtomicInteger rejected=new AtomicInteger();
   client.onShowFileChooser(host.web,v->{check(v==null,"rejected task is null");rejected.incrementAndGet();},new WebChromeClient.FileChooserParams());
   client.onActivityResult(activity.requestCode,Activity.RESULT_OK,new Intent());
   check(rejected.get()==1,"rejection completes exactly once");
   client.documentChanged();check(rejected.get()==1,"later invalidation cannot redeliver rejection");
   occupied.cancel(true);((ThreadPoolExecutor)files).remove((Runnable)occupied);
   client.destroy();client.destroy();check(calls.get()==100,"idempotent destroy");
  } finally {release.countDown();client.destroy();check(files.awaitTermination(5,TimeUnit.SECONDS),"bounded executor shutdown");Handler.drain();}
 }
 public static void main(String[] args)throws Exception {
  NativeHostPolicy.useOrigin("https://gateway.example.com");
  notificationBoundary();
  workBoundary();
  queueBound();cancellationReclaimsQueueAndCallbacks();
  System.out.println("PASS DesktopChromeClient bounded executor/callback checks: "+checks);
 }
 private static void notificationBoundary()throws Exception {
  Host host=new Host();DesktopChromeClient chrome=new DesktopChromeClient(new Activity(),host);
  String marker="hermes.android.notifications.v1", page=host.web.getUrl(), data="{\"operation\":\"status\",\"payload\":{}}";
  try{
   JsPromptResult result=new JsPromptResult();
   check(chrome.onJsPrompt(host.web,page,marker,data,result),"notification standard prompt seam absent");
   check(host.notifications==1&&"{\"ok\":true}".equals(result.value),"trusted notification callback not dispatched");
   for(String url:new String[]{"https://evil.invalid/",NativeHostPolicy.appUrl()+"?x=1"}){
    result=new JsPromptResult();chrome.onJsPrompt(host.web,url,marker,data,result);
    check(host.notifications==1,"foreign frame/document dispatched native notification");
   }
   chrome.onJsPrompt(new WebView(),page,marker,data,new JsPromptResult());
   chrome.onJsPrompt(host.web,page,marker,"{\"operation\":\"fetch\",\"payload\":{}}",new JsPromptResult());
   chrome.onJsPrompt(host.web,page,marker,"{\"operation\":\"status\",\"payload\":{},\"url\":\"https://evil.invalid\"}",new JsPromptResult());
   host.page=false;chrome.onJsPrompt(host.web,page,marker,data,new JsPromptResult());
   check(host.notifications==1,"invalid operation/owner/payload dispatched");
   host.page=true;chrome.destroy();chrome.onJsPrompt(host.web,page,marker,data,new JsPromptResult());
   check(host.notifications==1,"destroyed chrome dispatched native notification");
  }finally{chrome.destroy();}
  System.out.println("PASS real WebChromeClient notification prompt exact-document/owner/operation boundary");
 }
 private static void workBoundary()throws Exception {
  Host host=new Host();DesktopChromeClient chrome=new DesktopChromeClient(new Activity(),host);
  String marker="hermes.android.work.v1",page=host.web.getUrl();
  try{
   JsPromptResult result=new JsPromptResult();
   chrome.onJsPrompt(host.web,page,marker,"{\"active\":true}",result);
   check(host.workCalls==1&&"{\"ok\":true}".equals(result.value),"trusted work request not dispatched");
   for(String invalid:new String[]{"{}","{\"active\":\"true\"}","{\"active\":true,\"url\":\"https://evil.invalid\"}"})
    chrome.onJsPrompt(host.web,page,marker,invalid,new JsPromptResult());
   chrome.onJsPrompt(host.web,"https://evil.invalid/",marker,"{\"active\":true}",new JsPromptResult());
   chrome.onJsPrompt(new WebView(),page,marker,"{\"active\":true}",new JsPromptResult());
   check(host.workCalls==1,"invalid schema/frame/owner entered work controller");
   host.foreground=false;result=new JsPromptResult();
   chrome.onJsPrompt(host.web,page,marker,"{\"active\":true}",result);
   check("{\"ok\":false}".equals(result.value),"background start was accepted");
   chrome.destroy();chrome.onJsPrompt(host.web,page,marker,"{\"active\":false}",new JsPromptResult());
   check(host.workCalls==2,"destroyed document controlled work");
  }finally{chrome.destroy();}
  System.out.println("PASS real WebChromeClient work bridge exact-page/boolean-only/background/destroy boundary");
 }
}
