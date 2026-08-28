import { useState } from "react";
import { CandlestickDiagram } from "../components/CandlestickDiagram";
import { KDCrossDiagram } from "../components/KDCrossDiagram";

const TABS = [
  { key: "candlestick", label: "認識 K 線" },
  { key: "ma", label: "均線" },
  { key: "volume", label: "量價關係" },
  { key: "kd", label: "KD 指標" },
  { key: "fundamentals", label: "基本面怎麼看" },
  { key: "dividend", label: "除權息" },
  { key: "oddlot", label: "零股交易規則" },
  { key: "fees", label: "手續費與交易稅" },
  { key: "orders", label: "委託／成交回報" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function TutorialPage() {
  const [tab, setTab] = useState<TabKey>("candlestick");

  return (
    <div className="tutorial">
      <h2 className="section-title">股市教學</h2>

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

      {tab === "ma" && (
        <section className="panel tutorial-card">
          <h3 className="tutorial-heading">均線（移動平均線）</h3>
          <p>
            均線是把最近 N 天的收盤價取平均、連成一條線，用來把短期價格波動「磨平」，比較容易看出股價目前的<b>趨勢方向</b>。
          </p>

          <h4 className="tutorial-subheading">常見的均線天數</h4>
          <ul className="tutorial-list">
            <li><b>5 日線</b>（週線）：短期趨勢與短線持有者的平均成本。</li>
            <li><b>20 日線</b>（月線）：中期趨勢，常被當作短中期的支撐 / 壓力參考。</li>
            <li><b>60 日線</b>（季線）：中長期趨勢，也常被當作法人 / 中長線買盤的平均成本。</li>
            <li>更長天期還有半年線（120 日）、年線（240 日），用來看更長期的趨勢。</li>
          </ul>

          <div className="tutorial-grid">
            <div>
              <h4 className="tutorial-subheading buy-text">多頭排列</h4>
              <p>股價 &gt; 5 日線 &gt; 20 日線 &gt; 60 日線，且各條均線都朝上，代表多頭趨勢明確。</p>
            </div>
            <div>
              <h4 className="tutorial-subheading sell-text">空頭排列</h4>
              <p>順序完全相反、股價落在所有均線下方，且均線都朝下，代表空頭趨勢明確。</p>
            </div>
          </div>

          <h4 className="tutorial-subheading">均線糾結</h4>
          <p>
            當短、中、長天期均線纏繞在一起、糾結成一團時，代表多空力道相當、方向不明確，常常是變盤的前兆。糾結之後如果帶量突破，值得特別留意後續走勢。
          </p>

          <p className="tutorial-note">
            均線也常被當作「動態的支撐 / 壓力」：股價拉回接近均線容易出現買盤支撐，反彈到均線附近則容易遇到賣壓，但均線是落後指標（用過去的價格算出來的），不會預測未來，只能輔助判斷。
          </p>
        </section>
      )}

      {tab === "volume" && (
        <section className="panel tutorial-card">
          <h3 className="tutorial-heading">量價關係</h3>
          <p>
            成交量代表市場對這檔股票的參與熱度與資金認同度。常聽到的「量比價先行」，意思是成交量的變化，常常比股價本身更早反映出買賣力道的轉變。
          </p>

          <h4 className="tutorial-subheading">常見的量價判斷</h4>
          <ul className="tutorial-list">
            <li><b>價漲量增</b>：上漲有成交量支撐，追價意願強，趨勢通常比較健康、有力。</li>
            <li><b>價漲量縮</b>：股價上漲但量能萎縮，代表追高意願不足，漲勢可能後繼無力。</li>
            <li><b>價跌量增</b>：下跌且成交量放大，代表賣壓沉重，甚至出現恐慌性賣壓。</li>
            <li><b>價跌量縮</b>：下跌但量能萎縮，代表賣壓有限，股價可能接近止跌。</li>
          </ul>

          <h4 className="tutorial-subheading">爆量要特別注意</h4>
          <p>
            成交量明顯放大（例如是近期均量的好幾倍）時，通常代表有重要籌碼正在轉手，可能是趨勢轉折的訊號。但同樣的「爆量」出現在低檔和高檔，意義可能完全相反：低檔爆量常是「換手上攻」的起漲訊號，高檔爆量卻可能是主力「倒貨出場」的訊號，一定要搭配股價當時所在的相對位置一起判斷。
          </p>
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

      {tab === "dividend" && (
        <section className="panel tutorial-card">
          <h3 className="tutorial-heading">除權息是什麼？</h3>
          <p>
            公司賺錢之後，常常會把一部分獲利以股利的形式發還給股東。發放<b>現金股利</b>叫做「除息」，發放<b>股票股利</b>叫做「除權」，兩者都有的話就統稱「除權息」。
          </p>

          <h4 className="tutorial-subheading">為什麼股價會在除權息當天往下跳？</h4>
          <p>
            因為股利是從公司口袋掏出來發給股東的，公司帳上的淨值因此減少，股價要相應往下修正，才能反映公司價值的減少——這是制度上的正常調整，並不是股價無緣無故下跌。
          </p>
          <code className="tutorial-formula">除息參考價 ≈ 除息前一日收盤價 − 每股現金股利</code>
          <p style={{ marginTop: 10 }}>
            （除權的計算方式是依股票股利的比例去調整，公式較複雜，這裡先不展開；實務上很多公司是現金股利、股票股利一起發，會用更完整的公式一次算出參考價。）
          </p>

          <h4 className="tutorial-subheading">填權息 / 貼權息</h4>
          <ul className="tutorial-list">
            <li><b>填權 / 填息</b>：除權息之後，股價又漲回到除權息前的價位，代表市場願意用原本的價位認同這家公司。</li>
            <li><b>貼權 / 貼息</b>：除權息之後股價一直沒有漲回去，代表拿到的股利可能被股價的下跌抵銷掉了。</li>
          </ul>

          <p className="tutorial-note">
            這跟「基本面」提到的殖利率是同一件事的兩面：殖利率＝現金股利 ÷ 股價，是<b>發放前</b>的預期報酬率；除權息則是股利<b>實際發放</b>、股價相應調整的那個動作。領到股利不代表穩賺，如果之後貼息，等於是「左手換右手」。
          </p>
        </section>
      )}

      {tab === "oddlot" && (
        <section className="panel tutorial-card">
          <h3 className="tutorial-heading">零股交易規則</h3>
          <p>
            台股一張是 1,000 股，買賣不足一張（1～999 股）就叫做<b>零股</b>。本站模擬的正是零股交易，方便小資族用比較少的資金分批布局，或是分散投資高價股。
          </p>

          <h4 className="tutorial-subheading">交易時段</h4>
          <ul className="tutorial-list">
            <li>
              <b>盤中零股（09:00～13:30）</b>：跟整股同時段交易，採逐筆撮合（價格優先、時間優先），本站的撮合邏輯就是模擬這個時段。
            </li>
            <li>
              <b>盤後零股（13:40～14:30）</b>：用當天收盤價「定價交易」下單，不能自己喊價，14:30 過後才會一次撮合，本站沒有實作這個時段。
            </li>
          </ul>

          <h4 className="tutorial-subheading">零股價格跟整股一樣嗎？</h4>
          <p>
            零股跟整股是同一檔股票、同一套價格系統，理論上零股成交價會很接近同時段的整股成交價。但因為零股的買賣參與者相對少、流動性較低，實際成交價偶爾會跟整股有落差，尤其是冷門股或股價很高的股票（例如一張要好幾百萬的股票，整股買氣淡、零股反而更熱絡）。
          </p>

          <p className="tutorial-note">
            本站的撮合方式：後端會定時輪詢即時報價，只要報價「觸及」你掛單的限價，就視為成交，不保證一定買得到／賣得掉，也不會用整股的委託簿深度去精算——是簡化過的模擬，重點放在讓你熟悉零股下單、部位管理的流程。
          </p>
        </section>
      )}

      {tab === "fees" && (
        <section className="panel tutorial-card">
          <h3 className="tutorial-heading">手續費與交易稅怎麼算？</h3>
          <p>本站每一筆成交都會自動算好手續費、交易稅，直接反映在「成交回報」和「交易紀錄」的欄位裡。原理其實很單純：</p>

          <div className="tutorial-grid">
            <div>
              <h4 className="tutorial-subheading">手續費</h4>
              <p>買進、賣出<b>都要付</b>，費率上限是成交金額的 <b>0.1425%</b>（實務上券商常打折，例如打 6 折）。</p>
            </div>
            <div>
              <h4 className="tutorial-subheading">交易稅</h4>
              <p>只有<b>賣出</b>的時候要付，現股交易稅是成交金額的 <b>0.3%</b>。</p>
            </div>
          </div>

          <h4 className="tutorial-subheading">實際算一次給你看</h4>
          <p>假設用 100 元買進 10 股，之後用 105 元賣出這 10 股：</p>
          <ul className="tutorial-list">
            <li>買進金額 = 100 × 10 = 1,000 元，手續費 = 1,000 × 0.1425% ≈ <b>1 元</b></li>
            <li>賣出金額 = 105 × 10 = 1,050 元，手續費 ≈ <b>1 元</b>，交易稅 = 1,050 × 0.3% ≈ <b>3 元</b></li>
            <li>價差獲利 = (105 − 100) × 10 = 50 元，扣掉手續費 2 元、交易稅 3 元，實際淨賺 <b>45 元</b></li>
          </ul>

          <p className="tutorial-note">
            本站採用標準費率（0.1425%）、不打折、也沒有設最低手續費門檻，賣出另計 0.3% 交易稅。真實券商很多會有「零股最低手續費」（例如每筆最低 1 元）的規定，跟本站的計算方式可能會有些微差異，實際下單前還是要以你使用的券商公告為準。
          </p>
        </section>
      )}

      {tab === "orders" && (
        <section className="panel tutorial-card">
          <h3 className="tutorial-heading">委託回報／成交回報是什麼？</h3>
          <p>
            本站的下單只支援<b>限價單</b>：下單時要填「你願意成交的價格」跟股數，系統<b>不保證一定會成交</b>，要等實際報價觸及你的限價才會成交。「交易」頁把你的訂單依狀態分成兩個區塊：
          </p>

          <div className="tutorial-grid">
            <div>
              <h4 className="tutorial-subheading">委託回報</h4>
              <p>
                今天下的單裡<b>還沒成交</b>的部分，狀態顯示「待成交」。下單當下，買單會先凍結需要的資金、賣單會先凍結對應的庫存，但錢或股票都還沒真的動。
              </p>
            </div>
            <div>
              <h4 className="tutorial-subheading">成交回報</h4>
              <p>今天下的單裡<b>已經成交</b>的部分，可以看到實際成交價、成交時間。訂單成交後會自動從委託回報移到成交回報。</p>
            </div>
          </div>

          <h4 className="tutorial-subheading">委託單的生命週期</h4>
          <ul className="tutorial-list">
            <li><b>當日有效</b>：收盤（13:30）還沒成交的話，會自動失效，凍結的資金／庫存也會跟著解凍。</li>
            <li><b>可以手動取消</b>：成交前隨時可以在委託回報按「取消」，提前解凍資金／庫存。</li>
          </ul>

          <p className="tutorial-note">
            為什麼掛單不一定會成交：因為是限價單，如果市場價格一直沒有觸及你設定的限價，訂單就會一直停在委託回報，等到收盤才失效——這是刻意模擬真實市場「限價單不保證成交」的特性，而不是系統故障。
          </p>
        </section>
      )}
    </div>
  );
}
