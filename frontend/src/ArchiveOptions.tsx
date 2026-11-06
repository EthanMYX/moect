import { useEffect, useRef, useState, useId } from "react";
import { call } from "./native";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";

export function useArchivePreferences(open: boolean) {
  const [zip, setZipValue] = useState(false),
    [encrypt, setEncryptValue] = useState(false),
    [password, setPassword] = useState("");
  const [hasPassword, setHasPassword] = useState(false),
    [loaded, setLoaded] = useState(false),
    [error, setError] = useState("");
  const queue = useRef<Promise<any>>(Promise.resolve());
  useEffect(() => {
    if (!open) {
      setPassword("");
      return;
    }
    let current = true;
    setLoaded(false);
    setPassword("");
    setError("");
    queue.current
      .catch(() => {})
      .then(() => call("archive_preferences"))
      .then((value) => {
        if (current) {
          setZipValue(!!value.zip);
          setEncryptValue(!!value.encrypt);
          setHasPassword(!!value.has_password);
          setLoaded(true);
        }
      })
      .catch((error) => {
        if (current) setError(error.message);
      });
    return () => {
      current = false;
    };
  }, [open]);
  const remember = (value: any) => {
    const job = queue.current
      .catch(() => {})
      .then(() => call("archive_preferences", value))
      .then((result) => {
        setHasPassword(!!result.has_password);
        setError("");
      })
      .catch((error) => {
        setError(error.message);
        throw error;
      });
    queue.current = job;
    job.catch(() => {});
    return job;
  };
  const setZip = (value: boolean) => {
    setZipValue(value);
    if (!value) setEncryptValue(false);
    remember({ zip: value, encrypt: value ? encrypt : false });
  };
  const setEncrypt = (value: boolean) => {
    setEncryptValue(value);
    if (value) setZipValue(true);
    remember({ zip: value ? true : zip, encrypt: value });
  };
  const savePassword = () =>
    password ? remember({ password }) : queue.current;
  const flush = async () => {
    if (!loaded) throw new Error("正在读取导出偏好，请稍候");
    if (encrypt && !password && !hasPassword)
      throw new Error("请先设置加密压缩包密码");
    await queue.current;
    if (password) await remember({ password });
  };
  return {
    zip,
    encrypt,
    password,
    hasPassword,
    loaded,
    error,
    setZip,
    setEncrypt,
    setPassword,
    savePassword,
    flush,
  };
}

export function ArchiveOptions({
  model,
  disabled = false,
}: {
  model: ReturnType<typeof useArchivePreferences>;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <section className="space-y-3" aria-label="压缩与加密">
      <div className="rounded-2xl bg-muted/40 divide-y divide-border/50">
        <div className="flex items-center justify-between gap-5 px-5 py-4">
          <div>
            <label htmlFor={id + "-zip"} className="text-[13px] font-medium">
              导出为 ZIP 压缩包
            </label>
          </div>
          <Switch
            id={id + "-zip"}
            checked={model.zip}
            disabled={!model.loaded || disabled}
            onCheckedChange={model.setZip}
          />
        </div>
        <div className="flex items-center justify-between gap-5 px-5 py-4">
          <div>
            <label
              htmlFor={id + "-encrypt"}
              className="text-[13px] font-medium"
            >
              使用密码加密压缩包
            </label>
          </div>
          <Switch
            id={id + "-encrypt"}
            checked={model.encrypt}
            disabled={!model.loaded || disabled}
            onCheckedChange={model.setEncrypt}
          />
        </div>
        {model.encrypt && (
          <div className="px-5 py-4 space-y-2">
            <label
              className="text-[13px] font-medium"
              htmlFor={id + "-password"}
            >
              压缩包密码
            </label>
            <Input
              id={id + "-password"}
              type="password"
              autoComplete="new-password"
              maxLength={256}
              disabled={!model.loaded || disabled}
              value={model.password}
              placeholder={model.hasPassword ? "" : "输入解压密码"}
              onChange={(event) => model.setPassword(event.target.value)}
              onBlur={() => {
                model.savePassword().catch(() => {});
              }}
            />
          </div>
        )}
      </div>
      {model.error && (
        <p role="alert" className="text-xs text-red-600">
          {model.error}
        </p>
      )}
    </section>
  );
}
