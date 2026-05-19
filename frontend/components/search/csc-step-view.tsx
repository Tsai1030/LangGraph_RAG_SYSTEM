"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Calendar, ChevronRight, ChevronLeft } from "lucide-react";
import api from "@/lib/api";
import type {
  SearchCscSnapshot,
  SearchCscSaveRequest,
} from "@/lib/search/types";

/**
 * Wizard step — let the user edit CSC values for this run only.
 *
 * Unlike the (now-removed) admin editor this component:
 *   - never PUTs to /search/csc — that's the shared admin seed.
 *   - reports its final state via onComplete(payload), called when the
 *     user clicks "Next". The parent wizard stores the payload and
 *     ships it inside internal-data's csc_override on final submit.
 *
 * Defaults come from GET /search/csc/{group} (the shared seed). User
 * tweaks are local to this run.
 */
export interface CscStepPayload {
  monthly: SearchCscSaveRequest;
  quarterly: SearchCscSaveRequest;
}

interface Props {
  initial?: CscStepPayload;
  onComplete: (payload: CscStepPayload) => void;
  onBack: () => void;
}

type Group = "monthly" | "quarterly";

const GROUP_LABEL: Record<Group, { title: string; basePriceCol: string }> = {
  monthly: { title: "八.1 月盤", basePriceCol: "上月基價" },
  quarterly: { title: "八.2 季盤", basePriceCol: "上季基價" },
};

interface EditableRow {
  slot_index: number;
  product_name: string;
  prev_price: string;
  change_amount: string;
}

interface GroupState {
  period_label: string;
  announce_date: string;   // "YYYY/M/D" as backend expects
  rows: EditableRow[];
}

function snapToEditable(snap: SearchCscSnapshot): GroupState {
  return {
    period_label: snap.period_label,
    announce_date: snap.announce_date,
    rows: snap.rows.map((r) => ({
      slot_index: r.slot_index,
      product_name: r.product_name,
      prev_price: String(r.prev_price),
      change_amount: String(r.change_amount),
    })),
  };
}

function stateToPayload(s: GroupState): SearchCscSaveRequest {
  return {
    period_label: s.period_label,
    announce_date: s.announce_date,
    rows: s.rows.map((r) => ({
      slot_index: r.slot_index,
      prev_price: parseInt(r.prev_price.replace(/,/g, ""), 10) || 0,
      change_amount: parseInt(r.change_amount.replace(/[,+]/g, ""), 10) || 0,
    })),
  };
}

// "2026/4/15" ↔ "2026-04-15" for native date input.
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

export function CscStepView({ initial, onComplete, onBack }: Props) {
  // Fetch defaults for both groups in parallel. Defaults seed the form
  // when the user first lands on this step; subsequent visits restore
  // their previous edits via the `initial` prop (parent wizard).
  const monthlyQ = useQuery<SearchCscSnapshot>({
    queryKey: ["search-csc", "monthly"],
    queryFn: async () => {
      const r = await api.get<SearchCscSnapshot>("/search/csc/monthly");
      return r.data;
    },
  });
  const quarterlyQ = useQuery<SearchCscSnapshot>({
    queryKey: ["search-csc", "quarterly"],
    queryFn: async () => {
      const r = await api.get<SearchCscSnapshot>("/search/csc/quarterly");
      return r.data;
    },
  });

  // Local form state seeded once from defaults or `initial`. We can't
  // useState(() => initial ?? snapToEditable(...)) at init time because
  // defaults arrive async; rely on the effect below to seed once.
  const [state, setState] = useState<{ monthly: GroupState; quarterly: GroupState } | null>(
    initial
      ? {
          monthly: { ...initial.monthly, rows: initial.monthly.rows.map((r) => ({
            slot_index: r.slot_index,
            product_name: "",
            prev_price: String(r.prev_price),
            change_amount: String(r.change_amount),
          })) },
          quarterly: { ...initial.quarterly, rows: initial.quarterly.rows.map((r) => ({
            slot_index: r.slot_index,
            product_name: "",
            prev_price: String(r.prev_price),
            change_amount: String(r.change_amount),
          })) },
        }
      : null,
  );

  useEffect(() => {
    if (state) return;   // already seeded
    if (!monthlyQ.data || !quarterlyQ.data) return;
    setState({
      monthly: snapToEditable(monthlyQ.data),
      quarterly: snapToEditable(quarterlyQ.data),
    });
  }, [state, monthlyQ.data, quarterlyQ.data]);

  // If we have initial values but the defaults arrived after, backfill
  // product_name for display (initial doesn't carry it).
  useEffect(() => {
    if (!state) return;
    if (!monthlyQ.data || !quarterlyQ.data) return;
    if (state.monthly.rows[0]?.product_name) return;   // already named
    const nameByIdx = (snap: SearchCscSnapshot) =>
      Object.fromEntries(snap.rows.map((r) => [r.slot_index, r.product_name]));
    const m = nameByIdx(monthlyQ.data);
    const q = nameByIdx(quarterlyQ.data);
    setState((s) =>
      s
        ? {
            monthly: { ...s.monthly, rows: s.monthly.rows.map((r) => ({ ...r, product_name: m[r.slot_index] ?? "" })) },
            quarterly: { ...s.quarterly, rows: s.quarterly.rows.map((r) => ({ ...r, product_name: q[r.slot_index] ?? "" })) },
          }
        : s,
    );
  }, [state, monthlyQ.data, quarterlyQ.data]);

  const updateRow = (
    group: Group,
    idx: number,
    field: "prev_price" | "change_amount",
    v: string,
  ) => {
    setState((s) =>
      s
        ? {
            ...s,
            [group]: {
              ...s[group],
              rows: s[group].rows.map((r, i) =>
                i === idx ? { ...r, [field]: v.replace(/[^\d.+\-,]/g, "") } : r,
              ),
            },
          }
        : s,
    );
  };

  const updateMeta = (group: Group, field: "period_label" | "announce_date", v: string) => {
    setState((s) => (s ? { ...s, [group]: { ...s[group], [field]: v } } : s));
  };

  const isLoading = !state || monthlyQ.isLoading || quarterlyQ.isLoading;

  const onNext = () => {
    if (!state) return;
    onComplete({
      monthly: stateToPayload(state.monthly),
      quarterly: stateToPayload(state.quarterly),
    });
  };

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader />

      {isLoading ? (
        <div
          className="p-6 text-[13px]"
          style={{
            background: "var(--search-surface-card)",
            borderRadius: "var(--search-radius-card)",
            boxShadow: "var(--search-shadow-card)",
            color: "var(--search-text-tertiary)",
          }}
        >
          載入預設盤價…
        </div>
      ) : (
        (["monthly", "quarterly"] as Group[]).map((g) => (
          <GroupTable
            key={g}
            group={g}
            state={state![g]}
            onUpdateRow={(idx, field, v) => updateRow(g, idx, field, v)}
            onUpdateMeta={(field, v) => updateMeta(g, field, v)}
          />
        ))
      )}

      <div className="flex justify-between gap-3 pt-2">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-2 px-3.5 py-2 text-[13px] font-medium"
          style={{
            background: "var(--search-surface-hover)",
            color: "var(--search-text-secondary)",
            borderRadius: "var(--search-radius-control)",
          }}
        >
          <ChevronLeft className="w-4 h-4" /> 上一步
        </button>
        <button
          onClick={onNext}
          disabled={isLoading}
          className="inline-flex items-center gap-2 px-4 py-2 text-[13px] font-medium disabled:opacity-50"
          style={{
            background: "var(--search-accent)",
            color: "white",
            borderRadius: "var(--search-radius-control)",
          }}
        >
          下一步 <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

function PageHeader() {
  return (
    <div className="max-w-3xl">
      <div
        className="text-[10px] font-semibold uppercase tracking-[0.12em]"
        style={{ color: "var(--search-accent)" }}
      >
        STEP 4 — CSC
      </div>
      <h1
        className="mt-1.5 text-[22px] sm:text-[28px] font-semibold tracking-tight leading-tight"
        style={{ color: "var(--search-text-primary)" }}
      >
        八.中鋼盤價（本次會議用）
      </h1>
      <p
        className="mt-2 text-[13px] sm:text-[14px] leading-relaxed"
        style={{ color: "var(--search-text-secondary)" }}
      >
        預設值是上次共用設定，可針對本次會議調整。修改只影響這次產出的 Word，
        不會覆蓋共用預設。
      </p>
    </div>
  );
}

function GroupTable({
  group,
  state,
  onUpdateRow,
  onUpdateMeta,
}: {
  group: Group;
  state: GroupState;
  onUpdateRow: (idx: number, field: "prev_price" | "change_amount", v: string) => void;
  onUpdateMeta: (field: "period_label" | "announce_date", v: string) => void;
}) {
  const { title, basePriceCol } = GROUP_LABEL[group];

  // Derived display: prev + change for each row.
  const displayRows = useMemo(
    () =>
      state.rows.map((r) => {
        const prev = parseInt(r.prev_price.replace(/,/g, ""), 10) || 0;
        const change = parseInt(r.change_amount.replace(/[,+]/g, ""), 10) || 0;
        return { ...r, newPrice: prev + change };
      }),
    [state.rows],
  );

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
        className="px-4 sm:px-6 pt-4 pb-3 border-b"
        style={{ borderColor: "var(--search-border-subtle)" }}
      >
        <h2
          className="text-[15px] font-semibold"
          style={{ color: "var(--search-text-primary)" }}
        >
          {title}
        </h2>
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-xl">
          <label className="block">
            <span
              className="block text-[11px] font-medium mb-1"
              style={{ color: "var(--search-text-tertiary)" }}
            >
              <Calendar className="inline w-3 h-3 mr-1" />
              期別
            </span>
            <input
              type="text"
              value={state.period_label}
              onChange={(e) => onUpdateMeta("period_label", e.target.value)}
              placeholder={group === "monthly" ? "115 年 5 月份" : "115 年第二季"}
              className="w-full px-3 py-1.5 text-[13px] outline-none"
              style={{
                background: "var(--search-surface-input)",
                border: "1px solid var(--search-border-subtle)",
                borderRadius: "var(--search-radius-control)",
                color: "var(--search-text-primary)",
              }}
            />
          </label>
          <label className="block">
            <span
              className="block text-[11px] font-medium mb-1"
              style={{ color: "var(--search-text-tertiary)" }}
            >
              <Calendar className="inline w-3 h-3 mr-1" />
              中鋼發佈日期
            </span>
            <input
              type="date"
              value={dateStrToIso(state.announce_date)}
              onChange={(e) => onUpdateMeta("announce_date", isoToDateStr(e.target.value))}
              className="w-full px-3 py-1.5 text-[13px] outline-none"
              style={{
                background: "var(--search-surface-input)",
                border: "1px solid var(--search-border-subtle)",
                borderRadius: "var(--search-radius-control)",
                color: "var(--search-text-primary)",
                colorScheme: "light",
              }}
            />
          </label>
        </div>
      </div>

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
              <th className="px-6 py-2 font-medium text-[11px] uppercase tracking-wider">
                產品
              </th>
              <th className="px-3 py-2 font-medium text-[11px] uppercase tracking-wider text-right">
                {basePriceCol}
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
            {displayRows.map((r, i) => (
              <tr
                key={r.slot_index}
                style={{ borderTop: "1px solid var(--search-border-subtle)" }}
              >
                <td
                  className="px-6 py-1.5"
                  style={{ color: "var(--search-text-primary)" }}
                >
                  {r.product_name || `#${r.slot_index}`}
                </td>
                <td className="px-3 py-1.5 text-right">
                  <input
                    type="text"
                    value={r.prev_price}
                    onChange={(e) => onUpdateRow(i, "prev_price", e.target.value)}
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
                    onChange={(e) => onUpdateRow(i, "change_amount", e.target.value)}
                    className="w-20 px-2 py-1 text-[13px] text-right tabular-nums outline-none"
                    style={{
                      background: "var(--search-surface-input)",
                      border: "1px solid var(--search-border-subtle)",
                      borderRadius: "var(--search-radius-control)",
                      color: "var(--search-status-error)",
                    }}
                  />
                </td>
                <td
                  className="px-6 py-1.5 text-right tabular-nums"
                  style={{ color: "var(--search-text-primary)" }}
                >
                  {r.newPrice.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
