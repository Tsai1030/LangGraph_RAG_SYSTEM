// Auth
export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  role?: "user" | "admin";
  search_enabled?: boolean;
}

// Conversations
export interface ConversationOut {
  id: string;
  title: string | null;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
  last_message_preview: string | null;
}

export interface MessageOut {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  meta: MessageMeta | null;
  created_at: string;
}

export interface MessageMeta {
  sources?: Source[];
  form_files?: FormFile[];
  token_count?: number;
}

export interface ConversationDetail {
  id: string;
  title: string | null;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
  messages: MessageOut[];
  summary: string | null;
}

// Sources
export interface Source {
  source_file: string;
  section: string;
  section_code: string;
  tags: string[];
}

// 表單下載卡（靜態空白檔 / 已填寫靜態表 / 動態匯出檔皆共用此型）
export interface FormFile {
  form_id: string;
  display_name: string;
  download_url: string;
}

// SSE Events
export type SSEEvent =
  | { type: "text"; content: string }
  | { type: "form_files"; data: FormFile[] }
  | { type: "sources"; data: Source[] }
  | { type: "done" };
