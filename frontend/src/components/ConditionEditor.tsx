import type { Condition } from "../types";

const TYPE_LABEL: Record<Condition["type"], string> = {
  kd_value: "KD 數值",
  kd_cross: "KD 交叉",
  ma_compare: "均線比較",
  price_vs_ma: "股價 vs 均線",
  streak: "連續漲跌天數",
  cumulative_change: "累積漲跌幅",
};

const PERIOD_OPTIONS: Array<5 | 20 | 60> = [5, 20, 60];

function defaultForType(type: Condition["type"]): Condition {
  switch (type) {
    case "kd_value":
      return { type: "kd_value", line: "k", operator: "lt", value: 20 };
    case "kd_cross":
      return { type: "kd_cross", direction: "golden" };
    case "ma_compare":
      return { type: "ma_compare", fast: 5, slow: 20, operator: "gt" };
    case "price_vs_ma":
      return { type: "price_vs_ma", period: 20, operator: "gt" };
    case "streak":
      return { type: "streak", direction: "up", days: 3 };
    case "cumulative_change":
      return { type: "cumulative_change", days: 5, operator: "gte", percent: 5 };
  }
}

interface Props {
  label: string;
  hint: string;
  conditions: Condition[];
  onChange: (conditions: Condition[]) => void;
}

export function ConditionEditor({ label, hint, conditions, onChange }: Props) {
  function updateAt(index: number, next: Condition) {
    onChange(conditions.map((c, i) => (i === index ? next : c)));
  }

  function removeAt(index: number) {
    onChange(conditions.filter((_, i) => i !== index));
  }

  function addCondition() {
    onChange([...conditions, defaultForType("kd_value")]);
  }

  return (
    <div className="condition-editor">
      <div className="condition-editor-header">
        <h3>{label}</h3>
        <span className="order-hint">{hint}</span>
      </div>
      {conditions.length === 0 && <div className="empty-hint">尚未設定條件</div>}
      {conditions.map((cond, index) => (
        <div className="condition-row" key={index}>
          <select
            value={cond.type}
            onChange={(e) => updateAt(index, defaultForType(e.target.value as Condition["type"]))}
          >
            {Object.entries(TYPE_LABEL).map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>

          {cond.type === "kd_value" && (
            <>
              <select value={cond.line} onChange={(e) => updateAt(index, { ...cond, line: e.target.value as "k" | "d" })}>
                <option value="k">K 值</option>
                <option value="d">D 值</option>
              </select>
              <select
                value={cond.operator}
                onChange={(e) =>
                  updateAt(index, { ...cond, operator: e.target.value as "gt" | "lt" | "gte" | "lte" })
                }
              >
                <option value="gt">大於</option>
                <option value="lt">小於</option>
                <option value="gte">大於等於</option>
                <option value="lte">小於等於</option>
              </select>
              <input
                type="number"
                min={0}
                max={100}
                value={cond.value}
                onChange={(e) => updateAt(index, { ...cond, value: Number(e.target.value) })}
              />
            </>
          )}

          {cond.type === "kd_cross" && (
            <select
              value={cond.direction}
              onChange={(e) => updateAt(index, { ...cond, direction: e.target.value as "golden" | "death" })}
            >
              <option value="golden">黃金交叉（K 由下往上穿過 D）</option>
              <option value="death">死亡交叉（K 由上往下穿過 D）</option>
            </select>
          )}

          {cond.type === "ma_compare" && (
            <>
              <select value={cond.fast} onChange={(e) => updateAt(index, { ...cond, fast: Number(e.target.value) as 5 | 20 | 60 })}>
                {PERIOD_OPTIONS.map((p) => (
                  <option key={p} value={p}>
                    {p} 日均線
                  </option>
                ))}
              </select>
              <select
                value={cond.operator}
                onChange={(e) => updateAt(index, { ...cond, operator: e.target.value as "gt" | "lt" })}
              >
                <option value="gt">大於</option>
                <option value="lt">小於</option>
              </select>
              <select value={cond.slow} onChange={(e) => updateAt(index, { ...cond, slow: Number(e.target.value) as 5 | 20 | 60 })}>
                {PERIOD_OPTIONS.map((p) => (
                  <option key={p} value={p}>
                    {p} 日均線
                  </option>
                ))}
              </select>
            </>
          )}

          {cond.type === "price_vs_ma" && (
            <>
              <span className="condition-static-label">股價</span>
              <select
                value={cond.operator}
                onChange={(e) => updateAt(index, { ...cond, operator: e.target.value as "gt" | "lt" })}
              >
                <option value="gt">大於</option>
                <option value="lt">小於</option>
              </select>
              <select value={cond.period} onChange={(e) => updateAt(index, { ...cond, period: Number(e.target.value) as 5 | 20 | 60 })}>
                {PERIOD_OPTIONS.map((p) => (
                  <option key={p} value={p}>
                    {p} 日均線
                  </option>
                ))}
              </select>
            </>
          )}

          {cond.type === "streak" && (
            <>
              <select
                value={cond.direction}
                onChange={(e) => updateAt(index, { ...cond, direction: e.target.value as "up" | "down" })}
              >
                <option value="up">連續上漲</option>
                <option value="down">連續下跌</option>
              </select>
              <input
                type="number"
                min={1}
                value={cond.days}
                onChange={(e) => updateAt(index, { ...cond, days: Number(e.target.value) })}
              />
              <span className="condition-static-label">天</span>
            </>
          )}

          {cond.type === "cumulative_change" && (
            <>
              <span className="condition-static-label">最近</span>
              <input
                type="number"
                min={1}
                value={cond.days}
                onChange={(e) => updateAt(index, { ...cond, days: Number(e.target.value) })}
              />
              <span className="condition-static-label">天累積漲跌幅</span>
              <select
                value={cond.operator}
                onChange={(e) => updateAt(index, { ...cond, operator: e.target.value as "gte" | "lte" })}
              >
                <option value="gte">大於等於</option>
                <option value="lte">小於等於</option>
              </select>
              <input
                type="number"
                step="0.1"
                value={cond.percent}
                onChange={(e) => updateAt(index, { ...cond, percent: Number(e.target.value) })}
              />
              <span className="condition-static-label">%</span>
            </>
          )}

          <span className="cancel-link danger-link" onClick={() => removeAt(index)}>
            移除
          </span>
        </div>
      ))}
      <button type="button" className="add-condition-btn" onClick={addCondition}>
        + 新增條件
      </button>
    </div>
  );
}
