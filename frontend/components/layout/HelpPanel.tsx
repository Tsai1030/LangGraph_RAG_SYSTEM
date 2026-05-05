"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, ChevronRight, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onClose: () => void;
}

interface Category {
  id: string;
  title: string;
  body: React.ReactNode;
}

const CATEGORIES: Category[] = [
  {
    id: "start",
    title: "開始使用",
    body: (
      <>
        <p>
          登入後系統會自動帶到「歡迎頁」，左側會出現對話清單。
          想開始新對話可以：
        </p>
        <ul>
          <li>點左側 <b>新對話</b> 按鈕（或直接在歡迎頁的輸入框送出問題）</li>
          <li>點歡迎頁中的建議卡片快速試問</li>
        </ul>
        <p>若離線過久，重新整理會自動還原 session，不需要再登入一次。</p>
      </>
    ),
  },
  {
    id: "chat",
    title: "對話操作",
    body: (
      <>
        <p>每則 AI 回覆下方都有兩顆按鈕：</p>
        <ul>
          <li><b>Copy</b>：把回覆全文複製到剪貼簿（保留 markdown）</li>
          <li><b>Retry</b>：重答這一輪。會把這則 AI 回答以及之後的所有訊息一併捨棄，重新送出對應的問題</li>
        </ul>
        <p>
          側邊欄滑入對話列會看到右側 <b>三點按鈕</b>，可以：
        </p>
        <ul>
          <li><b>Rename</b> — 重新命名對話</li>
          <li><b>Delete</b> — 刪除對話（會跳出確認 modal）</li>
        </ul>
      </>
    ),
  },
  {
    id: "form-download",
    title: "靜態表單下載",
    body: (
      <>
        <p>
          輸入框最左邊的 <b>表單按鈕</b>（資料夾圖標）會列出系統內所有可用的標準表單。
        </p>
        <ul>
          <li>滑到列上會彈出右側選單，點 <b>Download</b> 直接下載空白 .docx</li>
          <li>單擊整列會把選單鎖定住，方便慢慢選</li>
        </ul>
        <p>下載的檔名會帶上表單顯示名稱，方便辨識。</p>
      </>
    ),
  },
  {
    id: "form-fill",
    title: "AI 代填表單",
    body: (
      <>
        <p>
          想讓 AI 幫你填好表單再下載？在表單按鈕的下拉選單點 <b>Ask AI</b>：
        </p>
        <ul>
          <li>會跳出確認視窗，按 <b>Start</b> 開始填寫流程</li>
          <li>對話會進入問答模式，AI 會逐欄問你需要的資訊</li>
          <li>填完後會出現「（已填寫）」的下載卡，點下載即可拿到填好的 .docx</li>
        </ul>
        <p>
          若中途想換一張表，重新從表單按鈕點 <b>Ask AI</b> 即可，
          系統會提醒你舊的填表進度會被覆蓋。
        </p>
      </>
    ),
  },
  {
    id: "dynamic-form",
    title: "動態表單生成",
    body: (
      <>
        <p>
          系統內沒有的表單可以直接用文字描述讓 AI 即時生成，例如：
        </p>
        <pre>幫我做一份混凝土澆置前的查驗表，需要欄位：項目、檢查標準、結果</pre>
        <p>
          AI 會用 markdown 表格直接顯示在對話內。表格右上角有複製按鈕，
          可以把整張表複製成 markdown 格式。
        </p>
        <p>想匯出成檔案？追問：</p>
        <ul>
          <li>「把這份匯出成 Excel」 → .xlsx</li>
          <li>「轉成 CSV 給我」 → .csv</li>
        </ul>
        <p>下方會出現下載卡，點即下載。</p>
      </>
    ),
  },
  {
    id: "sources",
    title: "來源引用",
    body: (
      <>
        <p>
          每則 AI 回答下方會列出 <b>Sources</b> 區塊，標示這次回答參考了哪些章節，
          含檔名、章節碼與相關標籤。
        </p>
        <p>
          如果回答內容跟你預期不符，先看一下 Sources 是否取對章節 —
          有時換個關鍵字（例如改用章節碼直接問）能拿到更準的結果。
        </p>
      </>
    ),
  },
  {
    id: "images",
    title: "圖片預覽",
    body: (
      <>
        <p>
          回答內若含圖片，點圖片會在螢幕中央放大顯示，
          按 Esc 或點背景即可關閉。
        </p>
      </>
    ),
  },
];

export default function HelpPanel({ open, onClose }: Props) {
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (activeId) setActiveId(null);
        else onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, activeId, onClose]);

  if (!open) return null;

  const active = CATEGORIES.find((c) => c.id === activeId) ?? null;

  return (
    <div
      className={cn(
        // 桌機：右下浮卡；手機：全螢幕
        "fixed z-[55] bg-white shadow-2xl flex flex-col",
        "inset-0 md:inset-auto",
        "md:right-5 md:bottom-5 md:w-[380px] md:h-[560px] md:max-h-[calc(100vh-2.5rem)]",
        "md:rounded-2xl md:border md:border-zinc-200"
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-4 h-12 border-b border-zinc-100 shrink-0">
        {active && (
          <button
            onClick={() => setActiveId(null)}
            className="size-7 -ml-1 flex items-center justify-center rounded-md hover:bg-zinc-100 transition-colors"
            aria-label="返回"
          >
            <ArrowLeft size={15} className="text-zinc-600" />
          </button>
        )}
        <span className="flex-1 text-[14px] font-semibold text-zinc-900 truncate">
          {active ? active.title : "使用說明"}
        </span>
        <button
          onClick={onClose}
          className="size-7 -mr-1 flex items-center justify-center rounded-md hover:bg-zinc-100 transition-colors"
          aria-label="關閉"
        >
          <X size={15} className="text-zinc-600" />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        {active ? (
          <div className="help-prose px-5 py-4 text-[13.5px] text-zinc-700 leading-relaxed">
            {active.body}
          </div>
        ) : (
          <ul className="py-1">
            {CATEGORIES.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => setActiveId(c.id)}
                  className="w-full flex items-center gap-2 px-4 py-3 hover:bg-zinc-50 transition-colors"
                >
                  <span className="flex-1 text-left text-[14px] text-zinc-800">
                    {c.title}
                  </span>
                  <ChevronRight size={14} className="text-zinc-400 shrink-0" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
