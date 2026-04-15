# CUAD Benchmark Report (Real Legal Contracts)

| System   | Precision@1 | Efficiency | Provenance | Composite |
|----------|-------------|------------|------------|-----------|
| RAG      | 0.10 | 0.03 | 0.20 | 0.10 |
| GraphRAG | 0.20 | 0.03 | 0.30 | 0.17 |
| Akashik  | 0.60 | 0.38 | 0.70 | 0.56 |

## Clause Type Breakdown
| Clause Type    | Akashik P@1 | RAG P@1 | Akashik Provenance |
|---------------|-------------|---------|-------------------|
| governing_law  | 0.50 | 0.25 | 0.75 |
| renewal        | 0.67 | 0.00 | 0.67 |
| notice         | 0.67 | 0.00 | 0.67 |

## Comparison: Synthetic vs CUAD
| Metric      | Synthetic | CUAD  | Delta |
|-------------|-----------|-------|-------|
| Precision@1 | 0.96 | 0.60 | -0.36 |
| Efficiency  | 0.43 | 0.38 | -0.05 |
| Provenance  | 0.96 | 0.70 | -0.26 |
| Composite   | 0.80 | 0.56 | -0.24 |

## Failure Analysis
- `cuad_02_governing_law` (governing_law): normalized query `rogers govern governed governing laws ontario canada`; expected source `EuromediaHoldingsCorp_20070215_10SB12G_EX-10.B_01__525118_EX-10.B_01__Content_License_Agreement.txt`, top source `EuromediaHoldingsCorp_20070215_10SB12G_EX-10.B_01__525118_EX-10.B_01__Content_License_Agreement.txt`; top result: This Agreement shall be governed by laws of the Province of Ontario and the federal laws of Canada applicable therein.
- `cuad_03_governing_law` (governing_law): normalized query `psitech govern governed governing laws nevada`; expected source `GopageCorp_20140221_10-K_EX-10.1_8432966_EX-10.1_Content_License_Agreement.txt`, top source `CybergyHoldingsInc_20140520_10-Q_EX-10.27_8605784_EX-10.27_Affiliate_Agreement.txt`; top result: This Agreement is accepted by Company in the State of Nevada and shall be governed by and construed in accordance with the laws thereof, which laws shall prevail in the event of any conflict.
- `cuad_06_renewal` (renewal): normalized query `renew renewal renewed renewing additional period periods term perpetual`; expected source `FuseMedicalInc_20190321_10-K_EX-10.43_11575454_EX-10.43_Distributor_Agreement.txt`, top source `WaterNowInc_20191120_10-Q_EX-10.12_11900227_EX-10.12_Distributor_Agreement.txt`; top result: Upon expiration of the Initial Term of this Agreement, this Agreement will automatically renew for additional, successive five (5) year periods unless either Party provides the other Party written notice of its desire to terminate at least one hundred twent...
- `cuad_08_notice` (notice): normalized query `terminate terminated termination renew renewal renewed renewing additional period periods 30 thirty written notice`; expected source `EcoScienceSolutionsInc_20171117_8-K_EX-10.1_10956472_EX-10.1_Endorsement_Agreement.txt`, top source `GopageCorp_20140221_10-K_EX-10.1_8432966_EX-10.1_Content_License_Agreement.txt`; top result: Thereafter, this Agreement shall renew automatically for one (1) additional three (3) year period (the "Renewal Term" and collectively, together with the Initial Term, the "Term") unless either party provides the other with written notice of non-renewal at ...
