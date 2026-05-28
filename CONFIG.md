# ⚙️ OpenCrew — CONFIG
 
> **Đây là file DUY NHẤT bạn cần đọc.**
> Làm theo từ trên xuống dưới. Xong → chạy 1 lệnh → đi ngủ.
 
-----
 
## Bước 1: Cài Python (1 lần)
 
```powershell
cd d:\binhpv7\open-hand
pip install -r requirements.txt
```
 
-----
 
## Bước 2: Tạo file `.env`
 
Tạo file `d:\binhpv7\open-hand\.env` — copy nội dung bên dưới, điền giá trị thật:
 
```env
# ===== BẮT BUỘC =====
 
# API key MiMo-v2.5-Pro từ Xiaomi
# Lấy từ: https://platform.xiaomi.com hoặc provider bạn dùng
MIMO_API_KEY=
 
# Endpoint URL (chọn 1):
#   Xiaomi trực tiếp: https://api.xiaomi.com/v1 (check docs Xiaomi)
#   OpenRouter:       https://openrouter.ai/api/v1
MIMO_BASE_URL=
 
# Tên model (check với provider):
#   Xiaomi: mimo-v2.5-pro
#   OpenRouter: xiaomi/mimo-v2.5-pro
MIMO_MODEL=
 
# ===== OPTIONAL (điền sau cũng được) =====
 
# GitHub — để agents commit code lên repo
# Tạo tại: https://github.com/settings/tokens
GITHUB_TOKEN=
HF_USERNAME=
```
 
> ⚠️ Chỉ cần 3 dòng đầu (MIMO_API_KEY, MIMO_BASE_URL, MIMO_MODEL) là đủ chạy.
 
-----
 
## Bước 3: Test API key
 
```powershell
python build.py --test
```
 
Nếu thấy `✅ OK` → sang bước 4.
Nếu thấy `❌` → kiểm tra lại 3 dòng trong `.env`.
 
-----
 
## Bước 4: Chạy
 
```powershell
python build.py
```
 
**Cắm sạc. Đi ngủ. 1-3 ngày sau mở laptop → có source code chạy được.**
 
-----
 
## Bước 5 (sau khi build xong): Test hệ thống
 
```powershell
# Chạy toàn bộ OpenCrew locally
cd output
npm install
npm run dev
# Mở http://localhost:3000 → thấy config panel giống router admin
```
 
-----
 
## FAQ
 
**Q: Laptop tắt/ngủ giữa chừng?**
A: Chạy lại `python build.py` — nó tự resume từ chỗ dang dở.
 
**Q: Hết token?**
A: Với 13 tỷ token MiMo sẽ không hết. Nếu có, code đã gen được giữ nguyên.
 
**Q: Muốn xem tiến độ?**
A: `python build.py --status`
 
**Q: Build xong rồi làm gì?**
A: Mở `http://localhost:3000` → config API keys, MCP servers, A2A connections trên giao diện web.
 
 