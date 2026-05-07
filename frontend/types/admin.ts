export interface AdminUserOut {
  id: string;
  email: string;
  display_name: string | null;
  role: "user" | "admin";
  is_active: boolean;
  created_at: string;
  updated_at: string;
  conversation_count: number;
  last_active_at: string | null;
}

export interface AdminUserListOut {
  items: AdminUserOut[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminConversationOut {
  id: string;
  user_id: string;
  user_email: string | null;
  title: string | null;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface AdminMessageOut {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  token_count: number | null;
  created_at: string;
}

export interface AdminConversationDetail extends AdminConversationOut {
  messages: AdminMessageOut[];
}

export interface StatsBreakdown {
  total: number;
  today: number;
  this_week: number;
}

export interface AdminStatsOut {
  users: { total: number; active: number; admin: number };
  conversations: StatsBreakdown;
  messages: StatsBreakdown;
  tokens: { total: number; today: number };
  cost_estimate_usd: { total: number; today: number };
  note: string;
}

export interface VectorCollectionInfo {
  name: string;
  document_count: number;
  sample_files: string[];
}

export interface AdminVectorInfo {
  active_version: string;
  resolved_path: string;
  collections: VectorCollectionInfo[];
}

export interface AdminTimeSeriesPoint {
  date: string;
  messages: number;
  conversations: number;
  tokens: number;
}

export interface AdminTimeSeriesOut {
  days: number;
  points: AdminTimeSeriesPoint[];
}
