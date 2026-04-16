import axios from "axios";
import { useAuthStore } from "@/store/authStore";

const api = axios.create({
  baseURL: "/api",
  withCredentials: true, // send HttpOnly cookie automatically
});

// Attach access token to every request
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// On 401, try to refresh and retry once
let _isRefreshing = false;
let _refreshQueue: Array<(token: string) => void> = [];

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config;

    if (error.response?.status !== 401 || original._retry) {
      return Promise.reject(error);
    }

    original._retry = true;

    if (_isRefreshing) {
      return new Promise((resolve) => {
        _refreshQueue.push((token) => {
          original.headers.Authorization = `Bearer ${token}`;
          resolve(api(original));
        });
      });
    }

    _isRefreshing = true;
    try {
      const { data } = await axios.post(
        "/api/auth/refresh",
        {},
        { withCredentials: true }
      );
      const newToken: string = data.access_token;
      useAuthStore.getState().setAccessToken(newToken);
      _refreshQueue.forEach((cb) => cb(newToken));
      _refreshQueue = [];
      original.headers.Authorization = `Bearer ${newToken}`;
      return api(original);
    } catch {
      useAuthStore.getState().clearAuth();
      return Promise.reject(error);
    } finally {
      _isRefreshing = false;
    }
  }
);

export default api;
