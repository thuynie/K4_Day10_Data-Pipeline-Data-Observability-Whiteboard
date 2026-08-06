# Báo cáo cá nhân — Dương Tiến Dũng — Evaluation & Observability

## 1. Thông tin cá nhân

| Thông tin | Nội dung                                                                        |
|---|---------------------------------------------------------------------------------|
| Họ và tên | Dương Tiến Dũng                                                                 |
| MSSV | 2A202602020                                                                     |
| Khóa/Lớp | K4                                                                              |
| Tên nhóm | Whiteboard                                                              |
| Vai trò chính | Evaluation & Observability Owner                                                |
| Repository | https://github.com/thuynie/K4_Day10_Data-Pipeline-Data-Observability-Whiteboard |
| Ngày hoàn thành | 2026-08-06                                                                      |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
|---|---|---|---|---|
| Evaluation test set | `src/evaluation/testset.py` — `build_test_set` | Cleaned DataFrame | `data/eval/test_set.json` | Hoàn thành và đã kiểm chứng |
| Data quality | `src/observability/quality.py` — `run_data_quality_checks` | Cleaned/corrupted/repaired DataFrame và `Settings` | JSON quality report theo từng trạng thái | Hoàn thành và đã kiểm chứng với baseline sạch và dữ liệu lỗi tổng hợp |
| Freshness monitoring | `src/observability/quality.py` — `build_freshness_report` | `published`, `age_days`, freshness threshold | `data/quality/freshness_report.json` | Hoàn thành và đã kiểm chứng |
| Baseline reporting | `src/observability/reporting.py` — `generate_phase1_report` | Source summary, metrics, quality, freshness | `data/reports/phase1_report.md` | Hoàn thành hàm và đã smoke test |
| Corruption comparison reporting | `src/observability/reporting.py` — `generate_corruption_report` | Metrics/quality/freshness của ba trạng thái | `data/reports/corruption_report.md` | Hoàn thành hàm và đã smoke test |

Tôi chỉ nhận ownership trực tiếp cho ba file `testset.py`, `quality.py` và `reporting.py`. Hoàng Thị Thuyên phụ trách `crossref.py`, `cleaning.py`; thành viên 3 phụ trách `corruption.py`, `phase1.py`, `corruption_flow.py`.

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
|---|---|---|
| Kiểm tra data contract | Cleaning và retrieval/index | Xác nhận test set dùng `paper_id` tồn tại trong clean corpus và question có exact title để lookup |
| Kiểm tra môi trường | Toàn nhóm | Đồng bộ 160 package theo `uv.lock`, cài project editable và xử lý lỗi `ModuleNotFoundError: core` |
| Kiểm tra tương thích Ragas | Evaluation metrics | Xác nhận đường chạy qua compatibility shim trong `metrics.py` import được Ragas |
| Bảo vệ phạm vi commit | Repository chung | Không stage `.idea/`; chỉ hướng dẫn commit đúng ba module và báo cáo/artifact thuộc phần cá nhân |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
|---|---|---|---|
| Tạo evaluation set xác định | `build_test_set`, `data/eval/test_set.json` | 12 sample từ 3 paper, đủ 4 question type | Đọc JSON và kiểm tra schema/ID |
| Kiểm tra chất lượng baseline | `run_data_quality_checks`, `data/quality/baseline_quality.json` | 9/9 check đạt, 0 check thất bại trên 24 dòng sạch | Đọc `success`, `checks_passed`, `checks_failed` |
| Theo dõi freshness | `build_freshness_report`, `data/quality/freshness_report.json` | Trạng thái `fresh`, 0/24 dòng stale | Đọc freshness JSON |
| Kiểm tra khả năng phát hiện lỗi | `run_data_quality_checks` với DataFrame lỗi tổng hợp | Phát hiện 6 check thất bại | Chạy lệnh kiểm thử module |
| Kiểm tra Markdown report | Hai hàm trong `reporting.py` | Sinh được baseline/comparison report từ payload truyền vào | Smoke test bằng dữ liệu kiểm thử, không ghi metrics giả vào artifact chính thức |

Output cụ thể đã tạo:

- Clean rows: **24**.
- Evaluation samples: **12**.
- Question types: `summary`, `authors`, `date`, `categories`.
- Baseline quality: **PASS — 9/9 checks**.
- Baseline freshness: **FRESH — 0 stale rows**.
- Latest publication: **2026-08-05**.
- Oldest publication: **2026-02-12**.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Phần việc của tôi giải quyết hai câu hỏi chính:

1. Làm sao tạo một bộ câu hỏi có ground truth rõ ràng để đánh giá retrieval và câu trả lời một cách lặp lại?
2. Làm sao phát hiện dữ liệu đầu vào bị thiếu, trùng, sai schema, summary quá ngắn hoặc quá cũ trước khi lỗi dữ liệu ảnh hưởng tới RAG agent?

Ngoài ra, kết quả evaluation và observability cần được chuyển thành báo cáo Markdown có thể đọc, audit và so sánh giữa baseline, corrupted và repaired.

### Cách triển khai evaluation set

`build_test_set` thực hiện các bước:

1. Kiểm tra DataFrame không rỗng và có đủ các cột bắt buộc.
2. Chuẩn hóa giá trị chuỗi, loại dòng thiếu `paper_id` hoặc `title` và loại `paper_id` trùng.
3. Sắp xếp ổn định theo `paper_id`, sau đó chọn tối đa ba document đại diện. Cùng một clean corpus luôn tạo ra cùng test set dù thứ tự dòng ban đầu thay đổi.
4. Tạo bốn loại câu hỏi cho mỗi document: summary, authors, publication date và categories.
5. Đặt exact title trong dấu nháy đơn để lớp QA có thể vừa semantic search vừa exact-title lookup.
6. Ground truth của summary dùng câu đầu tiên, khớp với logic `_extract_answer` hiện tại trong `retrieval/qa.py`.
7. Mỗi sample chứa đầy đủ `id`, `question_type`, `question`, `ground_truth`, `ground_truth_doc_ids` và được ghi bằng helper `write_json`.

### Cách triển khai data quality và freshness

Quality report gồm chín checks theo các dimension:

| Check | Dimension | Kỳ vọng |
|---|---|---|
| `row_count_positive` | Volume | Có ít nhất một dòng |
| `required_columns_present` | Schema | Có đủ `paper_id`, `title`, `summary`, `published`, `age_days` |
| `paper_id_not_null` | Completeness | Không có ID rỗng |
| `paper_id_unique` | Uniqueness | Không có ID trùng |
| `title_not_null` | Completeness | Không có title rỗng |
| `summary_not_null` | Completeness | Không có summary rỗng |
| `summary_min_length` | Validity | Summary dài ít nhất 100 ký tự |
| `age_days_valid` | Validity | Không null, không âm và là số |
| `rows_within_freshness_threshold` | Freshness | Không vượt ngưỡng 180 ngày |

Mỗi check lưu tên, dimension, trạng thái, observed value và expectation. Overall `success` chỉ bằng `true` khi toàn bộ check đạt; kết quả không được hard-code.

Freshness report parse `published` an toàn, tính latest/oldest publication, stale rows, invalid dates, unknown ages và freshness ratio. Trạng thái là:

- `fresh`: dataset có dữ liệu hợp lệ, không có stale/unknown/invalid row.
- `stale`: có ít nhất một tín hiệu cũ hoặc không hợp lệ.
- `unknown`: dataset rỗng hoặc không có ngày hợp lệ.

### Cách triển khai reporting

Baseline report hiển thị source/config, metrics, từng quality check, freshness và phần diễn giải. Comparison report tạo bảng baseline–corrupted–repaired, tính corruption delta và repair delta, đồng thời liệt kê metrics thực sự giảm hoặc phục hồi. Hàm không tự bịa kết luận: nếu payload không có metric, báo cáo hiển thị `N/A`.

### Input, output và contract

| Thành phần | Mô tả |
|---|---|
| Input | Cleaned DataFrame với schema từ `cleaning.py`; `Settings`; metrics dictionary từ `metrics.py` |
| Output | Evaluation JSON, quality JSON, freshness JSON, baseline Markdown, comparison Markdown |
| Module phụ thuộc | `core.config`, `core.utils`, `ingestion.cleaning`, `evaluation.metrics` |
| Module sử dụng output | `pipelines.phase1`, `pipelines.corruption_flow`, báo cáo nhóm và bước demo |
| Điều kiện lỗi xử lý | DataFrame rỗng, thiếu cột, null/blank, duplicate ID, ngày sai, age âm/null, report thiếu metric |

### Cách xác minh

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip check
python -m compileall -q src
python -c "import core, evaluation, observability; print('Môi trường hoạt động tốt')"
```

Tạo lại artifact thuộc phần cá nhân:

```powershell
python -c "import pandas as pd; from core.config import load_settings; from evaluation.testset import build_test_set; from observability.quality import run_data_quality_checks, build_freshness_report; s=load_settings(); df=pd.read_json(s.paths.clean_json); build_test_set(df, s.paths.eval_testset); run_data_quality_checks(df, s, 'baseline_quality'); build_freshness_report(df, s, s.paths.freshness_report); print('Đã tạo artifact evaluation/quality/freshness')"
```

- **Kết quả mong đợi:** import thành công; tạo test set, baseline quality và freshness JSON.
- **Kết quả thực tế:** 12 samples; quality PASS 9/9; freshness FRESH, 0 stale rows.
- **Artifact:** `data/eval/test_set.json`, `data/quality/baseline_quality.json`, `data/quality/freshness_report.json`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Nếu lấy sample theo vị trí dòng hiện tại, việc cleaning/sort lại có thể làm test set thay đổi giữa các lần chạy. Khi đó comparison baseline–corrupted–repaired không còn công bằng.
- **Các phương án cân nhắc:** (1) random sampling với seed; (2) lấy các dòng đầu tiên theo thứ tự DataFrame; (3) chuẩn hóa, deduplicate và sort ổn định theo `paper_id`.
- **Phương án chọn:** phương án 3, sau đó giữ nguyên artifact test set cho cả ba trạng thái.
- **Lý do:** deterministic, dễ audit, không phụ thuộc row order và không cần quản lý random seed riêng.
- **Bằng chứng:** cùng clean corpus sinh 12 sample có ID ổn định; mỗi `ground_truth_doc_ids` trỏ tới paper ID trong clean corpus.

Một quyết định thứ hai là coi dataset chỉ `fresh` khi không có bất kỳ stale, unknown age hoặc invalid publication date. Tiêu chí nghiêm ngặt này giúp corruption ở một phần dữ liệu vẫn tạo tín hiệu cảnh báo thay vì bị che bởi publication mới nhất.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng:** `ModuleNotFoundError: No module named 'core'` khi chạy Python từ project root.
- **Lệnh tái hiện:** `.\.venv\Scripts\python.exe -c "import core"`.
- **Nguyên nhân gốc:** dependency đã có trong `.venv` nhưng package nằm trong `src/` chưa được cài editable; lệnh `uv` toàn cục cũng chưa tồn tại.
- **Cách xử lý:** nâng `pip/setuptools/wheel`, chạy `pip install -e ".[dev]"`, cài `uv`, sau đó `uv sync --frozen --extra dev` để đồng bộ đúng `uv.lock`.
- **Cách xác minh:** `pip check` báo `No broken requirements found`; import `core`, `evaluation`, `observability` thành công; uv kiểm tra 160 packages.
- **Điều học được:** cài `requirements.txt` đơn thuần không đảm bảo Python tìm thấy package theo layout `src/`; cần cài project editable hoặc dùng `uv sync`.

Blocker tích hợp còn lại không thuộc phạm vi của tôi:

- `src/pipelines/phase1.py`, `src/pipelines/corruption_flow.py` và `src/ingestion/corruption.py` vẫn còn `NotImplementedError`.
- Vì vậy chưa thể xác minh metrics end-to-end hoặc sinh báo cáo chính thức baseline/corrupted/repaired.
- Tôi không ghi nhận pipeline hoàn thành hoặc điền metrics giả khi chưa có artifact.

## 7. Hiểu biết về luồng end-to-end

1. **Dữ liệu từ Crossref đến vector index:** `crossref.py` tải và parse raw response thành `PaperRecord`. `cleaning.py` chuẩn hóa field, loại record không hợp lệ, tính `age_days` và tạo `text_for_embedding`. `index.py` embedding phần text này rồi nạp vector, document ID và metadata vào collection ChromaDB riêng cho từng trạng thái.

2. **Evaluation set và ground-truth IDs:** Mỗi câu hỏi có câu trả lời chuẩn và danh sách paper ID đúng. Evaluator chạy câu hỏi qua QA/index, kiểm tra retrieved IDs có giao với ground-truth IDs để tính retrieval hit, đồng thời so answer với ground truth bằng token F1 và judge.

3. **Quality checks và freshness:** Quality checks kiểm tra nhiều dimension như volume, schema, completeness, uniqueness và validity. Freshness tập trung vào độ mới của dataset qua `published`, `age_days`, threshold và số stale rows. Freshness là một phần quan trọng nhưng không thay thế toàn bộ quality checks.

4. **Vì sao dùng cùng test set:** Nếu thay test set giữa ba trạng thái, thay đổi metric có thể do câu hỏi khác chứ không phải corruption/repair. Khóa cùng một test set giúp phép so sánh có kiểm soát.

5. **Điều kiện repair thành công:** Repaired clean data phải được tạo lại từ raw source đáng tin cậy; quality/freshness phải phục hồi; cùng test set phải được dùng lại; repaired retrieval/answer metrics cần tiến gần hoặc trở lại baseline. Kết luận phải dựa trên JSON answers, metrics, quality, freshness và comparison report.

## 8. Phân tích kết quả

### Metrics và signals hiện có

| Metric/signal | Baseline | Corrupted | Repaired | Nhận xét cá nhân |
|---|---:|---:|---:|---|
| `retrieval_hit_rate` | Chưa có | Chưa có | Chưa có | Chờ orchestration/index chạy end-to-end |
| `mean_token_f1` | Chưa có | Chưa có | Chưa có | Không điền số giả |
| `judge_accuracy` | Chưa có | Chưa có | Chưa có | Cần answers artifact thực tế |
| `mean_judge_score` | Chưa có | Chưa có | Chưa có | Cần evaluator chạy thực tế |
| Quality checks | PASS 9/9 | Synthetic test: FAIL 6 checks | Chưa có | Baseline thật; corrupted ở đây chỉ là test module, chưa phải corruption artifact chính thức |
| Freshness status | FRESH, 0/24 stale | Synthetic test: STALE | Chưa có | Baseline thật; chờ corruption flow chính thức |

### Kết luận từ số liệu hiện tại

- Trên clean artifact hiện có: 24 rows → 9/9 quality checks đạt → freshness FRESH. Đây là bằng chứng observability baseline, chưa phải bằng chứng về agent performance.
- Trên DataFrame lỗi tổng hợp dùng để unit/smoke test: duplicate ID, title/summary thiếu, summary ngắn, ngày sai và age quá ngưỡng → 6 checks thất bại → freshness STALE. Điều này chứng minh module phát hiện được lỗi, nhưng chưa chứng minh retrieval metric giảm.
- Chưa thể hoàn thành chuỗi corruption → agent metric giảm hoặc repair → agent metric phục hồi vì pipeline corruption/orchestration chưa hoàn thiện. Sau khi có artifact, bảng này phải được cập nhật từ `data/results/*.json`.

## 9. Điều học được và hướng cải thiện

### Ba điều quan trọng nhất

1. Evaluation chỉ có ý nghĩa khi test set ổn định, ground truth rõ và document ID truy vết được đến corpus.
2. Data quality cần lưu observed value cho từng check; một cờ pass/fail chung không đủ để debug root cause.
3. Freshness/quality signal và RAG metric phải được nối bằng artifact thực tế; không được kết luận nhân quả chỉ vì corruption đã được tạo.

### Nếu có thêm thời gian

Tôi sẽ bổ sung pytest tự động cho edge cases của ba module và thêm trend report qua nhiều pipeline runs. Cải thiện được đo bằng tỷ lệ branch/edge-case được test, khả năng tái tạo report và thời gian phát hiện regression.

## 10. Nội dung trình bày ngắn

> Em là Dương Tiến Dũng, MSSV 2A202602020, phụ trách Evaluation & Observability. Em hoàn thiện ba module chính. Thứ nhất, `testset.py` tạo bộ evaluation cố định từ cleaned corpus, gồm 12 câu hỏi và bốn loại summary, authors, date, categories; mỗi câu có ground truth và paper ID để chấm retrieval. Thứ hai, `quality.py` kiểm tra chín điều kiện về volume, schema, completeness, uniqueness, summary validity và freshness. Trên 24 dòng clean hiện tại, cả 9 check đều pass và không có dòng stale. Thứ ba, `reporting.py` tạo báo cáo baseline và bảng so sánh baseline–corrupted–repaired, bao gồm delta metrics và quality/freshness signals. Em cũng xử lý lỗi môi trường do project chưa được cài editable và đã đồng bộ 160 package theo uv.lock. Hiện metrics end-to-end chưa có vì các flow orchestration/corruption của phần khác vẫn còn NotImplementedError, nên em không đưa số liệu giả vào báo cáo.

## 11. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Mọi kết luận về kết quả hiện có đều có artifact hoặc lệnh kiểm chứng.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này được viết riêng theo phần việc của tôi.

**Họ và tên:** Dương Tiến Dũng

**Ngày xác nhận:** 2026-08-06
