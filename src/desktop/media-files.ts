import type { HermesSelectPathsOptions } from "../../vendor/hermes/apps/desktop/src/global";

// Only ephemeral in-document browser File capabilities. These are never PC paths
// and are never serialized into an upload/prompt. No persistent storage or bridge.
export function createSelectedFiles(isDisposed: () => boolean) {
  const files = new Map<string, File>();
  const paths = new WeakMap<File, string>();
  const pending = new Set<(error: Error) => void>();
  let total = 0;
  const check = () => {
    if (isDisposed()) throw new Error("Android connection has been closed.");
  };
  const register = (file: File): string => {
    check();
    if (
      !(file instanceof File) ||
      !file.name ||
      file.name.length > 255 ||
      file.name !== file.name.trim() ||
      file.name.endsWith(".") ||
      /[\u0000-\u001f/\\:*?"<>|%]/.test(file.name) ||
      /^(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)/i.test(file.name)
    )
      throw new Error("Unsupported selected filename.");
    const known = paths.get(file);
    if (known && files.has(known)) return known;
    if (
      file.size > 26214400 ||
      files.size >= 64 ||
      total + file.size > 104857600
    )
      throw new Error(
        "Selected file limit reached; reselect fewer or smaller files.",
      );
    const path = `android-selected/${crypto.randomUUID()}/${file.name}`;
    files.set(path, file);
    paths.set(file, path);
    total += file.size;
    return path;
  };
  const get = (path: string): File => {
    check();
    const file = files.get(path);
    if (!file)
      throw new Error("Selected file is unavailable; select it again.");
    return file;
  };
  const selectPaths = (
    options: HermesSelectPathsOptions = {},
  ): Promise<string[]> => {
    check();
    if (options.directories)
      return Promise.reject(
        new Error("Choose PC folders using the remote workspace picker."),
      );
    return new Promise((resolve, reject) => {
      const input = document.createElement("input");
      input.type = "file";
      input.multiple = options.multiple !== false;
      input.accept = (options.filters ?? [])
        .flatMap((f) => f.extensions)
        .map((ext) => {
          if (ext === "*") return "";
          if (!/^[a-zA-Z0-9]+$/.test(ext))
            throw new Error("Invalid file filter.");
          return `.${ext}`;
        })
        .filter(Boolean)
        .join(",");
      input.hidden = true;
      let settled = false;
      const cleanup = () => {
        input.remove();
        pending.delete(cancel);
      };
      const cancel = (error: Error) => {
        if (!settled) {
          settled = true;
          cleanup();
          reject(error);
        }
      };
      input.addEventListener(
        "cancel",
        () => {
          if (!settled) {
            settled = true;
            cleanup();
            resolve([]);
          }
        },
        { once: true },
      );
      input.addEventListener(
        "change",
        () => {
          if (settled) return;
          const retainedPaths = new Set(files.keys());
          try {
            check();
            const selected = Array.from(input.files ?? []).map(register);
            settled = true;
            cleanup();
            resolve(selected);
          } catch (error) {
            // Selection is synchronous and atomic: keep existing composer
            // handles, but release everything registered by this failed batch.
            for (const [path, file] of files) {
              if (!retainedPaths.has(path)) {
                files.delete(path);
                total -= file.size;
              }
            }
            cancel(
              error instanceof Error
                ? error
                : new Error("File selection failed."),
            );
          }
        },
        { once: true },
      );
      pending.add(cancel);
      document.body.append(input);
      // Deliberately synchronous under the Attach click/user activation.
      try {
        input.click();
      } catch {
        cancel(new Error("File chooser could not open."));
      }
    });
  };
  const readFileDataUrl = async (path: string): Promise<string> => {
    const file = get(path);
    const data = new Uint8Array(await file.arrayBuffer());
    check();
    const parts: string[] = [];
    for (let offset = 0; offset < data.length; offset += 49152) {
      let binary = "";
      for (const byte of data.subarray(offset, offset + 49152))
        binary += String.fromCharCode(byte);
      parts.push(btoa(binary));
    }
    return `data:${file.type || "application/octet-stream"};base64,${parts.join("")}`;
  };
  return {
    register,
    get,
    selectPaths,
    readFileDataUrl,
    isLocalPath: (path: string) => files.has(path),
    discard: (path: string) => {
      const file = files.get(path);
      if (file) {
        files.delete(path);
        total -= file.size;
      }
    },
    savePastedText: async (text: string) => {
      if (typeof text !== "string" || text.length > 26214400)
        throw new Error("Pasted text exceeds the file limit.");
      return register(
        new File([text], `paste-${crypto.randomUUID()}.txt`, {
          type: "text/plain",
        }),
      );
    },
    saveImageBuffer: async (
      data: Uint8Array,
      extension = ".png",
      name?: string,
    ) => {
      const types: Record<string, string> = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
      };
      if (!(data instanceof Uint8Array) || !Object.hasOwn(types, extension))
        throw new Error("Invalid selected image.");
      return register(
        new File(
          [data.slice().buffer],
          name || `image-${crypto.randomUUID()}${extension}`,
          { type: types[extension] },
        ),
      );
    },
    dispose: () => {
      for (const cancel of [...pending])
        cancel(new Error("Android connection has been closed."));
      files.clear();
      total = 0;
    },
  };
}
