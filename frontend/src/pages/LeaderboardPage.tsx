import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth/AuthContext";
import type { LeaderboardEntry } from "../types";

export default function LeaderboardPage() {
  const { nickname: myNickname } = useAuth();
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function refresh() {
      const res = await api.getLeaderboard();
      if (!cancelled) {
        setEntries(res);
        setLoading(false);
      }
    }

    refresh();
    const timer = setInterval(refresh, 15000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <>
      <h2 className="section-title">排行榜</h2>
      <div className="panel">
        {loading ? (
          <div className="empty-hint">載入中...</div>
        ) : entries.length === 0 ? (
          <div className="empty-hint">目前沒有可顯示的帳戶</div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>名次</th>
                  <th>暱稱</th>
                  <th>總資產</th>
                  <th>現金餘額</th>
                  <th>部位市值</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry, index) => (
                  <tr key={`${entry.nickname}-${index}`} className={entry.nickname === myNickname ? "leaderboard-me" : ""}>
                    <td>{index + 1}</td>
                    <td style={{ textAlign: "left" }}>{entry.nickname}</td>
                    <td>{entry.total_assets.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                    <td>{entry.cash_balance.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                    <td>{entry.market_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
