# Corruption impact report

_Generated at: 2026-08-06T15:15:54.458803+00:00_

Ba trang thai dung chung test set, ground truth, evaluator va top-k.
Khac biet metric vi vay den tu chat luong du lieu, khong phai tu cau hinh.

## Metrics: baseline vs corrupted vs repaired

| Metric | Baseline | Corrupted | Δ vs baseline | Repaired | Δ vs baseline |
| --- | --- | --- | --- | --- | --- |
| Retrieval hit rate | 1.0000 | 0.7500 | -0.2500 | 1.0000 | 0.0000 |
| Mean token F1 | 0.9314 | 0.7135 | -0.2180 | 0.9314 | 0.0000 |
| Judge accuracy | 1.0000 | 0.7500 | -0.2500 | 1.0000 | 0.0000 |
| Mean judge score | 4.5000 | 3.6875 | -0.8125 | 4.5000 | 0.0000 |


> **Luu y:** ca ba trang thai deu dung heuristic judge (baseline=`heuristic`, corrupted=`heuristic`, repaired=`heuristic`), khong phai LLM. Vi dung chung mot cach cham nen so sanh van nhat quan, nhung `judge_accuracy` chi la ham bac thang cua `token_f1` chu khong phai danh gia doc lap.


## Data quality

| Field | Corrupted | Repaired |
| --- | --- | --- |
| Overall | FAIL | PASS |
| Checks passed | 7/12 | 12/12 |
| Total rows | 23 | 24 |
| Failed checks | paper_id_unique, summary_not_null, summary_min_length, freshness_within_threshold, title_no_duplicates | - |


## Freshness

| Field | Corrupted | Repaired |
| --- | --- | --- |
| Status | stale | fresh |
| Stale rows | 4 | 0 |
| Latest published | 2026-06-15 | 2026-08-05 |
| Max age (days) | 9533 | 175 |


## Phan tich

- **Retrieval hit rate**: corrupted `-0.2500` so voi baseline; repair keo lai `+0.2500`; repaired con lech `+0.0000` so voi baseline.
- **Mean token F1**: corrupted `-0.2180` so voi baseline; repair keo lai `+0.2180`; repaired con lech `+0.0000` so voi baseline.
- **Judge accuracy**: corrupted `-0.2500` so voi baseline; repair keo lai `+0.2500`; repaired con lech `+0.0000` so voi baseline.
- **Mean judge score**: corrupted `-0.8125` so voi baseline; repair keo lai `+0.8125`; repaired con lech `+0.0000` so voi baseline.
- Ket luan: du lieu hong lam giam do chinh xac cua retrieval, keo theo chat luong cau tra loi cua agent.
