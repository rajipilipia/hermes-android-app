package us.pilipia.hermes.prototype;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.os.SystemClock;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InterruptedIOException;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** Read-only, process-memory capability registry. Never resolves a URI into a path. */
public final class LocalDocumentsProvider extends ContentProvider {
    public static final String AUTHORITY = "us.pilipia.hermes.prototype.documents";
    private static final String DIRECTORY = "local-documents";
    private static final long LIFETIME_MS = 10L * 60L * 1000L;
    private static final int MAX_FILES = 64;
    private static final String PREFIX = "content://" + AUTHORITY + "/";
    private static final LinkedHashMap<String, Entry> ENTRIES = new LinkedHashMap<String, Entry>();

    /** Pending entries reserve capacity but are not addressable through the provider. */
    static final class Entry {
        final String token;
        final File root;
        final String displayName;
        final String mime;
        final long created;
        File file;
        long size;
        boolean ready;

        Entry(String token, File root, File file, String displayName, String mime, long created) {
            this.token = token;
            this.root = root;
            this.file = file;
            this.displayName = displayName;
            this.mime = mime;
            this.created = created;
        }
    }

    @Override public boolean onCreate() {
        cleanup(getContext());
        return true;
    }

    static synchronized Entry reserve(Context context, String name, String mime) throws IOException {
        checkInterrupted();
        File root = cacheRoot(context);
        prune(root, SystemClock.elapsedRealtime());
        while (files(root).length >= MAX_FILES) {
            Entry oldest = null;
            for (Entry candidate : ENTRIES.values()) {
                if (candidate.ready && candidate.root.equals(root)) {
                    oldest = candidate;
                    break;
                }
            }
            if (oldest == null) throw new IOException("Document cache capacity reached");
            discard(oldest);
            if (oldest.file.exists()) throw new IOException("Cannot evict cached document");
        }
        String token = UUID.randomUUID().toString();
        File file = new File(root, token + ".part");
        if (!file.createNewFile()) throw new IOException("Cannot reserve cached document");
        Entry entry = new Entry(token, root, file, name, mime, SystemClock.elapsedRealtime());
        ENTRIES.put(token, entry);
        return entry;
    }

    static synchronized FileOutputStream openOutput(Entry entry) throws IOException {
        checkInterrupted();
        if (ENTRIES.get(entry.token) != entry || entry.ready || expired(entry, SystemClock.elapsedRealtime())
                || !owned(entry)) throw new IOException("Cached document unavailable");
        return new FileOutputStream(entry.file);
    }

    static synchronized Uri publish(Entry entry, long size) throws IOException {
        checkInterrupted();
        if (ENTRIES.get(entry.token) != entry || entry.ready || expired(entry, SystemClock.elapsedRealtime())
                || !owned(entry) || size < 0 || size != entry.file.length()) {
            throw new IOException("Cached document unavailable");
        }
        File complete = new File(entry.root, entry.token + ".blob");
        if (!entry.file.renameTo(complete)) throw new IOException("Cannot finalize cached document");
        entry.file = complete;
        entry.size = size;
        entry.ready = true;
        return Uri.parse(PREFIX + entry.token);
    }

    static synchronized void discard(Entry entry) {
        if (entry == null) return;
        if (ENTRIES.get(entry.token) == entry) ENTRIES.remove(entry.token);
        // These are exclusively generated cache children, never names from an input URI.
        try {
            if (entry.file.getParentFile().equals(entry.root)) entry.file.delete();
        } catch (SecurityException ignored) { /* Cleanup retries on the next operation/startup. */ }
    }

    static synchronized void cleanup(Context context) {
        if (context == null) return;
        try {
            prune(cacheRoot(context), SystemClock.elapsedRealtime());
        } catch (IOException | RuntimeException ignored) {
            // Best effort lifecycle cleanup; future reads/writes still fail closed.
        }
    }

    private static File cacheRoot(Context context) throws IOException {
        if (context == null || context.getCacheDir() == null) throw new IOException("Cache unavailable");
        File cache = context.getCacheDir().getCanonicalFile();
        File root = new File(cache, DIRECTORY);
        if (!root.getCanonicalFile().equals(root)) throw new IOException("Invalid cache directory");
        if (!root.isDirectory() && !root.mkdir()) throw new IOException("Cache unavailable");
        return root;
    }

    private static File[] files(File root) throws IOException {
        File[] files = root.listFiles();
        if (files == null) throw new IOException("Cache unavailable");
        return files;
    }

    private static boolean expired(Entry entry, long now) {
        return now < entry.created || now - entry.created >= LIFETIME_MS;
    }

    private static boolean owned(Entry entry) throws IOException {
        return entry.file.getParentFile().equals(entry.root)
                && entry.file.getCanonicalFile().equals(entry.file)
                && entry.file.isFile();
    }

    /** Startup removes orphaned files: UUID mappings are intentionally never reconstructed. */
    private static void prune(File root, long now) throws IOException {
        Iterator<Map.Entry<String, Entry>> iterator = ENTRIES.entrySet().iterator();
        while (iterator.hasNext()) {
            Entry entry = iterator.next().getValue();
            if (expired(entry, now) || !owned(entry)) {
                iterator.remove();
                entry.file.delete();
            }
        }
        Set<File> retained = new HashSet<File>();
        for (Entry entry : ENTRIES.values()) if (entry.root.equals(root)) retained.add(entry.file);
        for (File file : files(root)) {
            if (!retained.contains(file)) file.delete(); // Not recursive: never follow directories/symlinks.
        }
    }

    private static String token(Uri uri) {
        if (uri == null) throw new IllegalArgumentException("Invalid document URI");
        String text = uri.toString();
        if (text.length() != PREFIX.length() + 36 || !text.startsWith(PREFIX)) {
            throw new IllegalArgumentException("Invalid document URI");
        }
        String token = text.substring(PREFIX.length());
        if (!token.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")) {
            throw new IllegalArgumentException("Invalid document URI");
        }
        return token;
    }

    private static Entry find(Context context, Uri uri) throws IOException {
        String token = token(uri);
        File root = cacheRoot(context);
        prune(root, SystemClock.elapsedRealtime());
        Entry entry = ENTRIES.get(token);
        if (entry == null || !entry.ready || !entry.root.equals(root) || !owned(entry)
                || entry.file.length() != entry.size) throw new IOException("Document unavailable");
        return entry;
    }

    @Override public Cursor query(Uri uri, String[] projection, String selection,
                                  String[] selectionArgs, String sortOrder) {
        if (selection != null || selectionArgs != null || sortOrder != null) {
            throw new IllegalArgumentException("Document queries do not accept filters");
        }
        if (projection != null && projection.length > 2) throw new IllegalArgumentException("Unsupported document columns");
        String[] columns = projection == null
                ? new String[] {OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE} : projection.clone();
        for (String column : columns) {
            if (!OpenableColumns.DISPLAY_NAME.equals(column) && !OpenableColumns.SIZE.equals(column)) {
                throw new IllegalArgumentException("Unsupported document column");
            }
        }
        synchronized (LocalDocumentsProvider.class) {
            try {
                Entry entry = find(getContext(), uri);
                MatrixCursor cursor = new MatrixCursor(columns, 1);
                Object[] row = new Object[columns.length];
                for (int i = 0; i < columns.length; i++) {
                    row[i] = OpenableColumns.DISPLAY_NAME.equals(columns[i]) ? entry.displayName : Long.valueOf(entry.size);
                }
                cursor.addRow(row);
                return cursor;
            } catch (IOException | SecurityException failure) {
                throw new IllegalArgumentException("Document unavailable");
            }
        }
    }

    @Override public String getType(Uri uri) {
        synchronized (LocalDocumentsProvider.class) {
            try {
                return find(getContext(), uri).mime;
            } catch (IOException | SecurityException failure) {
                throw new IllegalArgumentException("Document unavailable");
            }
        }
    }

    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("Document provider is read-only");
        synchronized (LocalDocumentsProvider.class) {
            try {
                return ParcelFileDescriptor.open(find(getContext(), uri).file, ParcelFileDescriptor.MODE_READ_ONLY);
            } catch (IOException | RuntimeException failure) {
                throw new FileNotFoundException("Document unavailable");
            }
        }
    }

    @Override public Uri insert(Uri uri, ContentValues values) {
        throw new SecurityException("Document provider is read-only");
    }

    @Override public int bulkInsert(Uri uri, ContentValues[] values) {
        throw new SecurityException("Document provider is read-only");
    }

    @Override public int delete(Uri uri, String selection, String[] selectionArgs) {
        throw new SecurityException("Document provider is read-only");
    }

    @Override public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        throw new SecurityException("Document provider is read-only");
    }

    private static void checkInterrupted() throws InterruptedIOException {
        if (Thread.currentThread().isInterrupted()) throw new InterruptedIOException("Document operation cancelled");
    }
}
