import type {
  Account,
  AdminAccount,
  AuthResponse,
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
  Order,
  OrderSide,
  OrderStatus,
  OrderType,
  Position,
  PricePoint,
  Quote,
  RealizedPnlSummary,
  Stock,
  Strategy,
  StrategyInput,
  StrategyTradeRecord,
  Trade,
  WatchlistItem,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
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
};
