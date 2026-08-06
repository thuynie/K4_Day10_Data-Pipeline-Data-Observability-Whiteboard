# Phase 1 - Baseline pipeline report

_Generated at: 2026-08-06T15:15:54.457998+00:00_

## Source

| Field | Value |
| --- | --- |
| `source_api` | Crossref REST API |
| `source_query` | agentic retrieval augmented generation large language model |
| `source_filter` | from-pub-date:2026-02-07,has-abstract:true |
| `llm_provider` | gemini |
| `llm_model` | gemini-2.5-flash |
| `embedding_model` | gemini-embedding-001 |
| `top_k` | 4 |
| `note` | Report dung lai tu artifact co san (rebuild_reports.py), khong chay lai pipeline. |
| `baseline_metrics` | /home/trungdq/AITHUCCHIEN/Labs_đang_làm/K4_Day10_Data-Pipeline-Data-Observability-Whiteboard/data/results/baseline_metrics.json |
| `agent_metrics` | /home/trungdq/AITHUCCHIEN/Labs_đang_làm/K4_Day10_Data-Pipeline-Data-Observability-Whiteboard/data/results/agent_metrics.json |


## Evaluation metrics

| Metric | Value |
| --- | --- |
| Samples | 32 |
| Retrieval hit rate | 1.0000 |
| Mean token F1 | 0.9314 |
| Judge accuracy | 1.0000 |
| Mean judge score | 4.5000 |

> **Luu y:** toan bo 32/32 cau dung heuristic judge, KHONG phai LLM (thuong do het quota hoac thieu API key). `judge_accuracy` va `mean_judge_score` o day chi la ham bac thang cua `token_f1` (>=0.95 -> 5, >=0.5 -> 3, con lai -> 1), khong phai danh gia doc lap. Khong so sanh hai con so nay voi lan chay co LLM that.

### Ragas

| Metric | Value |
| --- | --- |
| `skipped` | Set RUN_RAGAS=1 to enable the slower Ragas pass. |


## Agent evaluation

**Khong chay duoc.** Ca 32/32 cau deu loi, nen `agent_metrics.json` toan gia tri 0 - day la loi ha tang, KHONG phai ket qua do luong. Khong duoc doc bang nay nhu la agent tra loi sai.

Loi dau tien:

```
khong ro
```

Chay lai sau khi quota reset, hoac doi `LLM_PROVIDER` sang provider khac trong `.env`, roi chay `script/rebuild_reports.py` de cap nhat report.


## Data quality

| Metric | Value |
| --- | --- |
| Overall | PASS |
| Total rows | 24 |
| Checks passed | 12/12 |
| Success rate | 1.0000 |
| Critical failed | 0 |
| Warning failed | 0 |
| GX engine | ok |


### Chi tiet tung check

| Check | Severity | Result | Expected | Observed | Detail |
| --- | --- | --- | --- | --- | --- |
| `row_count_min` | critical | PASS | >= 5 rows | 24 | - |
| `paper_id_not_null` | critical | PASS | `paper_id` khong rong o moi dong | 0 | - |
| `paper_id_unique` | critical | PASS | `paper_id` unique | 0 | - |
| `title_not_null` | critical | PASS | `title` khong rong o moi dong | 0 | - |
| `title_min_length` | critical | PASS | len(`title`) >= 10 | 0 | - |
| `summary_not_null` | critical | PASS | `summary` khong rong o moi dong | 0 | - |
| `summary_min_length` | critical | PASS | len(`summary`) >= 100 | 0 | - |
| `text_for_embedding_not_null` | critical | PASS | `text_for_embedding` khong rong o moi dong | 0 | - |
| `published_format` | critical | PASS | `published` theo dinh dang YYYY-MM-DD | 0 | - |
| `age_days_non_negative` | critical | PASS | `age_days` la so >= 0 | 0 | - |
| `freshness_within_threshold` | warning | PASS | age_days <= 180 | 0 | - |
| `title_no_duplicates` | warning | PASS | khong co title trung lap (case-insensitive) | 0 | - |



## Freshness

| Field | Value |
| --- | --- |
| Status | fresh |
| Is fresh | yes |
| Threshold (days) | 180 |
| Total rows | 24 |
| Stale rows | 0 |
| Stale ratio | 0.0000 |
| Latest published | 2026-08-05 |
| Oldest published | 2026-02-12 |
| Days since latest | 1 |
| Age min / median / max | 1 / 66.0 / 175 |


## Ket luan

- Retrieval hit rate `1.0000` -> muc tot.
- Data quality PASS (12/12 checks).
- Dataset fresh: khong co dong nao cu hon 180 ngay.
