import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ScoreFormulaExplainer } from "../components/ScoreFormulaExplainer";
import type { ModelCatalog, ModelType, ModelTypeOption } from "../types";

/**
 * 模型教學。兩個子頁：
 *
 * 1. 系統怎麼運作——這個系統的業務邏輯（選股分數、出場規則、損益率怎麼算）
 * 2. 可訓練的模型——每個模型類型的理論介紹，先選種類再選模型
 *
 * 模型清單、分數公式、費率、每天持有幾檔全部來自後端的 /models/catalog，
 * 前端不自己維護一份。之後後端加了新的模型類型，這一頁會自動列出來——
 * 就算還沒寫理論介紹，也會明說「還沒有說明」，而不是假裝那個類型不存在。
 */

type SubTab = "business" | "models";

/** 模型家族：把後端的模型類型分組，下拉選單第一層用的 */
interface Family {
  key: string;
  label: string;
  summary: string;
  types: ModelType[];
}

// 名稱一律只寫英文，跟後端的模型名稱一致。這些演算法類別的通用名稱就是英文，
// 中文譯名各家不一（ensemble 就有「集成」「整體」等好幾種講法），寫了反而更亂
const FAMILIES: Family[] = [
  {
    key: "tree",
    label: "Tree Ensembles",
    summary: "很多棵決策樹投票／相加。表格式資料上長年的實務首選。",
    types: ["xgboost", "lightgbm", "random_forest"],
  },
  {
    key: "linear",
    label: "Linear Models",
    summary: "把每個特徵乘上一個係數再加起來。最單純、也最容易解釋。",
    types: ["logistic_regression"],
  },
  {
    key: "feedforward",
    label: "Feedforward Neural Network",
    summary: "多層非線性轉換，能學到特徵之間的交互作用。需要 GPU。",
    types: ["mlp"],
  },
  {
    key: "recurrent",
    label: "Recurrent Neural Network",
    summary: "吃「一段連續期間」而不是「某一天」，由網路自己看時間上的變化。需要 GPU。",
    types: ["gru", "lstm"],
  },
];

interface ModelArticle {
  tagline: string;
  /** 這個演算法本身怎麼運作（理論） */
  theory: string[];
  strengths: string[];
  limitations: string[];
  /** 在這個系統裡實際怎麼被使用 */
  inThisSystem: string;
  /** 特徵重要性那張圖對這個模型代表什麼 */
  importanceMeaning: string;
}

const ARTICLES: Partial<Record<ModelType, ModelArticle>> = {
  xgboost: {
    tagline: "梯度提升樹的代表作，Kaggle 表格式競賽長年的主力。",
    theory: [
      "「提升（boosting）」的核心是：先種一棵很淺的樹做出粗糙的預測，算出它錯在哪裡（殘差），再種第二棵樹專門去補第一棵的錯，如此反覆數百次。最終預測是所有樹的輸出相加。",
      "每棵樹的每一次分裂都在問「用哪個特徵、切在哪個值，能讓誤差下降最多」。XGBoost 用的是二階近似（同時看一階與二階導數）來估算這個下降量，比只看一階梯度更準，收斂也更快。",
      "它在目標函數裡直接放進了正則化項（樹的葉子數、葉子權重的大小），所以「樹要長多複雜」是被最佳化過程本身壓制的，不是只靠外部限制深度。",
    ],
    strengths: [
      "不需要特徵標準化，也不怕特徵之間量級差很多。",
      "能自動抓到非線性關係與特徵交互作用，不用人工造交叉項。",
      "對缺失值有內建的處理方式（學習「缺值時往哪一邊走」）。",
    ],
    limitations: [
      "樹是用「切一刀」的方式逼近，對平滑的線性關係反而不如線性模型俐落。",
      "樹的數量一多就很容易把訓練資料背起來，必須靠驗證集盯著。",
      "看不到「時間順序」——每一列樣本對它來說是獨立的，昨天跟今天沒有先後關係。",
    ],
    inThisSystem:
      "迴歸頭用 XGBRegressor、分類頭用 XGBClassifier，兩個各自獨立訓練、吃同一份特徵矩陣。注意這裡的「共用」只是共用特徵，不是共用權重——樹模型沒有可以共享的隱藏層。",
    importanceMeaning:
      "詳情頁的特徵重要性是 feature_importances_，代表這個特徵在所有樹的分裂中平均貢獻了多少誤差下降。一律是正值，看不出影響方向（漲還是跌）。",
  },
  lightgbm: {
    tagline: "跟 XGBoost 同屬梯度提升樹，但長樹的順序不一樣，通常更快。",
    theory: [
      "跟 XGBoost 一樣是一棵接一棵地補前面的錯，差別在「怎麼長一棵樹」。XGBoost 是逐層（level-wise）生長：同一層的節點一起展開，樹會長得對稱。",
      "LightGBM 是逐葉（leaf-wise）生長：每次只挑「展開後誤差能降最多」的那一片葉子去分裂。同樣的葉子數下通常誤差更低，但樹會長得歪斜、也更容易過擬合，所以要靠葉子數上限來收。",
      "它另外用直方圖把連續特徵先分箱（例如切成 255 個桶），找分裂點時只要掃過桶而不是每一個原始值，這是它在大資料上明顯比較快的主因。",
    ],
    strengths: [
      "在樣本數多的時候訓練速度明顯快過 XGBoost，記憶體也吃得少。",
      "同樣的葉子數下通常能達到更低的誤差。",
    ],
    limitations: [
      "逐葉生長讓它在小資料上特別容易過擬合。",
      "分箱是一種有損壓縮，特徵的極細微差異會被抹掉。",
      "跟所有樹模型一樣，看不到時間順序。",
    ],
    inThisSystem: "迴歸頭 LGBMRegressor、分類頭 LGBMClassifier，同樣是兩個獨立模型吃同一份特徵。",
    importanceMeaning: "同 XGBoost，是分裂貢獻度，一律非負、看不出方向。",
  },
  random_forest: {
    tagline: "很多棵各自獨立的深樹取平均。原理最直觀，也最不容易調壞。",
    theory: [
      "跟提升樹相反：隨機森林的每棵樹是「各自獨立」長的，彼此不知道對方犯了什麼錯，最後把所有樹的預測平均（迴歸）或投票（分類）。",
      "關鍵在製造差異。每棵樹只看隨機抽出的一部分樣本（bootstrap），每次分裂也只考慮隨機抽出的一部分特徵。這讓每棵樹都有點不一樣、犯的錯也不一樣，平均之後隨機誤差互相抵銷。",
      "單獨一棵深樹幾乎必定過擬合，但只要每棵樹的錯誤方向夠不相關，平均起來的變異數就會大幅下降——這是它有效的整個理由。",
    ],
    strengths: [
      "參數少、預設值就很能打，很難調壞。",
      "樹之間彼此獨立，可以完全平行訓練。",
      "對離群值相對不敏感。",
    ],
    limitations: [
      "整體效果通常略遜於調好的梯度提升樹。",
      "模型檔案大、預測時要跑過所有樹，比較慢。",
      "取平均會讓它不太敢預測極端值——而選股最在意的往往正是極端的那幾檔。",
    ],
    inThisSystem: "RandomForestRegressor + RandomForestClassifier，同樣是兩個獨立模型。",
    importanceMeaning: "分裂貢獻度，非負、無方向。",
  },
  logistic_regression: {
    tagline: "最單純的基準線。跑得快、看得懂，而且是唯一能看出「影響方向」的。",
    theory: [
      "線性模型假設「答案 = 每個特徵乘上一個係數再加總」。迴歸頭用普通線性回歸直接輸出報酬率；分類頭用邏輯迴歸，先算出同樣的加權總和，再用 sigmoid 把它壓到 0~1 當作機率。",
      "訓練就是在找那組讓誤差最小的係數。因為關係被限制成線性，模型能表達的形狀非常有限——但也因此不太可能把雜訊背起來。",
      "係數大小會直接受特徵量級影響，所以標準化在這裡不是可選項而是必要條件（本系統對所有模型一律標準化）。",
    ],
    strengths: [
      "係數本身就是可解釋的權重，正負號直接說明方向。",
      "訓練與推論都極快，資料少的時候反而比複雜模型穩。",
      "最適合當基準線——複雜模型贏不過它，就代表複雜度沒換到東西。",
    ],
    limitations: [
      "只能表達線性關係，抓不到「量增配合價漲才有意義」這種交互作用。",
      "對離群值敏感。",
      "同樣看不到時間順序。",
    ],
    inThisSystem: "迴歸頭是 LinearRegression、分類頭是 LogisticRegression（邏輯迴歸本身只能做分類，所以迴歸那邊配一個普通線性回歸）。",
    importanceMeaning:
      "這是唯一在特徵重要性圖上會出現負值的類型：長條往左代表這個特徵越大、預測值越低。其他類型的重要性一律非負。",
  },
  mlp: {
    tagline: "第一個真正共享 encoder 的類型：兩個任務共用同一組隱藏層。",
    theory: [
      "MLP 是 Multilayer Perceptron（多層感知器）的縮寫。它把輸入特徵經過數層「線性轉換 + 非線性啟用函數」的堆疊。每一層都在把資料投影到一個新的空間，讓原本糾纏在一起的樣本逐漸變得可分。",
      "非線性啟用函數（ReLU、Tanh、GELU）是關鍵：少了它，疊再多層線性轉換的結果仍然只是一個線性轉換，等於白疊。",
      "訓練用反向傳播——先算出預測跟答案的誤差，再依鏈鎖律把「每個權重該調多少」一路往回推，然後用 Adam 這類最佳化器更新。Dropout 在訓練時隨機關掉一部分神經元，強迫網路不能只依賴少數幾條路徑。",
      "這裡的雙任務是真的共享：同一組隱藏層之後接兩個輸出頭，兩個任務的梯度會一起更新那組共享層。這跟樹模型「訓練兩個獨立模型」有本質差別。",
    ],
    strengths: [
      "能自動學到特徵之間的高階交互作用。",
      "共享 encoder 讓兩個任務互相當對方的正則化——分類任務學到的東西會幫助迴歸任務，反之亦然。",
      "在 GPU 上訓練，樣本數再多也還算快。",
    ],
    limitations: [
      "在表格式資料上，通常打不贏調好的梯度提升樹——這是實務上一再被驗證的結果。",
      "需要標準化、需要調的參數多（層數、寬度、學習率、dropout、epochs）。",
      "極容易過擬合，一定要盯著驗證 loss 曲線。",
      "還是看不到時間順序：一列樣本就是某一天的快照。",
    ],
    inThisSystem: "訓練一律使用 GPU，沒有可用的 GPU 會直接讓訓練失敗，不會靜默退回 CPU。詳情頁會顯示完整的逐層結構與訓練過程的 loss 曲線。",
    importanceMeaning:
      "神經網路沒有內建的特徵重要性。詳情頁用的是第一層權重的絕對值平均，只能粗略看出「這個特徵在第一層被用得多重」。因為兩個頭共用隱藏層，這份指標對兩個任務是同一份，無法拆開。",
  },
  gru: {
    tagline: "吃「連續 N 天」而不是「某一天」。用閘控機制決定要記住還是忘掉。",
    theory: [
      "GRU 是 Gated Recurrent Unit（閘控循環單元）的縮寫。循環神經網路依序讀入序列裡的每一個時間步，並維持一個「隱藏狀態」把先前看過的東西濃縮起來帶著走。讀完整段之後，最後一個時間步的狀態就是對這段歷史的總結。",
      "最原始的 RNN 有梯度消失問題：誤差往回傳好幾十步之後會衰減到幾乎為零，等於學不到比較久以前的影響。GRU 用兩個閘來解決：更新閘決定「這一步要保留多少舊狀態、吸收多少新資訊」，重置閘決定「算新候選狀態時要參考多少舊狀態」。",
      "閘的值是網路自己學出來的（0~1 之間），所以它可以學會「這段期間沒什麼事，狀態原封不動帶過去」，梯度也就能沿著這條路徑順利回傳。",
      "跟前面所有類型最大的差別：它不需要我們預先算好「5日乖離率」「20日累積漲跌幅」這種彙總特徵，理論上能自己從原始序列裡看出變化的形狀。",
    ],
    strengths: [
      "唯一能看到時間順序的類型——同樣的今日特徵，前面是連跌五天還是連漲五天，對它是不同的輸入。",
      "比 LSTM 少一個閘、參數更少，訓練較快，小資料上通常更不容易過擬合。",
    ],
    limitations: [
      "訓練樣本的資訊量沒有變多，但參數變多了，過擬合風險比 MLP 更高。",
      "前面歷史不足 N 天的股票（剛上市、或本地日K還沒回補到那麼早）當天完全無法評分，會被排除在選股候選之外。",
      "序列長度拉長，記憶體與訓練時間都跟著線性增加。",
      "必須依序處理時間步，沒辦法像 Transformer 那樣整段平行計算。",
    ],
    inThisSystem:
      "一個樣本是「這一天之前連續 N 個交易日」的特徵視窗（N 由 admin 設定，預設 20）。網路讀完整段後取最後一個時間步的狀態，接到兩個輸出頭。詳情頁的結構表因此會多一個時間維度，寫成 (None、時間步、特徵數)。",
    importanceMeaning:
      "用第一個 GRU 層「吃輸入特徵」那組權重（weight_ih_l0）的絕對值平均。GRU 把多個閘的權重疊在同一個矩陣裡，這裡直接整體取平均，只看得出哪個輸入特徵被用得重，看不出是被哪個閘用到。",
  },
  lstm: {
    tagline: "循環神經網路裡最經典的一支。比 GRU 多一個閘與一條獨立的記憶線。",
    theory: [
      "LSTM 是 Long Short-Term Memory（長短期記憶）的縮寫。它比 GRU 多維護一條東西：除了隱藏狀態，還有一條獨立的「細胞狀態」，可以想成一條專門用來長期攜帶資訊的輸送帶。",
      "三個閘各司其職：遺忘閘決定細胞狀態裡哪些舊資訊該丟掉，輸入閘決定這一步有哪些新資訊值得寫進去，輸出閘決定細胞狀態裡有多少要洩漏成這一步的隱藏狀態輸出。",
      "細胞狀態的更新主要是「乘上遺忘閘再加上新資訊」這種加法形式，梯度沿著它回傳時不會反覆被權重矩陣連乘，這正是它能記住比較長期依賴的原因。",
    ],
    strengths: [
      "獨立的記憶線讓它在需要記住較長期資訊時，理論上比 GRU 更有本錢。",
      "同樣能看到時間順序。",
    ],
    limitations: [
      "參數比 GRU 多約三分之一，訓練更慢、也更容易過擬合。",
      "在中短序列上，實務結果通常跟 GRU 差不多，多出來的複雜度未必換得到東西。",
      "其餘限制與 GRU 相同（歷史不足的股票無法評分、記憶體隨序列長度增加）。",
    ],
    inThisSystem: "跟 GRU 完全同一條資料管線，只是把循環層換成 LSTM。同樣需要 GPU。",
    importanceMeaning: "同 GRU，取第一層 weight_ih_l0 的絕對值平均。LSTM 是四個閘疊在一起。",
  },
};

export default function ModelTutorialPage() {
  const [subTab, setSubTab] = useState<SubTab>("business");
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [error, setError] = useState("");
  const [familyKey, setFamilyKey] = useState(FAMILIES[0].key);
  const [modelType, setModelType] = useState<ModelType>("xgboost");

  useEffect(() => {
    api
      .getModelCatalog()
      .then(setCatalog)
      .catch((e) => setError(e instanceof Error ? e.message : "載入失敗"));
  }, []);

  useEffect(() => {
    if (!catalog || window.location.hash !== "#score-formula") return;
    // 這一段在「系統怎麼運作」子頁底下，先切過去才捲得到
    setSubTab("business");
    // 等這次 render 把該區塊放進 DOM 再捲
    requestAnimationFrame(() => {
      document.getElementById("score-formula")?.scrollIntoView({ block: "start", behavior: "smooth" });
    });
  }, [catalog]);

  /** 依後端實際回報的類型分組。後端有、但這裡沒歸類的，統一落到「其他」 */
  const groups = useMemo(() => {
    if (!catalog) return [];
    const byKey = new Map(catalog.model_types.map((t) => [t.key, t]));
    const claimed = new Set<string>();

    const known = FAMILIES.map((family) => {
      const options = family.types
        .map((key) => byKey.get(key))
        .filter((t): t is ModelTypeOption => Boolean(t));
      options.forEach((t) => claimed.add(t.key));
      return { ...family, options };
    }).filter((g) => g.options.length > 0);

    const rest = catalog.model_types.filter((t) => !claimed.has(t.key));
    if (rest.length > 0) {
      known.push({
        key: "other",
        label: "Other",
        summary: "後端新增、但這一頁還沒補上分類的模型類型。",
        types: [],
        options: rest,
      });
    }
    return known;
  }, [catalog]);

  const activeGroup = groups.find((g) => g.key === familyKey) ?? groups[0];
  const activeOption = activeGroup?.options.find((o) => o.key === modelType) ?? activeGroup?.options[0];
  const article = activeOption ? ARTICLES[activeOption.key] : undefined;

  function handleFamilyChange(key: string) {
    setFamilyKey(key);
    const group = groups.find((g) => g.key === key);
    // 切換種類時把第二層自動帶到該種類的第一個，不然會停在一個不屬於這一類的模型
    if (group?.options[0]) setModelType(group.options[0].key);
  }

  return (
    <div className="tutorial">
      <h2 className="section-title">模型教學</h2>

      <div className="tutorial-tabs">
        <button className={subTab === "business" ? "active" : ""} onClick={() => setSubTab("business")}>
          系統怎麼運作
        </button>
        <button className={subTab === "models" ? "active" : ""} onClick={() => setSubTab("models")}>
          可訓練的模型
        </button>
      </div>

      {error && <div className="panel model-notice">{error}</div>}
      {!catalog && !error && <div className="panel">載入中…</div>}

      {catalog && subTab === "business" && <BusinessSection catalog={catalog} />}

      {catalog && subTab === "models" && (
        <>
          <section className="panel tutorial-card">
            <h3 className="tutorial-heading">選一個模型來看</h3>
            <p>先選種類，再選該種類底下的模型。這份清單直接來自後端，跟訓練表單上可選的完全一致。</p>
            <div className="strategy-form-grid">
              <label>
                模型種類
                <select value={activeGroup?.key ?? ""} onChange={(e) => handleFamilyChange(e.target.value)}>
                  {groups.map((g) => (
                    <option key={g.key} value={g.key}>
                      {g.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                模型
                <select value={activeOption?.key ?? ""} onChange={(e) => setModelType(e.target.value as ModelType)}>
                  {activeGroup?.options.map((o) => (
                    <option key={o.key} value={o.key}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {activeGroup && <p className="order-hint">{activeGroup.summary}</p>}
          </section>

          {activeOption && <ModelArticleCard option={activeOption} article={article} />}
        </>
      )}
    </div>
  );
}

function ModelArticleCard({ option, article }: { option: ModelTypeOption; article?: ModelArticle }) {
  if (!article) {
    return (
      <section className="panel tutorial-card">
        <h3 className="tutorial-heading">{option.label}</h3>
        <p className="order-hint">這個模型類型還沒有寫理論介紹。它可以正常訓練，只是這一頁還沒補上說明。</p>
      </section>
    );
  }

  return (
    <section className="panel tutorial-card">
      <h3 className="tutorial-heading">{option.label}</h3>
      <p>
        <b>{article.tagline}</b>
      </p>

      <div className="model-badges">
        {option.is_neural && <span className="model-badge">需要 GPU</span>}
        {option.is_sequence ? (
          <span className="model-badge">吃連續 N 天的序列</span>
        ) : (
          <span className="model-badge">吃單日特徵</span>
        )}
        {option.is_neural && <span className="model-badge">真正共享 encoder</span>}
      </div>

      <h4 className="tutorial-subheading">它是怎麼運作的</h4>
      {article.theory.map((paragraph, i) => (
        <p key={i}>{paragraph}</p>
      ))}

      <div className="tutorial-grid">
        <div>
          <h4 className="tutorial-subheading buy-text">強項</h4>
          <ul className="tutorial-list">
            {article.strengths.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="tutorial-subheading sell-text">限制</h4>
          <ul className="tutorial-list">
            {article.limitations.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      </div>

      <h4 className="tutorial-subheading">在這個系統裡</h4>
      <p>{article.inThisSystem}</p>

      <h4 className="tutorial-subheading">特徵重要性圖對它代表什麼</h4>
      <p>{article.importanceMeaning}</p>
    </section>
  );
}

function BusinessSection({ catalog }: { catalog: ModelCatalog }) {
  const commission = (catalog.commission_rate * 100).toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  const tax = (catalog.tax_rate * 100).toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  const roundTrip = ((catalog.commission_rate * 2 + catalog.tax_rate) * 100).toFixed(4).replace(/0+$/, "");

  return (
    <>
      <section className="panel tutorial-card">
        <h3 className="tutorial-heading">這個系統每天在做什麼</h3>
        <p>
          這不是一個「人下單」的系統，是一個「模型自己選股、自己記錄成績」的系統。每個訓練完成且未封存的模型版本，
          在每個交易日收盤後各自跑一次以下流程：
        </p>
        <ol className="tutorial-list">
          <li>用當天收盤的全市場資料，替每一檔上市股票算出一組特徵（技術指標 + 估值）。</li>
          <li>把特徵餵給模型，同時得到「預期報酬率」與「達標機率」兩個輸出。</li>
          <li>把兩個輸出合成一個分數，取分數最高的前 {catalog.top_n} 名標記為持有。</li>
          <li>對手上已經持有的部位，依出場規則判斷要不要賣出。</li>
        </ol>
        <p className="order-hint">
          刻意不做即時或當沖：只用收盤資料、一天跑一次。訓練時看到的特徵跟上線後看到的特徵因此完全同源，
          不會有「訓練用日K、上線用即時報價」造成的分布落差。
        </p>
      </section>

      <section className="panel tutorial-card">
        <h3 className="tutorial-heading">為什麼要同時預測兩件事</h3>
        <p>每個模型都是「雙任務」的，同一組特徵同時餵給兩個輸出：</p>
        <div className="tutorial-grid">
          <div>
            <h4 className="tutorial-subheading">迴歸頭：未來 N 天報酬率</h4>
            <p>回答「大概會漲多少」。問題是它對極端值很敏感，少數幾檔暴漲暴跌的股票就能把預測值整個帶偏。</p>
          </div>
          <div>
            <h4 className="tutorial-subheading">分類頭：報酬超過門檻的機率</h4>
            <p>回答「有多大把握會漲超過門檻」。它對極端值穩健得多，但完全不區分「剛好達標」與「大漲」。</p>
          </div>
        </div>
        <p>
          兩個各有各的盲點，所以兩個都算、再合成一個分數。這也是多任務學習的一個附帶好處：對神經網路來說，
          兩個任務共用同一組隱藏層，等於互相當對方的正則化。
        </p>
      </section>

      <section className="panel tutorial-card" id="score-formula">
        <h3 className="tutorial-heading">選股分數怎麼算</h3>
        <ScoreFormulaExplainer info={catalog.score_formula} />
      </section>

      <section className="panel tutorial-card">
        <h3 className="tutorial-heading">什麼時候賣出</h3>
        <p>出場規則分四層，依序判斷，先觸發的先生效：</p>
        <ol className="tutorial-list">
          <li>
            <b>最長持有天數</b>：到了就無條件賣出。避免部位無限期卡住。
          </li>
          <li>
            <b>停損 / 停利</b>：損益率碰到設定的百分比就出場。
          </li>
          <li>
            <b>最少持有天數</b>：還沒滿的話，下面那一層不會被檢查——避免訊號一抖動就被洗出場。
          </li>
          <li>
            <b>規則條件</b>：例如 KD 死亡交叉、跌破均線這類技術面條件。
          </li>
        </ol>
        <p className="order-hint">
          回測跟正式上線呼叫的是同一份出場判斷程式碼。這是刻意的——不然「回測時的行為」跟「上線後的行為」
          很容易在後續改動中悄悄分岔，而那種分岔通常要等到實際虧錢才會被發現。
        </p>
      </section>

      <section className="panel tutorial-card">
        <h3 className="tutorial-heading">損益率怎麼算</h3>
        <p>
          這個系統<b>不追蹤金額也不追蹤股數</b>，只記錄每一筆持有的淨損益率百分比。因為模型的好壞跟「投入多少錢」
          無關，而假的虛擬資金只會讓人誤以為那是真實績效。
        </p>
        <div className="formula-box">
          <div className="formula-main">淨損益率 = ( 賣出價 × (1 − {commission}% − {tax}%) − 買進價 × (1 + {commission}%) ) ÷ 買進價 × (1 + {commission}%)</div>
          <div className="formula-def">
            手續費 {commission}%（買賣各收一次）、證券交易稅 {tax}%（只在賣出時收）
          </div>
        </div>
        <p>
          所以一買一賣的固定成本約 <b>{roundTrip}%</b>——這代表一筆完全沒有價差的交易，帳面上就會是負的。
          頁面上剛開倉、還沒有價格變動的部位顯示 −{roundTrip}% 就是這個原因，不是計算錯誤。
        </p>
      </section>

      <section className="panel tutorial-card">
        <h3 className="tutorial-heading">資料怎麼切分</h3>
        <p>訓練 / 驗證 / 測試三段一律<b>依時間先後切</b>，絕不隨機切。</p>
        <ul className="tutorial-list">
          <li>
            股價資料有時序性。隨機切分會讓訓練集裡混進比測試集更晚的日期，模型等於間接看到了未來，
            回測成績會漂亮得不真實。
          </li>
          <li>
            標準化用的平均數與標準差<b>只用訓練集計算</b>，再套用到驗證與測試。用全部資料算的話，
            測試集的分布資訊就洩漏到訓練階段了。
          </li>
          <li>
            label 是「未來 N 天的報酬率」，所以資料尾端那 N 天沒有答案可以對，一律排除，不拿沒成熟的 label 訓練。
          </li>
          <li>
            特徵一律只用「當天及之前」的資料計算。估值快照是月頻的稀疏資料，取用時往前找「最後一筆日期不晚於特徵日」的那一筆，
            不會不小心對到之後才發布的數字。
          </li>
        </ul>
      </section>

      <section className="panel tutorial-card">
        <h3 className="tutorial-heading">特徵怎麼處理</h3>
        <p>
          選股跟預測股價是兩件事。選股要回答的是「<b>今天這 1300 檔裡，哪幾檔相對強</b>」——
          所以特徵處理的重點不是把數字弄準，而是讓同一天的股票之間可以公平比較。
          下面三項都是同一天的橫斷面運算，不看未來，所以在資料切分之前就先做。
        </p>
        <div className="tutorial-grid">
          <div>
            <h4 className="tutorial-subheading">橫斷面排名</h4>
            <p>
              把每個特徵換成「當天在全市場的分位數」（0~1）。z-score 用的是整個訓練期的平均與標準差，
              等於拿去年的數值直接跟今年比；市場整體波動變大的時期，所有股票的特徵會一起偏移。
              排名只比當天，而那正是選股要的，極端值也自動被壓進 0~1，不用另外處理。
            </p>
          </div>
          <div>
            <h4 className="tutorial-subheading">產業中性化</h4>
            <p>
              把每個特徵減掉<b>當天、同產業</b>的中位數。「電子股今天全漲」不該被當成個股的本事——
              減掉同業之後，剩下的才是這檔相對同業的強弱。用中位數而不是平均數，因為產業內常有一兩檔
              漲停或剛除權的極端值會把平均數拉走。當天不到 3 檔的產業會併成一組，
              否則一檔自己一組時減掉自己的中位數恆等於 0，那一列的特徵就被抹掉了。
            </p>
          </div>
          <div>
            <h4 className="tutorial-subheading">產業別（類別特徵）</h4>
            <p>
              跟中性化相反的做法：不減掉產業成分，而是把產業別攤成 0/1 欄位<b>交給模型自己決定要不要用</b>。
              用 one-hot 而不是把產業代碼當整數，因為代碼是名目尺度——「24 半導體」跟「25 電腦週邊」
              相鄰不代表它們比「01 水泥」接近。沒有產業別的 ETF 與受益證券自成一欄，
              「不屬於任何已知產業」本身就是一個類別。
            </p>
          </div>
          <div>
            <h4 className="tutorial-subheading">超額報酬 label</h4>
            <p>
              預測目標可以選「絕對報酬」或「超額報酬」。後者把個股報酬減掉同期間的大盤報酬，
              問的是「這檔會不會贏過大盤」而不是「會不會漲」。大盤走多頭的期間，
              絕對報酬會讓模型學到「什麼時候市場在漲」——那不是選股能力。
            </p>
          </div>
        </div>
        <p className="tutorial-note">
          <b>實測結果：產業中性化是有害的。</b>同一套設定下六折滾動驗證的測試 Rank IC 從 +0.065 掉到 +0.039，
          而且<b>訓練分數也一起掉</b>（0.288 → 0.253）——如果只是過擬合，訓練分數會維持或上升；
          兩邊一起掉代表它移除的是真訊號。合理的解讀是台股的產業輪動本身就帶有可預測性，
          強制減掉同業等於把那一層丟掉。改成把產業別當類別特徵餵進去，平均值有回升（+0.072）
          但標準差翻倍、六折裡只贏四折，差異小到跟雜訊分不開。<b>兩種做法目前都預設關閉。</b>
        </p>
        <p className="tutorial-note">
          <b>大盤特徵與產業 0/1 欄不做排名與中性化。</b>市場漲跌幅、市場寬度這類特徵在同一天對所有股票是同一個值，
          做橫斷面排名會讓全部股票拿到同一個名次、減掉中位數會讓整欄變成 0，等於把那個特徵消滅。
          實測沒排除時測試 Rank IC 從 +0.053 掉到 +0.023。
        </p>
      </section>

      <section className="panel tutorial-card">
        <h3 className="tutorial-heading">為什麼要滾動驗證</h3>
        <p>
          只切一次「訓練／驗證／測試」，量到的很可能是那一段測試期剛好是什麼行情，而不是模型的能力。
          <b>滾動驗證（walk-forward）</b>把整段歷史切成好幾折，每一折都往後推移固定的月數，
          各自訓練、各自在自己的測試期評分，最後看的是<b>平均值與標準差</b>。
        </p>
        <ul className="tutorial-list">
          <li>
            單次切分曾經在同一套設定下量到 −0.035、−0.038、−0.076 這種數字，換成六折滾動之後
            平均是 +0.053、六折全為正——差別不在模型，在於前者量的是雜訊。
          </li>
          <li>
            <b>幾折全為正</b>比平均值本身更值得看。平均值高但只有三折為正，代表某一折特別好而已。
          </li>
          <li>
            折與折之間的訓練期高度重疊，所以這仍然<b>不等於</b>六次獨立的驗證，不能拿標準差直接當信賴區間。
          </li>
          <li>
            每一折的標準化參數各自從自己的訓練段計算，不會共用——共用的話後面折次的訓練段就看到了前面折次的測試分布。
          </li>
        </ul>
      </section>

      <section className="panel tutorial-card">
        <h3 className="tutorial-heading">模型詳情頁的數字怎麼讀</h3>
        <div className="tutorial-grid">
          <div>
            <h4 className="tutorial-subheading">Rank IC</h4>
            <p>
              預測值與實際報酬的等級相關係數。<b>這是這個系統最該看的指標</b>——選股實際上只在乎排序對不對，
              不在乎預測值本身準不準。0 代表跟隨機排序差不多；業界的多因子訊號能長期穩定在 0.03~0.05 就算堪用。
            </p>
          </div>
          <div>
            <h4 className="tutorial-subheading">AUC</h4>
            <p>
              隨便抽一個達標樣本與一個沒達標樣本，模型給前者較高機率的比率。0.5 是隨機。
              它只看排序，<b>完全看不出機率數字本身準不準</b>。
            </p>
          </div>
          <div>
            <h4 className="tutorial-subheading">Brier score 與校準曲線</h4>
            <p>
              這兩個才在看「機率準不準」。模型說 70% 的那批標的，實際上是不是真有七成達標？
              校準曲線落在對角線下方，代表模型系統性地過度自信。
            </p>
          </div>
          <div>
            <h4 className="tutorial-subheading">訓練 vs 驗證的差距</h4>
            <p>
              訓練分數漂亮但驗證分數平庸，代表模型只是把訓練資料背起來了。詳情頁上方的紅框「資料品質提醒」
              會在偵測到這種情況時直接寫出來。
            </p>
          </div>
        </div>
        <p className="order-hint">
          這個系統不會替你判斷「哪個模型比較好」。所有數字原樣呈現，包含難看的那些——判斷留給看的人。
        </p>
      </section>

      <section className="panel tutorial-card">
        <h3 className="tutorial-heading">這個系統刻意不做的事</h3>
        <ul className="tutorial-list">
          <li>
            <b>不做當沖、不做盤中即時</b>：只在收盤後跑一次。
          </li>
          <li>
            <b>只做上市（TWSE）</b>：不含上櫃與興櫃。
          </li>
          <li>
            <b>不追蹤資金與股數</b>：只記錄損益率百分比。
          </li>
          <li>
            <b>不做投資建議</b>：這是一個模型表現的展示系統，不是推薦名單。回測績效不保證未來表現，
            而且上面幾個模型的測試集表現都明白顯示排序能力接近隨機。
          </li>
        </ul>
      </section>
    </>
  );
}
