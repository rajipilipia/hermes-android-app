package us.pilipia.hermes.prototype;

import java.io.IOException;
import java.io.InputStream;
import java.io.InterruptedIOException;
import java.io.OutputStream;

/** Fixed-memory copying with a one-byte oversize probe; neither stream is closed. */
public final class BoundedStreams {
    private BoundedStreams() { }

    public static long copy(InputStream input, OutputStream output, long limit) throws IOException {
        if (input == null || output == null) throw new NullPointerException("Missing stream");
        if (limit < 0) throw new IllegalArgumentException("Negative copy limit");
        checkInterrupted(0);
        byte[] buffer = new byte[8192];
        long copied = 0;
        while (copied < limit) {
            checkInterrupted(copied);
            int requested = (int) Math.min(buffer.length, limit - copied);
            int count = input.read(buffer, 0, requested);
            checkInterrupted(copied);
            if (count < 0) return copied;
            if (count == 0) {
                int one = input.read();
                checkInterrupted(copied);
                if (one < 0) return copied;
                output.write(one);
                copied++;
            } else {
                output.write(buffer, 0, count);
                copied += count;
            }
        }
        checkInterrupted(copied);
        int probe = input.read();
        checkInterrupted(copied);
        if (probe != -1) throw new IOException("Document exceeds copy limit");
        return copied;
    }

    private static void checkInterrupted(long copied) throws InterruptedIOException {
        if (Thread.currentThread().isInterrupted()) {
            InterruptedIOException failure = new InterruptedIOException("Document copy cancelled");
            failure.bytesTransferred = (int) Math.min(Integer.MAX_VALUE, copied);
            throw failure;
        }
    }
}
