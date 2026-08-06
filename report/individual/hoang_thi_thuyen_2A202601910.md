# Báo cáo cá nhân — Hoàng Thị Thuyên — Ingestion & Cleaning

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
|---|---|
| Họ và tên | Hoàng Thị Thuyên |
| MSSV | 2A202601910 |
| Khóa/Lớp | K4 |
| Nhóm | hiteboard |
| Vai trò | Ingestion & Cleaning Owner |
| Repository | https://github.com/thuynie/K4_Day10_Data-Pipeline-Data-Observability-Whiteboard |
| Ngày kiểm chứng | 2026-08-06 |

## 2. Phạm vi công việc

| Phần việc | File/hàm chính | Input | Output | Trạng thái |
|---|---|---|---|---|
| Crossref ingestion | `src/ingestion/crossref.py` | Crossref REST API hoặc snapshot local | `crossref_response.json`, `crossref_records.json` | Hoàn thành |
| Parse và chuẩn hóa raw schema | `parse_crossref_payload`, `PaperRecord` | Crossref payload | Danh sách `PaperRecord` | Hoàn thành |
| Retry, cache và lineage | `fetch_source_records`, `_write_fetch_metadata` | Settings/API response | Raw artifacts và fetch metadata | Hoàn thành |
| Cleaning và data modeling | `src/ingestion/cleaning.py` — `build_clean_dataframe` | Danh sách `PaperRecord` | Clean DataFrame/CSV/JSON | Hoàn thành |

Phạm vi ownership chỉ gồm `crossref.py` và `cleaning.py`. Evaluation/observability thuộc Dương Tiến Dũng; corruption/orchestration thuộc thành viên 3.

## 3. Kết quả đã bàn giao

| Artifact/signal | Kết quả kiểm chứng |
|---|---:|
| Raw records | 24 |
| Clean records | 24 |
| Số cột clean | 16 |
| Duplicate `paper_id` | 0 |
| Missing title | 0 |
| Summary ngắn nhất | 826 ký tự |
| Latest publication | 2026-08-05 |
| Oldest publication | 2026-02-12 |

Artifact liên quan:

- `data/raw/crossref_response.json`: response gốc để truy vết.
- `data/raw/crossref_records.json`: raw records đã parse theo schema thống nhất.
- `data/clean/papers_clean.json`: dữ liệu sạch cho evaluation/index.
- `data/clean/papers_clean.csv`: phiên bản bảng dễ kiểm tra.

## 4. Giải thích kỹ thuật

### Ingestion từ Crossref

`PaperRecord` định nghĩa contract gồm `paper_id`, `title`, `summary`, authors, categories, primary category, published/updated dates, abstract/PDF URLs và comment. Parser:

1. Đọc items từ cấu trúc response Crossref.
2. Bỏ record không có DOI hoặc title.
3. Loại XML/HTML, unescape entity và chuẩn hóa whitespace.
4. Ghép given/family name của authors; dùng `Unknown` khi thiếu.
5. Chuẩn hóa subjects thành categories; dùng `General` khi thiếu.
6. Chọn publication/update date theo chuỗi fallback và chuẩn hóa `YYYY-MM-DD`.
7. Tìm PDF URL trong Crossref links và fallback về DOI URL.

Fetch flow sử dụng timeout, retry tối đa ba lần cho HTTP 429/5xx và exponential backoff. Khi `REFRESH_SOURCE` tắt, pipeline dùng snapshot local để giữ dữ liệu ổn định. Nếu API lỗi nhưng cache có sẵn, flow chuyển sang trạng thái degraded cache thay vì làm mất khả năng tái hiện.

### Cleaning và data model

`build_clean_dataframe` thực hiện:

1. Loại record thiếu `paper_id`.
2. Làm sạch title, summary, author và category.
3. Dùng giá trị thay thế có kiểm soát cho authors/categories.
4. Parse `published`, tính `age_days` theo run date và không cho age âm.
5. Tính `summary_chars`.
6. Tạo `text_for_embedding` theo format title–authors–summary.
7. Deduplicate theo `paper_id`.
8. Loại title rỗng và summary dưới 100 ký tự.
9. Sắp xếp publication date giảm dần và ghi CSV/JSON.

### Data contract

| Thành phần | Mô tả |
|---|---|
| Nguồn | Crossref REST API `/works` |
| Query | Agentic retrieval augmented generation/large language model theo Settings |
| Raw ID | DOI được dùng làm `paper_id` |
| Clean key | `paper_id`, duy nhất |
| Embedding text | `Title: ... \| Authors: ... \| Summary: ...` |
| Freshness field | `published`, `age_days` |
| Consumer | Test-set builder, Chroma index, quality/freshness checks |

## 5. Quyết định kỹ thuật quan trọng

- **Bối cảnh:** API ngoài có thể rate-limit hoặc tạm thời lỗi, trong khi baseline cần reproducible.
- **Phương án cân nhắc:** luôn fetch mới; chỉ dùng file local; fetch có retry và fallback cache.
- **Lựa chọn:** retry có kiểm soát kết hợp raw snapshot/cache.
- **Lý do:** vẫn lấy được dữ liệu mới khi nguồn hoạt động nhưng không làm pipeline mất khả năng tái hiện khi mạng lỗi.
- **Bằng chứng:** raw response và parsed records được lưu tách biệt; `fetch_source_records` có nhánh cache và metadata trạng thái.

## 6. Lỗi và edge cases đã xử lý

- Abstract Crossref có JATS/XML: loại tag và unescape HTML trước khi cleaning.
- Crossref date có thể chỉ có năm/tháng: bổ sung tháng/ngày mặc định hợp lệ.
- DOI/title thiếu: loại record sớm để bảo vệ document key.
- Author/subject thiếu: fallback `Unknown`/`General` để contract không vỡ.
- Link PDF thiếu: fallback về abstract/DOI URL.
- API trả 429 hoặc 5xx: retry/backoff; có local snapshot thì dùng cache.

Blocker còn lại của toàn bài nằm ngoài ownership: `corruption.py`, `phase1.py`, `corruption_flow.py` chưa được thành viên 3 tích hợp nên chưa có metrics ba trạng thái.

## 7. Cách xác minh

```powershell
.\.venv\Scripts\Activate.ps1
python -m compileall -q src
python -c "from ingestion.crossref import load_raw_records; from core.config import load_settings; s=load_settings(); print(len(load_raw_records(s.paths.raw_records_json)))"
python -c "import pandas as pd; d=pd.read_json('data/clean/papers_clean.json'); print(len(d), d.paper_id.duplicated().sum(), d.summary_chars.min())"
```

Kết quả thực tế: 24 raw records; 24 clean records; 0 duplicate ID; summary tối thiểu 826 ký tự.

## 8. Hiểu biết luồng end-to-end

Crossref response được lưu nguyên bản, parse sang `PaperRecord`, sau đó cleaning tạo corpus có key và embedding text ổn định. Thành viên 2 dùng clean corpus để tạo test set và quality/freshness signals. Retrieval owner/index dùng cùng corpus để build vector store. Thành viên 3 sẽ tạo corrupted copy, chạy lại pipeline và repair từ raw snapshot. Repair chỉ đáng tin khi tạo lại từ raw source, không sửa trực tiếp metrics hay corrupted JSON.

## 9. Kết quả và giới hạn

Phần ingestion/cleaning đã có artifact thực tế và contract hợp lệ. Tuy nhiên chưa thể kết luận ảnh hưởng lên `retrieval_hit_rate`, token F1 hoặc judge score vì orchestration chưa hoàn thành. Báo cáo này không gán metrics giả cho phần chưa chạy.

## 10. Nội dung trình bày ngắn

> Em là Hoàng Thị Thuyên, MSSV 2A202601910, phụ trách Ingestion và Cleaning. Em hoàn thiện luồng lấy dữ liệu Crossref, parse về `PaperRecord`, chuẩn hóa HTML, authors, categories, dates và URLs; đồng thời có retry/backoff và cache để pipeline tái hiện được khi API lỗi. Ở bước cleaning, em chuẩn hóa schema, loại record không hợp lệ, deduplicate DOI, tính `age_days`, `summary_chars` và tạo `text_for_embedding`. Artifact hiện có 24 raw và 24 clean records, không có ID trùng, không thiếu title, summary ngắn nhất 826 ký tự. Phần này cung cấp clean corpus cho evaluation, quality và vector index.

## 11. Cam kết

- [x] Báo cáo chỉ nhận ownership cho `crossref.py` và `cleaning.py`.
- [x] Các con số nêu trong báo cáo được đọc từ artifact hiện có.
- [x] Không ghi pipeline end-to-end hoàn thành khi chưa kiểm chứng.
- [x] Không chứa API key, token hoặc nội dung `.env`.

**Họ và tên:** Hoàng Thị Thuyên

**MSSV:** 2A202601910

**Ngày xác nhận:** 2026-08-06
