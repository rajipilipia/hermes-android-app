import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import java.util.function.Consumer;

/** Real NativeAuth with injected durable fixture, no Android or remote provider. */
public final class NativePersistenceHostTest {
 static Class<?> core,transport,store,credential;
 static final AtomicReference<Object> saved=new AtomicReference<>();
 static int saves; static boolean failSave;
 static void check(boolean b,String message){if(!b)throw new AssertionError(message);}
 static Object get(Object target,String name)throws Exception{return target.getClass().getField(name).get(target);}
 static Object invoke(Object target,String method)throws Exception{
  try{return target.getClass().getMethod(method).invoke(target);}catch(InvocationTargetException e){throw (Exception)e.getCause();}
 }
 static Object fixture()throws Exception{return Proxy.newProxyInstance(core.getClassLoader(),new Class[]{store},(o,m,a)->{
  switch(m.getName()) {case "load":return saved.get();case "save":if(failSave)throw new java.io.IOException("synthetic save failure");saves++;saved.set(a[0]);return null;case "clear":saved.set(null);return null;default:throw new AssertionError(m);}
 });}
 static Map<String,Object> token(String access,String refresh,long expiry){Map<String,Object> t=NativeAuthHostTest.token(access,expiry);t.put("refresh_token",refresh);return t;}
 static Object auth(InvocationHandler handler)throws Exception{return core.getConstructor(transport,store,String.class).newInstance(NativeAuthHostTest.http(core,transport,handler),fixture(),"https://gateway.example.com");}
 static void login(Object auth)throws Exception {try{core.getMethod("signIn",Consumer.class,int.class).invoke(auth,(Consumer<String>)(url)->{try{NativeAuthHostTest.get(NativeAuthHostTest.callback(url,null));}catch(Exception e){throw new RuntimeException(e);}},2000);}catch(InvocationTargetException e){throw (Exception)e.getCause();}}
 public static void main(String[] args)throws Exception{
  core=Class.forName("us.pilipia.hermes.prototype.NativeAuth");transport=Class.forName(core.getName()+"$Transport");
  try{store=Class.forName(core.getName()+"$Store");credential=Class.forName(core.getName()+"$Credential");}catch(ClassNotFoundException missing){throw new AssertionError("NativeAuth has no refresh-only durable store; restart loses sign-in",missing);}
  AtomicInteger renewals=new AtomicInteger(),tickets=new AtomicInteger();
  InvocationHandler http=(o,m,a)->{
   if(a[0].equals("/auth/native/token"))return token("fixture-access","fixture-refresh-1",System.currentTimeMillis()/1000+3600);
   if(a[0].equals("/auth/native/refresh")){check(((Map<?,?>)a[1]).get("refresh_token").equals("fixture-refresh-1"),"restore did not renew saved refresh");renewals.incrementAndGet();return token("fixture-access-new","fixture-refresh-2",System.currentTimeMillis()/1000+3600);}
   check(get(saved.get(),"refreshToken").equals("fixture-refresh-2"),"rotation published before durable save");Map<String,Object> r=new HashMap<>();r.put("ticket","fixture-ticket-"+tickets.incrementAndGet());return r;
  };
  Object first=auth(http);login(first);
  check(get(saved.get(),"refreshToken").equals("fixture-refresh-1"),"valid sign-in did not save refresh");
  check(credential.getFields().length==3,"store must expose only refresh/provider/pending metadata");
  Object restarted=auth(http);check(renewals.get()==0,"constructor did network before foreground admission");
  check(invoke(restarted,"ticket").equals("fixture-ticket-1"),"restore failed fresh ticket");
  check(invoke(restarted,"ticket").equals("fixture-ticket-2")&&renewals.get()==1,"restore did not single renewal then fresh tickets");
  invoke(restarted,"signOut");check(saved.get()==null,"explicit sign-out did not clear disk");
  try{invoke(auth(http),"ticket");throw new AssertionError("signed out record restored");}catch(java.io.IOException expected){}
  System.out.println("PASS durable refresh-only sign-in/restart/rotation-before-publication/fresh tickets/logout");
  lifecycleAndFailures(http);
  foregroundBeforeDispatch();
  cancellationBeforeDispatch();
  corruptRestore(http);
 }
 static void fails(Object auth)throws Exception{try{invoke(auth,"ticket");throw new AssertionError("expected closed auth");}catch(java.io.IOException expected){}}
 static void lifecycleAndFailures(InvocationHandler working)throws Exception {
  Object first=auth(working);login(first);invoke(first,"close");check(saved.get()!=null,"lifecycle close erased login");
  for(int status:new int[]{0,503,400,401,403}){
   saved.set(credential.getConstructor(String.class,String.class,boolean.class).newInstance("fixture-refresh-1","nous",false));
   AtomicInteger calls=new AtomicInteger();Object broken=auth((o,m,a)->{calls.incrementAndGet();if(status==0)throw new java.net.UnknownHostException("synthetic offline");throw new us.pilipia.hermes.prototype.NativeAuth.HttpFailure(status);});
   fails(broken);
   if(status==0||status==503){
    check(saved.get()!=null,"transient error erased durable credential");
    check((Boolean)get(saved.get(),"pending"),"ambiguous refresh must remain marked pending before delivery");
    fails(broken);fails(auth((o,m,a)->{throw new AssertionError("pending refresh replayed after restart");}));
    check(calls.get()==1,"automatic replay after ambiguous refresh");
   }else check(saved.get()==null,"invalid/revoked refresh not erased");
  }
  saved.set(null);failSave=true;
  Object failed=auth(working);try{login(failed);throw new AssertionError("save failure reported sign-in success");}catch(java.io.IOException expected){}finally{failSave=false;}
  check(saved.get()==null,"failed persistence stored login");fails(failed);
  for(boolean refresh:new boolean[]{false,true}){
   saved.set(null);AtomicReference<Object> owner=new AtomicReference<>();
   Object racing=auth((o,m,a)->{if(a[0].equals(refresh?"/auth/native/refresh":"/auth/native/token")){invoke(owner.get(),"signOut");return token("late-access","late-refresh",System.currentTimeMillis()/1000+3600);}return token("initial","fixture-refresh-1",1);});owner.set(racing);
   if(refresh){login(racing);fails(racing);}else try{login(racing);throw new AssertionError("late sign-in succeeded");}catch(java.io.IOException expected){}
   check(saved.get()==null,"late response resurrected logout");fails(racing);
  }
  System.out.println("PASS lifecycle preservation/offline/503/no-ambiguous-replay/revocation/save-failure/late-auth logout fences");
 }
 static void foregroundBeforeDispatch()throws Exception {
  saved.set(credential.getConstructor(String.class,String.class,boolean.class).newInstance("fixture-refresh-1","nous",false));
  AtomicBoolean foreground=new AtomicBoolean(false);AtomicInteger dispatched=new AtomicInteger();
  InvocationHandler gated=(o,m,a)->{
   String path;
   if(m.getName().equals("refresh")){
    if(!foreground.get())throw new java.io.IOException("synthetic foreground wait expired before HTTP");
    ((java.util.concurrent.Callable<?>)a[1]).call();path="/auth/native/refresh";
   }else{
    path=(String)a[0];
    if(m.getName().equals("dispatch"))((java.util.concurrent.Callable<?>)a[3]).call();
    if(path.equals("/auth/native/refresh")&&!foreground.get())throw new java.io.IOException("synthetic foreground wait expired before HTTP");
   }
   if(path.equals("/auth/native/refresh")){
    check((Boolean)get(saved.get(),"pending"),"refresh dispatched before durable pending marker");
    dispatched.incrementAndGet();return token("ready-access","ready-refresh",System.currentTimeMillis()/1000+3600);
   }
   Map<String,Object> reply=new HashMap<>();reply.put("ticket","ready-ticket");return reply;
  };
  Object a=core.getConstructor(transport,store,String.class).newInstance(Proxy.newProxyInstance(core.getClassLoader(),new Class[]{transport},gated),fixture(),"https://gateway.example.com");
  fails(a);check(dispatched.get()==0,"background readiness failure sent HTTP");
  check(!(Boolean)get(saved.get(),"pending"),"foreground wait poisoned saved login before HTTP dispatch");
  foreground.set(true);check(invoke(a,"ticket").equals("ready-ticket"),"foreground return failed existing login");
  check(dispatched.get()==1&&!(Boolean)get(saved.get(),"pending"),"foreground recovery did not rotate exactly once");
  System.out.println("PASS foreground readiness before refresh marker/no false ambiguity/exactly-once dispatch");
 }
 static void cancellationBeforeDispatch()throws Exception {
  for(String operation:new String[]{"token","ticket"})for(String cancellation:new String[]{"close","signOut"}){
   saved.set(null);AtomicReference<Object> owner=new AtomicReference<>();
   AtomicBoolean armed=new AtomicBoolean(operation.equals("token"));AtomicInteger dispatched=new AtomicInteger();
   String blocked=operation.equals("token")?"/auth/native/token":"/api/auth/ws-ticket";
   InvocationHandler waiting=(o,m,a)->{
    String path=(String)a[0];
    // Model cancellation while native transport is waiting for foreground.
    if(path.equals(blocked)&&armed.get())invoke(owner.get(),cancellation);
    if(m.getName().equals("dispatch"))((java.util.concurrent.Callable<?>)a[3]).call();
    if(path.equals(blocked))dispatched.incrementAndGet();
    if(path.equals("/auth/native/token"))return token("fixture-access","fixture-refresh-1",System.currentTimeMillis()/1000+3600);
    Map<String,Object> reply=new HashMap<>();reply.put("ticket","fixture-ticket");return reply;
   };
   Object a=core.getConstructor(transport,store,String.class).newInstance(Proxy.newProxyInstance(core.getClassLoader(),new Class[]{transport},waiting),fixture(),"https://gateway.example.com");owner.set(a);
   if(operation.equals("ticket")){login(a);armed.set(true);fails(a);}
   else try{login(a);throw new AssertionError("cancelled token exchange succeeded");}catch(java.io.IOException expected){}
   check(dispatched.get()==0,"cancelled "+operation+" dispatched HTTP after foreground wait / "+cancellation);
   if(cancellation.equals("signOut"))check(saved.get()==null,"cancelled dispatch restored signed-out credentials");
   else if(operation.equals("ticket"))check(saved.get()!=null,"lifecycle cancellation erased saved login");
  }
  System.out.println("PASS foreground-wait cancellation blocks token/ticket HTTP for close and sign-out");
 }
 static void corruptRestore(InvocationHandler http)throws Exception {
  AtomicBoolean corrupt=new AtomicBoolean(true),cleared=new AtomicBoolean();
  Object damaged=Proxy.newProxyInstance(core.getClassLoader(),new Class[]{store},(o,m,a)->{
   if(m.getName().equals("load"))throw new java.io.IOException("synthetic invalidated key");
   if(m.getName().equals("clear")){corrupt.set(false);cleared.set(true);return null;}
   check(!corrupt.get(),"explicit fresh sign-in failed to reset invalid storage");saved.set(a[0]);return null;
  });
  Object a;
  try{a=core.getConstructor(transport,store,String.class).newInstance(NativeAuthHostTest.http(core,transport,http),damaged,"https://gateway.example.com");}
  catch(InvocationTargetException e){throw new AssertionError("corrupt store prevents explicit fresh login instead of fail-closed unauthenticated restore",e.getCause());}
  fails(a);check(!cleared.get(),"corrupt restore erased data without explicit action");login(a);check(cleared.get(),"fresh sign-in did not repair invalid storage");
  System.out.println("PASS corrupt/key-invalid restore stays unauthenticated; only explicit fresh sign-in repairs storage");
 }
}
