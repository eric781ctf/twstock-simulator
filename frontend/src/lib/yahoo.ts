/** Yahoo奇摩股市的個股頁面網址，上市用 .TW、上櫃用 .TWO。 */
export function yahooStockUrl(code: string, market: "TWSE" | "TPEX"): string {
  const suffix = market === "TWSE" ? "TW" : "TWO";
  return `https://tw.stock.yahoo.com/quote/${code}.${suffix}`;
}
