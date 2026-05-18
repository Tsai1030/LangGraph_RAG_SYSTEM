/**
 * SEARCH module DTO types — mirror the backend Pydantic schemas in
 * app/modules/search/api/schemas.py.
 *
 * Naming: every exported type carries a Search prefix so a stray
 * `GenerationRun` etc. import from this file does not collide with
 * RAG conventions (RAG has its own GenerationRun-adjacent concepts
 * down the road).
 */

export type SearchConfidence = "high" | "medium" | "low";

export interface SearchSlotValue {
  slot_key: string;
  label: string;
  value: string | null;
  raw_value: number | null;
  unit: string | null;
  confidence: SearchConfidence;
  source: string | null;
  source_url: string | null;
}

export interface SearchGenerationStatus {
  run_id: number;
  status: string;        // 'running' | 'success' | 'partial' | 'failed'
  meeting_date: string;  // ISO YYYY-MM-DD
  slots: SearchSlotValue[];
  has_output: boolean;
  notes?: string | null;
}

export interface SearchGenerationRunRequest {
  meeting_date: string;
  fengxing_open_date?: string;
}

export interface SearchInternalDataRequest {
  internal_data: Record<string, string>;
}

// ── CSC admin (中鋼盤價) ──────────────────────────────────────────────

export interface SearchCscRow {
  slot_index: number;
  product_name: string;
  prev_price: number;
  change_amount: number;
  new_price: number;
}

export interface SearchCscSnapshot {
  group: "monthly" | "quarterly";
  period_label: string;
  announce_date: string;
  rows: SearchCscRow[];
}

export interface SearchCscSaveRequest {
  period_label: string;
  announce_date: string;
  rows: { slot_index: number; prev_price: number; change_amount: number }[];
}

// ── Usage ─────────────────────────────────────────────────────────────

export interface SearchUsageAggregate {
  user_id: string | null;
  email: string | null;
  display_name: string | null;
  runs_total: number;
  runs_success: number;
  runs_failed: number;
  runs_partial: number;
  last_run_at: string | null;
}
