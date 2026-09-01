import type { ChangeEvent } from "react";

interface Props {
  value: string;
  onChange: (raw: string) => void;
  placeholder?: string;
  readOnly?: boolean;
}

// 顯示千分位逗號方便閱讀金額，但實際存的 value 永遠是不含逗號的原始數字字串，
// 送出表單時不用另外處理。
function formatWithCommas(raw: string): string {
  if (!raw) return "";
  const [intPart, decPart] = raw.split(".");
  const withCommas = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return decPart !== undefined ? `${withCommas}.${decPart}` : withCommas;
}

export function AmountInput({ value, onChange, placeholder, readOnly }: Props) {
  function handleChange(e: ChangeEvent<HTMLInputElement>) {
    const raw = e.target.value.replace(/,/g, "");
    if (!/^\d*\.?\d*$/.test(raw)) return;
    onChange(raw);
  }

  return (
    <input
      type="text"
      inputMode="decimal"
      placeholder={placeholder}
      value={formatWithCommas(value)}
      readOnly={readOnly}
      onChange={handleChange}
    />
  );
}
