"""Actual DesktopChromeClient under minimal Android plumbing; no OS/WebView proof."""
from pathlib import Path
import os
import runpy
import shutil
import subprocess
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.cache/chrome-client-tests'
JDK = Path(os.environ.get('JAVA_HOME', 'C:/Program Files/Microsoft/jdk-21.0.8.9-hotspot')) / 'bin'
SRC = ROOT / 'android/src/us/pilipia/hermes/prototype'
STUBS = runpy.run_path(str(ROOT / 'android/tests/test-local-documents.py'))['STUBS'].copy()
STUBS.update({
'android/webkit/ConsoleMessage.java': 'package android.webkit; public class ConsoleMessage { public enum MessageLevel { TIP, LOG, WARNING, ERROR, DEBUG } public String message(){return "";} public MessageLevel messageLevel(){return MessageLevel.LOG;} }',
'android/util/Log.java': 'package android.util; public class Log { public static final java.util.List<String> lines=new java.util.ArrayList<>(); public static int i(String a,String b){lines.add(b);return 0;} }',
'android/webkit/JsPromptResult.java': 'package android.webkit; public class JsPromptResult { public String value; public void confirm(String value){this.value=value;} public void cancel(){value="cancelled";} }',
'android/Manifest.java': 'package android; public final class Manifest { public static class permission { public static final String RECORD_AUDIO="android.permission.RECORD_AUDIO"; } }',
'android/content/pm/PackageManager.java': 'package android.content.pm; public class PackageManager { public static final int PERMISSION_GRANTED=0; }',
'android/app/Activity.java': '''package android.app;
public class Activity extends android.content.Context {
 public static final int RESULT_OK=-1; public int requestCode; public int consentCode;
 public java.io.File getCacheDir(){return new java.io.File(System.getProperty("java.io.tmpdir"));}
 public android.content.ContentResolver getContentResolver(){return null;}
 public void startActivityForResult(android.content.Intent i,int code){requestCode=code;}
 public int checkSelfPermission(String permission){return -1;}
 public void requestPermissions(String[] permissions,int code){consentCode=code;}
}''',
'android/os/Looper.java': 'package android.os; public class Looper { public static Looper getMainLooper(){return new Looper();} }',
'android/os/Handler.java': '''package android.os;
public class Handler {
 private static final java.util.List<Runnable> posted=new java.util.ArrayList<Runnable>();
 private static final java.util.List<Runnable> delayed=new java.util.ArrayList<Runnable>();
 public Handler(Looper looper){}
 public boolean post(Runnable r){synchronized(posted){posted.add(r);}return true;}
 public boolean postDelayed(Runnable r,long delay){delayed.add(r);return true;}
 public void removeCallbacks(Runnable r){delayed.remove(r);synchronized(posted){posted.remove(r);}}
 public void removeCallbacksAndMessages(Object token){delayed.clear();synchronized(posted){posted.clear();}}
 public static int delayedCount(){return delayed.size();}
 public static void drain(){while(true){Runnable r;synchronized(posted){if(posted.isEmpty())return;r=posted.remove(0);}r.run();}}
}''',
'android/view/View.java': 'package android.view; public class View { public static final int VISIBLE=0,INVISIBLE=4; public void setVisibility(int value){} }',
'android/view/ViewGroup.java': '''package android.view; public class ViewGroup extends View { public static class LayoutParams { public LayoutParams(int a,int b){} } public void addView(View v,LayoutParams p){} public void removeView(View v){} }''',
'android/webkit/WebView.java': 'package android.webkit; public class WebView extends android.view.View { public String url="https://gateway.example.com/assets/index.html#settings"; public String getUrl(){return url;} }',
'android/webkit/ValueCallback.java': 'package android.webkit; public interface ValueCallback<T> { void onReceiveValue(T value); }',
'android/webkit/PermissionRequest.java': '''package android.webkit; public abstract class PermissionRequest { public static final String RESOURCE_AUDIO_CAPTURE="android.webkit.resource.AUDIO_CAPTURE"; public abstract android.net.Uri getOrigin(); public abstract String[] getResources(); public abstract void grant(String[] values); public abstract void deny(); }''',
'android/webkit/MimeTypeMap.java': 'package android.webkit; public class MimeTypeMap { public static MimeTypeMap getSingleton(){return new MimeTypeMap();} public String getMimeTypeFromExtension(String ext){return "text/plain";} }',
'android/webkit/GeolocationPermissions.java': 'package android.webkit; public class GeolocationPermissions { public interface Callback { void invoke(String origin,boolean allow,boolean retain); } }',
'android/webkit/WebChromeClient.java': '''package android.webkit;
public class WebChromeClient {
 public static class FileChooserParams { public static final int MODE_OPEN=0,MODE_OPEN_MULTIPLE=1; public int getMode(){return MODE_OPEN;} public String[] getAcceptTypes(){return new String[]{"text/plain"};} }
 public interface CustomViewCallback { void onCustomViewHidden(); }
 public boolean onShowFileChooser(WebView v,ValueCallback<android.net.Uri[]> c,FileChooserParams p){return false;}
 public boolean onConsoleMessage(ConsoleMessage m){return false;}
 public void onPermissionRequest(PermissionRequest p){} public void onPermissionRequestCanceled(PermissionRequest p){}
 public void onGeolocationPermissionsShowPrompt(String o,GeolocationPermissions.Callback c){}
 public void onShowCustomView(android.view.View v,CustomViewCallback c){} public void onHideCustomView(){}
 public boolean onJsPrompt(WebView v,String url,String message,String value,JsPromptResult result){return false;}
}''',
})
STUBS['android/content/Intent.java'] = STUBS['android/content/Intent.java'].replace(' private android.net.Uri data;', ''' public static final String CATEGORY_OPENABLE="openable",EXTRA_MIME_TYPES="types",EXTRA_ALLOW_MULTIPLE="multiple";
 public static final int FLAG_GRANT_READ_URI_PERMISSION=1;
 public Intent addCategory(String value){return this;} public Intent setType(String value){return this;}
 public Intent putExtra(String key,String[] value){return this;} public Intent putExtra(String key,boolean value){return this;}
 public Intent addFlags(int value){return this;}
 private android.net.Uri data;''')
if OUT.exists(): shutil.rmtree(OUT)
(OUT / 'tmp').mkdir(parents=True)
for name, content in STUBS.items():
 target = OUT / 'fakes' / name
 target.parent.mkdir(parents=True, exist_ok=True)
 target.write_text(content.strip()+'\n',encoding='utf-8')
classes=OUT / 'classes'
classes.mkdir()
JSON=Path.home()/'.gradle/caches/modules-2/files-2.1/org.json/json/20250517/d67181bbd819ccceb929b580a4e2fcb0c8b17cd8/json-20250517.jar'
sources=[SRC / name for name in ['NativeHostPolicy.java','ServerOrigin.java','CallbackLease.java','BoundedStreams.java','LocalDocuments.java','LocalDocumentsProvider.java','DesktopChromeClient.java']]
sources += [ROOT / 'android/tests/DesktopChromeClientHostTest.java']
env=os.environ.copy()
env.update({key:str(OUT / 'tmp') for key in ['TMP','TEMP','TMPDIR']})
for args in [[JDK/'javac.exe','--release','8','-Xlint:-options','-cp',JSON,'-d',classes,*sorted((OUT/'fakes').rglob('*.java')),*sources],
 [JDK/'java.exe','-Djava.io.tmpdir='+str(OUT/'tmp'),'-cp',str(classes)+os.pathsep+str(JSON),'us.pilipia.hermes.prototype.DesktopChromeClientHostTest']]:
 result=subprocess.run(list(map(str,args)),cwd=ROOT,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
 print(result.stdout,end='')
 if result.returncode: raise SystemExit(result.returncode)
