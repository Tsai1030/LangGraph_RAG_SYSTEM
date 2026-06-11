"use client";

import { X } from "lucide-react";
import type { PendingDocument } from "@/types";

function formatSize(bytes?: number): string | null {
  if (!bytes) return null;
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function fileExt(filename: string): string {
  const m = filename.match(/\.([a-zA-Z0-9]+)$/);
  return (m?.[1] ?? "FILE").toUpperCase();
}

/**
 * DocumentCard — InputBar 內的文件附件卡（圓角方形）。
 *
 * status="uploading"：skeleton 線條（上長、下短、空隙、左下最短）+ pulse，
 * 不用轉圈 spinner。完成後顯示檔名、檔案大小與左下角格式 badge。
 */
export default function DocumentCard({
  doc,
  onRemove,
}: {
  doc: PendingDocument;
  onRemove?: (documentId: string) => void;
}) {
  const uploading = doc.status === "uploading";
  const size = formatSize(doc.size);

  return (
    <div className="relative">
      <div className="flex flex-col w-28 h-28 rounded-xl border border-zinc-200 bg-white p-2.5 shadow-sm">
        {uploading ? (
          <div className="flex flex-col h-full animate-pulse">
            <div className="h-2.5 w-full rounded-full bg-zinc-200" />
            <div className="h-2.5 w-2/3 rounded-full bg-zinc-200 mt-2" />
            <div className="h-2.5 w-1/3 rounded-full bg-zinc-200 mt-auto" />
          </div>
        ) : (
          <>
            <p className="text-[12px] font-medium text-zinc-800 leading-snug line-clamp-2 break-all">
              {doc.filename}
            </p>
            {size && <p className="text-[11px] text-zinc-400 mt-0.5">{size}</p>}
            <div className="mt-auto">
              <span className="inline-block px-1.5 py-0.5 rounded-md border border-zinc-300 text-[10px] font-semibold text-zinc-500 tracking-wide">
                {fileExt(doc.filename)}
              </span>
            </div>
          </>
        )}
      </div>

      {!uploading && onRemove && (
        <button
          type="button"
          onClick={() => onRemove(doc.document_id)}
          className="absolute -top-1.5 -right-1.5 size-5 rounded-full bg-zinc-800 hover:bg-zinc-700 text-white flex items-center justify-center shadow"
          title="移除"
        >
          <X size={11} />
        </button>
      )}
    </div>
  );
}
