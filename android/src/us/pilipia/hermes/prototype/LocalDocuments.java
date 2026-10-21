package us.pilipia.hermes.prototype;

import android.content.Context;
import android.content.ClipData;
import android.content.ContentResolver;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InterruptedIOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Locale;
import java.util.ArrayList;
import java.util.concurrent.Semaphore;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Bounded app-private document staging; no persisted grants or broad storage access. */
public final class LocalDocuments {
    public static final int MAX_ITEMS = 16;
    public static final long MAX_FILE_BYTES = 32L * 1024L * 1024L;
    public static final long MAX_TOTAL_BYTES = 64L * 1024L * 1024L;
    public static final int MAX_EXPORT_BYTES = 8 * 1024 * 1024;
    private final Context context;
    // A hostile provider may ignore interruption. Bound its worker/queue footprint;
    // the waiting caller can still cancel, unlink partials and fence publication.
    private static final ThreadPoolExecutor STAGING = executor("local-document-staging");
    private static final ThreadPoolExecutor CLOSING = executor("local-document-close");
    // Reserve disposal capacity BEFORE entering provider open. A hung close keeps
    // its permit; no later open can create an uncloseable, unbounded backlog.
    private static final Semaphore PROVIDER_STREAMS = new Semaphore(2);
    private static final ArrayBlockingQueue<ProviderInput> DISPOSALS = new ArrayBlockingQueue<ProviderInput>(2);
    private static boolean disposalScheduled; // Guarded by DISPOSALS; one draining task.

    public LocalDocuments(Context context) {
        if (context == null) throw new NullPointerException("Missing document context");
        Context application = context.getApplicationContext();
        this.context = application == null ? context : application;
    }

    /** Called only for the pending standard WebChromeClient file-picker result. */
    public Uri[] stage(final Intent result, final boolean multiple) throws IOException {
        checkInterrupted();
        final Staging operation = new Staging();
        Future<Uri[]> future;
        try {
            future = STAGING.submit(new Callable<Uri[]>() {
                @Override public Uri[] call() throws IOException { return stageSelected(result, multiple, operation); }
            });
        } catch (RejectedExecutionException failure) {
            throw new IOException("Document staging is busy");
        }
        boolean accepted = false;
        try {
            Uri[] uris = future.get();
            checkInterrupted();
            accepted = true;
            return uris;
        } catch (InterruptedException failure) {
            Thread.currentThread().interrupt();
            throw new InterruptedIOException("Document staging cancelled");
        } catch (ExecutionException failure) {
            if (failure.getCause() instanceof InterruptedIOException) {
                throw new InterruptedIOException("Document staging cancelled");
            }
            throw new IOException("Cannot stage selected document");
        } finally {
            if (!accepted) {
                operation.cancel();
                future.cancel(true);
                STAGING.remove((Runnable) future);
            }
        }
    }

    private Uri[] stageSelected(Intent result, boolean multiple, Staging operation) throws IOException {
        boolean complete = false;
        try {
            List<Uri> sources = selectedUris(result, multiple);
            ContentResolver resolver = context.getContentResolver();
            long total = 0;
            for (Uri source : sources) {
                checkInterrupted();
                String type = mime(resolver.getType(source));
                String name;
                // SIZE is deliberately not requested or trusted: only streamed bytes set limits.
                try (Cursor cursor = resolver.query(source, new String[] {OpenableColumns.DISPLAY_NAME},
                        null, null, null)) {
                    if (cursor == null || !cursor.moveToFirst()) throw new IOException("Missing document metadata");
                    int column = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                    if (column < 0 || cursor.isNull(column)) throw new IOException("Missing document metadata");
                    name = displayName(cursor.getString(column));
                }
                checkInterrupted();
                LocalDocumentsProvider.Entry entry = operation.reserve(context, name, type);
                long copied;
                try (InputStream input = operation.openInput(resolver, source);
                     OutputStream output = operation.output(entry)) {
                    if (input == null) throw new IOException("Document is not readable");
                    copied = BoundedStreams.copy(input, output, Math.min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - total));
                } finally {
                    operation.clearStreams();
                }
                total += copied;
                entry.size = copied;
            }
            checkInterrupted();
            Uri[] uris = operation.publish();
            complete = true;
            return uris;
        } catch (InterruptedIOException failure) {
            throw new InterruptedIOException("Document staging cancelled");
        } catch (IOException | RuntimeException failure) {
            throw new IOException("Cannot stage selected document");
        } finally {
            if (!complete) operation.cancel();
        }
    }

    private static List<Uri> selectedUris(Intent result, boolean multiple) throws IOException {
        if (result == null) throw new IOException("Missing document result");
        List<Uri> selected = new ArrayList<Uri>();
        ClipData clip = result.getClipData();
        if (clip != null) {
            int count = clip.getItemCount();
            if (count > MAX_ITEMS) throw new IOException("Too many selected documents");
            for (int i = 0; i < count; i++) {
                ClipData.Item item = clip.getItemAt(i);
                selected.add(item == null ? null : item.getUri());
            }
        }
        if (result.getData() != null) selected.add(result.getData());
        if (selected.isEmpty() || selected.size() > MAX_ITEMS || (!multiple && selected.size() != 1)) {
            throw new IOException("Invalid document selection count");
        }
        Set<String> unique = new HashSet<String>();
        for (Uri uri : selected) {
            if (uri == null || !"content".equals(uri.getScheme()) || uri.getAuthority() == null
                    || !uri.getAuthority().matches("[A-Za-z0-9._-]+")
                    || LocalDocumentsProvider.AUTHORITY.equalsIgnoreCase(uri.getAuthority())
                    || !unique.add(uri.toString())) throw new IOException("Invalid selected document URI");
        }
        return selected;
    }

    public Uri export(byte[] bytes, String displayName, String mime) throws IOException {
        if (bytes == null || bytes.length > MAX_EXPORT_BYTES) throw new IOException("Invalid export size");
        String name = displayName(displayName);
        String type = mime(mime);
        LocalDocumentsProvider.Entry entry = null;
        boolean complete = false;
        try {
            entry = LocalDocumentsProvider.reserve(context, name, type);
            long copied;
            try (InputStream input = new ByteArrayInputStream(bytes);
                 OutputStream output = LocalDocumentsProvider.openOutput(entry)) {
                copied = BoundedStreams.copy(input, output, MAX_EXPORT_BYTES);
            }
            Uri uri = LocalDocumentsProvider.publish(entry, copied);
            complete = true;
            return uri;
        } catch (InterruptedIOException failure) {
            throw new InterruptedIOException("Document export cancelled");
        } catch (IOException | RuntimeException failure) {
            throw new IOException("Cannot export document");
        } finally {
            if (!complete) LocalDocumentsProvider.discard(entry);
        }
    }

    public static void cleanup(Context context) {
        LocalDocumentsProvider.cleanup(context);
    }

    private static ThreadPoolExecutor executor(final String name) {
        ThreadPoolExecutor executor = new ThreadPoolExecutor(1, 1, 30, TimeUnit.SECONDS,
                new ArrayBlockingQueue<Runnable>(1), new ThreadFactory() {
                    @Override public Thread newThread(Runnable task) {
                        Thread thread = new Thread(task, name);
                        thread.setDaemon(true);
                        return thread;
                    }
                });
        executor.allowCoreThreadTimeOut(true);
        return executor;
    }

    private static final class Staging {
        private final List<LocalDocumentsProvider.Entry> pending = new ArrayList<LocalDocumentsProvider.Entry>(MAX_ITEMS);
        private boolean cancelled;
        private ProviderInput input;
        private OutputStream output;

        synchronized LocalDocumentsProvider.Entry reserve(Context context, String name, String type) throws IOException {
            if (cancelled) throw new InterruptedIOException("Document staging cancelled");
            LocalDocumentsProvider.Entry entry = LocalDocumentsProvider.reserve(context, name, type);
            boolean retained = false;
            try {
                pending.add(entry);
                retained = true;
                return entry;
            } finally {
                if (!retained) LocalDocumentsProvider.discard(entry);
            }
        }

        InputStream openInput(ContentResolver resolver, Uri source) throws IOException {
            checkInterrupted();
            if (!PROVIDER_STREAMS.tryAcquire()) throw new IOException("Document disposal is busy");
            ProviderInput owned = null;
            try {
                synchronized (this) {
                    if (cancelled) throw new InterruptedIOException("Document staging cancelled");
                }
                InputStream stream = resolver.openInputStream(source); // Never under our monitor.
                if (stream != null) owned = new ProviderInput(stream, this);
                synchronized (this) {
                    if (!cancelled) {
                        input = owned;
                        return owned;
                    }
                }
                // A cancelled late open transfers its sole close to the disposal
                // lane. TWR never receives it and cannot re-enter provider close.
                if (owned != null) owned.closeAsync();
                throw new InterruptedIOException("Document staging cancelled");
            } finally {
                if (owned == null) PROVIDER_STREAMS.release(); // null/throwing open owns no stream.
            }
        }

        synchronized OutputStream output(LocalDocumentsProvider.Entry entry) throws IOException {
            if (cancelled) throw new InterruptedIOException("Document staging cancelled");
            output = LocalDocumentsProvider.openOutput(entry);
            return output;
        }

        synchronized void clearStreams() { input = null; output = null; }

        synchronized Uri[] publish() throws IOException {
            if (cancelled) throw new InterruptedIOException("Document staging cancelled");
            Uri[] uris = new Uri[pending.size()];
            synchronized (LocalDocumentsProvider.class) {
                for (int i = 0; i < pending.size(); i++) {
                    LocalDocumentsProvider.Entry entry = pending.get(i);
                    uris[i] = LocalDocumentsProvider.publish(entry, entry.size);
                }
            }
            return uris;
        }

        void cancel() {
            final ProviderInput active;
            synchronized (this) {
                cancelled = true;
                // The output is our own local FileOutputStream, not provider code.
                closeQuietly(output);
                for (LocalDocumentsProvider.Entry entry : pending) LocalDocumentsProvider.discard(entry);
                active = input;
            }
            if (active != null) active.closeAsync();
        }
    }

    /** One close owner across cancellation and try-with-resources unwinding. */
    private static final class ProviderInput extends java.io.FilterInputStream {
        private final Staging owner;
        private boolean claimed; // Guarded by owner, together with its cancellation fence.

        ProviderInput(InputStream stream, Staging owner) {
            super(stream);
            this.owner = owner;
        }

        /** 0: already claimed, 1: normal close, 2: asynchronous disposal. */
        private int claimClose(boolean asynchronous) {
            synchronized (owner) {
                if (claimed) return 0;
                claimed = true;
                return asynchronous || owner.cancelled ? 2 : 1;
            }
        }

        @Override public void close() throws IOException {
            int disposition = claimClose(false);
            if (disposition == 0) return;
            if (disposition == 2) {
                enqueueDisposal();
                return;
            }
            try { in.close(); } // Normal close errors still fail the batch.
            finally { PROVIDER_STREAMS.release(); }
        }

        void dispose() {
            try { closeQuietly(in); }
            finally { PROVIDER_STREAMS.release(); }
        }

        void closeAsync() {
            if (claimClose(true) != 0) enqueueDisposal();
        }

        private void enqueueDisposal() {
            synchronized (DISPOSALS) {
                DISPOSALS.add(this); // At most two admitted streams, including the one closing.
                if (disposalScheduled) return;
                disposalScheduled = true;
                CLOSING.execute(new Runnable() {
                    @Override public void run() { drainDisposals(); }
                });
            }
        }
    }

    private static void drainDisposals() {
        while (true) {
            ProviderInput stream;
            synchronized (DISPOSALS) {
                stream = DISPOSALS.poll();
                if (stream == null) {
                    disposalScheduled = false;
                    return;
                }
            }
            // No operation/disposal monitor spans untrusted provider close. One
            // drainer avoids executor handoff rejection without dropping a stream
            // or creating replacement threads when provider close hangs.
            stream.dispose();
        }
    }

    private static void closeQuietly(java.io.Closeable stream) {
        if (stream == null) return;
        try { stream.close(); } catch (IOException | RuntimeException ignored) { }
    }

    private static void checkInterrupted() throws InterruptedIOException {
        if (Thread.currentThread().isInterrupted()) throw new InterruptedIOException("Document operation cancelled");
    }

    private static String displayName(String value) throws IOException {
        if (value == null || value.length() == 0 || value.length() > 255
                || value.trim().isEmpty() || ".".equals(value) || "..".equals(value)) {
            throw new IOException("Invalid document display name");
        }
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c == '/' || c == '\\' || Character.isISOControl(c)) {
                throw new IOException("Invalid document display name");
            }
        }
        return value;
    }

    private static String mime(String value) throws IOException {
        if (value == null || value.length() > 127
                || !value.matches("[A-Za-z0-9!#$&^_.+\\-]+/[A-Za-z0-9!#$&^_.+\\-]+")) {
            throw new IOException("Invalid document MIME type");
        }
        return value.toLowerCase(Locale.ROOT);
    }
}
