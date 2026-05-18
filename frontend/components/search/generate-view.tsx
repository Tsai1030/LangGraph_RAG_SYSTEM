"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useForm, type UseFormReturn } from "react-hook-form";
import {
  CalendarDays,
  Check,
  ChevronRight,
  Download,
  PenSquare,
  PlayCircle,
  Settings2,
  Table2,
} from "lucide-react";
import axios from "axios";
import api from "@/lib/api";
import type {
  SearchGenerationRunRequest,
  SearchGenerationStatus,
  SearchInternalDataRequest,
} from "@/lib/search/types";
import { LoadingOverlay, type LoadingStep } from "@/components/search/loading-overlay";

const STEP_DEFS = [
  { id: 1, label: "設定", icon: Settings2 },
  { id: 2, label: "抓取盤價", icon: PlayCircle },
  { id: 3, label: "抓取結果", icon: Table2 },
  { id: 4, label: "補內部資料", icon: PenSquare },
  { id: 5, label: "下載 Word", icon: Download },
] as const;

// Durations calibrated to the real cloud workflow (~180 s end-to-end on
// Render free + Neon). Local dev is faster (~30-60 s); the overlay
// finishes early and closes when the polling mutation resolves, so
// overshooting durations is fine for fast paths but undershooting (the
// old values) leaves the bar pinned at 100% for 2 minutes — looks broken.
const FETCH_STEPS: LoadingStep[] = [
  { text: "連線 steelnet 鋼鐵網會員區...", durationMs: 8000 },
  { text: "[search] 抓取本週豐興開盤新聞 (3 pages)", durationMs: 12000 },
  { text: "[rank] 由 LLM 篩選候選文章中...", durationMs: 14000 },
  { text: "[fetch] 下載命中文章內容", durationMs: 8000 },
  { text: "[parse] 抽取本週牌價:SD280 / 廢鋼 / 型鋼", durationMs: 5000 },
  { text: "[validate] 通過合理性驗證 (15,000–25,000 元/噸)", durationMs: 5000 },
  { text: "[derive] 推算 SD280W = SD280+200, SD420 = SD280+1000", durationMs: 5000 },
  { text: "[intl_scrap] 抽取美國貨櫃 / 日本 2H 廢鋼數字", durationMs: 6000 },
  { text: "[history] 查詢 price_history 過去 8 週", durationMs: 4000 },
  { text: "[csc] 讀取中鋼 八.1 / 八.2 admin 表單資料", durationMs: 4000 },
  { text: "[LLM] OpenAI web_search 大陸西本新幹線指數...", durationMs: 21000 },
  { text: "[LLM] OpenAI web_search LME 倫敦銅現貨...", durationMs: 21000 },
  { text: "[LLM] 撰寫六.3 大陸西本段落 (gpt-5.4)...", durationMs: 14000 },
  { text: "[LLM] 撰寫六.4 LME 銅價段落...", durationMs: 14000 },
  { text: "[LLM] 撰寫九.1 國內鋼筋市場敘述...", durationMs: 15000 },
  { text: "[LLM] 撰寫九.2 大陸鋼鐵市場敘述...", durationMs: 15000 },
  { text: "[render] 寫入 Word 模板 (python-docx)...", durationMs: 3500 },
  { text: "[done] 抓取完成,渲染結果頁中", durationMs: 3000 },
];

// internal-data re-runs the whole graph too (with cached LLM web_search
// results bypassed). Still ~60 s on cloud — stretch accordingly.
const APPLY_STEPS: LoadingStep[] = [
  { text: "[merge] 合併內部資料到 slot_values...", durationMs: 4000 },
  { text: "[narrate] 重新計算所有 slot 的最終值...", durationMs: 8000 },
  { text: "[LLM] 重新撰寫各段落敘述...", durationMs: 30000 },
  { text: "[history] 重新讀取 七.1–7.5 歷史表...", durationMs: 4000 },
  { text: "[render] 寫入 Word 模板 (python-docx)...", durationMs: 10000 },
  { text: "[done] Word 已就緒,可下載", durationMs: 4000 },
];

/**
 * Poll GET /api/generation/{run_id} every 2.5 s until status flips
 * from "running". Render free tier cuts long HTTP requests around 100 s,
 * so the backend runs the LangGraph workflow as a detached asyncio task
 * and we discover its outcome by polling.
 *
 *   - status==="running"     → keep polling
 *   - status==="failed"      → throw with backend's `notes` as message
 *   - status==="success/partial" → resolve with the full response
 *   - transient 5xx (cold start) → log + keep polling, don't bail
 *
 * Caps at 10 min wall clock so a wedged backend doesn't pin the UI
 * indefinitely.
 */
async function pollUntilDone(
  runId: number,
): Promise<SearchGenerationStatus> {
  const POLL_MS = 2500;
  const MAX_MS = 10 * 60 * 1000;
  const startedAt = Date.now();
  while (Date.now() - startedAt < MAX_MS) {
    await new Promise((r) => setTimeout(r, POLL_MS));
    try {
      const { data: s } = await api.get<SearchGenerationStatus>(`/search/generation/${runId}`);
      if (s.status === "failed") {
        throw new Error(s.notes ?? "抓取失敗（無錯誤訊息）");
      }
      if (s.status !== "running") return s;
    } catch (err) {
      if (
        axios.isAxiosError(err) &&
        err.response &&
        err.response.status >= 500 &&
        err.response.status < 600
      ) {
        // Cold-start 5xx — back off and try again.
        continue;
      }
      throw err;
    }
  }
  throw new Error("等候逾時（10 分鐘）— 請查 backend log 確認 run 狀態");
}

interface InternalForm {
  meeting_time: string;
  contract_remaining_tons: string;
  contract_usable_until: string;
  meeting_conclusion_last_week: string;
  meeting_conclusion_this_week: string;
}

export function openingMondayLabel(isoDate: string): string {
  if (!isoDate) return "—";
  const d = new Date(isoDate + "T00:00:00");
  if (Number.isNaN(d.getTime())) return "—";
  const offset = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - offset);
  return `${d.getMonth() + 1}/${d.getDate()}（週一）`;
}

/**
 * Wizard view for the meeting-record generation flow. Self-contained:
 * holds its own step / form / mutation state. Designed to live alongside
 * other views (e.g. CscAdminView) inside the same MacShell — switching
 * between them via display:none preserves all in-flight state.
 */
export function GenerateView() {
  const [step, setStep] = useState<1 | 2 | 3 | 4 | 5>(1);
  const [meetingDate, setMeetingDate] = useState(
    () => new Date().toISOString().slice(0, 10),
  );
  const [result, setResult] = useState<SearchGenerationStatus | null>(null);

  const runMutation = useMutation({
    mutationFn: async (input: SearchGenerationRunRequest) => {
      const { data: initial } = await api.post<SearchGenerationStatus>(
        "/search/generation/run",
        input,
      );
      return pollUntilDone(initial.run_id);
    },
    onSuccess: (data) => {
      setResult(data);
      setStep(3);
    },
  });

  const internalForm = useForm<InternalForm>({
    defaultValues: {
      meeting_time: "17:00~17:30",
      contract_remaining_tons: "",
      contract_usable_until: "",
      meeting_conclusion_last_week: "",
      meeting_conclusion_this_week: "",
    },
  });

  const internalMutation = useMutation({
    mutationFn: async (form: InternalForm) => {
      if (!result) throw new Error("no active run");
      const payload: SearchInternalDataRequest = {
        internal_data: {
          meeting_time: form.meeting_time,
          contract_remaining_tons: form.contract_remaining_tons,
          contract_usable_until: form.contract_usable_until,
          meeting_conclusion_last_week: form.meeting_conclusion_last_week,
          meeting_conclusion_this_week: form.meeting_conclusion_this_week,
        },
      };
      await api.post<SearchGenerationStatus>(
        `/search/generation/${result.run_id}/internal-data`,
        payload,
      );
      return pollUntilDone(result.run_id);
    },
    onSuccess: (data) => {
      setResult(data);
      setStep(5);
    },
  });

  const downloadDocx = async () => {
    if (!result) return;
    // Use the existing axios instance so we inherit Bearer auth + baseURL.
    // responseType "blob" tells axios not to JSON-parse the docx bytes.
    let res;
    try {
      res = await api.get(`/search/generation/${result.run_id}/docx`, {
        responseType: "blob",
      });
    } catch (err) {
      const status = axios.isAxiosError(err) ? err.response?.status : "?";
      alert(
        status === 404
          ? "舊檔已過期，請重新產生"
          : `下載失敗: ${status ?? err}`,
      );
      return;
    }
    const cd = (res.headers["content-disposition"] as string) ?? "";
    const match = /filename\*?=(?:UTF-8'')?([^;]+)/i.exec(cd);
    const filename = match
      ? decodeURIComponent(match[1].replace(/^"|"$/g, ""))
      : `meeting_${result.run_id}.docx`;
    const url = URL.createObjectURL(res.data as Blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <LoadingOverlay
        open={runMutation.isPending}
        title="正在抓取本週資料"
        subtitle={`目標週：${openingMondayLabel(meetingDate)}`}
        steps={FETCH_STEPS}
      />
      <LoadingOverlay
        open={internalMutation.isPending}
        title="套用內部資料 + 重新生成 Word"
        subtitle="不需要再次抓取，僅重新渲染模板"
        steps={APPLY_STEPS}
      />

      <PageHeader
        eyebrow="WORKFLOW"
        title="鋼筋採購週會記錄"
        description="依序完成 5 個步驟即可產出 Word 檔案。系統會自動向 steelnet、OpenAI 等多個來源抓取本週市場資料。"
      />

      <StepBar current={step} onSelect={setStep} hasResult={!!result} />

      <div className="mt-8">
        {step === 1 && (
          <Step1
            meetingDate={meetingDate}
            setMeetingDate={setMeetingDate}
            onNext={() => setStep(2)}
          />
        )}
        {step === 2 && (
          <Step2
            meetingDate={meetingDate}
            isPending={runMutation.isPending}
            onRun={() => runMutation.mutate({ meeting_date: meetingDate })}
            onBack={() => setStep(1)}
            error={runMutation.error as Error | null}
          />
        )}
        {step === 3 && result && (
          <Step3
            result={result}
            onBack={() => setStep(2)}
            onNext={() => setStep(4)}
          />
        )}
        {step === 4 && (
          <Step4
            form={internalForm}
            isPending={internalMutation.isPending}
            error={internalMutation.error as Error | null}
            onSubmit={(d) => internalMutation.mutate(d)}
            onBack={() => setStep(3)}
          />
        )}
        {step === 5 && result && (
          <Step5
            result={result}
            onDownload={downloadDocx}
            onBack={() => setStep(4)}
          />
        )}
      </div>
    </>
  );
}

/* ─────────────────── shared layout primitives ─────────────────── */

function PageHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <div className="max-w-3xl">
      <div
        className="text-[10px] font-semibold uppercase tracking-[0.12em]"
        style={{ color: "var(--search-accent)" }}
      >
        {eyebrow}
      </div>
      <h1
        className="mt-1.5 text-[22px] sm:text-[28px] font-semibold tracking-tight leading-tight"
        style={{ color: "var(--search-text-primary)" }}
      >
        {title}
      </h1>
      <p
        className="mt-2 text-[13px] sm:text-[14px] leading-relaxed"
        style={{ color: "var(--search-text-secondary)" }}
      >
        {description}
      </p>
    </div>
  );
}

function Card({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`p-4 sm:p-6 ${className}`}
      style={{
        background: "var(--search-surface-card)",
        borderRadius: "var(--search-radius-card)",
        boxShadow: "var(--search-shadow-card)",
      }}
    >
      {children}
    </div>
  );
}

function StepBar({
  current,
  onSelect,
  hasResult,
}: {
  current: number;
  onSelect: (n: 1 | 2 | 3 | 4 | 5) => void;
  hasResult: boolean;
}) {
  return (
    <div
      className="mt-6 sm:mt-7 flex items-center gap-1 p-1.5 rounded-lg overflow-x-auto sm:w-fit -mx-1 sm:mx-0"
      style={{ background: "var(--search-surface-hover)" }}
    >
      {STEP_DEFS.map((s) => {
        const isActive = current === s.id;
        const isDone = current > s.id;
        const disabled = !hasResult && s.id > 2;
        return (
          <button
            key={s.id}
            disabled={disabled}
            onClick={() => onSelect(s.id as 1 | 2 | 3 | 4 | 5)}
            className="flex items-center gap-1.5 sm:gap-2 px-2.5 sm:px-3 py-1.5 text-[12px] font-medium rounded-md transition-all disabled:cursor-not-allowed disabled:opacity-40 whitespace-nowrap shrink-0"
            style={
              isActive
                ? {
                    background: "var(--search-surface-card)",
                    color: "var(--search-text-primary)",
                    boxShadow:
                      "0 0 0 0.5px oklch(0% 0 0 / 0.06), 0 1px 2px oklch(0% 0 0 / 0.05)",
                  }
                : {
                    color: "var(--search-text-secondary)",
                    background: "transparent",
                  }
            }
          >
            <span
              className="w-4 h-4 rounded-full flex items-center justify-center text-[10px] font-semibold"
              style={
                isDone
                  ? { background: "var(--search-accent)", color: "white" }
                  : isActive
                    ? { background: "var(--search-accent-soft)", color: "var(--search-accent)" }
                    : { background: "var(--search-border-subtle)", color: "var(--search-text-tertiary)" }
              }
            >
              {isDone ? <Check className="w-2.5 h-2.5" /> : s.id}
            </span>
            <span>{s.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function PrimaryButton({
  children,
  onClick,
  disabled,
  trailing,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  trailing?: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-2 px-4 py-2 text-[13px] font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      style={{
        background: "var(--search-accent)",
        color: "white",
        borderRadius: "var(--search-radius-control)",
        boxShadow: "0 1px 2px oklch(60% 0.21 256 / 0.30)",
      }}
      onMouseEnter={(e) => {
        if (!disabled)
          e.currentTarget.style.background = "var(--search-accent-hover)";
      }}
      onMouseLeave={(e) => {
        if (!disabled)
          e.currentTarget.style.background = "var(--search-accent)";
      }}
    >
      {children}
      {trailing}
    </button>
  );
}

function SecondaryButton({
  children,
  onClick,
  leading,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  leading?: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-2 px-3.5 py-2 text-[13px] font-medium transition-colors"
      style={{
        background: "var(--search-surface-hover)",
        color: "var(--search-text-secondary)",
        borderRadius: "var(--search-radius-control)",
      }}
      onMouseEnter={(e) =>
        (e.currentTarget.style.background = "var(--search-surface-selected)")
      }
      onMouseLeave={(e) =>
        (e.currentTarget.style.background = "var(--search-surface-hover)")
      }
    >
      {leading}
      {children}
    </button>
  );
}

/* ─────────────────────── Steps ─────────────────────── */

function Step1({
  meetingDate,
  setMeetingDate,
  onNext,
}: {
  meetingDate: string;
  setMeetingDate: (v: string) => void;
  onNext: () => void;
}) {
  return (
    <Card>
      <h2
        className="text-[16px] font-semibold mb-1"
        style={{ color: "var(--search-text-primary)" }}
      >
        會議基本資訊
      </h2>
      <p
        className="text-[13px] leading-relaxed mb-6"
        style={{ color: "var(--search-text-secondary)" }}
      >
        指定本週會議日期。豐興每週一開盤，系統自動以該週的週一為盤價基準日。
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 max-w-xl">
        <FieldLabel
          icon={<CalendarDays className="w-3.5 h-3.5" />}
          label="會議日期"
        >
          <input
            type="date"
            value={meetingDate}
            onChange={(e) => setMeetingDate(e.target.value)}
            className="w-full px-3 py-2 text-[13px] outline-none"
            style={{
              background: "var(--search-surface-input)",
              border: "1px solid var(--search-border-subtle)",
              borderRadius: "var(--search-radius-control)",
              color: "var(--search-text-primary)",
            }}
          />
        </FieldLabel>
        <FieldLabel
          icon={<CalendarDays className="w-3.5 h-3.5" />}
          label="豐興開盤日（自動推算）"
        >
          <div
            className="px-3 py-2 text-[13px]"
            style={{
              background: "var(--search-surface-hover)",
              border: "1px solid var(--search-border-subtle)",
              borderRadius: "var(--search-radius-control)",
              color: "var(--search-text-secondary)",
            }}
          >
            {openingMondayLabel(meetingDate)}
          </div>
        </FieldLabel>
      </div>

      <div className="mt-7 flex justify-end">
        <PrimaryButton
          onClick={onNext}
          trailing={<ChevronRight className="w-4 h-4" />}
        >
          下一步：抓取盤價
        </PrimaryButton>
      </div>
    </Card>
  );
}

function Step2({
  meetingDate,
  isPending,
  onRun,
  onBack,
  error,
}: {
  meetingDate: string;
  isPending: boolean;
  onRun: () => void;
  onBack: () => void;
  error: Error | null;
}) {
  return (
    <Card>
      <h2
        className="text-[16px] font-semibold mb-1"
        style={{ color: "var(--search-text-primary)" }}
      >
        抓取盤價
      </h2>
      <p
        className="text-[13px] leading-relaxed mb-2"
        style={{ color: "var(--search-text-secondary)" }}
      >
        目標週：
        <span
          className="font-semibold"
          style={{ color: "var(--search-text-primary)" }}
        >
          {openingMondayLabel(meetingDate)}
        </span>
      </p>
      <p
        className="text-[12px]"
        style={{ color: "var(--search-text-tertiary)" }}
      >
        系統將呼叫豐興 (steelnet) → weekly_market → market_narrator 三個來源，
        視 OpenAI 速度約 30–60 秒。
      </p>

      <div className="mt-6 flex items-center gap-2">
        <PrimaryButton
          onClick={onRun}
          disabled={isPending}
          trailing={!isPending && <ChevronRight className="w-4 h-4" />}
        >
          {isPending ? "抓取中…" : "開始抓取"}
        </PrimaryButton>
        <SecondaryButton onClick={onBack}>← 上一步</SecondaryButton>
      </div>

      {error && (
        <div
          className="mt-5 px-3 py-2 text-[12px] rounded"
          style={{
            background: "oklch(96% 0.04 27)",
            color: "var(--search-status-error)",
          }}
        >
          抓取失敗：{error.message}
        </div>
      )}
    </Card>
  );
}

function Step3({
  result,
  onBack,
  onNext,
}: {
  result: SearchGenerationStatus;
  onBack: () => void;
  onNext: () => void;
}) {
  return (
    <Card>
      <div className="flex items-baseline justify-between mb-1">
        <h2
          className="text-[16px] font-semibold"
          style={{ color: "var(--search-text-primary)" }}
        >
          抓取結果
        </h2>
        <div
          className="text-[12px]"
          style={{ color: "var(--search-text-tertiary)" }}
        >
          Run #{result.run_id} · {result.meeting_date}
        </div>
      </div>
      <p
        className="text-[13px] mb-6"
        style={{ color: "var(--search-text-secondary)" }}
      >
        以下是各 slot 抽到的值。低信心 (medium / low) 的欄位會在 Word 中以紅字標示。
      </p>

      {/* Desktop: full table */}
      <div
        className="hidden sm:block rounded-lg overflow-hidden"
        style={{ border: "1px solid var(--search-border-subtle)" }}
      >
        <table className="w-full text-[13px]">
          <thead>
            <tr
              className="text-left"
              style={{
                background: "var(--search-surface-hover)",
                color: "var(--search-text-tertiary)",
              }}
            >
              <th className="px-4 py-2 font-medium text-[11px] uppercase tracking-wider">欄位</th>
              <th className="px-4 py-2 font-medium text-[11px] uppercase tracking-wider">數值</th>
              <th className="px-4 py-2 font-medium text-[11px] uppercase tracking-wider">單位</th>
              <th className="px-4 py-2 font-medium text-[11px] uppercase tracking-wider">信心</th>
              <th className="px-4 py-2 font-medium text-[11px] uppercase tracking-wider">來源</th>
            </tr>
          </thead>
          <tbody>
            {result.slots.map((s, i) => (
              <tr
                key={s.slot_key}
                style={{
                  borderTop:
                    i === 0 ? "none" : "1px solid var(--search-border-subtle)",
                }}
              >
                <td className="px-4 py-2.5 font-medium" style={{ color: "var(--search-text-primary)" }}>
                  {s.label}
                </td>
                <td className="px-4 py-2.5 tabular-nums" style={{ color: "var(--search-text-primary)" }}>
                  {s.value ?? "—"}
                </td>
                <td className="px-4 py-2.5" style={{ color: "var(--search-text-tertiary)" }}>
                  {s.unit ?? ""}
                </td>
                <td className="px-4 py-2.5">
                  <ConfidenceBadge level={s.confidence} />
                </td>
                <td className="px-4 py-2.5 text-[12px]" style={{ color: "var(--search-text-tertiary)" }}>
                  {s.source ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile: stacked card list — much more readable on narrow screens */}
      <div className="sm:hidden space-y-2">
        {result.slots.map((s) => (
          <div
            key={s.slot_key}
            className="p-3 rounded-lg"
            style={{
              background: "var(--search-surface-hover)",
              border: "1px solid var(--search-border-subtle)",
            }}
          >
            <div className="flex items-baseline justify-between gap-2 mb-1.5">
              <div
                className="text-[13px] font-medium truncate"
                style={{ color: "var(--search-text-primary)" }}
              >
                {s.label}
              </div>
              <ConfidenceBadge level={s.confidence} />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span
                className="text-[15px] font-semibold tabular-nums"
                style={{ color: "var(--search-text-primary)" }}
              >
                {s.value ?? "—"}
              </span>
              <span
                className="text-[11px]"
                style={{ color: "var(--search-text-tertiary)" }}
              >
                {s.unit ?? ""}
              </span>
            </div>
            {s.source && (
              <div
                className="mt-1 text-[10px] uppercase tracking-wider"
                style={{ color: "var(--search-text-tertiary)" }}
              >
                來源：{s.source}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="mt-6 flex justify-between">
        <SecondaryButton onClick={onBack}>← 上一步</SecondaryButton>
        <PrimaryButton
          onClick={onNext}
          trailing={<ChevronRight className="w-4 h-4" />}
        >
          下一步：補內部資料
        </PrimaryButton>
      </div>
    </Card>
  );
}

function Step4({
  form,
  isPending,
  error,
  onSubmit,
  onBack,
}: {
  form: UseFormReturn<InternalForm>;
  isPending: boolean;
  error: Error | null;
  onSubmit: (data: InternalForm) => void;
  onBack: () => void;
}) {
  return (
    <Card>
      <h2
        className="text-[16px] font-semibold mb-1"
        style={{ color: "var(--search-text-primary)" }}
      >
        補內部資料
      </h2>
      <p
        className="text-[13px] mb-6"
        style={{ color: "var(--search-text-secondary)" }}
      >
        這些欄位無法自動抓取，請手動填寫。空白會在 Word 中顯示「—」。
      </p>

      <form
        onSubmit={form.handleSubmit(onSubmit)}
        className="grid grid-cols-1 sm:grid-cols-2 gap-5 max-w-3xl"
      >
        <FieldLabel label="會議時間">
          <input
            {...form.register("meeting_time")}
            placeholder="17:00~17:30"
            className="w-full px-3 py-2 text-[13px] outline-none"
            style={{
              background: "var(--search-surface-input)",
              border: "1px solid var(--search-border-subtle)",
              borderRadius: "var(--search-radius-control)",
            }}
          />
        </FieldLabel>
        <FieldLabel label="採購合約剩餘總量（噸）">
          <input
            {...form.register("contract_remaining_tons")}
            placeholder="57,198"
            className="w-full px-3 py-2 text-[13px] outline-none tabular-nums"
            style={{
              background: "var(--search-surface-input)",
              border: "1px solid var(--search-border-subtle)",
              borderRadius: "var(--search-radius-control)",
            }}
          />
        </FieldLabel>
        <FieldLabel label="可使用至">
          <input
            {...form.register("contract_usable_until")}
            placeholder="116 年 1 月"
            className="w-full px-3 py-2 text-[13px] outline-none"
            style={{
              background: "var(--search-surface-input)",
              border: "1px solid var(--search-border-subtle)",
              borderRadius: "var(--search-radius-control)",
            }}
          />
        </FieldLabel>
        <div className="hidden sm:block" />
        <FieldLabel label="上週會議結論" className="sm:col-span-2">
          <textarea
            {...form.register("meeting_conclusion_last_week")}
            rows={2}
            placeholder="當週鋼筋市場皆維持平盤……"
            className="w-full px-3 py-2 text-[13px] outline-none leading-relaxed resize-y"
            style={{
              background: "var(--search-surface-input)",
              border: "1px solid var(--search-border-subtle)",
              borderRadius: "var(--search-radius-control)",
            }}
          />
        </FieldLabel>
        <FieldLabel label="本週會議結論" className="sm:col-span-2">
          <textarea
            {...form.register("meeting_conclusion_this_week")}
            rows={3}
            placeholder="當前國內鋼筋市場正處於……"
            className="w-full px-3 py-2 text-[13px] outline-none leading-relaxed resize-y"
            style={{
              background: "var(--search-surface-input)",
              border: "1px solid var(--search-border-subtle)",
              borderRadius: "var(--search-radius-control)",
            }}
          />
        </FieldLabel>

        <div className="sm:col-span-2 flex justify-between mt-2">
          <SecondaryButton onClick={onBack}>← 上一步</SecondaryButton>
          <PrimaryButton
            disabled={isPending}
            trailing={!isPending && <ChevronRight className="w-4 h-4" />}
          >
            {isPending ? "更新中…" : "套用並前往下載"}
          </PrimaryButton>
        </div>

        {error && (
          <div
            className="sm:col-span-2 px-3 py-2 text-[12px] rounded"
            style={{
              background: "oklch(96% 0.04 27)",
              color: "var(--search-status-error)",
            }}
          >
            更新失敗：{error.message}
          </div>
        )}
      </form>
    </Card>
  );
}

function Step5({
  result,
  onDownload,
  onBack,
}: {
  result: SearchGenerationStatus;
  onDownload: () => void;
  onBack: () => void;
}) {
  return (
    <Card>
      <h2
        className="text-[16px] font-semibold mb-1"
        style={{ color: "var(--search-text-primary)" }}
      >
        下載 Word
      </h2>
      <div
        className="flex items-center gap-2 text-[13px] mb-6"
        style={{ color: "var(--search-text-secondary)" }}
      >
        <span>Run #{result.run_id} · {result.meeting_date}</span>
        <span style={{ color: "var(--search-text-tertiary)" }}>·</span>
        <span style={{
          color: result.has_output
            ? "var(--search-status-success)"
            : "var(--search-status-warn)",
        }}>
          {result.has_output ? "Word 已就緒" : "尚未產生"}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <PrimaryButton
          onClick={onDownload}
          disabled={!result.has_output}
          trailing={<Download className="w-4 h-4" />}
        >
          下載會議記錄 Word
        </PrimaryButton>
        <SecondaryButton onClick={onBack}>← 修改內部資料</SecondaryButton>
      </div>

      <p
        className="mt-6 text-[12px]"
        style={{ color: "var(--search-text-tertiary)" }}
      >
        打開 Word 後，紅字代表低信心欄位，灰色「—」代表尚未填入。
      </p>
    </Card>
  );
}

/* ─────────────────────── building blocks ─────────────────────── */

function FieldLabel({
  label,
  icon,
  children,
  className = "",
}: {
  label: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={`flex flex-col gap-1.5 ${className}`}>
      <span
        className="flex items-center gap-1.5 text-[11px] font-medium"
        style={{ color: "var(--search-text-secondary)" }}
      >
        {icon}
        {label}
      </span>
      {children}
    </label>
  );
}

function ConfidenceBadge({ level }: { level: string }) {
  const map: Record<string, { bg: string; fg: string; label: string }> = {
    high: {
      bg: "oklch(95% 0.04 145)",
      fg: "var(--search-status-success)",
      label: "High",
    },
    medium: {
      bg: "oklch(95% 0.04 80)",
      fg: "var(--search-status-warn)",
      label: "Medium",
    },
    low: {
      bg: "oklch(96% 0.04 27)",
      fg: "var(--search-status-error)",
      label: "Low",
    },
  };
  const m = map[level] ?? map.low;
  return (
    <span
      className="inline-flex items-center px-1.5 py-0.5 text-[10px] font-semibold rounded"
      style={{ background: m.bg, color: m.fg }}
    >
      {m.label}
    </span>
  );
}
