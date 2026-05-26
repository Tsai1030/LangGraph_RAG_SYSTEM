"use client";

import { GoogleOAuthProvider } from "@react-oauth/google";

/**
 * Client-side wrapper for GoogleOAuthProvider, so the (server) root layout
 * can include it without becoming a client component.
 *
 * NEXT_PUBLIC_GOOGLE_CLIENT_ID 必須在 .env.local 設好（從 Google Cloud
 * Console → APIs & Services → Credentials → OAuth 2.0 Client ID）。
 */
export default function GoogleAuthProvider({ children }: { children: React.ReactNode }) {
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
  if (!clientId) {
    // dev 階段忘了設環境變數會在這裡掉，避免 silent fail
    console.warn("[GoogleAuthProvider] NEXT_PUBLIC_GOOGLE_CLIENT_ID 未設定，Google 登入將無法使用");
    return <>{children}</>;
  }
  return <GoogleOAuthProvider clientId={clientId}>{children}</GoogleOAuthProvider>;
}
