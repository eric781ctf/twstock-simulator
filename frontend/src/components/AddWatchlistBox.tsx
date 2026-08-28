import { useState } from "react";
import { api } from "../api";
import type { Stock } from "../types";

interface Props {
  disabled: boolean;
  onAdded: () => void;
}

export function AddWatchlistBox({ disabled, onAdded }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Stock[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSearch(value: string) {
    setQuery(value);
    setError(null);
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

  async function handleAdd(stock: Stock) {
    setSubmitting(true);
    setError(null);
    try {
      await api.addToWatchlist(stock.code);
      setQuery("");
      setResults([]);
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "加入自選股失敗");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="panel">
      <h2>加入自選股</h2>
      {disabled ? (
        <div className="empty-hint">自選股清單已滿 20 檔，移除一些才能再新增</div>
      ) : (
        <>
          <input
            placeholder="搜尋股票代碼或名稱"
            value={query}
            onChange={(e) => handleSearch(e.target.value)}
            disabled={submitting}
          />
          {results.length > 0 && (
            <div className="search-results">
              {results.map((s) => (
                <div key={s.code} onClick={() => !submitting && handleAdd(s)}>
                  {s.code} {s.name} <span style={{ color: "var(--muted)" }}>({s.market})</span>
                </div>
              ))}
            </div>
          )}
          {error && <div className="error-msg">{error}</div>}
        </>
      )}
    </div>
  );
}
