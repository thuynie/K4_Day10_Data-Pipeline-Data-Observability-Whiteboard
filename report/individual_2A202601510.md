# Member Role Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Đặng Quang Trung |
| MSSV | 2A202601510 |
| Khóa/Lớp | K4 |
| Tên nhóm | Whiteboard |
| Vai trò chính | Pipeline owner — toàn bộ ingestion → observability → corruption flow; kiêm review code cho các thành viên khác |
| Repository | https://github.com/thuynie/K4_Day10_Data-Pipeline-Data-Observability-Whiteboard |
| Ngày hoàn thành | 2026-08-06 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Raw ingestion | `src/ingestion/crossref.py` — `fetch_source_records`, `parse_crossref_payload` | Crossref REST API | `data/raw/crossref_response.json`, `crossref_records.json` (24 records) | Hoàn thành |
| Cleaning & data modeling | `src/ingestion/cleaning.py` — `build_clean_dataframe`, `save_clean_dataframe` | 24 `PaperRecord` | `data/clean/papers_clean.{csv,json}` (24 dòng, 16 cột) | Hoàn thành |
| Embedding & vector store | `src/retrieval/index.py` — `LocalEmbeddingIndex` | cleaned DataFrame | Chroma collection `papers-baseline`, `data/embeddings/papers_embeddings.json` | Hoàn thành |
| Evaluation set | `src/evaluation/testset.py` — `build_test_set` | cleaned DataFrame | `data/eval/test_set.json` (32 câu, 4 loại) | Hoàn thành |
| Evaluation & metrics | `src/evaluation/metrics.py` — `evaluate_pipeline`, `evaluate_agent_pipeline`, `judge_provenance` | test set + index | `baseline_metrics.json`, `baseline_answers.json`, `agent_*.json` | Hoàn thành (agent eval bị chặn bởi quota, xem mục 6) |
| Data quality & freshness | `src/observability/quality.py` — `run_data_quality_checks`, `build_freshness_report` | cleaned/corrupted/repaired DataFrame | `data/quality/quality_{baseline,corrupted,repaired}.json`, `freshness_*.json`, `gx/*_gx_result.json` | Hoàn thành |
| Reporting | `src/observability/reporting.py` — `generate_phase1_report`, `generate_corruption_report` | các dict artifact | `data/reports/phase1_report.md`, `corruption_report.md` | Hoàn thành |
| Baseline orchestration | `src/pipelines/phase1.py` | settings | toàn bộ artifact Pha 1 | Hoàn thành |
| Corruption & repair flow | `src/ingestion/corruption.py`, `src/pipelines/corruption_flow.py` | cleaned baseline + raw snapshot | `corrupted_*`, `repaired_*`, `corruption_log.json` | Hoàn thành |
| Test tự động | `tests/test_observability.py` | — | 15 test, pass 15/15 | Hoàn thành |
| Tiện ích vận hành | `script/rebuild_reports.py` | artifact JSON có sẵn | dựng lại markdown report không gọi LLM | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Debug lỗi ChromaDB `NotFoundError` | `src/retrieval/index.py` (module dùng chung) | Sửa root cause, pipeline chạy được end-to-end — chi tiết mục 6 |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Thu thập 24 paper từ Crossref có retry/backoff | `crossref.py:262-293` | 2 raw artifact | `ls data/raw/` |
| Làm sạch, loại record summary < 100 ký tự, dựng `text_for_embedding` | `cleaning.py:118,151` | 24 dòng sạch | `python -c "import pandas;print(pandas.read_csv('data/clean/papers_clean.csv').shape)"` |
| Bộ 12 data quality check chia 2 mức critical/warning | `quality.py:262-322` | `quality_baseline.json` — 12/12 PASS | `cat data/quality/quality_baseline.json` |
| Freshness monitoring theo ngưỡng 180 ngày | `quality.py:325-397` | `freshness_report.json` — fresh, 0/24 stale | `cat data/quality/freshness_report.json` |
| 6 kịch bản corruption có seed cố định | `corruption.py`, `corruption_log.json` | 24 → 23 dòng, 22 bản ghi bị tác động | `cat data/results/corruption_log.json` |
| Repair bằng cách chạy lại ingestion từ raw | `corruption_flow.py:132-153` | `repaired_metrics.json` — bằng đúng baseline | `diff data/results/{baseline,repaired}_metrics.json` |
| 15 unit test cho observability | `tests/test_observability.py` | pass 15/15 | `pytest tests/test_observability.py -v` |

Một output cụ thể mà phần việc của tôi tạo ra và dùng để xác minh:

`data/results/corruption_log.json` ghi lại từng event corruption kèm `paper_ids` bị tác động và `testset_hits` — số câu hỏi trong test set trỏ tới đúng những record đó. Nhờ trường này tôi chứng minh được corruption thực sự chạm vào vùng dữ liệu mà evaluation đo, chứ không phải làm hỏng những record không ai hỏi tới. Cả 6 kịch bản đều có `testset_hit_count >= 1`, và `testset_overlap.ok = true`.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Chứng minh bằng số liệu rằng chất lượng dữ liệu quyết định chất lượng câu trả lời của RAG agent. Muốn kết luận đó có giá trị thì phép đo phải cô lập được đúng một biến: dữ liệu. Mọi thứ còn lại — test set, ground truth, embedding model, số chiều, top-k, cách chấm điểm — phải giữ nguyên tuyệt đối giữa ba trạng thái baseline / corrupted / repaired.

### Cách triển khai

**Data quality checks.** 12 check chia hai mức nghiêm trọng. `critical` gồm row count, `paper_id` not-null và unique, `title` not-null và đủ dài, `summary` not-null và >= 100 ký tự, `text_for_embedding` not-null, `published` đúng định dạng `YYYY-MM-DD`, `age_days` không âm. `warning` gồm freshness và title trùng lặp. Cờ `success` của cả run chỉ false khi có check critical fail.

Lý do tách hai mức: dữ liệu cũ là tín hiệu cần theo dõi, không phải lỗi schema. Nếu để freshness làm fail cả run thì mọi lần chạy sau 180 ngày đều FAIL và cờ `success` mất hết sức phân biệt.

Ngưỡng `MIN_SUMMARY_CHARS = 100` được đặt trùng với rule lọc trong `cleaning.py:151`. Hai nơi lệch nhau thì quality check sẽ báo fail trên chính dữ liệu mà cleaning coi là hợp lệ.

**Great Expectations.** Chạy như lớp kiểm tra thứ hai trong `_run_great_expectations`, ghi kết quả vào `data/quality/gx/`. Toàn bộ nằm trong `try/except`: GX đổi API giữa các minor version là chuyện thường, và một thư viện phụ trợ không được phép làm vỡ pipeline. Khi lỗi thì ghi `{"status": "skipped", "reason": ...}` thay vì ném exception. Thực tế cả ba lần chạy đều `status: ok`.

**Freshness.** Ngoài 5 trường bắt buộc còn thêm `stale_ratio`, `days_since_latest`, `min/median/max_age_days` và `stale_examples`. `max_age_days` là trường bắt được kịch bản `stale_published_date` rõ nhất: baseline 175 ngày, corrupted vọt lên 9533 ngày.

**Corruption.** 6 kịch bản, seed cố định `42` để tái lập được: xóa 4 record mới nhất, đẩy 4 ngày xuất bản về năm 2000, xóa trắng 4 summary, chèn nhiễu vào 4 summary, cắt 3 title còn 18 ký tự, nhân đôi 3 record giữ nguyên `paper_id`. Mỗi kịch bản đánh vào một loại tín hiệu quality khác nhau, nên bảng check fail đọc lên là biết corruption nào đã chạy.

**Repair.** Không sửa tay dòng nào. `corruption_flow.py:141` gọi lại `build_clean_dataframe(records, ...)` từ đúng snapshot `data/raw/crossref_records.json`. Đây là lý do phải giữ snapshot raw ở Pha 1 — repair là chạy lại ingestion từ nguồn đáng tin, không phải vá dữ liệu hỏng.

**Reporting.** Cả hai hàm sinh report chỉ đọc lại dict artifact rồi render, không tính lại metric. Tránh đúng lỗi "báo cáo không match artifact thực tế" trong danh sách trừ điểm. Delta trong corruption report luôn tính theo hướng `mới − cũ`, nên dấu âm luôn có nghĩa là tụt giảm, không cần đoán.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | Cleaned DataFrame 16 cột (`paper_id`, `title`, `summary`, `published`, `age_days`, `text_for_embedding`, ...) + `Settings` |
| Output | `quality_{label}.json` (schema thống nhất: `success`, `checks_total/passed/failed`, `critical_failed`, `failed_check_names`, mảng `checks`), `freshness_*.json`, `*_report.md` |
| Module phụ thuộc | `core.config` (đường dẫn, ngưỡng freshness), `core.utils` (ghi JSON/text), `pandas`, `great_expectations` (tùy chọn) |
| Module sử dụng output | `pipelines/phase1.py`, `pipelines/corruption_flow.py`, `observability/reporting.py`, `script/rebuild_reports.py` |
| Điều kiện lỗi cần xử lý | DataFrame rỗng; thiếu cột; GX lỗi import hoặc đổi API; `published` sai định dạng; `age_days` không phải số |

Ba điều kiện lỗi đầu đều có test riêng: `test_empty_dataframe_is_handled`, `test_missing_column_does_not_crash`, và nhánh `except` của `_run_great_expectations`.

### Cách xác minh

```bash
source .venv/bin/activate
pytest tests/test_observability.py -v
python script/run_phase1.py
python script/run_corruption_flow.py
python script/rebuild_reports.py
```

- **Kết quả mong đợi:** 15/15 test pass; baseline quality 12/12 PASS và freshness `fresh`; corrupted quality FAIL với đúng nhóm check tương ứng 6 kịch bản; repaired quay về 12/12 PASS và `fresh`.
- **Kết quả thực tế:** đúng như mong đợi. Baseline 12/12 PASS / fresh; corrupted 7/12 với 5 check fail (`paper_id_unique`, `summary_not_null`, `summary_min_length`, `freshness_within_threshold`, `title_no_duplicates`) và freshness `stale` 4/23; repaired 12/12 PASS / fresh. GX `status: ok` ở cả ba.
- **Artifact/log:** `data/quality/quality_{baseline,corrupted,repaired}.json`, `data/quality/freshness_{report,corrupted,repaired}.json`, `data/quality/gx/`, `data/reports/{phase1_report,corruption_report}.md`. Không file nào chứa secret; `.env` đã nằm trong `.gitignore`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Đề bài mô tả bước 5 là "duyệt test set, gọi agent trả lời". Nhưng nếu dùng LLM agent làm đường đo chính cho cả ba trạng thái thì mỗi lần chạy sẽ ra số khác nhau do LLM sampling, và bảng so sánh baseline/corrupted/repaired mất cơ sở — không phân biệt được bao nhiêu phần chênh lệch đến từ dữ liệu hỏng, bao nhiêu đến từ nhiễu của model.

- **Các phương án đã cân nhắc:**
  1. Chỉ dùng agent. Đúng chữ của đề nhất, nhưng metric dao động và tốn khoảng 130 lượt gọi LLM mỗi lần chạy.
  2. Chỉ dùng `qa.answer_question` (deterministic, retrieve rồi trích field metadata). Ổn định tuyệt đối nhưng không chứng minh được agent chạy được.
  3. Chạy cả hai trên cùng test set, ghi ra hai bộ metric riêng.

- **Phương án đã chọn:** phương án 3. `evaluate_pipeline` (deterministic) là đường đo chính dùng cho bảng so sánh Pha 2; `evaluate_agent_pipeline` là đường đo phụ, trả lời câu hỏi "agent thật có làm được không".

- **Lý do:** Đây là bài lab về *data* observability, nên biến cần cô lập là chất lượng dữ liệu. Đường deterministic cho phép khẳng định chắc chắn: mọi thay đổi metric giữa ba trạng thái đều đến từ dữ liệu, vì không có nguồn ngẫu nhiên nào khác trong đường đó. Đường agent giữ lại phần chứng minh năng lực agent mà không làm ô nhiễm phép đo chính. Chi phí là phải duy trì hai code path, nhưng chúng dùng chung `_token_f1` và `_judge_answer` nên phần trùng lặp nhỏ.

- **Bằng chứng quyết định phù hợp:** `repaired_metrics.json` trùng khít `baseline_metrics.json` tới từng chữ số (`retrieval_hit_rate` 1.0, `mean_token_f1` 0.9314378311928397). Nếu đường đo có yếu tố ngẫu nhiên thì hai file này gần như chắc chắn sẽ lệch nhau, và tôi sẽ không thể kết luận "repair phục hồi hoàn toàn" mà chỉ nói được "repair phục hồi xấp xỉ".

  Để đo `retrieval_hit_rate` của agent một cách trung thực, tôi thêm callback `on_retrieve` vào `build_agent` — hai tool gọi callback với `paper_id` chúng trả về. Không có phần này thì chỉ thấy câu trả lời cuối cùng, không biết agent đã thực sự đọc document nào.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:**

  ```
  chromadb.errors.NotFoundError: Error getting collection:
  Collection [0385675d-bf98-49ca-8875-7046c965dfbd] does not exist.
    File "src/retrieval/index.py", line 148, in search
    File "src/evaluation/metrics.py", line 114, in evaluate_pipeline
  ```

- **Lệnh tái hiện:** `python script/run_phase1.py` — lỗi nổ ở bước evaluate, sau khi index đã build xong.

- **Nguyên nhân gốc:** `LocalEmbeddingIndex.build()` tạo collection rồi trả về `cls(...)`, và constructor đi **lấy lại collection lần thứ hai**:

  ```python
  # build():   client.delete_collection() -> client.create_collection()   (UUID mới)
  # __init__(): chromadb.PersistentClient(...) -> get_collection(name=...)
  ```

  `chromadb.PersistentClient` dùng chung một `System` cho mỗi path trong cùng process, nên client thứ hai không phải instance mới — nó dùng lại cache đã có, và cache đó vẫn map tên collection tới UUID **trước khi bị xóa**. `get_collection()` trả về object trỏ tới UUID chết; lỗi chỉ lộ ra lúc `query()`.

  Bằng chứng: sqlite chỉ chứa một collection `papers-baseline` với UUID khác hẳn UUID trong thông báo lỗi, và `data/chroma/` có 4 thư mục segment mồ côi — rác của các collection đã bị xóa ở những lần chạy trước.

- **Cách xử lý:** Constructor nhận thêm hai tham số optional `client` và `collection`. `build()` truyền thẳng client và collection nó vừa tạo xuống, không fetch lại lần hai. Nhánh `load()` giữ nguyên `get_collection()` vì nó chạy trong process mới nên cache sạch, chỉ bổ sung thông báo lỗi rõ ràng thay cho exception khó hiểu của chroma.

- **Cách xác minh sau khi sửa:** `rm -rf data/chroma && python script/run_phase1.py` chạy hết end-to-end, sinh đủ artifact; sau đó `run_corruption_flow.py` build tiếp hai collection `papers-corrupted` và `papers-repaired` trên cùng store mà không lỗi.

- **Điều học được:** Cache ẩn ở tầng thư viện là loại bug khó thấy nhất, vì code đọc lên hoàn toàn hợp lý — "tạo xong thì lấy ra dùng". Nguyên tắc rút ra: khi đã có sẵn một handle vào tài nguyên vừa tạo thì dùng lại nó, đừng tra cứu lại qua tên. Mỗi lần tra cứu lại là một cơ hội để cache trả về thứ đã cũ.

### Blocker chưa xử lý xong

- **Triệu chứng:** `evaluate_agent_pipeline` lỗi toàn bộ 32/32 câu.

  ```
  ChatGoogleGenerativeAIError: 429 RESOURCE_EXHAUSTED
  Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests,
  limit: 20, model: gemini-2.5-flash
  ```

- **Phạm vi bị ảnh hưởng:** `data/results/agent_metrics.json` toàn giá trị 0 — đây là lỗi hạ tầng, **không phải kết quả đo lường**. Nghiêm trọng hơn: `_judge_answer` không ném lỗi khi không gọi được LLM mà lặng lẽ đổi sang heuristic token-overlap, nên **cả baseline lẫn corrupted lẫn repaired đều có 32/32 câu dùng heuristic judge**. `judge_accuracy` và `mean_judge_score` trong bài này vì vậy chỉ là hàm bậc thang của `token_f1` (`>=0.95 → 5`, `>=0.5 → 3`, còn lại `→ 1`), không phải đánh giá độc lập của LLM.

- **Những gì đã loại trừ:** Không phải lỗi code hay lỗi cấu hình — cùng đường code đó chạy được ở các lần trước khi quota còn; thông báo lỗi chỉ đích danh quota free tier của model.

- **Cách xử lý tạm thời:** Thêm `judge_provenance()` ghi `judge_source` / `judge_fallback_count` thẳng vào file metrics, và cảnh báo nổi bật trong cả hai report. Section "Agent evaluation" khi hỏng toàn bộ sẽ in nguyên văn lỗi thay vì bảng số 0 — bảng toàn 0 rất dễ bị đọc nhầm thành "agent trả lời sai".

- **Bước tiếp theo:** Chờ quota reset hoặc đổi `LLM_PROVIDER` sang OpenRouter/Ollama trong `.env`, chạy lại `run_phase1.py`, rồi `python script/rebuild_reports.py`. Hai chỉ số `retrieval_hit_rate` và `mean_token_f1` hoàn toàn không phụ thuộc LLM nên kết luận chính của bài lab không bị ảnh hưởng.

## 7. Hiểu biết về luồng end-to-end

**1. Dữ liệu đi từ Crossref đến vector index như thế nào?**

`fetch_source_records` gọi `https://api.crossref.org/works` với query `agentic retrieval augmented generation large language model` và filter `from-pub-date:...,has-abstract:true`, có retry 3 lần với backoff `2^n` cho các mã lỗi tạm thời (429, 5xx). Response thô lưu vào `crossref_response.json` để audit nguồn; bản đã parse phẳng theo schema `PaperRecord` (11 trường) lưu vào `crossref_records.json`. `build_clean_dataframe` strip HTML/XML, gộp `authors`/`categories`, tính `age_days`, loại record có summary dưới 100 ký tự, khử trùng theo `paper_id`, rồi dựng cột `text_for_embedding` theo format `Title: ... | Authors: ... | Summary: ...`. Chính cột đó được đưa qua `gemini-embedding-001` (1536 chiều) và nạp vào collection Chroma với `space: cosine`.

**2. Evaluation set và ground-truth document IDs dùng để đo retrieval/answer quality ra sao?**

Test set gồm 32 câu sinh từ dữ liệu sạch, chia 4 loại đều nhau (`summary`, `authors`, `date`, `categories`), mỗi câu mang theo `ground_truth` và `ground_truth_doc_ids`. Hai chỉ số đo hai tầng khác nhau: `retrieval_hit_rate` đo **tầng retrieval** — trong `top_k=4` document lấy về có ít nhất một cái nằm trong `ground_truth_doc_ids` không; `mean_token_f1` đo **tầng sinh câu trả lời** — độ chồng lấp tập token giữa câu trả lời và ground truth. Tách hai tầng là cần thiết vì retrieval hỏng và diễn đạt hỏng cần hai cách sửa khác nhau.

**3. Quality checks khác freshness monitoring ở điểm nào?**

Quality check hỏi "dữ liệu có đúng hình dạng không" — trả lời được ngay tại thời điểm chụp, không cần biết hôm nay là ngày nào. Freshness hỏi "dữ liệu có còn kịp thời không" — câu trả lời phụ thuộc thời điểm chạy, cùng một dataset hôm nay `fresh` thì sáu tháng sau thành `stale` dù không ai đụng vào. Vì khác bản chất nên trong code tôi để chúng khác mức nghiêm trọng: quality fail là `critical`, freshness fail chỉ là `warning`.

**4. Vì sao phải dùng cùng test set cho cả ba trạng thái?**

Vì `ground_truth` và `ground_truth_doc_ids` là hệ quy chiếu. Nếu sinh lại test set trên dữ liệu đã hỏng thì ground truth hỏng theo — câu hỏi về một paper đã bị xóa sẽ biến mất khỏi bộ đề, và corrupted sẽ được chấm trên bộ đề dễ hơn baseline. Lúc đó metric có thể còn *đẹp hơn* baseline, và kết luận sẽ ngược hoàn toàn với thực tế. Trong code, `phase1.py` chỉ build test set khi file chưa tồn tại hoặc khi bật `REFRESH_TEST_SET=1`, và corruption flow không bao giờ build lại.

**5. Repair được xem là thành công dựa trên artifact và metric nào?**

Ba tầng bằng chứng phải cùng phục hồi:

- **Quality:** `quality_repaired.json` trở lại `success: true`, 12/12 check pass, `total_rows` về đúng 24.
- **Freshness:** `freshness_repaired.json` về `status: fresh`, `stale_rows: 0`, `max_age_days` từ 9533 về 175, `latest_published` từ `2026-06-15` về `2026-08-05`.
- **Agent metrics:** `repaired_metrics.json` trùng khít baseline.

Chỉ một tầng phục hồi thì chưa đủ. Ví dụ nếu metric phục hồi nhưng quality vẫn fail thì nhiều khả năng repair chỉ vá phần dữ liệu mà test set chạm tới, chứ chưa dựng lại đúng dataset.

## 8. Phân tích kết quả

### Metrics chính

| Metric/signal | Baseline | Corrupted | Repaired | Nhận xét của cá nhân |
| --- | ---: | ---: | ---: | --- |
| `retrieval_hit_rate` | 1.0000 | 0.7500 | 1.0000 | Mất 8/32 câu. Đây là tầng bị đánh trực tiếp: 4 record bị xóa khỏi index thì không cách nào retrieve lại được. |
| `mean_token_f1` | 0.9314 | 0.7135 | 0.9314 | Giảm 0.2180. Vừa do retrieval trượt, vừa do summary bị xóa trắng/chèn nhiễu làm câu trả lời lệch từ vựng. |
| `judge_accuracy` | 1.0000 | 0.7500 | 1.0000 | Trùng khít `retrieval_hit_rate` — vì judge đang chạy heuristic bậc thang trên `token_f1`, không phải LLM (xem mục 6). Không đọc đây như đánh giá độc lập. |
| `mean_judge_score` | 4.5000 | 3.6875 | 4.5000 | Cùng hạn chế như trên. |
| Quality checks | 12/12 PASS | 7/12 FAIL | 12/12 PASS | 5 check fail: `paper_id_unique`, `summary_not_null`, `summary_min_length`, `freshness_within_threshold`, `title_no_duplicates`. |
| Freshness status | fresh (0/24) | stale (4/23) | fresh (0/24) | `max_age_days` 175 → 9533 → 175; `latest_published` 2026-08-05 → 2026-06-15 → 2026-08-05. |

### Kết luận từ số liệu

1. **Xóa 4 record mới nhất + xóa trắng 4 summary + nhân đôi 3 record** → quality từ 12/12 xuống 7/12 (`summary_not_null`, `summary_min_length`, `paper_id_unique` fail), freshness từ `fresh` sang `stale` với `max_age_days` vọt lên 9533 → `retrieval_hit_rate` 1.0 → 0.75 và `mean_token_f1` 0.9314 → 0.7135.

2. **Chạy lại `build_clean_dataframe` từ snapshot `data/raw/crossref_records.json`** → quality về 12/12 PASS, freshness về `fresh` 0/24 stale → `retrieval_hit_rate` và `mean_token_f1` về đúng bằng baseline tới từng chữ số thập phân.

**Corruption nào ảnh hưởng rõ nhất và vì sao?**

`drop_latest_records`. Nó chạm 2 trong 8 document có mặt trong test set — nhiều nhất trong 6 kịch bản, ngang với `duplicate_rows` — nhưng khác biệt nằm ở chỗ nó là kịch bản **không thể cứu được ở tầng retrieval**. Các kịch bản khác chỉ làm giảm chất lượng nội dung: summary bị xóa trắng hay title bị cắt còn 18 ký tự thì document vẫn nằm trong index, embedding vẫn tồn tại, câu hỏi vẫn có thể retrieve trúng — chỉ là câu trả lời sinh ra kém đi, tức mất điểm ở `mean_token_f1`. Còn record đã bị xóa thì không có vector nào trong collection để tìm, nên mất trọn điểm `retrieval_hit_rate`. Đó là lý do `retrieval_hit_rate` rơi 0.25 trong khi `mean_token_f1` chỉ rơi 0.218 — mức giảm của retrieval khớp gần đúng với tỉ lệ record bị xóa.

**Kết quả nào khác với kỳ vọng ban đầu?**

Tôi nghĩ repaired sẽ *xấp xỉ* baseline chứ không trùng khít tuyệt đối, vì mường tượng còn yếu tố ngẫu nhiên đâu đó trong embedding hoặc retrieval. Thực tế `diff data/results/{baseline,repaired}_metrics.json` không ra khác biệt nào.

Giả thuyết ban đầu của tôi là embedding có nhiễu. Cách kiểm tra: đối chiếu `papers_embeddings.json` và `papers_embeddings_repaired.json` — cả hai cùng `embedding_model`, `embedding_dimensions: 1536`, `task_type_document`, `document_count: 24`. Kết luận: đường đo hoàn toàn tất định — `qa.answer_question` không gọi LLM, embedding là hàm thuần túy của `text_for_embedding`, và repair dựng lại đúng cùng một `text_for_embedding` từ cùng một snapshot raw. Không có chỗ nào cho ngẫu nhiên. Đây hóa ra lại là bằng chứng mạnh nhất cho quyết định ở mục 5.

Một điểm bất ngờ thứ hai: `retrieval_hit_rate` baseline đạt trần 1.0. Ban đầu tôi tưởng đó là dấu hiệu tốt, sau mới nhận ra nó phản ánh bài toán đang dễ — test set sinh từ chính metadata, và hit rate tính ở mức top-4 nên chỉ cần trúng 1 trong 4 là đủ. Chỉ số chạm trần thì không còn khả năng phân biệt ở phía trên; may là nó vẫn phân biệt tốt ở phía dưới, đúng chiều mà bài lab cần đo.

## 9. Điều học được và hướng cải thiện

### Ba điều quan trọng nhất

1. **Về data pipeline:** Lưu raw response thô là thứ trông như dư thừa cho tới lúc cần repair. Toàn bộ bước repair của Pha 2 chỉ là chạy lại `build_clean_dataframe` trên `crossref_records.json` — không có snapshot đó thì không có cách nào phục hồi mà không gọi lại API, và gọi lại API thì dữ liệu đã khác, cột "Repaired" mất ý nghĩa so sánh. Raw snapshot không phải bản backup, nó là điểm tựa của phép đo.

2. **Về data quality/observability:** Tín hiệu quality chỉ hữu ích khi phân được mức nghiêm trọng. Ban đầu tôi định cho mọi check cùng trọng số, nhưng như vậy thì một dataset chỉ hơi cũ sẽ bị đánh FAIL ngang với dataset mất sạch `paper_id`. Tách `critical` và `warning` giúp cờ `success` giữ được sức phân biệt. Bài học thứ hai cùng loại: fallback im lặng nguy hiểm hơn lỗi ồn ào — `_judge_answer` âm thầm đổi sang heuristic khiến tôi suýt trình bày `judge_accuracy: 1.0` như điểm do LLM chấm.

3. **Về ảnh hưởng của data đến RAG agent:** Các loại lỗi dữ liệu không tác động ngang nhau, và chúng tác động ở những tầng khác nhau. Mất record thì hỏng ở tầng retrieval, không cứu được bằng model tốt hơn. Hỏng nội dung thì retrieval vẫn trúng nhưng câu trả lời kém, và đó là chỗ một agent tốt hơn có thể bù lại phần nào. Phân biệt được hai loại này thì mới biết nên đầu tư vào đâu.

### Nếu có thêm thời gian

Đo lại toàn bộ với LLM judge thật thay vì heuristic, bằng cách chuyển `LLM_PROVIDER` sang Ollama local để không bị chặn bởi quota. Hiện `judge_accuracy` đang trùng khít `retrieval_hit_rate` ở cả ba trạng thái (1.0 / 0.75 / 1.0) — dấu hiệu rõ ràng cho thấy nó không mang thêm thông tin nào ngoài `token_f1`. Cách đo cải thiện: chạy lại và kiểm tra `judge_source == "llm"` trong ba file metrics, rồi xem `judge_accuracy` có còn trùng khít `retrieval_hit_rate` nữa không. Nếu hai đường tách ra, chỉ số judge mới thực sự đóng góp một góc nhìn độc lập — cụ thể là bắt được những câu retrieve trúng nhưng trả lời sai, thứ mà `token_f1` chấm điểm khá cao chỉ vì trùng từ vựng.

## 10. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Mọi kết luận về kết quả đều có artifact hoặc metric để đối chiếu.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng — agent evaluation được ghi rõ là thất bại do quota tại mục 6 và mục 8.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Đặng Quang Trung
**Ngày xác nhận:** 2026-08-06
