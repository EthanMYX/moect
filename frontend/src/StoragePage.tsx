import { useEffect, useRef, useState } from "react";
import { call } from "./native";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { formatBytes } from "./formatBytes";

export function StoragePage({
  state,
  onChanged,
  onError,
}: {
  state: any;
  onChanged: () => Promise<any>;
  onError: (error: any) => void;
}) {
  const [data, setData] = useState<any>(null),
    [busy, setBusy] = useState(false),
    [confirm, setConfirm] = useState(false);
  const [resetConfirm,setResetConfirm]=useState(false);
  const loadSequence = useRef(0);
  const load = () => {
    const sequence = ++loadSequence.current;
    setBusy(true);
    return call("storage_info")
      .then((result) => { if (sequence === loadSequence.current) setData(result); })
      .catch((error) => { if (sequence === loadSequence.current) onError(error); })
      .finally(() => { if (sequence === loadSequence.current) setBusy(false); });
  };
  useEffect(() => {
    load();
    return () => { loadSequence.current += 1; };
  }, [state.storage_dir, state.storage_busy]);
  const active = state.tasks?.some((task: any) =>
    ["queued", "running"].includes(task.status),
  );
  const act = async (action: string) => {
    setConfirm(false);
    setResetConfirm(false);
    setBusy(true);
    try {
      const result = await call(action);
      if (!result.cancelled) await onChanged();
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="space-y-4">
      <h3 className="text-[14px] font-medium">缓存与存储</h3>
      {state.storage_warning && (
        <p className="text-xs text-amber-700">{state.storage_warning}</p>
      )}
      <div className="grid grid-cols-2 gap-3 rounded-xl bg-muted/30 p-4 text-xs">
        <div>
          缓存总占用{" "}
          <strong className="block mt-1 text-lg font-medium">
            {data ? formatBytes(data.bytes) : "正在统计…"}
          </strong>
        </div>
        <div className="space-y-1 text-muted-foreground">
          {data?.roots?.map((root: any) => (
            <div key={root.path}>
              <span>
                {root.current ? "当前位置" : "历史位置"}{" "}
                {formatBytes(root.bytes)}
              </span>
              <div className="break-all text-[11px]">{root.path}</div><p className="text-[11px]">快照 {formatBytes(root.categories?.archives||0)} · 媒体缓存 {formatBytes(root.categories?.["media-cache"]||0)} · 头像 {formatBytes(root.categories?.["avatar-cache"]||0)} · 预览 {formatBytes(root.categories?.previews||0)}</p>
            </div>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          className="rounded-full"
          disabled={busy || active}
          onClick={() => act("choose_cache")}
        >
          更改缓存位置
        </Button>
        <Button
          variant="outline"
          className="rounded-full"
          disabled={busy || active}
          onClick={() => setConfirm(true)}
        >
          清理过期快照与缓存
        </Button>
        <Button
          variant="ghost"
          className="rounded-full"
          disabled={busy}
          onClick={load}
        >
          刷新占用
        </Button>
        {state.storage_warning&&<Button variant="outline" className="rounded-full" disabled={busy||active} onClick={()=>setResetConfirm(true)}>恢复默认缓存位置</Button>}
      </div>
      {state.storage_busy && (
        <p className="text-xs text-primary">
          正在处理存储任务，可在任务页面查看进度。
        </p>
      )}
      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent>
          <DialogTitle>清理过期缓存</DialogTitle>
          <p className="text-sm text-muted-foreground">
            将清理已不再使用的快照、媒体下载缓存和预览缓存。下次需要时可重新整理或生成。
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirm(false)}>
              取消
            </Button>
            <Button onClick={() => act("storage_cleanup")}>开始清理</Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={resetConfirm} onOpenChange={setResetConfirm}><DialogContent><DialogTitle>恢复默认缓存位置</DialogTitle><p className="text-sm text-muted-foreground">将在本机默认位置重新生成缓存。完成后请重新连接微信，或重新打开本地备份。</p><div className="flex justify-end gap-2"><Button variant="ghost" onClick={()=>setResetConfirm(false)}>取消</Button><Button onClick={()=>act('storage_reset')}>恢复默认位置</Button></div></DialogContent></Dialog>
    </section>
  );
}
