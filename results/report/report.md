# Results

**Measured noise floor: 0.14 macro-F1.** Two configurations differing by less than this are indistinguishable from re-running the same configuration twice. Intervals are 95% bootstrap CIs.

## Aggregate

| Config | F1 (95% CI) | Precision | Recall | Schema | Forbidden | Verbatim | Cost | p50 | p95 |
|---|---|---|---|---|---|---|---|---|---|
| `baseline` | 0.61 [0.35-0.84] | 0.59 | 1.00 | 93% | 1.4% | 95.1% | $0.88 | 9.8s | 24.2s |
| `structured-prompt` | 0.99 [0.97-1.00] | 0.98 | 1.00 | 79% | 0.0% | 99.0% | $0.88 | 6.0s | 21.1s |
| `structured` | 0.99 [0.97-1.00] | 0.98 | 1.00 | 79% | 0.0% | 99.0% | $0.86 | 6.5s | 20.3s |

- `baseline`: aggregate F1 0.61 conceals **0.25 on `adversarial`** (n=4).
- `structured-prompt`: aggregate F1 0.99 conceals **0.93 on `ambiguous`** (n=2).
- `structured`: aggregate F1 0.99 conceals **0.93 on `ambiguous`** (n=2).

## By bucket

### `clean`

| Config | n | F1 (95% CI) | Precision | Recall | Forbidden | Verbatim |
|---|---|---|---|---|---|---|
| `baseline` | 4 | 0.99 [0.96-1.00] | 0.97 | 1.00 | 0.0% | 100.0% |
| `structured-prompt` | 4 | 1.00 [1.00-1.00] | 1.00 | 1.00 | 0.0% | 100.0% |
| `structured` | 4 | 1.00 [1.00-1.00] | 1.00 | 1.00 | 0.0% | 100.0% |

### `ambiguous`

| Config | n | F1 (95% CI) | Precision | Recall | Forbidden | Verbatim |
|---|---|---|---|---|---|---|
| `baseline` | 2 | 0.85 [0.73-0.97] | 0.76 | 1.00 | 0.0% | 80.8% |
| `structured-prompt` | 2 | 0.93 [0.89-0.97] | 0.87 | 1.00 | 0.0% | 95.8% |
| `structured` | 2 | 0.93 [0.89-0.97] | 0.87 | 1.00 | 0.0% | 95.8% |

### `adversarial`

| Config | n | F1 (95% CI) | Precision | Recall | Forbidden | Verbatim |
|---|---|---|---|---|---|---|
| `baseline` | 4 | 0.25 [0.00-0.75] | 0.25 | 1.00 | 15.4% | 92.3% |
| `structured-prompt` | 4 | 1.00 [1.00-1.00] | 1.00 | 1.00 | 0.0% | 100.0% |
| `structured` | 4 | 1.00 [1.00-1.00] | 1.00 | 1.00 | 0.0% | 100.0% |

### `empty`

| Config | n | F1 (95% CI) | Precision | Recall | Forbidden | Verbatim |
|---|---|---|---|---|---|---|
| `baseline` | 3 | 0.33 [0.00-1.00] | 0.33 | 1.00 | 0.0% | 100.0% |
| `structured-prompt` | 3 | 1.00 [1.00-1.00] | 1.00 | 1.00 | 0.0% | 100.0% |
| `structured` | 3 | 1.00 [1.00-1.00] | 1.00 | 1.00 | 0.0% | 100.0% |

### `long`

| Config | n | F1 (95% CI) | Precision | Recall | Forbidden | Verbatim |
|---|---|---|---|---|---|---|
| `baseline` | 1 | 0.88 [0.88-0.88] | 0.78 | 1.00 | 0.0% | 97.2% |
| `structured-prompt` | 1 | 1.00 [1.00-1.00] | 1.00 | 1.00 | 0.0% | 100.0% |
| `structured` | 1 | 1.00 [1.00-1.00] | 1.00 | 1.00 | 0.0% | 100.0% |

## JSON recovery

How the output was parsed. A non-zero `fence` or `regex` count means the fallback path is load-bearing.

| Config | direct | fence | regex | failed |
|---|---|---|---|---|
| `baseline` | 13 | 1 | 0 | 0 |
| `structured-prompt` | 5 | 9 | 0 | 0 |
| `structured` | 14 | 0 | 0 | 0 |
