"""Synthetic host contracts + real API-36 compilation, not an APK/device proof.

Android fakes supply only framework plumbing; real document code uses real files
and streams. Generated files, subprocess logs and Java temp files stay in .cache.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.cache' / 'local-documents-tests'
JDK = Path(os.environ.get('JAVA_HOME', 'C:/Program Files/Microsoft/jdk-21.0.8.9-hotspot')) / 'bin'
SDK = Path(os.environ.get('ANDROID_SDK_ROOT', 'C:/Android/Sdk'))
SRC = ROOT / 'android/src/us/pilipia/hermes/prototype'
NAMES = ['BoundedStreams.java', 'LocalDocuments.java', 'LocalDocumentsProvider.java']
STUBS = {
    'android/net/Uri.java': r'''
package android.net;
public final class Uri {
 private final String text; private final java.net.URI value;
 private Uri(String text) { this.text=text; this.value=java.net.URI.create(text); }
 public static Uri parse(String text) { return new Uri(text); }
 public String getScheme() { return value.getScheme(); }
 public String getAuthority() { return value.getAuthority(); }
 public String getEncodedAuthority() { return value.getRawAuthority(); }
 public String getPath() { return value.getPath(); }
 public String getEncodedPath() { return value.getRawPath(); }
 public String getQuery() { return value.getRawQuery(); }
 public String getFragment() { return value.getRawFragment(); }
 public String toString() { return text; }
 public boolean equals(Object other) { return other instanceof Uri && text.equals(other.toString()); }
 public int hashCode() { return text.hashCode(); }
}
''',
    'android/content/Context.java': r'''
package android.content;
public abstract class Context {
 public Context getApplicationContext() { return this; }
 public abstract java.io.File getCacheDir();
 public abstract ContentResolver getContentResolver();
}
''',
    'android/content/ContentResolver.java': r'''
package android.content;
public abstract class ContentResolver {
 public abstract android.database.Cursor query(android.net.Uri uri, String[] projection,
  String selection, String[] args, String order);
 public abstract String getType(android.net.Uri uri);
 public abstract java.io.InputStream openInputStream(android.net.Uri uri) throws java.io.FileNotFoundException;
}
''',
    'android/content/Intent.java': r'''
package android.content;
public class Intent {
 public static final String ACTION_OPEN_DOCUMENT="android.intent.action.OPEN_DOCUMENT";
 private android.net.Uri data; private ClipData clip;
 public Intent() { }
 public Intent(String action) { }
 public Intent setData(android.net.Uri value) { data=value; return this; }
 public android.net.Uri getData() { return data; }
 public Intent setClipData(ClipData value) { clip=value; return this; }
 public ClipData getClipData() { return clip; }
}
''',
    'android/content/ClipData.java': r'''
package android.content;
public class ClipData {
 private final java.util.List<Item> items=new java.util.ArrayList<Item>();
 public static ClipData newRawUri(CharSequence label, android.net.Uri uri) {
  ClipData result=new ClipData(); result.addItem(new Item(uri)); return result;
 }
 public void addItem(Item item) { items.add(item); }
 public int getItemCount() { return items.size(); }
 public Item getItemAt(int index) { return items.get(index); }
 public static class Item {
  private final android.net.Uri uri;
  public Item(android.net.Uri uri) { this.uri=uri; }
  public android.net.Uri getUri() { return uri; }
 }
}
''',
    'android/content/ContentValues.java': 'package android.content; public class ContentValues { }',
    'android/content/pm/ProviderInfo.java': 'package android.content.pm; public class ProviderInfo { }',
    'android/content/ContentProvider.java': r'''
package android.content;
public abstract class ContentProvider {
 private Context context;
 public Context getContext() { return context; }
 public void attachInfo(Context context, android.content.pm.ProviderInfo ignored) { this.context=context; onCreate(); }
 public abstract boolean onCreate();
 public abstract android.database.Cursor query(android.net.Uri uri, String[] projection,
  String selection, String[] args, String order);
 public abstract String getType(android.net.Uri uri);
 public abstract android.net.Uri insert(android.net.Uri uri, ContentValues values);
 public abstract int delete(android.net.Uri uri, String selection, String[] args);
 public abstract int update(android.net.Uri uri, ContentValues values, String selection, String[] args);
 public int bulkInsert(android.net.Uri uri, ContentValues[] values) { for(ContentValues value:values)insert(uri,value);return values.length; }
 public android.os.ParcelFileDescriptor openFile(android.net.Uri uri, String mode)
  throws java.io.FileNotFoundException { throw new java.io.FileNotFoundException(); }
}
''',
    'android/database/Cursor.java': r'''
package android.database;
public interface Cursor extends java.io.Closeable {
 boolean moveToFirst(); int getColumnIndex(String name); String getString(int index);
 long getLong(int index); boolean isNull(int index); int getCount(); String[] getColumnNames(); void close();
}
''',
    'android/database/MatrixCursor.java': r'''
package android.database;
public class MatrixCursor implements Cursor {
 private final String[] columns; private final java.util.List<Object[]> rows=new java.util.ArrayList<Object[]>();
 public MatrixCursor(String[] columns) { this.columns=columns.clone(); }
 public MatrixCursor(String[] columns, int capacity) { this(columns); }
 public void addRow(Object[] row) { rows.add(row.clone()); }
 public boolean moveToFirst() { return !rows.isEmpty(); }
 public int getColumnIndex(String name) { for(int i=0;i<columns.length;i++)if(columns[i].equals(name))return i;return -1; }
 public String getString(int index) { Object value=rows.get(0)[index];return value==null?null:value.toString(); }
 public long getLong(int index) { return ((Number)rows.get(0)[index]).longValue(); }
 public boolean isNull(int index) { return rows.get(0)[index]==null; }
 public int getCount() { return rows.size(); }
 public String[] getColumnNames() { return columns.clone(); }
 public void close() { }
}
''',
    'android/provider/OpenableColumns.java': r'''
package android.provider;
public interface OpenableColumns { String DISPLAY_NAME="_display_name"; String SIZE="_size"; }
''',
    'android/os/SystemClock.java': r'''
package android.os;
public final class SystemClock {
 private static long time=1000;
 public static long elapsedRealtime() { return time; }
 public static void advanceForTest(long amount) { time+=amount; }
}
''',
    'android/os/ParcelFileDescriptor.java': r'''
package android.os;
public class ParcelFileDescriptor implements java.io.Closeable {
 public static final int MODE_READ_ONLY=0x10000000;
 private final java.io.FileInputStream stream;
 private ParcelFileDescriptor(java.io.FileInputStream stream) { this.stream=stream; }
 public static ParcelFileDescriptor open(java.io.File file, int mode) throws java.io.FileNotFoundException {
  if(mode!=MODE_READ_ONLY)throw new AssertionError("Not read-only");
  return new ParcelFileDescriptor(new java.io.FileInputStream(file));
 }
 public void close() throws java.io.IOException { stream.close(); }
 public static class AutoCloseInputStream extends java.io.FilterInputStream {
  public AutoCloseInputStream(ParcelFileDescriptor descriptor) { super(descriptor.stream); }
 }
}
''',
}


def run(command, label):
    env = os.environ.copy()
    env.update({key: str(OUT / 'tmp') for key in ['TMP', 'TEMP', 'TMPDIR']})
    result = subprocess.run([str(arg) for arg in command], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, timeout=90)
    (OUT / (label + '.log')).write_text(result.stdout, encoding='utf-8')
    print(result.stdout, end='')
    if result.returncode:
        raise SystemExit(result.returncode)


def main():
    if sys.argv[1:] not in ([], ['--bounded-only'], ['--doc-cancellation-only'], ['--doc-errors-only']):
        raise SystemExit('Usage: test-local-documents.py [--bounded-only|--doc-cancellation-only|--doc-errors-only]')
    (OUT / 'tmp').mkdir(parents=True, exist_ok=True)
    generated = OUT / 'android-fakes'
    for name, content in STUBS.items():
        target = generated / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.strip() + '\n', encoding='utf-8')
    classes = OUT / 'host-classes'
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir()
    sources = [ROOT / 'android/tests/LocalDocumentsHostTest.java']
    sources += [SRC / name for name in NAMES if (SRC / name).exists()]
    run([JDK / 'javac.exe', '--release', '8', '-Xlint:-options', '-d', classes,
         *generated.rglob('*.java'), *sources], 'host-compile')
    run([JDK / 'java.exe', '-Xmx128m', '-Djava.io.tmpdir=' + str(OUT / 'tmp'), '-cp', classes,
         'us.pilipia.hermes.prototype.LocalDocumentsHostTest', *sys.argv[1:]], 'host-tests')
    if '--bounded-only' not in sys.argv:
        android = OUT / 'android-classes'
        android.mkdir(exist_ok=True)
        run([JDK / 'javac.exe', '--release', '8', '-Xlint:-options',
             '-classpath', SDK / 'platforms/android-36/android.jar', '-d', android,
             *[SRC / name for name in NAMES]], 'android-compile')
        print('PASS all three document classes compiled against Android API 36 (Java 8 target)')


if __name__ == '__main__':
    main()
