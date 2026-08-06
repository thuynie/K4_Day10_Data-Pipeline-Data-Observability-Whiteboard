# Phase 1 - Baseline pipeline report

_Generated at: 2026-08-06T14:07:17.585073+00:00_

## Source

| Field | Value |
| --- | --- |
| `source_api` | Crossref REST API |
| `source_query` | agentic retrieval augmented generation large language model |
| `source_filter` | from-pub-date:2026-02-07,has-abstract:true |
| `max_results` | 24 |
| `raw_records` | 24 |
| `clean_rows` | 24 |
| `dropped_rows` | 0 |
| `embedding_model` | gemini-embedding-001 |
| `embedding_dimensions` | 1536 |
| `collection_name` | papers-baseline |
| `llm_provider` | gemini |
| `llm_model` | gemini-2.5-flash |
| `top_k` | 4 |
| `judge_fallback_count` | 32/32 |
| `clean_csv` | /home/trungdq/AITHUCCHIEN/Labs_đang_làm/K4_Day10_Data-Pipeline-Data-Observability-Whiteboard/data/clean/papers_clean.csv |
| `clean_json` | /home/trungdq/AITHUCCHIEN/Labs_đang_làm/K4_Day10_Data-Pipeline-Data-Observability-Whiteboard/data/clean/papers_clean.json |
| `embeddings_manifest` | /home/trungdq/AITHUCCHIEN/Labs_đang_làm/K4_Day10_Data-Pipeline-Data-Observability-Whiteboard/data/embeddings/papers_embeddings.json |
| `eval_testset` | /home/trungdq/AITHUCCHIEN/Labs_đang_làm/K4_Day10_Data-Pipeline-Data-Observability-Whiteboard/data/eval/test_set.json |
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

### Ragas

| Metric | Value |
| --- | --- |
| `skipped` | Set RUN_RAGAS=1 to enable the slower Ragas pass. |


## Agent evaluation

Cung test set, cung ground truth, khac cach sinh cau tra loi:
`deterministic` di qua `qa.answer_question` (khong goi LLM, dung lam moc so sanh cho Pha 2), `agent` di qua `create_agent` voi hai tool.

| Metric | Deterministic | Agent | Δ |
| --- | --- | --- | --- |
| Retrieval hit rate | 1.0000 | 0.0000 | -1.0000 |
| Mean token F1 | 0.9314 | 0.0000 | -0.9314 |
| Judge accuracy | 1.0000 | 0.0000 | -1.0000 |
| Mean judge score | 4.5000 | 1 | -3.5000 |

> 32/32 cau agent khong tra loi duoc. Phan hut nay den tu loi ha tang (rate limit, timeout), khong phai tu chat luong du lieu.


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
