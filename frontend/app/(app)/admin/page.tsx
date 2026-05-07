"use client";

import { useEffect, useState } from "react";
import { Activity, DollarSign, MessageSquare, Users } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { TimeSeriesChart } from "@/components/admin/TimeSeriesChart";
import type { AdminStatsOut, AdminTimeSeriesOut } from "@/types/admin";

const RANGE_OPTIONS = [
  { label: "7 天", days: 7 },
  { label: "30 天", days: 30 },
  { label: "90 天", days: 90 },
] as const;

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>;
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="bg-white border border-zinc-200 rounded-xl p-5">
      <div className="flex items-center gap-2 text-xs text-zinc-500">
        <Icon size={14} className="text-zinc-400" />
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold text-zinc-900 tabular-nums">{value}</div>
      {sub && <div className="mt-1 text-xs text-zinc-500">{sub}</div>}
    </div>
  );
}

export default function AdminDashboardPage() {
  const [stats, setStats] = useState<AdminStatsOut | null>(null);
  const [series, setSeries] = useState<AdminTimeSeriesOut | null>(null);
  const [days, setDays] = useState<number>(30);
  const [loading, setLoading] = useState(true);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 第一次載入：stats 與 default 30 天 series 並行
  useEffect(() => {
    Promise.all([
      api.get<AdminStatsOut>("/admin/stats"),
      api.get<AdminTimeSeriesOut>(`/admin/stats/timeseries?days=${days}`),
    ])
      .then(([s, t]) => {
        setStats(s.data);
        setSeries(t.data);
      })
      .catch(() => setError("載入統計失敗"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 切換天數時只重抓 series，stats 不變
  const handleRangeChange = async (newDays: number) => {
    if (newDays === days) return;
    setDays(newDays);
    setSeriesLoading(true);
    try {
      const { data } = await api.get<AdminTimeSeriesOut>(
        `/admin/stats/timeseries?days=${newDays}`
      );
      setSeries(data);
    } catch {
      setError("載入趨勢失敗");
    } finally {
      setSeriesLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-zinc-500">
        <span className="size-4 border-2 border-zinc-300 border-t-zinc-700 rounded-full animate-spin-fast mr-2" />
        載入中…
      </div>
    );
  }

  if (error || !stats) {
    return (
      <div className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-xl px-4 py-3">
        {error ?? "無資料"}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Header + range picker */}
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold text-zinc-900">系統概覽</h2>
          <p className="text-sm text-zinc-500 mt-0.5">即時資料，每次進入此頁重新計算</p>
        </div>
        <div className="flex items-center gap-1 bg-zinc-100 rounded-lg p-0.5">
          {RANGE_OPTIONS.map((opt) => {
            const active = opt.days === days;
            return (
              <button
                key={opt.days}
                onClick={() => handleRangeChange(opt.days)}
                disabled={seriesLoading}
                className={cn(
                  "px-3 py-1.5 text-xs rounded-md transition-colors disabled:opacity-50",
                  active
                    ? "bg-white text-zinc-900 shadow-sm"
                    : "text-zinc-600 hover:text-zinc-900"
                )}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Trend chart */}
      <section className={cn(seriesLoading && "opacity-50 pointer-events-none transition-opacity")}>
        {series && <TimeSeriesChart points={series.points} />}
      </section>

      {/* Users */}
      <section>
        <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-2">使用者</h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <StatCard icon={Users} label="總使用者" value={stats.users.total} sub={`${stats.users.active} 啟用中`} />
          <StatCard icon={Users} label="管理員" value={stats.users.admin} />
          <StatCard
            icon={Users}
            label="停用帳號"
            value={stats.users.total - stats.users.active}
          />
        </div>
      </section>

      {/* Conversations */}
      <section>
        <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-2">對話</h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <StatCard icon={MessageSquare} label="累計對話" value={stats.conversations.total} />
          <StatCard icon={Activity} label="今日新增" value={stats.conversations.today} />
          <StatCard icon={Activity} label="近 7 日" value={stats.conversations.this_week} />
        </div>
      </section>

      {/* Messages */}
      <section>
        <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-2">訊息</h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <StatCard icon={MessageSquare} label="累計訊息" value={stats.messages.total} />
          <StatCard icon={Activity} label="今日新增" value={stats.messages.today} />
          <StatCard icon={Activity} label="近 7 日" value={stats.messages.this_week} />
        </div>
      </section>

      {/* Tokens */}
      <section>
        <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-2">Token 用量（估算）</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <StatCard
            icon={Activity}
            label="累計 tokens"
            value={stats.tokens.total.toLocaleString()}
            sub={`今日：${stats.tokens.today.toLocaleString()}`}
          />
          <StatCard
            icon={DollarSign}
            label="累計成本估算"
            value={`$${stats.cost_estimate_usd.total.toFixed(2)}`}
            sub={`今日：$${stats.cost_estimate_usd.today.toFixed(2)}`}
          />
        </div>
        <p className="mt-2 text-[11px] text-zinc-400 leading-relaxed">{stats.note}</p>
      </section>
    </div>
  );
}
