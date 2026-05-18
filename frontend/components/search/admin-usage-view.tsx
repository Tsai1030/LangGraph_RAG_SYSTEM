"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import api from "@/lib/api";
import type { SearchUsageAggregate } from "@/lib/search/types";

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function AdminUsageView() {
  const { data, isLoading } = useQuery<SearchUsageAggregate[]>({
    queryKey: ["admin", "search-usage"],
    queryFn: async () => {
      const res = await api.get<SearchUsageAggregate[]>("/admin/search-usage");
      return res.data;
    },
    refetchInterval: 30_000,
  });

  const rows = data ?? [];
  const totalRuns = rows.reduce((sum, r) => sum + r.runs_total, 0);
  const totalSuccess = rows.reduce((sum, r) => sum + r.runs_success, 0);
  const totalFailed = rows.reduce((sum, r) => sum + r.runs_failed, 0);

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
          使用流量
        </h1>
        <p
          className="mt-2 text-[13px] sm:text-[14px] leading-relaxed"
          style={{ color: "var(--search-text-secondary)" }}
        >
          以「產生會議記錄」為單位統計每位使用者的呼叫次數與最後一次使用時間。
          每 30 秒自動更新一次。
        </p>
      </div>

      <div className="mt-6 sm:mt-8 grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
        <StatCard label="總執行次數" value={totalRuns} />
        <StatCard
          label="成功"
          value={totalSuccess}
          accent="var(--search-status-success)"
        />
        <StatCard
          label="失敗"
          value={totalFailed}
          accent="var(--search-status-error)"
        />
      </div>

      <div className="mt-4 sm:mt-6">
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
              PER-USER
            </div>
            <h2
              className="mt-0.5 text-[15px] font-semibold inline-flex items-center gap-2"
              style={{ color: "var(--search-text-primary)" }}
            >
              <Activity className="w-4 h-4" />
              各帳號使用量
            </h2>
          </div>

          {isLoading ? (
            <div
              className="p-6 text-[13px]"
              style={{ color: "var(--search-text-tertiary)" }}
            >
              載入中…
            </div>
          ) : rows.length === 0 ? (
            <div
              className="p-8 text-center text-[13px]"
              style={{ color: "var(--search-text-tertiary)" }}
            >
              還沒有任何執行紀錄
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead>
                  <tr
                    className="text-left"
                    style={{
                      background: "var(--search-surface-hover)",
                      color: "var(--search-text-tertiary)",
                    }}
                  >
                    <th className="px-4 py-2 font-medium text-[11px] uppercase tracking-wider">
                      帳號
                    </th>
                    <th className="px-4 py-2 font-medium text-[11px] uppercase tracking-wider text-right">
                      總次數
                    </th>
                    <th className="px-4 py-2 font-medium text-[11px] uppercase tracking-wider text-right">
                      成功
                    </th>
                    <th className="px-4 py-2 font-medium text-[11px] uppercase tracking-wider text-right">
                      失敗
                    </th>
                    <th className="px-4 py-2 font-medium text-[11px] uppercase tracking-wider text-right pr-6">
                      最後執行
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr
                      key={r.user_id ?? `unknown-${r.last_run_at ?? "x"}`}
                      style={{ borderTop: "1px solid var(--search-border-subtle)" }}
                    >
                      <td
                        className="px-4 py-2 font-medium"
                        style={{ color: "var(--search-text-primary)" }}
                      >
                        {r.email ?? r.display_name ?? "（已刪除/未對應）"}
                      </td>
                      <td
                        className="px-4 py-2 text-right tabular-nums"
                        style={{ color: "var(--search-text-primary)" }}
                      >
                        {r.runs_total}
                      </td>
                      <td
                        className="px-4 py-2 text-right tabular-nums"
                        style={{ color: "var(--search-status-success)" }}
                      >
                        {r.runs_success}
                      </td>
                      <td
                        className="px-4 py-2 text-right tabular-nums"
                        style={{ color: "var(--search-status-error)" }}
                      >
                        {r.runs_failed}
                      </td>
                      <td
                        className="px-4 py-2 text-right pr-6 tabular-nums"
                        style={{ color: "var(--search-text-secondary)" }}
                      >
                        {fmtDateTime(r.last_run_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </>
  );
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: string;
}) {
  return (
    <div
      className="px-4 py-3"
      style={{
        background: "var(--search-surface-card)",
        borderRadius: "var(--search-radius-card)",
        boxShadow: "var(--search-shadow-card)",
      }}
    >
      <div
        className="text-[10px] font-semibold uppercase tracking-[0.12em]"
        style={{ color: "var(--search-text-tertiary)" }}
      >
        {label}
      </div>
      <div
        className="mt-1 text-[24px] font-semibold tabular-nums"
        style={{ color: accent ?? "var(--search-text-primary)" }}
      >
        {value.toLocaleString()}
      </div>
    </div>
  );
}
