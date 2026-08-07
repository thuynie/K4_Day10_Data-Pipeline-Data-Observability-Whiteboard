# Báo cáo nhóm — Day 10: Data Pipeline & Data Observability

## 1. Thông tin bài nộp

| Thông tin | Nội dung                                                                          |
| --- |-----------------------------------------------------------------------------------|
| Khóa/Lớp | K4                                                                                |
| Tên nhóm | Whiteboard                                                                        |
| Repository | `https://github.com/thuynie/K4_Day10_Data-Pipeline-Data-Observability-Whiteboard` |
| Ngày hoàn thành | 2026-08-06                                                                        |

### Thành viên và phân công

| STT | Họ và tên | MSSV | Vai trò chính | Module/deliverable sở hữu |
| --: | --- | --- | --- | --- |
| 1 | Hoàng Thị Thuyên | 2A202601910 | Ingestion & Cleaning Owner | `crossref.py`, `cleaning.py`; raw/clean schema và artifacts |
| 2 | Dương Tiến Dũng | 2A202602020 | Evaluation & Observability Owner | `testset.py`, `quality.py`, `reporting.py`; test set, quality/freshness và report |
| 3 | Đặng Quang Trung | 2A202601510 | Corruption & Pipeline Integration Owner | `corruption.py`, `phase1.py`, `corruption_flow.py`; tích hợp retrieval/agent, metrics và review |

## 2. Tóm tắt kết quả

Nhóm đã hoàn thành pipeline hai pha từ dữ liệu Crossref đến so sánh baseline–corrupted–repaired. Pha baseline lưu response và 24 raw records, tạo 24 clean records, embedding manifest, ChromaDB index, test set 32 câu, answers/metrics, 12 quality checks và freshness report. Trên đường đánh giá deterministic, baseline đạt retrieval hit rate 1,0000 và mean token F1 0,9314; toàn bộ 12/12 quality checks đạt và dữ liệu ở trạng thái fresh.

Nhóm chủ động tạo sáu dạng lỗi: xóa 4 bản ghi mới nhất, làm cũ ngày của 4 bản ghi, xóa summary của 4 bản ghi, chèn nhiễu vào 4 bản ghi, cắt title của 3 bản ghi và nhân đôi 3 bản ghi. Các lỗi được ép giao với frozen test set nên làm retrieval hit rate giảm 0,2500 và mean token F1 giảm 0,2180; quality chỉ còn 7/12 checks đạt và freshness chuyển sang stale. Repair dựng lại clean data từ raw snapshot đáng tin cậy, đưa 12/12 checks, freshness và toàn bộ metric về đúng baseline.

Giới hạn chính là Gemini free-tier hết quota: agent evaluation lỗi 32/32 câu và judge phải fallback sang heuristic. Vì vậy các số 0 trong `agent_metrics.json` không phải chất lượng agent; bảng so sánh chính sử dụng đường deterministic, còn `judge_accuracy` và `mean_judge_score` không phải đánh giá LLM độc lập.

## 3. Kiến trúc và luồng dữ liệu

```text
Crossref REST API / raw snapshot
    -> raw response + 24 parsed records
    -> cleaning + data contract
    -> embedding manifest + ChromaDB collection
    -> frozen test set + baseline evaluation
    -> quality/freshness signals
    -> six seeded corruptions + rebuild index + re-evaluation
    -> rebuild clean data from raw snapshot + re-index
    -> baseline/corrupted/repaired comparison report
```

| Khối | Input | Xử lý chính | Output/artifact | Owner |
| --- | --- | --- | --- | --- |
| Ingestion | Crossref `/works` hoặc cache | Fetch, retry/backoff, parse và chuẩn hóa | `data/raw/crossref_response.json`, `crossref_records.json` | Hoàng Thị Thuyên |
| Cleaning | Raw records | Làm sạch, validate, deduplicate, tạo field dẫn xuất | `data/clean/papers_clean.{csv,json}` | Hoàng Thị Thuyên |
| Embedding/index | Clean/corrupted/repaired data | Gemini embedding, collection riêng cho từng trạng thái | `data/embeddings/*.json`, local ChromaDB | Đặng Quang Trung |
| Evaluation | Clean data và frozen test set | Retrieval top-4, token F1, judge và answer artifact | `data/eval/test_set.json`, `data/results/*` | Dương Tiến Dũng; Trung tích hợp |
| Observability | DataFrame mỗi trạng thái | 12 quality checks và freshness 180 ngày | `data/quality/*`, `data/reports/*` | Dương Tiến Dũng |
| Corruption/repair | Baseline clean, frozen test set, raw snapshot | Sáu lỗi có seed; repair bằng cách clean lại raw | Corrupted/repaired datasets và `corruption_log.json` | Đặng Quang Trung |
| Orchestration | Toàn bộ contract/artifact | Điều phối pha 1 và pha 2, kiểm tra tính so sánh | Metrics và hai Markdown reports | Đặng Quang Trung |

## 4. Cách tái hiện kết quả

### Cấu hình không chứa secret

| Biến/cấu hình | Giá trị sử dụng |
| --- | --- |
| `LLM_PROVIDER` / `LLM_MODEL` | `gemini` / `gemini-2.5-flash` |
| Embedding model / dimensions | `gemini-embedding-001` / 1536 |
| Số lượng Crossref records | 24 |
| Retrieval `top_k` | 4 |
| Freshness threshold | 180 ngày |
| Corruption random seed | 42 |
| Collections | `papers-baseline`, `papers-corrupted`, `papers-repaired` |

Không lưu `.env` hoặc API key trong repository.

### Lệnh cài đặt và chạy

```powershell
uv sync
uv run python script/run_phase1.py
uv run python script/run_corruption_flow.py
uv run pytest tests/test_observability.py -v
```

| Lệnh | Trạng thái gần nhất | Thời điểm artifact (UTC) | Bằng chứng |
| --- | --- | --- | --- |
| Baseline pipeline | Thành công phần deterministic; agent eval thất bại do quota | 2026-08-06 14:07 | `baseline_metrics.json`, `quality_baseline.json`, `phase1_report.md` |
| Corruption flow | Thành công | 2026-08-06 14:00–14:19 | `corruption_log.json`, corrupted/repaired metrics và `corruption_report.md` |

## 5. Ingestion, cleaning và data contract

### Nguồn dữ liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Source | `https://api.crossref.org/works` |
| Query | `agentic retrieval augmented generation large language model` |
| Filter | `from-pub-date:2026-02-07,has-abstract:true` |
| Snapshot gần nhất | 2026-08-06; response trả 24 items |
| Raw/clean records | 24 / 24 |
| Retry/backoff | Tối đa 3 lần cho HTTP 429, 500, 502, 503, 504; exponential backoff và fallback cache |

### Raw và clean schema

| Trường | Kiểu | Bắt buộc | Ý nghĩa và xử lý thiếu/sai |
| --- | --- | --- | --- |
| `paper_id` | string | Có | DOI, document identity; record thiếu bị loại |
| `title` | string | Có | Loại tag/entity, chuẩn hóa whitespace; title rỗng bị loại |
| `summary` | string | Có | Làm sạch JATS/HTML; summary dưới 100 ký tự bị loại |
| `authors` / `authors_joined` | list / string | Không | Ghép given/family; fallback `Unknown` |
| `categories` / `categories_joined` | list / string | Không | Chuẩn hóa subject; fallback `General` |
| `published`, `updated` | string `YYYY-MM-DD` | Có | Chuỗi fallback từ các field ngày Crossref |
| `age_days` | integer | Có | Khoảng cách từ run date đến `published`, không âm |
| `abs_url`, `pdf_url` | string | Không | PDF link nếu có, nếu không fallback DOI URL |
| `text_for_embedding` | string | Có | Văn bản thống nhất để embedding |

### Quy tắc cleaning

| Quy tắc | Dimension | Record bị tác động trong snapshot | Cách xác minh |
| --- | --- | --: | --- |
| Loại record thiếu `paper_id` hoặc title | Completeness/validity | 0 | Raw và clean đều 24 records |
| Deduplicate theo `paper_id` | Uniqueness | 0 | `paper_id_unique` observed = 0 duplicate |
| Loại summary dưới 100 ký tự | Completeness/validity | 0 | Summary ngắn nhất 826 ký tự |
| Chuẩn hóa ngày, tính `age_days` và sắp xếp mới nhất trước | Validity/freshness | 24 | `published_format`, `age_days_non_negative` đều pass |

`paper_id` giữ nguyên DOI để nối raw, clean, vector metadata và ground truth. `text_for_embedding` được dựng theo các phần `Title`, `Authors`, `Categories`, `Summary`. `age_days` được tính từ ngày chạy đến `published`; khi corruption sửa ngày hoặc nội dung, các field dẫn xuất và embedding text được dựng lại để lỗi thật sự đi vào phép đo.

## 6. Evaluation setup

| Thành phần | Cấu hình thực tế |
| --- | --- |
| Số câu hỏi | 32 câu trên 8 document IDs |
| `question_type` | `summary`, `authors`, `date`, `categories` |
| Ground-truth ID | DOI trùng `paper_id` trong corpus |
| Embedding/vector store | `gemini-embedding-001`, ChromaDB, ba collection riêng |
| Retrieval `top_k` | 4 |
| LLM | Gemini 2.5 Flash; lần chạy cuối bị quota |
| Test set dùng chung | `data/eval/test_set.json` |

Test set được đóng băng và dùng lại nguyên trạng cho cả ba collection để giữ nguyên câu hỏi, ground truth, evaluator và top-k. Nhờ đó chênh lệch metric chỉ phản ánh dataset/index tương ứng, không do thay đổi độ khó của bộ câu hỏi. Mỗi corruption còn được ưu tiên chạm ít nhất một document trong test set; log xác nhận cả sáu scenario đều có overlap.

## 7. Kết quả baseline

| Artifact | Đường dẫn | Trạng thái | Ghi chú |
| --- | --- | --- | --- |
| Raw response/records | `data/raw/` | Có | 24 parsed records |
| Cleaned dataset | `data/clean/papers_clean.{csv,json}` | Có | 24 rows, 16 columns |
| Embedding manifest | `data/embeddings/papers_embeddings.json` | Có | Index có thể build lại; Chroma cache không commit |
| Evaluation set | `data/eval/test_set.json` | Có | 32 câu |
| Baseline answers/metrics | `data/results/baseline_*` | Có | Deterministic evaluation |
| Quality/freshness | `data/quality/` | Có | 12/12 pass, fresh |
| Baseline report | `data/reports/phase1_report.md` | Có | Có cảnh báo provenance của judge/agent |

| Metric | Giá trị | Diễn giải |
| --- | --: | --- |
| `retrieval_hit_rate` | 1,0000 | 32/32 câu retrieve được ground-truth document trong top-4 |
| `mean_token_f1` | 0,9314 | Answer deterministic khớp cao với ground truth |
| `judge_accuracy` | 1,0000 | Heuristic fallback, không phải LLM judge độc lập |
| `mean_judge_score` | 4,5000 | Heuristic fallback từ token F1 |
| Ragas | N/A | Bị tắt; artifact ghi `RUN_RAGAS=1` để bật lượt chạy chậm |

## 8. Data quality và freshness

| Check | Dimension | Ngưỡng/kỳ vọng | Baseline | Bằng chứng |
| --- | --- | --- | --- | --- |
| `row_count_min` | Volume | ≥ 5 rows | Pass: 24 | `quality_baseline.json` |
| ID completeness/uniqueness | Completeness/uniqueness | 0 null, 0 duplicate | Pass: 0/0 | `quality_baseline.json` |
| Title checks | Completeness/validity | 0 null, length ≥ 10, 0 duplicate | Pass: 0 lỗi | `quality_baseline.json` |
| Summary checks | Completeness/validity | 0 null, length ≥ 100 | Pass: 0 lỗi | `quality_baseline.json` |
| Embedding text | Completeness | 0 rỗng | Pass: 0 | `quality_baseline.json` |
| Published/age | Validity/freshness | `YYYY-MM-DD`, age ≥ 0 và ≤ 180 | Pass: 0 lỗi | `quality_baseline.json` |

Baseline có latest publication 2026-08-05, oldest 2026-02-12, max age 175 ngày và 0/24 stale rows, nên trạng thái là **fresh** theo ngưỡng 180 ngày. Tổng thể quality đạt **PASS, 12/12 checks**.

## 9. Corruption scenarios và repair

| Corruption | Cách tạo | Số record | Signal/tác động thực tế | Repair |
| --- | --- | --: | --- | --- |
| Drop latest | Xóa 4 records mới nhất | 4 | Thiếu 2 test documents; retrieval giảm | Rebuild từ raw snapshot |
| Stale date | Đổi ngày các records mới về năm 2000 | 4 | 4 stale rows, max age 9.533 ngày | Parse lại ngày raw |
| Blank summary | Xóa abstract | 4 | `summary_not_null` và `summary_min_length` fail | Clean lại raw summary |
| Inject noise | Chèn HTML, boilerplate, ký tự ngẫu nhiên | 4 | Nhiễu đi vào `text_for_embedding` | Clean lại raw text |
| Truncate title | Cắt còn 18 ký tự | 3 | Giảm tín hiệu title trong embedding | Khôi phục title raw |
| Duplicate rows | Nhân bản, giữ nguyên ID | 3 | 3 duplicate IDs/titles | Deduplicate khi cleaning raw |

`data/results/corruption_log.json` có đầy đủ seed, tham số, paper IDs, số lượng, chi tiết từng event và test-set overlap. Từ 24 rows, flow xóa 4 rồi thêm 3 duplicates nên corrupted còn 23 rows. Có 7/8 test documents bị ít nhất một scenario tác động và không scenario nào thiếu test-set hit.

Repair không sửa trực tiếp corrupted JSON hoặc metrics. Flow đọc lại `data/raw/crossref_records.json`, chạy cùng hàm `build_clean_dataframe`, build collection `papers-repaired` mới rồi đánh giá lại trên frozen test set. Việc repaired có 24 rows, 12/12 checks và metric trùng baseline chứng minh nguồn phục hồi là raw snapshot đáng tin cậy.

## 10. So sánh baseline, corrupted và repaired

| Metric/signal | Baseline | Corrupted | Repaired | Delta corruption | Phục hồi từ corrupted | Nhận xét |
| --- | --: | --: | --: | --: | --: | --- |
| `retrieval_hit_rate` | 1,0000 | 0,7500 | 1,0000 | -0,2500 | +0,2500 | Phục hồi hoàn toàn |
| `mean_token_f1` | 0,9314 | 0,7135 | 0,9314 | -0,2180 | +0,2180 | Phục hồi hoàn toàn |
| `judge_accuracy` | 1,0000 | 0,7500 | 1,0000 | -0,2500 | +0,2500 | Heuristic, không độc lập |
| `mean_judge_score` | 4,5000 | 3,6875 | 4,5000 | -0,8125 | +0,8125 | Heuristic, không độc lập |
| Quality checks | 12/12 PASS | 7/12 FAIL | 12/12 PASS | -5 checks | +5 checks | Null, duplicate và stale được phát hiện |
| Freshness | Fresh, 0 stale | Stale, 4 stale | Fresh, 0 stale | Fresh → stale | Stale → fresh | Max age 175 → 9.533 → 175 ngày |

Hai chuỗi bằng chứng chính:

1. Xóa các document mới và làm hỏng nội dung/metadata có chủ đích, đồng thời bảo đảm giao với test set → quality mất 5 checks và freshness chuyển stale → hit rate giảm 25 điểm phần trăm, kéo mean token F1 giảm 0,2180.
2. Dựng lại dữ liệu từ raw snapshot → 24 rows, unique/completeness/freshness trở lại 12/12 PASS → hit rate và token F1 trùng hoàn toàn baseline.

Các scenario được áp dụng cùng lúc nên artifact chứng minh tác động tổng hợp của corruption flow; chưa đủ để quy toàn bộ mức giảm metric cho riêng một scenario.

## 11. Vấn đề tích hợp quan trọng

- **Triệu chứng:** Sau khi build index, evaluate báo `chromadb.errors.NotFoundError` vì collection UUID không còn tồn tại.
- **Nguyên nhân:** `build()` tạo collection mới nhưng constructor lại lấy collection theo tên qua một `PersistentClient` dùng cache trong cùng process; cache trả handle trỏ tới UUID cũ đã bị xóa.
- **Cách xử lý:** Cho constructor nhận optional `client` và `collection`; `build()` truyền trực tiếp handle vừa tạo, còn `load()` mới lookup theo tên.
- **Cách xác minh:** Chạy lại baseline rồi corruption flow; ba collection được build/query nối tiếp và sinh đủ metrics/reports. Vector cache được loại khỏi Git vì có thể tái tạo từ manifest và clean artifacts.

## 12. Giới hạn và hướng cải thiện

| Giới hạn hiện tại | Ảnh hưởng | Hướng cải thiện có thể kiểm chứng |
| --- | --- | --- |
| Gemini free-tier trả 429, agent lỗi 32/32 câu | Chưa có bằng chứng agent/LLM run hoàn chỉnh | Đổi provider hoặc chờ quota, chạy lại pha 1; yêu cầu `agent_errors = 0` |
| Judge fallback heuristic | Judge metrics phụ thuộc token F1, không độc lập | Chạy LLM judge và kiểm tra `judge_fallback_count = 0` |
| Ragas chưa bật | Thiếu nhóm metric Ragas | Chạy với `RUN_RAGAS=1` và lưu kết quả |
| Corruptions chạy đồng thời | Chưa định lượng contribution riêng từng lỗi | Ablation: mỗi run chỉ bật một scenario, giữ seed/test set |
| Crossref là nguồn sống | Snapshot mới có thể đổi corpus | Ghi fetch metadata/hash và giữ raw snapshot của lần nộp |

## 13. Checklist trước khi nộp

- [x] Thông tin 3 thành viên, ownership và repository đã điền.
- [x] Baseline, corrupted và repaired dùng cùng `data/eval/test_set.json`.
- [x] Bảng metrics khớp các JSON trong `data/results/`.
- [x] Quality/freshness conclusions khớp artifacts trong `data/quality/`.
- [x] Các đường dẫn báo cáo và artifact tồn tại.
- [x] Mỗi thành viên có báo cáo vai trò riêng.
- [x] Không có `.env`, API key, token hoặc secret trong báo cáo.
- [ ] Chạy lại agent evaluation thành công sau khi có quota/provider khả dụng.
- [ ] Cả nhóm rà soát lại tên nhóm và ngày nộp trước khi commit.
