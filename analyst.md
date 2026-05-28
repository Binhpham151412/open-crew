# Phân Tích Kiến Trúc — build.py

---

## So Sánh: Hiện Tại vs Đúng

| | ❌ build.py hiện tại — **SAI** | ✅ Kiến trúc đúng — **CẦN BUILD** |
|---|---|---|
| **Tầng 1** | CrewAI Crew *(1 TechLead + 1 Coder agent)* | 11 FastAPI services thật *(Mỗi agent = 1 process chạy liên tục)* |
| **Tầng 2** | 1 task duy nhất cho toàn bộ phase | A2A protocol giữa agents *(HTTP POST thật, async, không block)* |
| **Tầng 3** | LLM trả về text trong 30 phút *(max_tokens=8192 → bị cắt giữa chừng)* | Redis task queue *(Agent pick task, xử lý, push kết quả)* |
| **Tầng 4** | `parse_and_save_files()` chạy *(Không tìm thấy `=== FILE:` → lưu raw)* | NextJS web UI giám sát *(Real-time logs, task timeline, config)* |
| **Kết quả** | 🔴 **Folder rỗng** — Code lỗi, agents chỉ là tên gọi | 🟢 **Hệ thống thật** hoạt động end-to-end |

---

## ❌ Luồng Sai — build.py Hiện Tại

```
CrewAI Crew (1 TechLead + 1 Coder agent)
        │
        ▼
1 task duy nhất cho toàn bộ phase
        │
        ▼
LLM trả về text trong 30 phút
(max_tokens=8192 → bị cắt giữa chừng)
        │
        ▼
parse_and_save_files() chạy
(Không tìm thấy === FILE: → lưu raw)
        │
        ▼
Kết quả: folder rỗng
(Code lỗi, agents chỉ là tên gọi)
```

---

## ✅ Luồng Đúng — Kiến Trúc Cần Build

```
11 FastAPI services thật
(Mỗi agent = 1 process chạy liên tục)
        │
        ▼
A2A protocol giữa agents
(HTTP POST thật, async, không block)
        │
        ▼
Redis task queue
(Agent pick task, xử lý, push kết quả)
        │
        ▼
NextJS web UI giám sát
(Real-time logs, task timeline, config)
```

---

## 🔍 3 Vấn Đề Gốc Rễ

> **① CrewAI không thể sinh 11 services thật — nó chỉ generate text**

> **② 8192 tokens = ~500 dòng code — không đủ cho 1 file FastAPI hoàn chỉnh**

> ③ `parse_and_save_files()` không tìm được marker `=== FILE:` trong output bị cắt → không lưu được file nào

---

## 💡 Giải Pháp Đúng

> **Tôi viết trực tiếp toàn bộ code — không qua CrewAI — sinh đúng file thật ngay bây giờ**

---

## 📌 Ghi Chú Quan Trọng

> CrewAI chỉ phù hợp cho **orchestration runtime**, không phải **code generation pipeline**

---

## Tóm Tắt

| Khía cạnh | Vấn đề | Giải pháp |
|---|---|---|
| **Framework** | CrewAI chỉ generate text, không tạo process thật | Viết code trực tiếp, không qua CrewAI |
| **Token limit** | 8192 tokens ≈ 500 dòng — không đủ 1 FastAPI file | Chia nhỏ từng file, viết trực tiếp |
| **File parsing** | Marker `=== FILE:` không tồn tại trong output bị truncate | Sinh file thật ngay, không parse text |
| **Architecture** | Agent chỉ là label, không phải process thật | 11 FastAPI process + Redis queue + A2A HTTP |