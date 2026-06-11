// Auth
export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  avatar_url?: string | null;
  role?: "user" | "admin";
  search_enabled?: boolean;
  has_password?: boolean;
  google_linked?: boolean;
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
  images?: { image_id: string; mime?: string }[]; // 使用者上傳圖片（泡泡縮圖；用 /api/chat/image/{id} 顯示）
  documents?: { document_id: string; filename: string; size?: number }[]; // 使用者上傳文件（泡泡卡片，與 InputBar DocumentCard 同設計）
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

// 待送出的已上傳圖片（InputBar 暫存，送出時帶 image_id 給後端）
export interface PendingImage {
  image_id: string;
  mime_type: string;
  preview_url: string; // 本地 object URL，供縮圖預覽
  name: string;
}

// 待送出的已上傳文件（PDF/DOCX/PPTX；上傳當下後端已完成解析與索引）
export interface PendingDocument {
  document_id: string; // status="uploading" 時為前端暫時 id，完成後換成後端 id
  filename: string;
  size?: number; // bytes，前端卡片顯示用
  status?: "uploading" | "ready"; // 未填視為 ready
}

// SSE Events
export type SSEEvent =
  | { type: "text"; content: string }
  | { type: "form_files"; data: FormFile[] }
  | { type: "sources"; data: Source[] }
  | { type: "done" };
