# Results

## Aggregate

| Config | F1 (95% CI) | Precision | Recall | Schema | Forbidden | Verbatim | Cost | p50 | p95 |
|---|---|---|---|---|---|---|---|---|---|
| `baseline` | 0.50 [0.12-0.85] | 0.45 | 1.00 | 60% | 0.0% | 98.0% | $0.29 | 9.6s | 24.2s |

- `baseline`: aggregate F1 0.50 conceals **0.00 on `adversarial`** (n=1).

## By bucket

### `clean`

| Config | n | F1 (95% CI) | Precision | Recall | Forbidden | Verbatim |
|---|---|---|---|---|---|---|
| `baseline` | 1 | 0.89 [0.89-0.89] | 0.80 | 1.00 | 0.0% | 97.1% |

### `ambiguous`

| Config | n | F1 (95% CI) | Precision | Recall | Forbidden | Verbatim |
|---|---|---|---|---|---|---|
| `baseline` | 1 | 0.60 [0.60-0.60] | 0.43 | 1.00 | 0.0% | 100.0% |

### `adversarial`

| Config | n | F1 (95% CI) | Precision | Recall | Forbidden | Verbatim |
|---|---|---|---|---|---|---|
| `baseline` | 1 | 0.00 [0.00-0.00] | 0.00 | 1.00 | 0.0% | 100.0% |

### `empty`

| Config | n | F1 (95% CI) | Precision | Recall | Forbidden | Verbatim |
|---|---|---|---|---|---|---|
| `baseline` | 2 | 0.50 [0.00-1.00] | 0.50 | 1.00 | 0.0% | 100.0% |

## JSON recovery

How the output was parsed. A non-zero `fence` or `regex` count means the fallback path is load-bearing.

| Config | direct | fence | regex | failed |
|---|---|---|---|---|
| `baseline` | 5 | 0 | 0 | 0 |
