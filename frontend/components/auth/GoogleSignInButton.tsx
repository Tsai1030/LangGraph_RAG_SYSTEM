"use client";

import { GoogleLogin, type CredentialResponse } from "@react-oauth/google";

type Props = {
  /** Called with Google ID token (credential) when user successfully picks an account. */
  onCredential: (credential: string) => void;
  onError?: () => void;
  /** GIS button text. login_with / signup_with / continue_with */
  text?: "signin_with" | "signup_with" | "continue_with";
  /** Restrict picker to this Workspace domain. NOTE: hint only, server still enforces. */
  hostedDomain?: string;
};

/**
 * Thin wrapper around @react-oauth/google's <GoogleLogin>.
 *
 * 為什麼自己包一層而不直接用 GoogleLogin：
 *   1. 三個頁面（login / register / settings）都要用，集中按鈕樣式/錯誤處理。
 *   2. 隔離 lib 細節 — 未來換 OAuth flow（如 useGoogleLogin）只改這裡。
 *   3. hostedDomain 提供型別友善的 prop，避免 page 散落 hd 字串。
 */
export default function GoogleSignInButton({
  onCredential,
  onError,
  text = "signin_with",
  hostedDomain,
}: Props) {
  const handleSuccess = (resp: CredentialResponse) => {
    if (resp.credential) onCredential(resp.credential);
  };

  return (
    <GoogleLogin
      onSuccess={handleSuccess}
      onError={onError}
      text={text}
      shape="rectangular"
      width="320"
      // GIS 的 hd 是 hint：強制只顯示該網域帳號到帳號選擇器；不是安全機制（後端仍要驗）
      hosted_domain={hostedDomain}
    />
  );
}
