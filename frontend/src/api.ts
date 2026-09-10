import type {
  Account,
  AdminAccount,
  AuthResponse,
  BackfillStatus,
  ChipStatus,
  BacktestRequest,
  BacktestResult,
  DailyBar,
  DailyBarStats,
  EquitySnapshot,
  FeatureFlag,
  Fundamentals,
  FundamentalsHistoryPoint,
  LeaderboardEntry,
  MarketSession,
  ModelDetail,
  ModelCatalog,
  ModelDeleteResult,
  ModelSummary,
  ModelTrainRequest,
  Order,
  OrderSide,
  OrderStatus,
  OrderType,
  Position,
  PricePoint,
  Quote,
  RealizedPnlSummary,
  SchedulerFlag,
  Stock,
  Strategy,
  StrategyInput,
  StrategyTradeRecord,
  Trade,
  TrainDefaults,
  WatchlistItem,
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
  register: (username: string, password: string, nickname: string) =>
    request<AuthResponse>("/auth/register", { method: "POST", body: JSON.stringify({ username, password, nickname }) }),
  login: (username: string, password: string) =>
    request<AuthResponse>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),

  getAccount: () => request<Account>("/account"),
  getEquityHistory: (days = 180) => request<EquitySnapshot[]>(`/account/equity-history?days=${days}`),
  searchStocks: (query: string) => request<Stock[]>(`/stocks?query=${encodeURIComponent(query)}`),
  getQuote: (code: string) => request<Quote>(`/stocks/${code}/quote`),
  getDailyHistory: (code: string, months = 3) =>
    request<DailyBar[]>(`/stocks/${code}/daily-history?months=${months}`),
  getIntraday: (code: string) => request<PricePoint[]>(`/stocks/${code}/intraday`),
  getFundamentals: (code: string) => request<Fundamentals>(`/stocks/${code}/fundamentals`),
  getFundamentalsHistory: (code: string, years = 3) =>
    request<FundamentalsHistoryPoint[]>(`/stocks/${code}/fundamentals-history?years=${years}`),
  getPositions: () => request<Position[]>("/positions"),
  getOrders: (params?: { status?: OrderStatus; todayOnly?: boolean }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.todayOnly) q.set("today_only", "true");
    const qs = q.toString();
    return request<Order[]>(`/orders${qs ? `?${qs}` : ""}`);
  },
  getTrades: (params?: { startDate?: string; endDate?: string }) => {
    const q = new URLSearchParams();
    if (params?.startDate) q.set("start_date", params.startDate);
    if (params?.endDate) q.set("end_date", params.endDate);
    const qs = q.toString();
    return request<Trade[]>(`/trades${qs ? `?${qs}` : ""}`);
  },
  placeOrder: (payload: {
    stock_code: string;
    side: OrderSide;
    order_type: OrderType;
    price?: number;
    stop_price?: number;
    quantity: number;
  }) => request<Order>("/orders", { method: "POST", body: JSON.stringify(payload) }),
  cancelOrder: (id: number) => request<Order>(`/orders/${id}`, { method: "DELETE" }),
  getRealizedPnlSummary: () => request<RealizedPnlSummary>("/trades/realized-pnl-summary"),

  getWatchlist: () => request<WatchlistItem[]>("/watchlist"),
  addToWatchlist: (stock_code: string) =>
    request<WatchlistItem>("/watchlist", { method: "POST", body: JSON.stringify({ stock_code }) }),
  removeFromWatchlist: (stock_code: string) =>
    request<void>(`/watchlist/${stock_code}`, { method: "DELETE" }),

  getLeaderboard: () => request<LeaderboardEntry[]>("/leaderboard"),

  getMarketSession: () => request<MarketSession>("/market/session"),

  getAdminAccounts: () => request<AdminAccount[]>("/admin/accounts"),
  getDefaultInitialCash: () => request<{ amount: number }>("/admin/settings/default-initial-cash"),
  setDefaultInitialCash: (amount: number) =>
    request<{ amount: number }>("/admin/settings/default-initial-cash", {
      method: "POST",
      body: JSON.stringify({ amount }),
    }),
  addCashToAll: (amount: number) =>
    request<{ updated: number }>("/admin/accounts/add-cash", { method: "POST", body: JSON.stringify({ amount }) }),
  deleteAccount: (userId: number) => request<{ deleted: boolean }>(`/admin/accounts/${userId}`, { method: "DELETE" }),
  freezeAccount: (userId: number) =>
    request<{ frozen_until: string }>(`/admin/accounts/${userId}/freeze`, { method: "POST" }),

  getStrategies: () => request<Strategy[]>("/strategies"),
  createStrategy: (payload: StrategyInput) =>
    request<Strategy>("/strategies", { method: "POST", body: JSON.stringify(payload) }),
  updateStrategy: (id: number, payload: StrategyInput) =>
    request<Strategy>(`/strategies/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteStrategy: (id: number) => request<{ deleted: boolean }>(`/strategies/${id}`, { method: "DELETE" }),
  activateStrategy: (id: number) => request<Strategy>(`/strategies/${id}/activate`, { method: "POST" }),
  deactivateStrategy: (id: number) => request<Strategy>(`/strategies/${id}/deactivate`, { method: "POST" }),
  getStrategyTrades: (id: number) => request<StrategyTradeRecord[]>(`/strategies/${id}/trades`),
  backtestStrategy: (id: number, payload: BacktestRequest) =>
    request<BacktestResult>(`/strategies/${id}/backtest`, { method: "POST", body: JSON.stringify(payload) }),

  getFeatureFlags: () => request<Record<string, boolean>>("/feature-flags"),
  getAdminFeatureFlags: () => request<FeatureFlag[]>("/admin/feature-flags"),
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
