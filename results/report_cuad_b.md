# CUAD Mode B Benchmark Report (Natural Legal Queries)

| System   | Precision@1 | Efficiency | Provenance | Composite |
|----------|-------------|------------|------------|-----------|
| RAG      | 0.00 | 0.03 | 0.20 | 0.05 |
| GraphRAG | 0.00 | 0.00 | 0.00 | 0.00 |
| Akashik  | 0.00 | 0.04 | 0.00 | 0.01 |

## Failure Analysis
- `cuad_01_governing_law_b` (governing_law): normalized query `sits s rules control this deal`; expected source `CybergyHoldingsInc_20140520_10-Q_EX-10.27_8605784_EX-10.27_Affiliate_Agreement.txt`, top source `None`; top result: None
- `cuad_02_governing_law_b` (governing_law): normalized query `legal forum applies this arrangement`; expected source `EuromediaHoldingsCorp_20070215_10SB12G_EX-10.B_01__525118_EX-10.B_01__Content_License_Agreement.txt`, top source `TomOnlineInc_20060501_20-F_EX-4.46_749700_EX-4.46_Co-Branding_Agreement.txt`; top result: Exhibit 4.46 6 rue Adolphe Fischer L-1520 Luxembourg Luxembourg
- `cuad_05_renewal_b` (renewal): normalized query `this arrangement keep going after first period`; expected source `TomOnlineInc_20060501_20-F_EX-4.46_749700_EX-4.46_Co-Branding_Agreement.txt`, top source `None`; top result: None
- `cuad_08_notice_b` (notice): normalized query `much warning needed before stopping another extension`; expected source `EcoScienceSolutionsInc_20171117_8-K_EX-10.1_10956472_EX-10.1_Endorsement_Agreement.txt`, top source `None`; top result: None
- `cuad_09_notice_b` (notice): normalized query `advance warning required avoid another cycle`; expected source `VitalibisInc_20180316_8-K_EX-10.2_11100168_EX-10.2_Hosting_Agreement.txt`, top source `None`; top result: None
