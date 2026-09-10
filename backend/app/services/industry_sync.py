"""上市公司產業別的同步。

用途只有一個：讓特徵可以做「產業中性化」。「電子股今天全漲」不該被當成個股
alpha——把每個特徵減掉當天同產業的中位數之後，剩下的才是這檔相對同業的強弱。

來源是 TWSE 的上市公司基本資料（t187ap03_L），一次請求拿全部上市公司，
不需要逐檔。產業別很少變動，所以這支是手動觸發＋每日同步時順帶更新即可，
不需要像日K那樣回補歷史。

**沒有歷史。** 這支端點給的是「現在」的產業別，拿不到「兩年前這檔屬於哪一類」。
產業別本來就極少變動，所以用現況回推是可接受的近似——但要知道這件事：如果
某檔中途改過分類，早期的樣本會被歸到現在的類別。
"""

import logging

import httpx
from sqlalchemy.orm import Session

from app.models import Market, Stock

logger = logging.getLogger(__name__)

TWSE_COMPANY_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"

# TWSE 的產業別代碼。只用於顯示——分組本身只需要代碼，名稱是給人看的
INDUSTRY_NAMES: dict[str, str] = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維",
    "05": "電機機械", "06": "電器電纜", "08": "玻璃陶瓷", "09": "造紙工業",
    "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業", "14": "建材營造",
    "15": "航運業", "16": "觀光餐旅", "17": "金融保險", "18": "貿易百貨",
    "19": "綜合", "20": "其他", "21": "化學工業", "22": "生技醫療業",
    "23": "油電燃氣業", "24": "半導體業", "25": "電腦及週邊設備業",
    "26": "光電業", "27": "通信網路業", "28": "電子零組件業",
    "29": "電子通路業", "30": "資訊服務業", "31": "其他電子業",
    "32": "文化創意業", "33": "農業科技業", "34": "電子商務",
    "35": "綠能環保", "36": "數位雲端", "37": "運動休閒", "38": "居家生活",
    "80": "管理股票",
}


def industry_label(code: str | None) -> str:
    if not code:
        return "未分類"
    return INDUSTRY_NAMES.get(code, f"產業 {code}")


async def sync_industries(db: Session) -> dict:
    """抓一次全上市公司的產業別並寫回 stocks。回傳更新了幾檔。"""
    async with httpx.AsyncClient(timeout=45, headers={"User-Agent": "Mozilla/5.0"}) as client:
        response = await client.get(TWSE_COMPANY_URL)
        response.raise_for_status()
        companies = response.json()

    by_code = {}
    for item in companies:
        code = str(item.get("公司代號") or "").strip()
        industry = str(item.get("產業別") or "").strip()
        if code and industry:
            by_code[code] = industry

    if not by_code:
        return {"updated": 0, "message": "TWSE 回傳的內容裡沒有產業別"}

    updated = 0
    for stock in db.query(Stock).filter(Stock.market == Market.TWSE).all():
        industry = by_code.get(stock.code)
        if industry and stock.industry != industry:
            stock.industry = industry
            updated += 1
    db.commit()

    logger.info("sync_industries: 更新 %d 檔（來源共 %d 家公司）", updated, len(by_code))
    return {"updated": updated, "message": f"更新 {updated} 檔的產業別（來源 {len(by_code)} 家公司）"}


def load_industry_map(db: Session) -> dict[str, str]:
    """{股票代碼: 產業代碼}。沒有產業別的（ETF、受益證券之類）不會出現在裡面。"""
    return {
        code: industry
        for code, industry in db.query(Stock.code, Stock.industry)
        .filter(Stock.market == Market.TWSE, Stock.industry.isnot(None))
        .all()
    }


def coverage(db: Session) -> dict:
    total = db.query(Stock).filter(Stock.market == Market.TWSE).count()
    classified = db.query(Stock).filter(Stock.market == Market.TWSE, Stock.industry.isnot(None)).count()
    counts: dict[str, int] = {}
    for (industry,) in (
        db.query(Stock.industry).filter(Stock.market == Market.TWSE, Stock.industry.isnot(None)).all()
    ):
        counts[industry] = counts.get(industry, 0) + 1
    return {
        "total_stocks": total,
        "classified": classified,
        "industry_count": len(counts),
        "top_industries": [
            {"code": code, "label": industry_label(code), "count": n}
            for code, n in sorted(counts.items(), key=lambda kv: -kv[1])[:8]
        ],
    }
