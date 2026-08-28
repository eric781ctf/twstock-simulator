import { useState } from "react";
import { CandlestickDiagram } from "../components/CandlestickDiagram";
import { KDCrossDiagram } from "../components/KDCrossDiagram";

const TABS = [
  { key: "candlestick", label: "認識 K 線" },
  { key: "kd", label: "KD 指標" },
  { key: "fundamentals", label: "基本面怎麼看" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function TutorialPage() {
  const [tab, setTab] = useState<TabKey>("candlestick");

  return (
    <div className="tutorial">
      <h2 className="section-title">技術教學</h2>

      <div className="tutorial-tabs">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "candlestick" && (
        <section className="panel tutorial-card">
          <h3 className="tutorial-heading">認識 K 線</h3>
          <p>
            K 線（蠟燭圖）記錄了某段時間（例如一天）裡股價的四個關鍵價位：<b>開盤價、收盤價、最高價、最低價</b>。
            光看一根 K 線的顏色和形狀，就能大致看出這段時間多空力道的變化。
          </p>

          <div className="diagram-wrap">
            <CandlestickDiagram />
          </div>

          <div className="tutorial-grid">
            <div>
              <h4 className="tutorial-subheading buy-text">紅 K（紅棒）</h4>
              <p>收盤價 &gt; 開盤價，代表這段時間股價是上漲收尾的。</p>
            </div>
            <div>
              <h4 className="tutorial-subheading sell-text">黑 K（黑棒）</h4>
              <p>收盤價 &lt; 開盤價，代表這段時間股價是下跌收尾的。有些軟體會把黑 K 畫成綠色。</p>
            </div>
          </div>

          <h4 className="tutorial-subheading">一根 K 線的三個部分</h4>
          <ul className="tutorial-list">
            <li>
              <b>實體（body）</b>
              ：開盤價與收盤價之間的長方形區塊。實體越長，代表這段時間漲跌幅度越大、多空力道越明確；實體很短甚至變成一條線（十字線），代表多空拉鋸、方向不明確，常出現在轉折點附近。
            </li>
            <li>
              <b>上影線</b>：實體上方的細線，代表這段時間曾經衝到的最高價。上影線越長，代表上方賣壓越重、曾經被打下來。
            </li>
            <li>
              <b>下影線</b>：實體下方的細線，代表這段時間曾經跌到的最低價。下影線越長，代表下方買盤越強、有人在低點承接。
            </li>
          </ul>
        </section>
      )}

      {tab === "kd" && (
        <section className="panel tutorial-card">
          <h3 className="tutorial-heading">KD 指標（隨機指標）</h3>
          <p>
            KD 是最常用的技術指標之一，由 <b>K 值</b>與<b>D 值</b>兩條線組成，數值都介於 0～100
            之間，用來判斷股價目前偏「超買」還是「超賣」，本站每檔股票的日 K 線 tab 下方都有畫出這兩條線。
          </p>

          <h4 className="tutorial-subheading">怎麼算出來的？</h4>
          <ol className="tutorial-list">
            <li>
              先算 <b>RSV</b>：比較「今天收盤價」跟「最近 n 天（通常是 9 天）的最高價、最低價」的相對位置。
              <br />
              <code className="tutorial-formula">RSV = (今日收盤價 − n 日內最低價) ÷ (n 日內最高價 − n 日內最低價) × 100</code>
            </li>
            <li>
              <b>K 值</b> = 前一天的 K 值 × 2/3 + 今天的 RSV × 1/3 —— 反應比較快、比較敏感。
            </li>
            <li>
              <b>D 值</b> = 前一天的 D 值 × 2/3 + 今天的 K 值 × 1/3 —— 再平滑一次，所以 D 線比 K 線更平緩、變化較慢。
            </li>
          </ol>

          <div className="diagram-wrap">
            <KDCrossDiagram />
          </div>

          <div className="tutorial-grid">
            <div>
              <h4 className="tutorial-subheading buy-text">黃金交叉</h4>
              <p>K 值由下往上穿過 D 值。尤其發生在低檔（20 以下）時，常被視為偏多訊號、可能反彈。</p>
            </div>
            <div>
              <h4 className="tutorial-subheading sell-text">死亡交叉</h4>
              <p>K 值由上往下穿過 D 值。尤其發生在高檔（80 以上）時，常被視為偏空訊號、可能拉回。</p>
            </div>
          </div>

          <h4 className="tutorial-subheading">超買超賣區</h4>
          <ul className="tutorial-list">
            <li>K、D 值 &gt; 80：通常視為「超買」，漲多了，拉回機率增加。</li>
            <li>K、D 值 &lt; 20：通常視為「超賣」，跌多了，反彈機率增加。</li>
          </ul>

          <p className="tutorial-note">
            提醒：KD 是很敏感的短線指標，在盤整格局容易出現「假交叉」（鈍化），不建議只看 KD
            就進出場，通常會搭配 K 線型態、成交量，甚至基本面一起判斷。
          </p>
        </section>
      )}

      {tab === "fundamentals" && (
        <section className="panel tutorial-card">
          <h3 className="tutorial-heading">基本面怎麼看？</h3>
          <p>
            技術面（K 線、KD 這些）是看「價格和成交量畫出來的圖形」在找進出場<b>時機</b>
            ；基本面則是回頭看「這家公司到底賺不賺錢、值不值得長期持有」，兩者角度不同，常常互補使用。
          </p>

          <div className="table-scroll">
            <table className="compare-table">
              <thead>
                <tr>
                  <th></th>
                  <th>技術面</th>
                  <th>基本面</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td style={{ textAlign: "left" }}>看什麼</td>
                  <td>價格、成交量畫出來的圖形與指標（K 線、KD、均線…）</td>
                  <td>財報數字、產業與公司體質</td>
                </tr>
                <tr>
                  <td style={{ textAlign: "left" }}>用途</td>
                  <td>找買賣「時機」</td>
                  <td>判斷公司「值不值得買」</td>
                </tr>
                <tr>
                  <td style={{ textAlign: "left" }}>時間長度</td>
                  <td>通常較短線</td>
                  <td>通常較長線</td>
                </tr>
                <tr>
                  <td style={{ textAlign: "left" }}>代表工具</td>
                  <td>K 線、KD、均線、MACD…</td>
                  <td>EPS、ROE、本益比、殖利率…</td>
                </tr>
              </tbody>
            </table>
          </div>

          <p>
            一般會把下面這幾類資訊<b>整合在一起看</b>，才稱得上是完整的基本面分析——只看單一數字（例如只看本益比很低）很容易被誤導。
          </p>

          <h4 className="tutorial-subheading">獲利能力</h4>
          <ul className="tutorial-list">
            <li>
              <b>EPS（每股盈餘）</b>：公司幫每一股股票賺了多少錢，是最基本的獲利指標。
            </li>
            <li>
              <b>ROE（股東權益報酬率）</b>：用股東的錢賺錢的效率，長期穩定的高 ROE 通常代表體質好。
            </li>
            <li>
              <b>毛利率 / 營益率 / 淨利率</b>：分別看「產品本身賺不賺錢」「本業經營效率」「最終真正落袋的比例」。
            </li>
          </ul>

          <h4 className="tutorial-subheading">評價指標（股價貴不貴）</h4>
          <ul className="tutorial-list">
            <li>
              <b>本益比（PE）</b>：股價 ÷ EPS，數字越高代表市場願意付出越多倍數買這家公司的獲利。
            </li>
            <li>
              <b>股價淨值比（PB）</b>：股價 ÷ 每股淨值，常用來評估銀行股、資產型公司。
            </li>
            <li>
              <b>殖利率</b>：現金股利 ÷ 股價，越高代表相對股價能拿到的配息報酬率越高。
            </li>
          </ul>

          <h4 className="tutorial-subheading">營運趨勢</h4>
          <ul className="tutorial-list">
            <li>
              月營收<b>年增率（YoY）</b>、<b>月增率（MoM）</b>：公司生意是在成長還是衰退。
            </li>
            <li>財報季的季增 / 年增比較：確認獲利趨勢是不是持續的，而不是單一季的曇花一現。</li>
          </ul>

          <h4 className="tutorial-subheading">體質與風險</h4>
          <ul className="tutorial-list">
            <li>
              <b>負債比、流動比率</b>：公司財務結構穩不穩、短期還債能力夠不夠。
            </li>
            <li>
              <b>現金流量表</b>：帳上的獲利有沒有真的變成現金，而不是紙上富貴。
            </li>
          </ul>

          <h4 className="tutorial-subheading">質化因素</h4>
          <ul className="tutorial-list">
            <li>產業地位與競爭優勢（護城河）</li>
            <li>產業趨勢與景氣循環位置</li>
            <li>經營團隊與公司治理</li>
          </ul>

          <p className="tutorial-note">
            把「這家公司賺多少錢（獲利能力）」+「現在股價貴不貴（評價指標）」+「生意是變好還變差（營運趨勢）」+「體質穩不穩（財務結構）」+「產業與經營團隊好不好（質化因素）」這幾塊資訊放在一起交叉比對，才是完整的基本面分析。
          </p>
        </section>
      )}
    </div>
  );
}
