> 🌐 English version: [README.en.md](README.en.md)

# 台股零股模擬交易系統

一個以真實台股報價為基礎的**零股交易模擬平台**。用限價單練習零股下單、觀察撮合成交、資金與部位變化，完全不涉及真實金錢或真實下單，純粹用來熟悉台股零股交易的流程與規則。

## 這是什麼

- 使用真實的台股即時報價（上市 TWSE / 上櫃 TPEx）驅動模擬撮合，而不是隨機或回放資料。
- 下單邏輯採**真實限價單**：買單「成交價 ≤ 限價」、賣單「成交價 ≥ 限價」才會成交，不是保證成交。
- 每個帳號皆為獨立的模擬資產，起始現金新台幣 100 萬元。
- 自動計算買賣手續費（0.1425%）與賣出交易稅（0.3%）。
- 後端每隔幾秒（預設 7 秒）於零股交易時段（09:00–13:30，週一至五）輪詢一次報價並嘗試撮合。

> ⚠️ **本專案僅供學習與練習使用，不是真實下單系統，也不構成任何投資建議。**

## 主要功能

- **登入 / 註冊**：每個使用者有各自獨立的帳號、現金與庫存。
- **首頁**：目前持有股票的 K 線圖與價格走勢圖，一檔股票一個區塊。
- **搜尋**：可查詢任意股票代號，顯示大版型的 K 線／分時走勢圖，並附上基本面資訊（本益比、殖利率、股價淨值比，含近 2–3 年歷史月資料），可直接將股票加入或移出自選股。
- **交易**：下單面板（買／賣、代號、股數、限價）＋ 委託回報／成交回報列表。
- **交易紀錄**：歷史成交明細（含手續費、交易稅）。
- **部位**：獨立分頁檢視目前持有部位與未實現損益。
- **股市教學**：分主題子頁，涵蓋 K 線、均線、量價關係、KD 指標、基本面怎麼看、除權息、零股交易規則、手續費與交易稅、委託／成交回報。
- **K 線圖表**：日 K 線可疊加 5 / 20 / 60 日均線（週線／月線／季線），分時走勢圖以台北時區正確顯示。
- **自選股**：加入自選股的股票會持續追蹤當日分時走勢；未加入自選股且沒有分時資料的個股，會提供連結導向 Yahoo奇摩股市查看。

## 技術架構

| 元件 | 技術 |
|---|---|
| 後端 | Python + FastAPI + SQLAlchemy 2.0 + APScheduler |
| 資料庫 | PostgreSQL 16 |
| 前端 | React + TypeScript + Vite + react-router-dom |
| 圖表 | lightweight-charts |
| 認證 | JWT（PyJWT）+ bcrypt |
| 容器化 | Docker Compose |

後端每隔一段時間（`TWSTOCK_POLL_INTERVAL_SECONDS`）會批次向 TWSE 的公開報價介面取得所有需要的股票報價（掛單中／持有中／自選股），並嘗試撮合待成交的委託單；收盤後未成交的委託會自動失效並解凍資金／庫存。

## 快速開始

### 需求

- Docker 與 Docker Compose

### 步驟

1. 複製環境變數範例檔並填入自己的值：

   ```bash
   cp .env.example .env
   ```

   打開 `.env`，將 `POSTGRES_PASSWORD` 與 `TWSTOCK_JWT_SECRET` 改成隨機字串（範例指令：`python -c "import secrets; print(secrets.token_urlsafe(32))"`）。**`TWSTOCK_JWT_SECRET` 沒有預設值，沒設定後端會直接啟動失敗。**

2. 啟動所有服務：

   ```bash
   docker compose up -d --build
   ```

3. 開啟瀏覽器：
   - 前端：http://localhost:5173
   - 後端 API 文件（Swagger）：http://localhost:8000/docs

4. 在前端頁面註冊一個帳號即可開始使用，每個新帳號會自動配發新台幣 100 萬元的模擬現金。

### 環境變數（`.env`）

| 變數 | 說明 | 預設值 |
|---|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL 密碼 | 需自行設定 |
| `TWSTOCK_JWT_SECRET` | JWT 簽章密鑰 | **必填，無預設值** |
| `TWSTOCK_INITIAL_CASH` | 新帳號起始現金 | 1,000,000 |
| `TWSTOCK_POLL_INTERVAL_SECONDS` | 撮合輪詢間隔（秒） | 7 |
| `TWSTOCK_TRADING_START` / `TWSTOCK_TRADING_END` | 零股交易時段 | 09:00 / 13:30 |

## 專案結構

```
backend/
  app/
    main.py            # FastAPI 進入點、排程任務
    config.py           # 環境變數設定
    models.py           # SQLAlchemy 資料表
    schemas.py           # Pydantic schema
    routers/             # API 路由（auth、stocks、account、positions、orders、trades、market_data、watchlist）
    services/
      matching.py        # 撮合邏輯、交易時段判斷
      twse_client.py      # TWSE / TPEx 報價與歷史資料串接
      stock_sync.py        # 股票清單、基本面資料同步與回補
frontend/
  src/
    pages/               # 首頁、搜尋、交易、交易紀錄、部位、股市教學、登入
    components/           # 圖表、表格、下單面板等元件
    hooks/, lib/, api.ts  # 資料抓取與工具函式
docker-compose.yml
.env.example
```

## 已知限制

- 上櫃（TPEx）股票沒有官方的歷史資料查詢 API，因此日K線與基本面歷史資料只能從系統啟動後開始逐日累積；上市（TWSE）股票則有完整的近期回補資料。
- 分時走勢圖僅追蹤已加入自選股的股票；未加入自選股的個股若當日尚無分時資料，會改為提供 Yahoo奇摩股市的外部連結。
- 報價來源為公開、非官方的即時報價介面，存在延遲與偶爾中斷的可能，不適合用於任何真實交易決策。
- 本系統不處理真實金流、不連接任何券商，僅為本地模擬。

## 授權

僅供個人學習與練習使用。
