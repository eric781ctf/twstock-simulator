FROM python:3.12-slim

WORKDIR /app

# LightGBM / XGBoost 的原生程式庫依賴 OpenMP runtime，slim 映像沒有內建
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# PyTorch 的 CUDA 版不在 PyPI，要指定官方 index。cu124 對應 CUDA 12.4，
# 支援 Turing(RTX 20 系列) 以後的顯卡。這層約 2.5GB，放在最後才不會讓
# 前面的依賴每次都跟著重建。
RUN pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cu124

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
