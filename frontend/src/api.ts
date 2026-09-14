import type {
  AuthResponse,
  BackfillStatus,
  ChipStatus,
  IndustryStatus,
  ShareholdingStatus,
  DailyBarStats,
  FeatureFlag,
  ModelDetail,
  ModelCatalog,
  ModelDeleteResult,
  ModelSummary,
  ModelTrainRequest,
  SchedulerFlag,
  TrainDefaults,
} from "./types";

/** 後端位址。
 *
 * 預設用「開啟這個網頁的主機」去組，而不是寫死 localhost。寫死的話，從別台
 * 裝置連進來時瀏覽器會去打**那台裝置自己的** localhost:8000，什麼都不會有——
 * 頁面框架載得出來但所有資料都是 Failed to fetch。
 *
 * 這樣寫的好處是位址變了也不用改設定：用 localhost 開就打 localhost，用
 * 192.168.0.11 開就打 192.168.0.11，用外網 IP 開就打那個外網 IP。
 * 要指到別的地方（例如後端在另一台機器）再用 VITE_API_BASE_URL 覆蓋。
 */
const API_PORT = 8000;
const BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? `${window.location.protocol}//${window.location.hostname}:${API_PORT}`;
const TOKEN_KEY = "twstock_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

class UnauthorizedError extends Error {}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE_URL}${path}`, { headers, ...options });

  if (res.status === 401 && token) {
    setToken(null);
    window.dispatchEvent(new Event("twstock:unauthorized"));
    throw new UnauthorizedError("登入已過期，請重新登入");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `請求失敗 (${res.status})`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  login: (username: string, password: string) =>
    request<AuthResponse>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),

  setFeatureFlag: (key: string, enabled: boolean) =>
    request<FeatureFlag>(`/admin/feature-flags/${key}`, { method: "POST", body: JSON.stringify({ enabled }) }),
  getDailyBarStats: () => request<DailyBarStats>("/admin/daily-bar-stats"),

  getBackfillStatus: () => request<BackfillStatus>("/admin/models/backfill-status"),
  getChipStatus: () => request<ChipStatus>("/admin/models/chip-status"),
  triggerChipBackfill: (targetMonths: number) =>
    request<ChipStatus>("/admin/models/chip-backfill", {
      method: "POST",
      body: JSON.stringify({ target_months: targetMonths }),
    }),
  getShareholdingStatus: () => request<ShareholdingStatus>("/admin/models/shareholding-status"),
  importShareholding: () =>
    request<ShareholdingStatus>("/admin/models/shareholding-import", { method: "POST" }),
  fetchShareholding: () =>
    request<ShareholdingStatus>("/admin/models/shareholding-fetch", { method: "POST" }),
  getIndustryStatus: () => request<IndustryStatus>("/admin/models/industry-status"),
  syncIndustries: () => request<IndustryStatus>("/admin/models/industry-sync", { method: "POST" }),
  getModelSchedulers: () => request<SchedulerFlag[]>("/admin/models/schedulers"),
  triggerBackfill: (targetMonths: number) =>
    request<BackfillStatus>("/admin/models/backfill", {
      method: "POST",
      body: JSON.stringify({ target_months: targetMonths }),
    }),

  getModelCatalog: () => request<ModelCatalog>("/models/catalog"),
  getPublicModels: () => request<ModelSummary[]>("/models"),
  getPublicModel: (id: number) => request<ModelDetail>(`/models/${id}`),

  getTrainDefaults: () => request<TrainDefaults>("/admin/models/train-defaults"),
  getAdminModels: () => request<ModelSummary[]>("/admin/models"),
  trainModel: (payload: ModelTrainRequest) =>
    request<ModelSummary>("/admin/models", { method: "POST", body: JSON.stringify(payload) }),
  archiveModel: (id: number) => request<ModelSummary>(`/admin/models/${id}/archive`, { method: "POST" }),
  unarchiveModel: (id: number) => request<ModelSummary>(`/admin/models/${id}/unarchive`, { method: "POST" }),
  deleteModel: (id: number) => request<ModelDeleteResult>(`/admin/models/${id}`, { method: "DELETE" }),
};
