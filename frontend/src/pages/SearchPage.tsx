import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ChartTabs } from "../components/ChartTabs";
import { useStockCharts } from "../hooks/useStockCharts";
import type { Fundamentals, Quote, Stock } from "../types";

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const code = searchParams.get("code") ?? "";

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Stock[]>([]);
  const [selected, setSelected] = useState<Stock | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [fundamentals, setFundamentals] = useState<Fundamentals | null>(null);

  const { bars, points, loading } = useStockCharts(code);

  async function handleSearch(value: string) {
    setQuery(value);
    if (value.trim().length === 0) {
      setResults([]);
      return;
    }
    try {
      setResults(await api.searchStocks(value.trim()));
    } catch {
      setResults([]);
    }
  }

  function selectStock(stock: Stock) {
    setResults([]);
    setQuery("");
    setSearchParams({ code: stock.code });
  }

  // code 來自網址（例如從自選股點股票名稱跳轉過來），只要 code 一變就重新載入該股票的所有資料。
  useEffect(() => {
    if (!code) {
      setSelected(null);
      setQuote(null);
      setFundamentals(null);
      return;
    }
    let cancelled = false;

    async function load() {
      try {
        const stocks = await api.searchStocks(code);
        const exact = stocks.find((s) => s.code === code) ?? null;
        if (!cancelled) setSelected(exact);
      } catch {
        if (!cancelled) setSelected(null);
      }
      try {
        const q = await api.getQuote(code);
        if (!cancelled) setQuote(q);
      } catch {
        if (!cancelled) setQuote(null);
      }
      try {
        const f = await api.getFundamentals(code);
        if (!cancelled) setFundamentals(f);
      } catch {
        if (!cancelled) setFundamentals(null);
      }
    }

    load();
    const timer = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [code]);

  return (
    <div className="search-page">
      <h2 className="section-title">搜尋股票</h2>

      <div className="panel">
        <input
          placeholder="搜尋股票代碼或名稱"
          value={query}
          onChange={(e) => handleSearch(e.target.value)}
          autoFocus
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
      </div>

      {!code ? (
        <div className="panel">
          <div className="empty-hint">搜尋股票代碼或名稱來查看走勢圖與基本面資料</div>
        </div>
      ) : (
        <div className="stock-block search-detail-block">
          <div className="stock-block-header">
            <span className="title">
              {code} {selected?.name ?? quote?.name ?? ""}
            </span>
            <span className="price">{quote?.price != null ? quote.price.toFixed(2) : "-"}</span>
          </div>
          <div className="stock-block-meta">
            <span>{selected?.market ?? ""}</span>
          </div>

          <div className="today-ohlc">
            <div>
              <span className="label">今日開盤</span>
              <span className="value">{quote?.open != null ? quote.open.toFixed(2) : "-"}</span>
            </div>
            <div>
              <span className="label">今日最高</span>
              <span className="value buy-text">{quote?.high != null ? quote.high.toFixed(2) : "-"}</span>
            </div>
            <div>
              <span className="label">今日最低</span>
              <span className="value sell-text">{quote?.low != null ? quote.low.toFixed(2) : "-"}</span>
            </div>
            <div>
              <span className="label">昨收</span>
              <span className="value">{quote?.prev_close != null ? quote.prev_close.toFixed(2) : "-"}</span>
            </div>
          </div>

          <ChartTabs
            bars={bars}
            points={points}
            loading={loading}
            size="large"
            stockCode={code}
            market={selected?.market}
          />

          <h3 className="tutorial-heading" style={{ marginTop: 24 }}>
            基本面
          </h3>
          {fundamentals ? (
            <div className="fundamentals-grid">
              <div>
                <span className="label">本益比 (PE)</span>
                <span className="value">{fundamentals.pe_ratio != null ? fundamentals.pe_ratio.toFixed(2) : "-"}</span>
              </div>
              <div>
                <span className="label">殖利率</span>
                <span className="value">
                  {fundamentals.dividend_yield != null ? `${fundamentals.dividend_yield.toFixed(2)}%` : "-"}
                </span>
              </div>
              <div>
                <span className="label">股價淨值比 (PB)</span>
                <span className="value">{fundamentals.pb_ratio != null ? fundamentals.pb_ratio.toFixed(2) : "-"}</span>
              </div>
            </div>
          ) : (
            <div className="empty-hint">暫無基本面資料</div>
          )}
        </div>
      )}
    </div>
  );
}
