import api from "./api";
import { useAuthStore } from "@/store/authStore";

export async function login(email: string, password: string): Promise<void> {
  const { data } = await api.post("/auth/login", { email, password });
  useAuthStore.getState().setAccessToken(data.access_token);
}

export async function register(
  email: string,
  password: string,
  display_name?: string
): Promise<void> {
  const { data } = await api.post("/auth/register", {
    email,
    password,
    display_name,
  });
  useAuthStore.getState().setAccessToken(data.access_token);
}

export async function logout(): Promise<void> {
  await api.post("/auth/logout");
  useAuthStore.getState().clearAuth();
}

// Call on page load to restore session via refresh token cookie
export async function tryRestoreSession(): Promise<boolean> {
  try {
    const { data } = await api.post("/auth/refresh");
    useAuthStore.getState().setAccessToken(data.access_token);
    return true;
  } catch {
    return false;
  }
}
