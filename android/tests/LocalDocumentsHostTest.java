package us.pilipia.hermes.prototype;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.reflect.InvocationTargetException;
import java.util.Arrays;
import android.content.ContentProvider;
import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.content.ClipData;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.util.UUID;

/** Synthetic host checks; no private filenames, device state or external services. */
public final class LocalDocumentsHostTest {
    private static int checks;

    public static void main(String[] args) throws Exception {
        copyPreservesBytesAtExactLimit();
        copyHonorsThreadInterruption();
        boundedStreamEdges();
        if (args.length == 0 || "--doc-cancellation-only".equals(args[0])) {
            cancelledLateOpenCloseDoesNotBlockHealthyStaging();
            cancelledReadDisposesStreamExactlyOnceWithoutBlockingStaging();
            cancelledTryWithResourcesHandoffCannotReclaimProviderClose();
            disposalSaturationRejectsBeforeOpeningAndRecovers();
        }
        if (args.length == 1 && "--doc-errors-only".equals(args[0])) validatesMetadataAndRollsBackErrors();
        if (args.length == 0) {
            exportPublishesReadOnlyOpaqueBytes();
            stageCopiesOnlySelectedContent();
            cancellationUnblocksCallerAndRemovesPartials();
            rejectsInvalidSelectionsBeforeOpeningStreams();
            validatesMetadataAndRollsBackErrors();
            streamedLimitsIgnoreAdvertisedSizes();
            providerRejectsPathsWritesAndExtraColumns();
            exportSizeAndMetadataLimits();
            expiryCapacityAndStartupPruning();
            pendingReservationsAreBoundedAndCannotRecreateEvictedFiles();
        }
        System.out.println("PASS local documents host checks: " + checks);
    }

    private static void copyPreservesBytesAtExactLimit() throws Exception {
        byte[] input = new byte[] {0, 1, 2, 3, -1};
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        long count = copy(new ByteArrayInputStream(input), output, input.length);
        check(count == input.length, "exact-limit byte count");
        check(Arrays.equals(input, output.toByteArray()), "exact-limit bytes preserved");
    }

    private static void copyHonorsThreadInterruption() throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        Thread.currentThread().interrupt();
        try {
            try {
                copy(new ByteArrayInputStream(new byte[] {1}), output, 1);
                throw new AssertionError("Interrupted copy must fail");
            } catch (java.io.InterruptedIOException expected) {
                check(output.size() == 0, "no writes after pre-existing interruption");
                check(Thread.currentThread().isInterrupted(), "interrupt status preserved");
            }
        } finally {
            Thread.interrupted();
        }
    }

    private static void boundedStreamEdges() throws Exception {
        CountingInput input = new CountingInput(1000000);
        CountingOutput output = new CountingOutput();
        expect(IOException.class, () -> copy(input, output, 8193));
        check(input.consumed == 8194, "oversize probe consumes at most limit plus one");
        check(output.written == 8193, "oversize copy never writes excess bytes");
        check(input.largestRequest <= 8192, "copy uses a fixed bounded buffer");
        check(!input.closed && !output.closed, "caller owns both streams");
        check(copy(new CountingInput(0), new CountingOutput(), 0) == 0, "zero limit accepts empty input");
        CountingInput nonempty = new CountingInput(8);
        CountingOutput zero = new CountingOutput();
        expect(IOException.class, () -> copy(nonempty, zero, 0));
        check(nonempty.consumed == 1 && zero.written == 0, "zero limit probes just one byte without writing");
        check(copy(new CountingInput(17), new CountingOutput(), Long.MAX_VALUE) == 17, "large limit has no overflow/allocation");
        expect(IllegalArgumentException.class, () -> copy(new CountingInput(0), new CountingOutput(), -1));
        expect(NullPointerException.class, () -> copy(null, new CountingOutput(), 1));
        check(copy(new InputStream() {
            boolean returned;
            public int read(byte[] bytes,int offset,int length) { return 0; }
            public int read() { if(returned)return -1;returned=true;return 3; }
        }, new CountingOutput(), 2) == 1, "zero-length provider reads cannot spin");
        expect(IOException.class, () -> copy(new CountingInput(20), new OutputStream() {
            public void write(int one) throws IOException { throw new IOException("Synthetic output failure"); }
        }, 20));
        CountingOutput interrupted = new CountingOutput();
        try {
            expect(java.io.InterruptedIOException.class, () -> copy(new InputStream() {
                public int read() { Thread.currentThread().interrupt();return 1; }
            }, interrupted, 1));
            check(interrupted.written == 0, "interruption during read prevents subsequent write");
            check(Thread.currentThread().isInterrupted(), "mid-read interrupt remains set");
        } finally { Thread.interrupted(); }
    }

    private static void exportPublishesReadOnlyOpaqueBytes() throws Exception {
        try (Fixture fixture = new Fixture()) {
            Object documents = documents(fixture.context);
            byte[] input = new byte[] {0, 7, 0, -1};
            Uri uri = (Uri) invoke(documents, "export", new Class<?>[] {byte[].class, String.class, String.class},
                    input, "synthetic.txt", "text/plain");
            check(uri.toString().matches("content://us\\.pilipia\\.hermes\\.prototype\\.documents/[0-9a-f-]{36}"),
                    "opaque content handle");
            ContentProvider provider = (ContentProvider) Class.forName(
                    "us.pilipia.hermes.prototype.LocalDocumentsProvider").getConstructor().newInstance();
            provider.attachInfo(fixture.context, null);
            check("text/plain".equals(provider.getType(uri)), "export MIME");
            try (Cursor cursor = provider.query(uri, null, null, null, null)) {
                check(cursor.moveToFirst(), "export metadata present");
                check(cursor.getColumnNames().length == 2, "only openable metadata columns");
                check("synthetic.txt".equals(cursor.getString(cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME))),
                        "export display name");
                check(cursor.getLong(cursor.getColumnIndex(OpenableColumns.SIZE)) == input.length, "actual export size");
            }
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            try (InputStream stream = new ParcelFileDescriptor.AutoCloseInputStream(provider.openFile(uri, "r"))) {
                copy(stream, output, input.length);
            }
            check(Arrays.equals(input, output.toByteArray()), "export bytes readable");
        }
    }

    private static void stageCopiesOnlySelectedContent() throws Exception {
        try (Fixture fixture = new Fixture()) {
            Object documents = documents(fixture.context);
            Uri source = fixture.resolver.add(5, "synthetic.bin", "application/octet-stream");
            Uri[] staged = stage(documents, new Intent().setData(source), false);
            check(staged.length == 1 && !staged[0].equals(source), "external URI replaced by staged handle");
            ContentProvider provider = provider(fixture.context);
            try (Cursor cursor = provider.query(staged[0], null, null, null, null)) {
                check(cursor.moveToFirst(), "staged metadata present");
                check(cursor.getLong(cursor.getColumnIndex(OpenableColumns.SIZE)) == 5, "staged actual size");
            }
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            try (InputStream input = new ParcelFileDescriptor.AutoCloseInputStream(provider.openFile(staged[0], "r"))) {
                check(copy(input, output, 5) == 5, "staged stream readable");
            }
            check(Arrays.equals(output.toByteArray(), new byte[] {42, 42, 42, 42, 42}), "staged bytes copied");
            check(fixture.resolver.closed == 1, "selected source stream closed");
        }
    }

    private static void cancellationUnblocksCallerAndRemovesPartials() throws Exception {
        for (boolean blockedOpen : new boolean[] {false, true}) {
        try (Fixture fixture = new Fixture()) {
            final Object documents = documents(fixture.context);
            Uri uri = fixture.resolver.add(100, "synthetic.bin", "application/octet-stream");
            final Source source = fixture.resolver.sources.get(uri);
            source.block = !blockedOpen;
            source.blockOpen = blockedOpen;
            final Intent result = new Intent().setData(uri);
            final java.util.concurrent.atomic.AtomicReference<Throwable> failure = new java.util.concurrent.atomic.AtomicReference<Throwable>();
            final java.util.concurrent.atomic.AtomicBoolean keptInterrupt = new java.util.concurrent.atomic.AtomicBoolean();
            Thread caller = new Thread(new Runnable() {
                public void run() {
                    try { stage(documents, result, false); }
                    catch (Throwable caught) { failure.set(caught); keptInterrupt.set(Thread.currentThread().isInterrupted()); }
                }
            }, "synthetic-picker-caller");
            caller.start();
            try {
                check(source.entered.await(5, java.util.concurrent.TimeUnit.SECONDS), "synthetic provider read entered");
                caller.interrupt();
                caller.join(1000);
                check(!caller.isAlive(), "cancellation must not wait for an uninterruptible provider read");
                check(failure.get() instanceof java.io.InterruptedIOException, "cancelled caller receives IO cancellation");
                check(keptInterrupt.get(), "staging caller keeps interrupt status");
                check(cacheFileCount(fixture) == 0, "cancellation removes partials before a blocked provider returns");
            } finally {
                source.release.countDown();
                caller.join(5000);
            }
            check(source.closedLatch.await(5, java.util.concurrent.TimeUnit.SECONDS), "cancelled source closed after provider unblocks");
            awaitLaneIdle("STAGING");
            awaitLaneIdle("CLOSING");
            check(source.closes.get() == 1, "cancelled provider closed exactly once after all workers finish");
            check(cacheFileCount(fixture) == 0, "cancelled stage has no partial or published cache files");
        }
        }
    }

    private static void cancelledLateOpenCloseDoesNotBlockHealthyStaging() throws Exception {
        cancelledBlockingClose(false);
    }

    private static void cancelledReadDisposesStreamExactlyOnceWithoutBlockingStaging() throws Exception {
        cancelledBlockingClose(true);
    }

    private static void cancelledBlockingClose(boolean blockedRead) throws Exception {
        try (Fixture fixture = new Fixture()) {
            Object documents = documents(fixture.context);
            Uri blocked = fixture.resolver.add(1, "late.bin", "application/octet-stream");
            Source source = fixture.resolver.sources.get(blocked);
            source.blockOpen = !blockedRead;
            source.block = blockedRead;
            source.blockClose = true;
            StageCall cancelled = new StageCall(documents, blocked);
            StageCall healthy = new StageCall(documents,
                    fixture.resolver.add(1, "healthy.bin", "application/octet-stream"));
            try {
                cancelled.thread.start();
                check(source.entered.await(5, java.util.concurrent.TimeUnit.SECONDS), "late provider open entered");
                cancelled.thread.interrupt();
                cancelled.thread.join(1000);
                check(!cancelled.thread.isAlive(), "late-open cancellation returns before provider open");
                check(cancelled.failure.get() instanceof java.io.InterruptedIOException && cancelled.keptInterrupt,
                        "late-open cancellation preserves IO exception and interrupt");
                check(cacheFileCount(fixture) == 0, "late-open cancellation unlinks partial before open returns");
                source.release.countDown();
                check(source.closeEntered.await(5, java.util.concurrent.TimeUnit.SECONDS), "late stream disposal entered");
                healthy.thread.start();
                healthy.thread.join(5000);
                check(!healthy.thread.isAlive() && healthy.failure.get() == null && healthy.value.length == 1,
                        "healthy staging completes before cancelled late-open close is released");
                check(source.closeRelease.getCount() == 1, "hostile provider close remains blocked during healthy success");
                check("local-document-close".equals(source.closeThread), "late stream disposed on bounded closing lane");
                assertLaneBounds();
                check(cacheFileCount(fixture) == 1, "only healthy handle published while cancelled disposal blocks");
            } finally {
                source.release.countDown();
                source.closeRelease.countDown();
                cancelled.thread.interrupt();
                healthy.thread.interrupt();
                cancelled.thread.join(5000);
                if (healthy.thread.getState() != Thread.State.NEW) healthy.thread.join(5000);
                awaitLaneIdle("STAGING");
                awaitLaneIdle("CLOSING");
            }
            check(source.closes.get() == 1, "late-open cancelled stream closed exactly once");
            check(cancelled.value == null && cacheFileCount(fixture) <= 1, "late disposal never republishes cancelled handle");
        }
    }

    private static void cancelledTryWithResourcesHandoffCannotReclaimProviderClose() throws Exception {
        try (Fixture fixture = new Fixture()) {
            Uri uri = fixture.resolver.add(0, "handoff.bin", "application/octet-stream");
            Source source = fixture.resolver.sources.get(uri);
            source.blockClose = true;
            Class<?> type = Class.forName(LocalDocuments.class.getName() + "$Staging");
            java.lang.reflect.Constructor<?> constructor = type.getDeclaredConstructor();
            constructor.setAccessible(true);
            Object operation = constructor.newInstance();
            java.lang.reflect.Method open = type.getDeclaredMethod("openInput", ContentResolver.class, Uri.class);
            open.setAccessible(true);
            final InputStream input = (InputStream) open.invoke(operation, fixture.resolver, uri);
            // Deterministically expose cancel()'s handoff: cancellation is visible,
            // but its out-of-monitor disposer has not claimed the active input yet.
            java.lang.reflect.Field cancelled = type.getDeclaredField("cancelled");
            cancelled.setAccessible(true);
            synchronized (operation) { cancelled.setBoolean(operation, true); }
            final java.util.concurrent.atomic.AtomicReference<Throwable> failure =
                    new java.util.concurrent.atomic.AtomicReference<Throwable>();
            Thread unwind = new Thread(new Runnable() {
                public void run() {
                    try (InputStream resource = input) { } // Real TWR ownership path.
                    catch (Throwable caught) { failure.set(caught); }
                }
            }, "synthetic-resource-unwind");
            try {
                unwind.start();
                check(source.closeEntered.await(5, java.util.concurrent.TimeUnit.SECONDS), "cancelled TWR provider close entered");
                unwind.join(1000);
                check(!unwind.isAlive() && failure.get() == null,
                        "cancelled TWR unwind must not reclaim blocking provider close during disposal handoff");
                check("local-document-close".equals(source.closeThread), "cancelled TWR handoff uses closing lane");
                java.lang.reflect.Method cancel = type.getDeclaredMethod("cancel");
                cancel.setAccessible(true);
                cancel.invoke(operation);
            } finally {
                source.closeRelease.countDown();
                unwind.join(5000);
                awaitLaneIdle("CLOSING");
            }
            check(source.closes.get() == 1, "cancellation and TWR handoff retain exactly one provider close");
        }
    }

    private static void disposalSaturationRejectsBeforeOpeningAndRecovers() throws Exception {
        try (Fixture fixture = new Fixture()) {
            Object documents = documents(fixture.context);
            Source[] sources = new Source[2];
            StageCall[] cancelled = new StageCall[2];
            Uri healthy = fixture.resolver.add(1, "healthy.bin", "application/octet-stream");
            Source healthySource = fixture.resolver.sources.get(healthy);
            try {
                for (int i = 0; i < sources.length; i++) {
                    Uri uri = fixture.resolver.add(1, "blocked.bin", "application/octet-stream");
                    Source source = sources[i] = fixture.resolver.sources.get(uri);
                    source.blockOpen = true;
                    source.blockClose = true;
                    StageCall call = cancelled[i] = new StageCall(documents, uri);
                    call.thread.start();
                    check(source.entered.await(5, java.util.concurrent.TimeUnit.SECONDS), "saturation provider open entered " + i);
                    call.thread.interrupt();
                    call.thread.join(1000);
                    check(!call.thread.isAlive() && call.failure.get() instanceof java.io.InterruptedIOException
                            && call.keptInterrupt, "saturation cancellation returns with interrupt " + i);
                    source.release.countDown();
                    awaitLaneIdle("STAGING");
                }
                check(sources[0].closeEntered.await(5, java.util.concurrent.TimeUnit.SECONDS), "first disposal blocks closing lane");
                check(sources[1].closeEntered.getCount() == 1, "second disposal waits behind blocked close");
                expect(IOException.class, () -> stage(documents, new Intent().setData(healthy), false));
                check(healthySource.opens.get() == 0, "full disposal capacity rejects BEFORE opening another provider stream");
                check(cacheFileCount(fixture) == 0, "disposal saturation leaves no partials or cancelled publication");
                assertLaneBounds();
                check(sources[0].closeRelease.getCount() == 1, "capacity rejection does not release hostile close");
            } finally {
                for (int i = 0; i < sources.length; i++) {
                    if (sources[i] != null) {
                        sources[i].release.countDown();
                        sources[i].closeRelease.countDown();
                    }
                    if (cancelled[i] != null) {
                        cancelled[i].thread.interrupt();
                        cancelled[i].thread.join(5000);
                    }
                }
                awaitLaneIdle("STAGING");
                for (Source source : sources) if (source != null && source.opens.get() != 0) {
                    check(source.closedLatch.await(5, java.util.concurrent.TimeUnit.SECONDS), "retained disposal eventually closes");
                }
                awaitLaneIdle("CLOSING");
            }
            for (int i = 0; i < sources.length; i++) {
                check(sources[i].closes.get() == 1, "saturated disposal retained and closed exactly once " + i);
                check(cancelled[i].value == null, "saturated cancellation never publishes " + i);
            }
            check(stage(documents, new Intent().setData(healthy), false).length == 1,
                    "admission recovers after disposal capacity returns");
            check(healthySource.opens.get() == 1 && healthySource.closes.get() == 1,
                    "recovered healthy provider stream opened and closed once");
            check(fixture.resolver.peakStreams.get() <= 2 && fixture.resolver.activeStreams.get() == 0,
                    "at most two admitted provider streams; no disposed resources retained");
        }
    }

    private static java.util.concurrent.ThreadPoolExecutor lane(String name) throws Exception {
        java.lang.reflect.Field field = LocalDocuments.class.getDeclaredField(name);
        field.setAccessible(true);
        return (java.util.concurrent.ThreadPoolExecutor) field.get(null);
    }

    private static void assertLaneBounds() throws Exception {
        for (String name : new String[] {"STAGING", "CLOSING"}) {
            java.util.concurrent.ThreadPoolExecutor executor = lane(name);
            check(executor.getMaximumPoolSize() == 1 && executor.getLargestPoolSize() <= 1,
                    name + " retains one worker without replacement threads");
            check(executor.getQueue().size() + executor.getQueue().remainingCapacity() == 1,
                    name + " retains one bounded executor queue slot");
        }
    }

    private static void awaitLaneIdle(String name) throws Exception {
        lane(name).submit(new Runnable() { public void run() { } }).get(5, java.util.concurrent.TimeUnit.SECONDS);
    }

    private static final class StageCall implements Runnable {
        final Object documents;
        final Uri source;
        final Thread thread;
        final java.util.concurrent.atomic.AtomicReference<Throwable> failure =
                new java.util.concurrent.atomic.AtomicReference<Throwable>();
        volatile boolean keptInterrupt;
        volatile Uri[] value;
        StageCall(Object documents, Uri source) {
            this.documents = documents;
            this.source = source;
            thread = new Thread(this, "synthetic-stage-caller");
        }
        public void run() {
            try { value = stage(documents, new Intent().setData(source), false); }
            catch (Throwable caught) { failure.set(caught); keptInterrupt = Thread.currentThread().isInterrupted(); }
        }
    }

    private static int cacheFileCount(Fixture fixture) throws IOException {
        try (java.util.stream.Stream<java.nio.file.Path> paths = Files.walk(fixture.root.toPath())) {
            return (int) paths.filter(Files::isRegularFile).count();
        }
    }

    private static void rejectsInvalidSelectionsBeforeOpeningStreams() throws Exception {
        try (Fixture fixture = new Fixture()) {
            Object documents = documents(fixture.context);
            expect(IOException.class, () -> stage(documents, null, true));
            expect(IOException.class, () -> stage(documents, new Intent(), true));
            for (String value : new String[] {"file:///synthetic", "https://synthetic.invalid/item", "data:text/plain,x",
                    "content://us.pilipia.hermes.prototype.documents/abc", "content://US.PILIPIA.HERMES.PROTOTYPE.DOCUMENTS/abc",
                    "content://0@us.pilipia.hermes.prototype.documents/abc"}) {
                expect(IOException.class, () -> stage(documents, new Intent().setData(Uri.parse(value)), false));
            }
            Uri first = fixture.resolver.add(0, "one.bin", "application/octet-stream");
            Uri second = fixture.resolver.add(0, "two.bin", "application/octet-stream");
            expect(IOException.class, () -> stage(documents, selection(first, first), true));
            expect(IOException.class, () -> stage(documents, selection(first).setData(first), true));
            expect(IOException.class, () -> stage(documents, selection(first, second), false));
            Uri[] tooMany = new Uri[17];
            Arrays.fill(tooMany, first);
            expect(IOException.class, () -> stage(documents, selection(tooMany), true));
            expect(IOException.class, () -> stage(documents, selection((Uri) null), true));
            check(fixture.resolver.opened == 0 && cacheFileCount(fixture) == 0, "invalid selections do not read or create files");
            Uri[] sixteen = new Uri[16];
            for (int i=0;i<sixteen.length;i++) sixteen[i] = fixture.resolver.add(0, "empty.bin", "application/octet-stream");
            check(stage(documents, selection(sixteen), true).length == 16, "sixteen-item selection accepted");
        }
    }

    private static void validatesMetadataAndRollsBackErrors() throws Exception {
        try (Fixture fixture = new Fixture()) {
            Object documents = documents(fixture.context);
            for (String name : new String[] {null, "", " ", ".", "..", "../escape", "a\\b", "bad\nname", repeat('a',256)}) {
                Uri uri = fixture.resolver.add(3, name, "text/plain");
                expect(IOException.class, () -> stage(documents, new Intent().setData(uri), false));
            }
            for (String type : new String[] {null, "", "*/*", "text/*", "text/plain; charset=utf-8", "text/plain\r\nX:y"}) {
                Uri uri = fixture.resolver.add(3, "synthetic.txt", type);
                expect(IOException.class, () -> stage(documents, new Intent().setData(uri), false));
            }
            check(fixture.resolver.opened == 0 && cacheFileCount(fixture) == 0, "invalid metadata rejected before opening");
            for (int mode=1;mode<=7;mode++) {
                Uri good = fixture.resolver.add(7, "good.bin", "application/octet-stream");
                Uri bad = fixture.resolver.add(9000, "bad.bin", "application/octet-stream");
                Source goodSource = fixture.resolver.sources.get(good);
                Source badSource = fixture.resolver.sources.get(bad);
                badSource.failureMode = mode;
                expect(IOException.class, () -> stage(documents, selection(good, bad), true));
                check(cacheFileCount(fixture) == 0, "failed batch removes all completed and partial files");
                check(goodSource.closedLatch.await(5, java.util.concurrent.TimeUnit.SECONDS)
                        && goodSource.opens.get() == 1 && goodSource.closes.get() == 1,
                        "completed stream closed exactly once in failing batch mode " + mode);
                boolean returnedStream = mode == 3 || mode == 4;
                if (returnedStream) {
                    check(badSource.closedLatch.await(5, java.util.concurrent.TimeUnit.SECONDS),
                            "failing provider stream closure completes within bound for mode " + mode);
                }
                check(badSource.opens.get() == (mode <= 4 ? 1 : 0), "per-source failing open count for mode " + mode);
                check(badSource.closes.get() == (returnedStream ? 1 : 0),
                        "per-source failing stream closed exactly once iff a stream was returned for mode " + mode);
            }
            check(fixture.resolver.activeStreams.get() == 0, "all failing-batch provider streams released");
        }
    }

    private static void streamedLimitsIgnoreAdvertisedSizes() throws Exception {
        final long perFile = 32L*1024L*1024L;
        try (Fixture fixture = new Fixture()) {
            Object documents = documents(fixture.context);
            Uri oversized = fixture.resolver.add(perFile+1, "oversized.bin", "application/octet-stream");
            expect(IOException.class, () -> stage(documents, new Intent().setData(oversized), false));
            check(fixture.resolver.sources.get(oversized).readBytes == perFile+1, "per-file size checked by limit-plus-one stream probe");
            check(cacheFileCount(fixture) == 0, "oversize input leaves no cache file");
            Uri first = fixture.resolver.add(perFile, "one.bin", "application/octet-stream");
            Uri second = fixture.resolver.add(perFile, "two.bin", "application/octet-stream");
            Uri third = fixture.resolver.add(2, "three.bin", "application/octet-stream");
            expect(IOException.class, () -> stage(documents, selection(first, second, third), true));
            check(fixture.resolver.sources.get(third).readBytes == 1, "aggregate budget probes only one extra byte");
            check(cacheFileCount(fixture) == 0, "aggregate failure rolls back whole batch");
            Uri[] exact = stage(documents, selection(first, second), true);
            check(exact.length == 2 && cacheFileCount(fixture) == 2, "exact per-file and aggregate limits accepted");
            ContentProvider provider = provider(fixture.context);
            try (Cursor cursor = provider.query(exact[1], new String[] {OpenableColumns.SIZE}, null, null, null)) {
                check(cursor.moveToFirst() && cursor.getLong(0) == perFile, "reported size comes from copied bytes, not advertised zero");
            }
        }
    }

    private static void providerRejectsPathsWritesAndExtraColumns() throws Exception {
        try (Fixture fixture = new Fixture()) {
            Object documents = documents(fixture.context);
            Uri valid = exported(documents, new byte[] {1});
            ContentProvider provider = provider(fixture.context);
            for (String mode : new String[] {null, "w", "wt", "rw", "wa", "rwt", "R"}) {
                expect(java.io.FileNotFoundException.class, () -> provider.openFile(valid, mode));
            }
            for (String value : new String[] {valid+"/name.txt", valid+"?x=1", valid+"#x", valid+"/../x",
                    valid+"/", "file:///synthetic",
                    "content://us.pilipia.hermes.prototype.documents/00000000-0000-0000-0000-000000000000",
                    valid.toString().replace("documents/", "documents.evil/"),
                    valid.toString().replace("-", "%2d")}) {
                Uri invalid = Uri.parse(value);
                expect(java.io.FileNotFoundException.class, () -> provider.openFile(invalid, "r"));
                expect(IllegalArgumentException.class, () -> provider.getType(invalid));
                expect(IllegalArgumentException.class, () -> provider.query(invalid, null, null, null, null));
            }
            expect(java.io.FileNotFoundException.class, () -> provider.openFile(null, "r"));
            expect(IllegalArgumentException.class, () -> provider.query(valid, new String[] {"_data"}, null, null, null));
            expect(IllegalArgumentException.class, () -> provider.query(valid, null, "x", null, null));
            expect(IllegalArgumentException.class, () -> provider.query(valid, null, null, new String[0], null));
            expect(IllegalArgumentException.class, () -> provider.query(valid, null, null, null, "x"));
            expect(SecurityException.class, () -> provider.insert(valid, new android.content.ContentValues()));
            expect(SecurityException.class, () -> provider.update(valid, new android.content.ContentValues(), null, null));
            expect(SecurityException.class, () -> provider.delete(valid, null, null));
            expect(SecurityException.class, () -> provider.bulkInsert(valid, new android.content.ContentValues[0]));
        }
    }

    private static void exportSizeAndMetadataLimits() throws Exception {
        try (Fixture fixture = new Fixture()) {
            Object documents = documents(fixture.context);
            expect(IOException.class, () -> exported(documents, new byte[8*1024*1024+1]));
            expect(IOException.class, () -> exported(documents, null));
            expect(IOException.class, () -> invoke(documents, "export", new Class<?>[] {byte[].class,String.class,String.class},
                    new byte[0], "../bad", "text/plain"));
            expect(IOException.class, () -> invoke(documents, "export", new Class<?>[] {byte[].class,String.class,String.class},
                    new byte[0], "synthetic", "*/*"));
            check(cacheFileCount(fixture) == 0, "invalid exports create no files");
            Uri exact = exported(documents, new byte[8*1024*1024]);
            ContentProvider provider = provider(fixture.context);
            try (Cursor cursor = provider.query(exact, new String[] {OpenableColumns.SIZE}, null, null, null)) {
                check(cursor.moveToFirst() && cursor.getLong(0) == 8L*1024L*1024L, "exact export limit accepted");
            }
            check(exported(documents, new byte[0]) != null, "empty export accepted");
        }
    }

    private static void expiryCapacityAndStartupPruning() throws Exception {
        try (Fixture fixture = new Fixture()) {
            Object documents = documents(fixture.context);
            Uri first = exported(documents, new byte[] {1});
            ContentProvider provider = provider(fixture.context);
            for (int i=0;i<64;i++) exported(documents, new byte[] {2});
            check(cacheFileCount(fixture) == 64, "cache evicts oldest at sixty-four files");
            expect(java.io.FileNotFoundException.class, () -> provider.openFile(first, "r"));
            Uri live = exported(documents, new byte[] {3});
            android.os.SystemClock.advanceForTest(10L*60L*1000L-1);
            try (ParcelFileDescriptor descriptor = provider.openFile(live, "r")) {
                check(descriptor != null, "handle valid just before ten-minute expiry");
            }
            android.os.SystemClock.advanceForTest(1);
            expect(java.io.FileNotFoundException.class, () -> provider.openFile(live, "r"));
            check(cacheFileCount(fixture) == 0, "expired files physically evicted");
            Uri retained = exported(documents, new byte[] {4});
            File directory = new File(fixture.root, "local-documents");
            File orphan = new File(directory, "synthetic-orphan.part");
            Files.write(orphan.toPath(), new byte[] {5});
            File outside = new File(fixture.root, "unrelated-cache.bin");
            Files.write(outside.toPath(), new byte[] {6});
            provider.onCreate();
            check(!orphan.exists() && outside.exists(), "startup pruning is confined to owned cache directory");
            check("application/octet-stream".equals(provider.getType(retained)), "startup preserves live memory registry handles");
            java.lang.reflect.Field entries = provider.getClass().getDeclaredField("ENTRIES");
            entries.setAccessible(true);
            ((java.util.Map<?,?>)entries.get(null)).clear(); // Simulated process death, not a production test hook.
            provider.onCreate();
            expect(java.io.FileNotFoundException.class, () -> provider.openFile(retained, "r"));
            check(directory.list().length == 0 && outside.exists(), "process restart cannot reconstruct persisted capabilities");
        }
    }

    private static void pendingReservationsAreBoundedAndCannotRecreateEvictedFiles() throws Exception {
        try (Fixture fixture = new Fixture()) {
            LocalDocumentsProvider.Entry[] entries = new LocalDocumentsProvider.Entry[64];
            try {
                for (int i=0;i<entries.length;i++) entries[i] = LocalDocumentsProvider.reserve(
                        fixture.context, "synthetic.bin", "application/octet-stream");
                check(cacheFileCount(fixture) == 64, "pending reservations count toward file capacity");
                expect(IOException.class, () -> LocalDocumentsProvider.reserve(fixture.context, "synthetic.bin", "application/octet-stream"));
                LocalDocuments.cleanup(fixture.context);
                check(cacheFileCount(fixture) == 64, "cleanup preserves unexpired pending files");
                android.os.SystemClock.advanceForTest(10L*60L*1000L);
                LocalDocuments.cleanup(fixture.context);
                check(cacheFileCount(fixture) == 0, "cleanup expires pending reservations");
                expect(IOException.class, () -> LocalDocumentsProvider.openOutput(entries[0]));
                check(cacheFileCount(fixture) == 0, "late writer cannot recreate an evicted partial");
            } finally {
                for (LocalDocumentsProvider.Entry entry : entries) LocalDocumentsProvider.discard(entry);
            }
        }
    }

    private static Uri exported(Object documents, byte[] bytes) throws Exception {
        return (Uri) invoke(documents, "export", new Class<?>[] {byte[].class,String.class,String.class},
                bytes, "synthetic.bin", "application/octet-stream");
    }

    private static String repeat(char value, int count) {
        char[] chars = new char[count];Arrays.fill(chars,value);return new String(chars);
    }

    private static Intent selection(Uri... uris) {
        ClipData clip = ClipData.newRawUri("synthetic", uris[0]);
        for (int i=1;i<uris.length;i++) clip.addItem(new ClipData.Item(uris[i]));
        return new Intent().setClipData(clip);
    }

    private interface Throwing { void run() throws Exception; }

    private static void expect(Class<? extends Throwable> type, Throwing operation) throws Exception {
        try { operation.run(); }
        catch (Throwable caught) {
            check(type.isInstance(caught), "expected " + type.getSimpleName() + ", got " + caught.getClass().getSimpleName());
            return;
        }
        throw new AssertionError("Expected " + type.getSimpleName());
    }

    private static Uri[] stage(Object documents, Intent result, boolean multiple) throws Exception {
        return (Uri[]) invoke(documents, "stage", new Class<?>[] {Intent.class, boolean.class}, result, multiple);
    }

    private static ContentProvider provider(Context context) throws Exception {
        ContentProvider provider = (ContentProvider) Class.forName(
                "us.pilipia.hermes.prototype.LocalDocumentsProvider").getConstructor().newInstance();
        provider.attachInfo(context, null);
        return provider;
    }

    private static Object documents(Context context) throws Exception {
        try {
            return Class.forName("us.pilipia.hermes.prototype.LocalDocuments")
                    .getConstructor(Context.class).newInstance(context);
        } catch (ClassNotFoundException missing) {
            throw new AssertionError("Missing local document implementation");
        }
    }

    private static Object invoke(Object target, String name, Class<?>[] types, Object... args) throws Exception {
        try {
            return target.getClass().getMethod(name, types).invoke(target, args);
        } catch (InvocationTargetException failure) {
            Throwable cause = failure.getCause();
            if (cause instanceof Exception) throw (Exception) cause;
            if (cause instanceof Error) throw (Error) cause;
            throw failure;
        }
    }

    private static final class Fixture implements java.io.Closeable {
        final File root = new File(System.getProperty("java.io.tmpdir"), "fixture-" + UUID.randomUUID());
        final Resolver resolver = new Resolver();
        final Context context = new Context() {
            public File getCacheDir() { return root; }
            public ContentResolver getContentResolver() { return resolver; }
        };
        Fixture() throws IOException {
            if (!root.mkdir()) throw new IOException("Cannot create synthetic fixture");
        }
        public void close() throws IOException {
            try (java.util.stream.Stream<java.nio.file.Path> paths = Files.walk(root.toPath())) {
                java.nio.file.Path[] all = paths.sorted(java.util.Comparator.reverseOrder()).toArray(java.nio.file.Path[]::new);
                for (java.nio.file.Path path : all) Files.deleteIfExists(path);
            }
        }
    }

    private static final class Source {
        long length;
        long readBytes;
        int failureMode;
        String name;
        String mime;
        boolean block;
        boolean blockOpen;
        boolean blockClose;
        volatile String closeThread;
        final java.util.concurrent.atomic.AtomicInteger opens = new java.util.concurrent.atomic.AtomicInteger();
        final java.util.concurrent.atomic.AtomicInteger closes = new java.util.concurrent.atomic.AtomicInteger();
        final java.util.concurrent.CountDownLatch closeEntered = new java.util.concurrent.CountDownLatch(1);
        final java.util.concurrent.CountDownLatch closeRelease = new java.util.concurrent.CountDownLatch(1);
        final java.util.concurrent.CountDownLatch entered = new java.util.concurrent.CountDownLatch(1);
        final java.util.concurrent.CountDownLatch release = new java.util.concurrent.CountDownLatch(1);
        final java.util.concurrent.CountDownLatch closedLatch = new java.util.concurrent.CountDownLatch(1);
        Source(long length, String name, String mime) { this.length=length; this.name=name; this.mime=mime; }
        void awaitRelease() {
            entered.countDown();
            while (release.getCount() != 0) {
                try { release.await(); } catch (InterruptedException ignored) { }
            }
        }
    }

    private static final class Resolver extends ContentResolver {
        final java.util.Map<Uri, Source> sources = new java.util.LinkedHashMap<Uri, Source>();
        int opened;
        int closed;
        final java.util.concurrent.atomic.AtomicInteger activeStreams = new java.util.concurrent.atomic.AtomicInteger();
        final java.util.concurrent.atomic.AtomicInteger peakStreams = new java.util.concurrent.atomic.AtomicInteger();
        Uri add(long length, String name, String mime) {
            Uri uri = Uri.parse("content://synthetic.provider/item/" + sources.size());
            sources.put(uri, new Source(length, name, mime));
            return uri;
        }
        public Cursor query(Uri uri, String[] columns, String selection, String[] args, String order) {
            Source source = sources.get(uri);
            if (source == null) throw new SecurityException("Synthetic URI unavailable");
            if (source.failureMode == 5) return null;
            if (source.failureMode == 6) columns = new String[] {OpenableColumns.SIZE};
            MatrixCursor cursor = new MatrixCursor(columns);
            if (source.failureMode == 7) return cursor;
            Object[] row = new Object[columns.length];
            for (int i=0;i<columns.length;i++) {
                if (OpenableColumns.DISPLAY_NAME.equals(columns[i])) row[i] = source.name;
                else if (OpenableColumns.SIZE.equals(columns[i])) row[i] = Long.valueOf(0);
                else throw new AssertionError("Unexpected metadata column");
            }
            cursor.addRow(row);
            return cursor;
        }
        public String getType(Uri uri) { return sources.get(uri).mime; }
        public InputStream openInputStream(Uri uri) {
            final Source source = sources.get(uri);
            opened++;
            source.opens.incrementAndGet();
            if (source.blockOpen) source.awaitRelease();
            if (source.failureMode == 1) return null;
            if (source.failureMode == 2) throw new SecurityException("Synthetic read denied");
            peakStreams.accumulateAndGet(activeStreams.incrementAndGet(), Math::max);
            return new InputStream() {
                long remaining = source.length;
                private void awaitRelease() {
                    if (!source.block) return;
                    source.awaitRelease();
                }
                public int read() throws IOException {
                    awaitRelease();
                    if(source.failureMode==3 && remaining<source.length)throw new IOException("Synthetic read failure");
                    if (remaining==0)return -1;remaining--;source.readBytes++;return 42;
                }
                public int read(byte[] bytes,int offset,int count) throws IOException {
                    awaitRelease();
                    if(source.failureMode==3 && remaining<source.length)throw new IOException("Synthetic read failure");
                    if (remaining==0)return -1;
                    int actual=(int)Math.min(remaining,count);
                    Arrays.fill(bytes,offset,offset+actual,(byte)42);remaining-=actual;source.readBytes+=actual;return actual;
                }
                public void close() throws IOException {
                    source.closes.incrementAndGet();
                    source.closeThread = Thread.currentThread().getName();
                    source.closeEntered.countDown();
                    while (source.blockClose && source.closeRelease.getCount() != 0) {
                        try { source.closeRelease.await(); } catch (InterruptedException ignored) { }
                    }
                    activeStreams.decrementAndGet();
                    source.release.countDown();closed++;source.closedLatch.countDown();
                    if(source.failureMode==4)throw new IOException("Synthetic close failure");
                }
            };
        }
    }

    private static final class CountingInput extends InputStream {
        final long length;
        long consumed;
        int largestRequest;
        boolean closed;
        CountingInput(long length) { this.length=length; }
        public int read() { if(consumed==length)return -1;consumed++;return 42; }
        public int read(byte[] bytes,int offset,int count) {
            largestRequest=Math.max(largestRequest,count);
            if(consumed==length)return -1;
            int actual=(int)Math.min(length-consumed,count);
            Arrays.fill(bytes,offset,offset+actual,(byte)42);consumed+=actual;return actual;
        }
        public void close() { closed=true; }
    }

    private static final class CountingOutput extends OutputStream {
        long written;
        boolean closed;
        public void write(int one) { written++; }
        public void write(byte[] bytes,int offset,int count) { written+=count; }
        public void close() { closed=true; }
    }

    private static long copy(InputStream input, OutputStream output, long limit) throws Exception {
        try {
            return ((Long) Class.forName("us.pilipia.hermes.prototype.BoundedStreams")
                    .getMethod("copy", InputStream.class, OutputStream.class, long.class)
                    .invoke(null, input, output, limit)).longValue();
        } catch (ClassNotFoundException missing) {
            throw new AssertionError("Missing bounded copy implementation");
        } catch (InvocationTargetException failure) {
            Throwable cause = failure.getCause();
            if (cause instanceof Exception) throw (Exception) cause;
            if (cause instanceof Error) throw (Error) cause;
            throw failure;
        }
    }

    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) throw new AssertionError(message);
    }
}
