import asyncio, httpx, json

HEADERS = {"User-Agent": "Mozilla/5.0"}
DATE = "20260907"

CANDIDATES = [
    ("三大法人 T86 (rwd)", "https://www.twse.com.tw/rwd/zh/fund/T86", {"date": DATE, "selectType": "ALL", "response": "json"}),
    ("融資融券 MI_MARGN (rwd)", "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN", {"date": DATE, "selectType": "ALL", "response": "json"}),
]

async def main():
    async with httpx.AsyncClient(timeout=30, headers=HEADERS) as c:
        for name, url, params in CANDIDATES:
            try:
                r = await c.get(url, params=params)
                print(f"\n=== {name} ===")
                print("  HTTP", r.status_code)
                if r.status_code != 200:
                    continue
                d = r.json()
                print("  stat:", d.get("stat"))
                print("  頂層 keys:", list(d.keys())[:10])
                if "fields" in d:
                    print("  fields:", d["fields"])
                    print("  資料筆數:", len(d.get("data") or []))
                    if d.get("data"): print("  第一列:", d["data"][0])
                for t in (d.get("tables") or []):
                    print("  表:", t.get("title"), "| 筆數", len(t.get("data") or []))
                    print("    fields:", (t.get("fields") or [])[:12])
                    if t.get("data"): print("    第一列:", t["data"][0][:12])
            except Exception as e:
                print(f"\n=== {name} === 失敗: {type(e).__name__}: {e}")
            await asyncio.sleep(4)

asyncio.run(main())
