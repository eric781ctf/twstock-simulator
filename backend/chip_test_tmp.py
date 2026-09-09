from datetime import date
from app.database import SessionLocal
from app.services.ml.features import build_feature_rows, CHIP_FEATURE_KEYS
from app.models import ChipDaily

db = SessionLocal()
c = db.query(ChipDaily).filter(ChipDaily.stock_code == "2330").order_by(ChipDaily.trade_date.desc()).first()
print(f"2330 最新籌碼（{c.trade_date}）: 外資 {c.foreign_net:,} 股 | 投信 {c.trust_net:,} | 三大法人 {c.institution_net:,} | 融資 {c.margin_balance:,} 張")

rows, _ = build_feature_rows(db, date(2026, 6, 1), date(2026, 9, 7), date(2026, 9, 1))
print(f"\n產出 {len(rows)} 列")

filled = {k: sum(1 for r in rows if r.get(k) is not None) for k in CHIP_FEATURE_KEYS}
print("\n各籌碼特徵有值的比例：")
for k, n in filled.items():
    print(f"  {k:24} {n:6}/{len(rows)}  ({n/len(rows)*100:.1f}%)")

r = next(r for r in rows if r["stock_code"] == "2330" and r["foreign_net_ratio"] is not None)
print(f"\n2330 於 {r['as_of_date']}:")
print(f"  外資買賣超/成交量 = {r['foreign_net_ratio']:.3f}%")
print(f"  外資近5日        = {r['foreign_net_ratio_5d']:.3f}%")
print(f"  三大法人         = {r['institution_net_ratio']:.3f}%")
print(f"  融資5日變化      = {r['margin_change_5d']}")

# 手動驗算當日外資比率
chip = db.query(ChipDaily).filter(ChipDaily.stock_code=="2330", ChipDaily.trade_date==r["as_of_date"]).one()
expect = chip.foreign_net / r["volume"] * 100
print(f"\n手算驗證: {chip.foreign_net:,} / {int(r['volume']):,} * 100 = {expect:.3f}%  相符: {abs(expect - r['foreign_net_ratio']) < 1e-9}")
db.close()
