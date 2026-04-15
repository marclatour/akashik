# CUAD Benchmark Report (Real Legal Contracts)

| System   | Precision@1 | Efficiency | Provenance | Composite |
|----------|-------------|------------|------------|-----------|
| RAG      | 0.10 | 0.03 | 0.20 | 0.10 |
| GraphRAG | 0.20 | 0.03 | 0.30 | 0.17 |
| Akashik  | 0.70 | 0.27 | 0.80 | 0.59 |

## Clause Type Breakdown
| Clause Type    | Akashik P@1 | RAG P@1 | Akashik Provenance |
|---------------|-------------|---------|-------------------|
| governing_law  | 0.75 | 0.25 | 1.00 |
| renewal        | 0.67 | 0.00 | 0.67 |
| notice         | 0.67 | 0.00 | 0.67 |

## Comparison: Synthetic vs CUAD
| Metric      | Synthetic | CUAD  | Delta |
|-------------|-----------|-------|-------|
| Precision@1 | 0.96 | 0.70 | -0.26 |
| Efficiency  | 0.43 | 0.27 | -0.16 |
| Provenance  | 0.96 | 0.80 | -0.16 |
| Composite   | 0.80 | 0.59 | -0.21 |

## Failure Analysis
- `cuad_02_governing_law` (governing_law): normalized query `rogers govern governed governing laws ontario canada`; entity filter `['rogers']`; expected source `EuromediaHoldingsCorp_20070215_10SB12G_EX-10.B_01__525118_EX-10.B_01__Content_License_Agreement.txt`, top source `EuromediaHoldingsCorp_20070215_10SB12G_EX-10.B_01__525118_EX-10.B_01__Content_License_Agreement.txt`; top result: This Agreement shall be governed by laws of the Province of Ontario and the federal laws of Canada applicable therein.
- `cuad_06_renewal` (renewal): normalized query `renew renewal renewed renewing additional period periods term perpetual`; entity filter `None`; expected source `FuseMedicalInc_20190321_10-K_EX-10.43_11575454_EX-10.43_Distributor_Agreement.txt`, top source `WaterNowInc_20191120_10-Q_EX-10.12_11900227_EX-10.12_Distributor_Agreement.txt`; top result: Upon expiration of the Initial Term of this Agreement, this Agreement will automatically renew for additional, successive five (5) year periods unless either Party provides the other Party written notice of its desire to terminate at least one hundred twent...
- `cuad_08_notice` (notice): normalized query `terminate terminated termination renew renewal renewed renewing additional period periods 30 thirty written notice`; entity filter `None`; expected source `EcoScienceSolutionsInc_20171117_8-K_EX-10.1_10956472_EX-10.1_Endorsement_Agreement.txt`, top source `GopageCorp_20140221_10-K_EX-10.1_8432966_EX-10.1_Content_License_Agreement.txt`; top result: Thereafter, this Agreement shall renew automatically for one (1) additional three (3) year period (the "Renewal Term" and collectively, together with the Initial Term, the "Term") unless either party provides the other with written notice of non-renewal at ...
