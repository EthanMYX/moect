import { useEffect, useRef, useState } from "react";
import { call } from "./native";
import { Button } from "@/components/ui/button";

let queue: Promise<any> = Promise.resolve();

export function LocalMediaPreview({ hint }: { hint: any }) {
  const holder = useRef<HTMLDivElement>(null),
    dialog = useRef<HTMLDialogElement>(null);
  const [result, setResult] = useState<any>(null),
    [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false,
      started = false;
    setResult(null);
    const start = () => {
      if (started) return;
      started = true;
      const job = queue
        .catch(() => {})
        .then(() => {
          if (cancelled) throw new Error("cancelled");
          return call("preview_media", hint);
        });
      queue = job.then(
        () => undefined,
        () => undefined,
      );
      job
        .then((value) => {
          if (!cancelled) setResult(value);
        })
        .catch((error) => {
          if (!cancelled) setResult({ notice: error.message });
        });
    };
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          observer.disconnect();
          start();
        }
      },
      { rootMargin: "120px" },
    );
    if (holder.current) observer.observe(holder.current);
    return () => {
      cancelled = true;
      observer.disconnect();
    };
  }, [hint.session, hint.shard, hint.local_id, hint.server_id, attempt]);
  return (
    <div ref={holder} className="mt-2 min-h-10 max-w-full">
      {!result && (
        <div className="rounded-xl bg-muted/50 px-4 py-5 text-xs text-muted-foreground">
          正在读取本地{hint.kind === "voice" ? "语音" : "图片 / 表情"}…
        </div>
      )}
      {result?.url && result.kind === "image" && (
        <>
          <button
            type="button"
            className="block max-w-full rounded-xl overflow-hidden"
            title="放大图片"
            aria-label="放大图片"
            onClick={() => dialog.current?.showModal()}
          >
            <img
              src={result.url}
              alt={hint.kind === "emoji" ? "微信表情" : "微信图片"}
              className={
                hint.kind === "emoji"
                  ? "max-w-40 max-h-40 object-contain"
                  : "max-w-full max-h-80 object-contain"
              }
            />
          </button>
          <dialog
            ref={dialog}
            className="m-auto rounded-2xl border border-border bg-card text-foreground p-4 max-w-[94vw] max-h-[94vh] backdrop:bg-black/70"
            onClick={(event) => {
              if (event.target === event.currentTarget) dialog.current?.close();
            }}
          >
            <div className="flex justify-end mb-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => dialog.current?.close()}
              >
                关闭
              </Button>
            </div>
            <img
              src={result.url}
              alt="放大预览"
              className="max-w-[86vw] max-h-[80vh] object-contain"
            />
          </dialog>
        </>
      )}
      {result?.url && result.kind === "audio" && (
        <audio
          controls
          preload="metadata"
          src={result.url}
          className="max-w-full"
        />
      )}
      {result?.notice && (
        <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap">
          {result.notice}
        </p>
      )}
      {result && !result.url && (
        <Button
          variant="ghost"
          size="sm"
          className="mt-1 text-xs"
          onClick={() => setAttempt((value) => value + 1)}
        >
          重试读取
        </Button>
      )}
    </div>
  );
}
