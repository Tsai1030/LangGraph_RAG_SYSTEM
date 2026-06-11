"use client";

import { useEffect, useState } from "react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  /** 使用者上傳圖（GET /api/chat/image/{id}）。與 src 二擇一。 */
  imageId?: string;
  /** 任意需認證的後端圖片 URL（如 /api/images/...，KB 附圖）。與 imageId 二擇一。 */
  src?: string;
  alt?: string;
  className?: string;
  onClick?: (objectUrl: string) => void;
}

// blob object URL 快取：串流中 markdown 每個 token 重渲染會重掛載元件，
// 沒有快取會對同一張圖重複打 API。object URL 由快取持有、不 revoke
// （每對話 KB 圖數量有限，常駐記憶體成本可忽略）。
const blobCache = new Map<string, Promise<string>>();

function fetchObjectUrl(path: string): Promise<string> {
  let p = blobCache.get(path);
  if (!p) {
    p = api
      .get(path, { responseType: "blob" })
      .then(({ data }) => URL.createObjectURL(data as Blob));
    // 失敗不留在快取，之後重掛載可重試
    p.catch(() => blobCache.delete(path));
    blobCache.set(path, p);
  }
  return p;
}

/**
 * AuthImage — 顯示需要認證的後端圖片。
 * <img> 無法帶 Bearer token，故用 axios（攔截器會自動帶 token）抓 blob → object URL 顯示。
 * 載入失敗時 render null（等同舊版 <img onError> 的隱藏行為）。
 */
export default function AuthImage({ imageId, src, alt = "", className, onClick }: Props) {
  const path = src ? src.replace(/^\/api/, "") : `/chat/image/${imageId}`;
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setUrl(null);
    setFailed(false);
    fetchObjectUrl(path)
      .then((u) => {
        if (!cancelled) setUrl(u);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  if (failed) return null;
  if (!url) {
    return <div className={cn("bg-zinc-200 animate-pulse", className)} />;
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt={alt} className={className} onClick={() => onClick?.(url)} />
  );
}
