// Desktop's edit-menu host member (hermesDesktop.contextMenuEdit, NG-4 2026-10-20). Electron runs
// webContents.copy()/cut()/paste() in main; Android has no main process, so the page's own edit
// commands do the same on the focused field. Paste needs the clipboard read, which Android
// WebView may refuse: then it is a no-op, as Desktop's empty-clipboard paste is.
export type EditCommand = "copy" | "cut" | "paste" | "selectAll";

export async function contextMenuEdit(command: EditCommand, doc: Document = document): Promise<void> {
  if (command === "paste") {
    let text = "";
    try {
      text = (await globalThis.navigator?.clipboard?.readText?.()) ?? "";
    } catch {
      return;
    }
    if (text) doc.execCommand("insertText", false, text);
    return;
  }
  doc.execCommand(command);
}
