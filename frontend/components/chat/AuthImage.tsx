"use client";

import { useEffect, useState } from "react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  imageId: string;
  alt?: string;
  className?: string;
  onClick?: (objectUrl: string) => void;
}

/**
 * AuthImage — 顯示需要認證的後端圖片（GET /api/chat/image/{id}）。
 * <img> 無法帶 Bearer token，故用 axios（攔截器會自動帶 token）抓 blob → object URL 顯示。
 */
export default function AuthImage({ imageId, alt = "", className, onClick }: Props) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let revoked = false;
    let obj: string | null = null;
    api
      .get(`/chat/image/${imageId}`, { responseType: "blob" })
      .then(({ data }) => {
        if (revoked) return;
        obj = URL.createObjectURL(data as Blob);
        setUrl(obj);
      })
      .catch(() => {});
    return () => {
      revoked = true;
      if (obj) URL.revokeObjectURL(obj);
    };
  }, [imageId]);

  if (!url) {
    return <div className={cn("bg-zinc-200 animate-pulse", className)} />;
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt={alt} className={className} onClick={() => onClick?.(url)} />
  );
}
