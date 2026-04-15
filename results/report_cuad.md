# CUAD Benchmark Report (Real Legal Contracts)

| System   | Precision@1 | Efficiency | Provenance | Composite |
|----------|-------------|------------|------------|-----------|
| RAG      | 0.10 | 0.03 | 0.20 | 0.10 |
| GraphRAG | 0.30 | 0.04 | 0.40 | 0.24 |
| Akashik  | 0.90 | 0.16 | 1.00 | 0.70 |

## Clause Type Breakdown
| Clause Type    | Akashik P@1 | RAG P@1 | Akashik Provenance |
|---------------|-------------|---------|-------------------|
| governing_law  | 0.75 | 0.25 | 1.00 |
| renewal        | 1.00 | 0.00 | 1.00 |
| notice         | 1.00 | 0.00 | 1.00 |

## Comparison: Synthetic vs CUAD
| Metric      | Synthetic | CUAD  | Delta |
|-------------|-----------|-------|-------|
| Precision@1 | 0.96 | 0.90 | -0.06 |
| Efficiency  | 0.43 | 0.16 | -0.27 |
| Provenance  | 0.96 | 1.00 | 0.04 |
| Composite   | 0.80 | 0.70 | -0.10 |

## Failure Analysis
- `cuad_02_governing_law` (governing_law): normalized query `govern governed governing laws ontario canada`; entity filter `['videoondemand']`; expected source `EuromediaHoldingsCorp_20070215_10SB12G_EX-10.B_01__525118_EX-10.B_01__Content_License_Agreement.txt`, top source `EuromediaHoldingsCorp_20070215_10SB12G_EX-10.B_01__525118_EX-10.B_01__Content_License_Agreement.txt`; top result: This Agreement shall be governed by laws of the Province of Ontario and the federal laws of Canada applicable therein.
