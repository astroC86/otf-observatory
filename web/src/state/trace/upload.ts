import type { ChangeEvent } from "react";
import { uploadFile } from "../../api/client";
import { mutate } from "../../api/mutate";
import type { ImportJob } from "../../api/types/common";
import { updateUi } from "../store";
import { notify } from "../uiActions";
import { beginTraceLoad, isCurrentTraceLoad, setLoadingId } from "./requests";
import { waitImport } from "./open";
import { loadTrace } from "./load";
export async function uploadFolder(event: ChangeEvent<HTMLInputElement>): Promise<void> {
  const request = beginTraceLoad();
  try {
    const files = [...(event.target.files || [])],
      anchors = files.filter((file) => /\.(otf2|otf)$/.test(file.name));
    const anchor = anchors[0];
    if (anchors.length !== 1 || !anchor)
      throw Error("Select a folder containing exactly one .otf2 or .otf anchor.");
    const { token } = await mutate<{ token: string }>("upload/start", {});
    if (!isCurrentTraceLoad(request)) return;
    updateUi({ dialog: "loading", loadingTitle: "Importing trace folder" });
    for (const [index, file] of files.entries()) {
      updateUi({
        loadingPhase: `Copying ${file.name}`,
        loadingCount: `${index + 1} / ${files.length} files`,
      });
      await uploadFile(token, file);
      if (!isCurrentTraceLoad(request)) return;
    }
    const job = await mutate<ImportJob>("upload/finish", {
      token,
      anchor: anchor.webkitRelativePath,
    });
    if (!isCurrentTraceLoad(request)) return;
    setLoadingId(job.id);
    updateUi({ loadingTitle: "Opening trace" });
    await waitImport(job.id, request);
    if (!isCurrentTraceLoad(request)) return;
    await loadTrace(job.id, null, request);
  } catch (error) {
    if (!isCurrentTraceLoad(request)) return;
    updateUi({ dialog: null });
    notify(error instanceof Error ? error.message : String(error));
  }
}
