import type { ScoreFormulaInfo } from "../types";

interface Props {
  info: ScoreFormulaInfo;
  /** 這個模型實際用的權重；建模表單上還沒送出時傳目前輸入值 */
  weights?: { return: number; probability: number } | null;
}

/**
 * 選股分數的公式與說明。admin 訓練表單跟公開的模型詳情頁共用同一個元件，
 * 內容全部來自後端（`SCORE_FORMULA_INFO`），前端不自己抄一份公式描述——
 * 不然改了實作卻忘了改說明，頁面就會騙人。
 */
export function ScoreFormulaExplainer({ info, weights }: Props) {
  return (
    <div className="formula-explainer">
      <div className="formula-explainer-head">
        <span className="formula-name">{info.name}</span>
        <span className="formula-summary">{info.summary}</span>
      </div>

      <div className="formula-box">
        <div className="formula-main">{info.formula}</div>
        <div className="formula-def">{info.definition}</div>
        {/* 教學頁沒有「某一個模型」可以講，這時不能顯示假的目前權重 */}
        <div className="formula-weights">
          {weights ? (
            <>
              目前權重：w₁（預期報酬）= <b>{weights.return}</b>　w₂（達標機率）= <b>{weights.probability}</b>
            </>
          ) : (
            <>w₁、w₂ 兩個權重由 admin 在訓練每個模型時各自設定，會顯示在該模型的詳情頁上。</>
          )}
        </div>
      </div>

      <div className="formula-reasons">
        <span className="formula-subtitle">為什麼要先標準化</span>
        <ul>
          {info.reasons.map((reason, i) => (
            <li key={i}>{reason}</li>
          ))}
        </ul>
      </div>

      <div className="formula-limitation">
        <span className="formula-subtitle">這個做法沒有解決的部分</span>
        <p>{info.limitation}</p>
      </div>
    </div>
  );
}
