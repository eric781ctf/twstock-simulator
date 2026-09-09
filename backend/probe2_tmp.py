import asyncio, httpx
HEADERS = {"User-Agent": "Mozilla/5.0"}

async def main():
    async with httpx.AsyncClient(timeout=30, headers=HEADERS) as c:
        r = await c.get("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
                        params={"date": "20260907", "selectType": "ALL", "response": "json"})
        d = r.json()
        t = next(x for x in d["tables"] if "彙總" in (x.get("title") or ""))
        print("完整 fields（共 %d 個）:" % len(t["fields"]))
        for i, f in enumerate(t["fields"]):
            print(f"  [{i:2}] {f}")
        row = next(x for x in t["data"] if x[0] == "2330")
        print("\n2330 台積電那一列（共 %d 欄）:" % len(row))
        for i, v in enumerate(row):
            print(f"  [{i:2}] {v}")

asyncio.run(main())
