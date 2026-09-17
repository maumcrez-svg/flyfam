# The mirror diagnostic — is the trained brain the negative of the untrained one?

Fable addendum 5, computed in step (iii) of the D12 wave **before any new run**, from two files `d11-001` already wrote. No brain ran, no socket was opened, nothing was recomputed: `scores_trained.jsonl` (`321d82ef000c…`) and `scores_reference.jsonl` (`cde2a79cf6e2…`).

**5,168** of 5,177 grid rows are `VALID` under both brains — TRAINED `bbca5c4ba65c…` and REFERENCE `ba95b60503d6…`.

## 1. The two valences, row by row

| | n | Pearson r | Spearman ρ | Kendall τ | OLS a | OLS b | R² | reversed pairs |
|---|---|---|---|---|---|---|---|---|
| **overall** | 5,168 | 0.0046 | 0.0135 | 0.0117 | -3.4865 | **0.0045** | 0.0000 | 49.21 % |
| block 1 | 1,853 | -0.0154 | -0.0136 | -0.0064 | -3.4697 | **-0.0155** | 0.0002 | 50.11 % |
| block 2 | 1,864 | 0.0393 | 0.0539 | 0.0377 | -3.5161 | **0.0394** | 0.0015 | 47.91 % |
| block 3 | 1,451 | -0.0154 | -0.0029 | 0.0013 | -3.4663 | **-0.0148** | 0.0002 | 49.74 % |

`b` is the slope of `trained = a + b · reference` in Hz per Hz. A brain that had become the exact negative of the untrained one would show `b = −1`, `τ = −1` and 100 % of row pairs reversed.

## 2. Within a tick — the ranking the fly would actually act on

Kendall τ between the two branches **inside each tick's cohort**, which is the quantity that decides which candidate a round selects: mean **0.0030** over 402 ticks (median 0.0246, SD 0.2167, range [-0.6061, 0.7143]; size-weighted mean 0.0079). **177** of those ticks have a negative τ and **0** have τ exactly −1 — a cohort ranked in perfectly reversed order. 0 ticks carry fewer than two comparable rows and have no τ.

## 3. The AUCs, beside each other

| quantity | value |
|---|---|
| rows with a settled label | 5,013 (488 positive / 4,525 negative) |
| AUC(trained) | **0.411579** |
| AUC(reference) | 0.588454 |
| AUC(−reference) | **0.411546** |
| 1 − AUC(reference) | 0.411546 |
| AUC(trained) − (1 − AUC(reference)) | **0.000034** |
| AUC(trained) − AUC(−reference) | 0.000034 |

The two lines of this page that answer the owner's question sit in different sections and are stated together here, as numbers: the residual of AUC(trained) from 1 − AUC(reference) is **0.000034**, while Kendall τ between the two rankings over the same rows is **0.0117**, the OLS slope is **0.0045** and the mean within-tick τ is **0.0030**. One scalar lands on the mirror; the ordering that scalar summarises does not. Both are reported and neither is interpreted here.

## 4. What these numbers are, and what they are not

They are a description of two recorded score files. The mechanistic reading — that fifteen punishments depressed the approach pathway in proportion to the prior valence, so the trained valence is a decreasing affine function of the untrained one — is a **hypothesis** that `b` and `τ` test. It is **not a finding** until the owner states it as one. Nothing here is a rate in the market, and no interval was pre-registered for any single AUC above.
