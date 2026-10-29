import type { PreviewTarget } from "../../vendor/hermes/apps/desktop/src/store/preview";
import { openExternal } from "./native-browser";

/** PC files stay inside the authenticated app preview, never a phone file:// URL. */
export async function openAndroidPreview(target: PreviewTarget): Promise<void> {
  if (target.kind === "file") {
    const { openPreview } = await import("../../vendor/hermes/apps/desktop/src/store/preview");
    openPreview({ ...target, renderMode: target.renderMode ?? "preview" });
    return;
  }
  await openExternal(target.url);
}
