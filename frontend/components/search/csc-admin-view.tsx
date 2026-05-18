"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Calendar, Check, Save } from "lucide-react";
import api from "@/lib/api";
import type {
  SearchCscSaveRequest,
  SearchCscSnapshot,
} from "@/lib/search/types";

type Group = "monthly" | "quarterly";

const GROUP_LABELS: Record<Group, { title: string; eyebrow: string }> = {
  monthly: { title: "八.1 月盤鋼品", eyebrow: "MONTHLY" },
  quarterly: { title: "八.2 季盤鋼品", eyebrow: "QUARTERLY" },
};

interface EditableRow {
  slot_index: number;
  product_name: string;
  prev_price: string;
  change_amount: string;
}

function snapToEditable(snap: SearchCscSnapshot): EditableRow[] {
  return snap.rows.map((r) => ({
    slot_index: r.slot_index,
    product_name: r.product_name,
    prev_price: String(r.prev_price),
    change_amount: String(r.change_amount),
  }));
}

/* ─── Period dropdown options ───
   Rolling window centred on the current month / quarter. Reads as a short
   list users can scan without scrolling. Newest first. */
function periodOptions(group: Group): string[] {
  const now = new Date();
  const opts: string[] = [];
  if (group === "monthly") {
    // Future 3 + current + past 8 = 12 total
    for (let offset = 3; offset >= -8; offset--) {
      const d = new Date(now.getFullYear(), now.getMonth() + offset, 1);
      const rocY = d.getFullYear() - 1911;
      const m = d.getMonth() + 1;
      opts.push(`${rocY} 年 ${m} 月份`);
    }
  } else {
    // Future 2 + current + past 3 = 6 total
    const Q_LABEL = ["一", "二", "三", "四"];
    const curQ = Math.floor(now.getMonth() / 3); // 0..3
    const curY = now.getFullYear();
    for (let offset = 2; offset >= -3; offset--) {
      let qIdx = curQ + offset;
      let y = curY;
      while (qIdx < 0) {
        qIdx += 4;
        y -= 1;
      }
      while (qIdx > 3) {
        qIdx -= 4;
        y += 1;
      }
      const rocY = y - 1911;
      opts.push(`${rocY} 年第${Q_LABEL[qIdx]}季`);
    }
  }
  return opts;
}

/* ─── Announce-date conversion: "2026/4/15" ⇄ "2026-04-15" ─── */
function dateStrToIso(s: string): string {
  if (!s) return "";
  const parts = s.split("/");
  if (parts.length !== 3) return "";
  const [y, m, d] = parts;
  return `${y.padStart(4, "0")}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
}

function isoToDateStr(iso: string): string {
  if (!iso) return "";
  const parts = iso.split("-");
  if (parts.length !== 3) return "";
  const [y, m, d] = parts;
  return `${y}/${parseInt(m, 10)}/${parseInt(d, 10)}`;
}

/**
 * CSC price admin view. Self-contained — designed to live alongside
 * GenerateView inside the same MacShell, swapped via display:none so
 * unsaved table edits survive view switches.
 */
export function CscAdminView() {
  return (
    <>
      <div className="max-w-3xl">
        <div
          className="text-[10px] font-semibold uppercase tracking-[0.12em]"
          style={{ color: "var(--search-accent)" }}
        >
          ADMIN
        </div>
        <h1
          className="mt-1.5 text-[22px] sm:text-[28px] font-semibold tracking-tight leading-tight"
          style={{ color: "var(--search-text-primary)" }}
        >
          中鋼盤價維護
        </h1>
        <p
          className="mt-2 text-[13px] sm:text-[14px] leading-relaxed"
          style={{ color: "var(--search-text-secondary)" }}
        >
          中鋼每月發佈月盤、每季發佈季盤。在這裡更新後，下次「產生會議記錄」時 八.1 / 八.2
          兩張表會自動填入這些數字。
        </p>
      </div>

      <div className="mt-6 sm:mt-8 space-y-4 sm:space-y-6">
        <GroupEditor group="monthly" />
        <GroupEditor group="quarterly" />
      </div>
    </>
  );
}

function GroupEditor({ group }: { group: Group }) {
  const qc = useQueryClient();
  const queryKey = ["csc", group];
  const { data, isLoading } = useQuery<SearchCscSnapshot>({
    queryKey,
    queryFn: async () => {
      const res = await api.get<SearchCscSnapshot>(`/admin/search-csc/${group}`);
      return res.data;
    },
  });

  // Re-key inner editor when server data version changes — lets us seed
  // the form inputs from `data` without setState-in-effect.
  const dataVersion = data
    ? `${data.period_label}|${data.announce_date}|${data.rows.length}`
    : "loading";

  return (
    <GroupEditorInner
      key={dataVersion}
      group={group}
      data={data}
      isLoading={isLoading}
      qc={qc}
      queryKey={queryKey}
    />
  );
}

interface InnerProps {
  group: Group;
  data: SearchCscSnapshot | undefined;
  isLoading: boolean;
  qc: ReturnType<typeof useQueryClient>;
  queryKey: readonly unknown[];
}

function GroupEditorInner({
  group,
  data,
  isLoading,
  qc,
  queryKey,
}: InnerProps) {
  const [period, setPeriod] = useState(data?.period_label ?? "");
  const [announceDate, setAnnounceDate] = useState(data?.announce_date ?? "");
  const [rows, setRows] = useState<EditableRow[]>(
    data ? snapToEditable(data) : [],
  );
  const [savedFlag, setSavedFlag] = useState(false);

  useEffect(() => {
    if (!savedFlag) return;
    const id = setTimeout(() => setSavedFlag(false), 4000);
    return () => clearTimeout(id);
  }, [savedFlag]);

  const save = useMutation({
    mutationFn: (body: SearchCscSaveRequest) =>
      api.put<SearchCscSnapshot>(`/admin/search-csc/${group}`, body),
    onSuccess: () => {
      setSavedFlag(true);
      qc.invalidateQueries({ queryKey });
    },
  });

  const update = (
    idx: number,
    field: "prev_price" | "change_amount",
    v: string,
  ) => {
    setRows((prev) =>
      prev.map((r, i) =>
        i === idx ? { ...r, [field]: v.replace(/[^\d.+\-,]/g, "") } : r,
      ),
    );
  };

  const onSave = () => {
    const body: SearchCscSaveRequest = {
      period_label: period,
      announce_date: announceDate,
      rows: rows.map((r) => ({
        slot_index: r.slot_index,
        prev_price: parseInt(r.prev_price.replace(/,/g, ""), 10) || 0,
        change_amount: parseInt(r.change_amount.replace(/[,+]/g, ""), 10) || 0,
      })),
    };
    save.mutate(body);
  };

  if (isLoading) {
    return (
      <div
        className="p-6 text-[13px]"
        style={{
          background: "var(--search-surface-card)",
          borderRadius: "var(--search-radius-card)",
          boxShadow: "var(--search-shadow-card)",
          color: "var(--search-text-tertiary)",
        }}
      >
        載入中…
      </div>
    );
  }

  return (
    <section
      className="overflow-hidden"
      style={{
        background: "var(--search-surface-card)",
        borderRadius: "var(--search-radius-card)",
        boxShadow: "var(--search-shadow-card)",
      }}
    >
      <div
        className="px-4 sm:px-6 pt-4 sm:pt-5 pb-4 border-b"
        style={{ borderColor: "var(--search-border-subtle)" }}
      >
        <div
          className="text-[10px] font-semibold uppercase tracking-[0.12em]"
          style={{ color: "var(--search-text-tertiary)" }}
        >
          {GROUP_LABELS[group].eyebrow}
        </div>
        <h2
          className="mt-0.5 text-[15px] font-semibold"
          style={{ color: "var(--search-text-primary)" }}
        >
          {GROUP_LABELS[group].title}
        </h2>

        <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4 max-w-xl">
          <Field label="期別" icon={<Calendar className="w-3.5 h-3.5" />}>
            <PeriodSelect
              group={group}
              value={period}
              onChange={setPeriod}
            />
          </Field>
          <Field
            label="中鋼發佈日期"
            icon={<Calendar className="w-3.5 h-3.5" />}
          >
            <input
              type="date"
              value={dateStrToIso(announceDate)}
              onChange={(e) => setAnnounceDate(isoToDateStr(e.target.value))}
              className="w-full px-3 py-1.5 text-[13px] outline-none"
              style={{
                background: "var(--search-surface-input)",
                border: "1px solid var(--search-border-subtle)",
                borderRadius: "var(--search-radius-control)",
                color: "var(--search-text-primary)",
                colorScheme: "light",
              }}
            />
          </Field>
        </div>
      </div>

      {/* Desktop: 4-col table */}
      <div className="hidden sm:block overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr
              className="text-left"
              style={{
                background: "var(--search-surface-hover)",
                color: "var(--search-text-tertiary)",
              }}
            >
              <th className="px-6 py-2 font-medium text-[11px] uppercase tracking-wider">
                產品
              </th>
              <th className="px-3 py-2 font-medium text-[11px] uppercase tracking-wider text-right">
                {group === "monthly" ? "上月基價" : "上季基價"}
              </th>
              <th className="px-3 py-2 font-medium text-[11px] uppercase tracking-wider text-right">
                調整金額
              </th>
              <th className="px-6 py-2 font-medium text-[11px] uppercase tracking-wider text-right">
                調整後基價
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const prev = parseInt(r.prev_price.replace(/,/g, ""), 10) || 0;
              const change =
                parseInt(r.change_amount.replace(/[,+]/g, ""), 10) || 0;
              const newPrice = prev + change;
              return (
                <tr
                  key={r.slot_index}
                  style={{ borderTop: "1px solid var(--search-border-subtle)" }}
                >
                  <td className="px-6 py-1.5" style={{ color: "var(--search-text-primary)" }}>
                    {r.product_name}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <input
                      type="text"
                      value={r.prev_price}
                      onChange={(e) => update(i, "prev_price", e.target.value)}
                      className="w-24 px-2 py-1 text-[13px] text-right tabular-nums outline-none"
                      style={{
                        background: "var(--search-surface-input)",
                        border: "1px solid var(--search-border-subtle)",
                        borderRadius: "var(--search-radius-control)",
                        color: "var(--search-text-primary)",
                      }}
                    />
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <input
                      type="text"
                      value={r.change_amount}
                      onChange={(e) => update(i, "change_amount", e.target.value)}
                      className="w-20 px-2 py-1 text-[13px] text-right tabular-nums outline-none"
                      style={{
                        background: "var(--search-surface-input)",
                        border: "1px solid var(--search-border-subtle)",
                        borderRadius: "var(--search-radius-control)",
                        color: "var(--search-status-error)",
                      }}
                    />
                  </td>
                  <td className="px-6 py-1.5 text-right tabular-nums" style={{ color: "var(--search-text-secondary)" }}>
                    {newPrice.toLocaleString()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Mobile: per-product card with stacked inputs */}
      <div className="sm:hidden divide-y" style={{ borderColor: "var(--search-border-subtle)" }}>
        {rows.map((r, i) => {
          const prev = parseInt(r.prev_price.replace(/,/g, ""), 10) || 0;
          const change =
            parseInt(r.change_amount.replace(/[,+]/g, ""), 10) || 0;
          const newPrice = prev + change;
          return (
            <div
              key={r.slot_index}
              className="px-4 py-3"
              style={{ borderColor: "var(--search-border-subtle)" }}
            >
              <div
                className="text-[13px] font-medium mb-2"
                style={{ color: "var(--search-text-primary)" }}
              >
                {r.product_name}
              </div>
              <div className="grid grid-cols-3 gap-2">
                <label className="flex flex-col gap-0.5">
                  <span className="text-[10px]" style={{ color: "var(--search-text-tertiary)" }}>
                    {group === "monthly" ? "上月基價" : "上季基價"}
                  </span>
                  <input
                    type="text"
                    inputMode="numeric"
                    value={r.prev_price}
                    onChange={(e) => update(i, "prev_price", e.target.value)}
                    className="w-full px-2 py-1.5 text-[13px] text-right tabular-nums outline-none"
                    style={{
                      background: "var(--search-surface-input)",
                      border: "1px solid var(--search-border-subtle)",
                      borderRadius: "var(--search-radius-control)",
                      color: "var(--search-text-primary)",
                    }}
                  />
                </label>
                <label className="flex flex-col gap-0.5">
                  <span className="text-[10px]" style={{ color: "var(--search-text-tertiary)" }}>
                    調整
                  </span>
                  <input
                    type="text"
                    inputMode="numeric"
                    value={r.change_amount}
                    onChange={(e) => update(i, "change_amount", e.target.value)}
                    className="w-full px-2 py-1.5 text-[13px] text-right tabular-nums outline-none"
                    style={{
                      background: "var(--search-surface-input)",
                      border: "1px solid var(--search-border-subtle)",
                      borderRadius: "var(--search-radius-control)",
                      color: "var(--search-status-error)",
                    }}
                  />
                </label>
                <div className="flex flex-col gap-0.5">
                  <span className="text-[10px]" style={{ color: "var(--search-text-tertiary)" }}>
                    調整後
                  </span>
                  <div
                    className="w-full px-2 py-1.5 text-[13px] text-right tabular-nums"
                    style={{
                      background: "var(--search-surface-hover)",
                      border: "1px solid var(--search-border-subtle)",
                      borderRadius: "var(--search-radius-control)",
                      color: "var(--search-text-primary)",
                    }}
                  >
                    {newPrice.toLocaleString()}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div
        className="px-4 sm:px-6 py-3 flex items-center justify-between border-t"
        style={{
          borderColor: "var(--search-border-subtle)",
          background: "var(--search-surface-titlebar)",
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
        }}
      >
        <div className="text-[12px]" style={{ color: "var(--search-text-tertiary)" }}>
          {rows.length} 個產品
        </div>
        <div className="flex items-center gap-3">
          {savedFlag && (
            <span
              className="inline-flex items-center gap-1 text-[12px]"
              style={{ color: "var(--search-status-success)" }}
            >
              <Check className="w-3.5 h-3.5" />
              已儲存
            </span>
          )}
          {save.error && (
            <span
              className="text-[12px]"
              style={{ color: "var(--search-status-error)" }}
            >
              錯誤：{(save.error as Error).message}
            </span>
          )}
          <button
            onClick={onSave}
            disabled={save.isPending}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[13px] font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              background: "var(--search-accent)",
              color: "white",
              borderRadius: "var(--search-radius-control)",
            }}
            onMouseEnter={(e) => {
              if (!save.isPending)
                e.currentTarget.style.background = "var(--search-accent-hover)";
            }}
            onMouseLeave={(e) => {
              if (!save.isPending)
                e.currentTarget.style.background = "var(--search-accent)";
            }}
          >
            <Save className="w-3.5 h-3.5" />
            {save.isPending ? "儲存中…" : "儲存"}
          </button>
        </div>
      </div>
    </section>
  );
}

function Field({
  label,
  icon,
  children,
}: {
  label: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5">
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

/**
 * Native <select> dropdown for period_label. Always includes the current
 * value as an option even if it's not in the generated list (so loading
 * a legacy / customised label doesn't lose data).
 */
function PeriodSelect({
  group,
  value,
  onChange,
}: {
  group: Group;
  value: string;
  onChange: (v: string) => void;
}) {
  const generated = periodOptions(group);
  const options =
    value && !generated.includes(value) ? [value, ...generated] : generated;

  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full appearance-none px-3 py-1.5 pr-8 text-[13px] outline-none cursor-pointer"
        style={{
          background: "var(--search-surface-input)",
          border: "1px solid var(--search-border-subtle)",
          borderRadius: "var(--search-radius-control)",
          color: value ? "var(--search-text-primary)" : "var(--search-text-tertiary)",
        }}
      >
        {!value && (
          <option value="" disabled>
            選擇{group === "monthly" ? "月份" : "季別"}…
          </option>
        )}
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
      {/* Custom chevron — appearance-none kills the native one */}
      <svg
        className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2"
        width="10"
        height="6"
        viewBox="0 0 10 6"
        fill="none"
        aria-hidden
      >
        <path
          d="M1 1l4 4 4-4"
          stroke="var(--search-text-tertiary)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}
