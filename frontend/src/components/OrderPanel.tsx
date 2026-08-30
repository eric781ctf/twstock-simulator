import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import type { MarketSession, OrderSide, Quote, Stock } from "../types";

export interface OrderPrefill {
  stockCode: string;
  stockName: string;
  market: "TWSE" | "TPEX";
  side: OrderSide;
}

interface Props {
  onOrderPlaced: () => void;
  prefill?: OrderPrefill | null;
  marketSession?: MarketSession | null;
}

export function OrderPanel({ onOrderPlaced, prefill, marketSession }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Stock[]>([]);
  const [selected, setSelected] = useState<Stock | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [side, setSide] = useState<OrderSide>("buy");
  const [price, setPrice] = useState("");
  const [quantity, setQuantity] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const isAfterHours = marketSession?.status === "after_hours";
  const isClosed = marketSession?.status === "closed";
  const sideLabel = side === "buy" ? "買進" : "賣出";

  async function handleSearch(value: string) {
    setQuery(value);
    if (value.trim().length === 0) {
      setResults([]);
      return;
    }
    try {
      const stocks = await api.searchStocks(value.trim());
      setResults(stocks);
    } catch {
      setResults([]);
    }
  }

  async function selectStock(stock: Stock) {
    setSelected(stock);
    setResults([]);
    setQuery(`${stock.code} ${stock.name}`);
    try {
      const q = await api.getQuote(stock.code);
      setQuote(q);
      if (q.price != null) setPrice(String(q.price));
    } catch {
      setQuote(null);
    }
  }

  // 從自選股 block 點「買」「賣」跳轉過來時，自動帶入股票與方向。
  useEffect(() => {
    if (!prefill) return;
    setSide(prefill.side);
    selectStock({ code: prefill.stockCode, name: prefill.stockName, market: prefill.market });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.stockCode, prefill?.side]);

  // 盤後買賣固定用收盤價，不開放使用者自行輸入限價，價格欄位跟著報價走。
  useEffect(() => {
    if (isAfterHours && quote?.price != null) {
      setPrice(String(quote.price));
    }
  }, [isAfterHours, quote]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!selected) {
      setError("請先選擇股票");
      return;
    }
    if (isClosed) {
      setError("非交易時間，暫不接受下單");
      return;
    }
    const priceNum = Number(price);
    const qtyNum = Number(quantity);
    if (!priceNum || priceNum <= 0) {
      setError(isAfterHours ? "目前無收盤價資訊，請稍後再試" : "請輸入有效限價");
      return;
    }
    if (!qtyNum || qtyNum <= 0 || qtyNum >= 1000) {
      setError("零股股數需介於 1~999 股");
      return;
    }

    setSubmitting(true);
    try {
      await api.placeOrder({ stock_code: selected.code, side, price: priceNum, quantity: qtyNum });
      setQuantity("");
      onOrderPlaced();
    } catch (err) {
      setError(err instanceof Error ? err.message : "下單失敗");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="panel">
      <h2>下單</h2>
      <input
        placeholder="搜尋股票代碼或名稱"
        value={query}
        onChange={(e) => handleSearch(e.target.value)}
      />
      {results.length > 0 && (
        <div className="search-results">
          {results.map((s) => (
            <div key={s.code} onClick={() => selectStock(s)}>
              {s.code} {s.name} <span style={{ color: "var(--muted)" }}>({s.market})</span>
            </div>
          ))}
        </div>
      )}

      {selected && (
        <div className="selected-stock">
          <div>
            {selected.code} {selected.name}
          </div>
          <div className="price">
            {quote?.price != null ? quote.price.toFixed(2) : quote?.prev_close != null ? `${quote.prev_close.toFixed(2)} (昨收)` : "無報價"}
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="side-toggle">
          <button type="button" className={`buy ${side === "buy" ? "active" : ""}`} onClick={() => setSide("buy")}>
            買進
          </button>
          <button type="button" className={`sell ${side === "sell" ? "active" : ""}`} onClick={() => setSide("sell")}>
            賣出
          </button>
        </div>
        <input
          type="number"
          step="0.01"
          placeholder={isAfterHours ? "收盤價" : "限價"}
          value={price}
          readOnly={isAfterHours}
          onChange={(e) => setPrice(e.target.value)}
        />
        {isAfterHours && <div className="order-hint">盤後{sideLabel}將以今日收盤價成交，送出後立即成交</div>}
        {isClosed && <div className="order-hint warn">非交易時間，暫不接受{sideLabel}委託</div>}
        <input
          type="number"
          placeholder="股數 (1~999)"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
        />
        {error && <div className="error-msg">{error}</div>}
        <button className="submit" type="submit" disabled={submitting || isClosed}>
          {submitting ? "送出中..." : isAfterHours ? `送出盤後${sideLabel}單` : side === "buy" ? "送出買單" : "送出賣單"}
        </button>
      </form>
    </div>
  );
}
