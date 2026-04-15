# CUAD Benchmark Report (Real Legal Contracts)

| System        | Precision@1 | Efficiency | Provenance | Composite |
|---------------|-------------|------------|------------|-----------|
| RAG      | 0.10 | 0.03 | 0.20 | 0.10 |
| GraphRAG | 0.30 | 0.04 | 0.40 | 0.24 |
| RAG-Embedding | 0.10 | 0.03 | 0.30 | 0.12 |
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

## RAG-Embedding vs Akashik Disagreements
| Query ID | Category | Expected Source | RAG-Embedding Top | Akashik Top |
|----------|----------|-----------------|-------------------|-------------|
| cuad_01_governing_law | scope_win | CybergyHoldingsInc_20140520_10-Q_EX-10.27_8605784_EX-10.27_Affiliate_Agreement.txt | GopageCorp_20140221_10-K_EX-10.1_8432966_EX-10.1_Content_License_Agreement.txt: Agreement, no failure to exercise, or delay in exercising, any rights, remedy... | CybergyHoldingsInc_20140520_10-Q_EX-10.27_8605784_EX-10.27_Affiliate_Agreement.txt: This Agreement is accepted by Company in the State of Nevada and shall be gov... |
| cuad_02_governing_law | both_wrong | EuromediaHoldingsCorp_20070215_10SB12G_EX-10.B_01__525118_EX-10.B_01__Content_License_Agreement.txt | EuromediaHoldingsCorp_20070215_10SB12G_EX-10.B_01__525118_EX-10.B_01__Content_License_Agreement.txt: obligations hereunder in compliance with Applicable Law and, in particular, t... | EuromediaHoldingsCorp_20070215_10SB12G_EX-10.B_01__525118_EX-10.B_01__Content_License_Agreement.txt: This Agreement shall be governed by laws of the Province of Ontario and the f... |
| cuad_03_governing_law | benchmark_ambiguity | GopageCorp_20140221_10-K_EX-10.1_8432966_EX-10.1_Content_License_Agreement.txt | GopageCorp_20140221_10-K_EX-10.1_8432966_EX-10.1_Content_License_Agreement.txt: Agreement, no failure to exercise, or delay in exercising, any rights, remedy... | GopageCorp_20140221_10-K_EX-10.1_8432966_EX-10.1_Content_License_Agreement.txt: This Agreement shall be governed by and construed in accordance with the inte... |
| cuad_04_governing_law | scope_win | EdietsComInc_20001030_10QSB_EX-10.4_2606646_EX-10.4_Co-Branding_Agreement.txt | VitalibisInc_20180316_8-K_EX-10.2_11100168_EX-10.2_Hosting_Agreement.txt: or other written means) of Licensee, which approval shall not be unreasonably... | EdietsComInc_20001030_10QSB_EX-10.4_2606646_EX-10.4_Co-Branding_Agreement.txt: This Agreement shall be interpreted and enforced in accordance with the laws ... |
| cuad_05_renewal | scope_win | TomOnlineInc_20060501_20-F_EX-4.46_749700_EX-4.46_Co-Branding_Agreement.txt | VitalibisInc_20180316_8-K_EX-10.2_11100168_EX-10.2_Hosting_Agreement.txt: shall automatically renew beyond the Initial Term for successive one (I) year... | TomOnlineInc_20060501_20-F_EX-4.46_749700_EX-4.46_Co-Branding_Agreement.txt: This Agreement shall automatically continue following the Initial Term, for a... |
| cuad_06_renewal | scope_win | FuseMedicalInc_20190321_10-K_EX-10.43_11575454_EX-10.43_Distributor_Agreement.txt | VitalibisInc_20180316_8-K_EX-10.2_11100168_EX-10.2_Hosting_Agreement.txt: shall automatically renew beyond the Initial Term for successive one (I) year... | FuseMedicalInc_20190321_10-K_EX-10.43_11575454_EX-10.43_Distributor_Agreement.txt: 11.1 This agreement begins on the Commencement Date and, subject to clause 11... |
| cuad_07_renewal | scope_win | WaterNowInc_20191120_10-Q_EX-10.12_11900227_EX-10.12_Distributor_Agreement.txt | VitalibisInc_20180316_8-K_EX-10.2_11100168_EX-10.2_Hosting_Agreement.txt: shall automatically renew beyond the Initial Term for successive one (I) year... | WaterNowInc_20191120_10-Q_EX-10.12_11900227_EX-10.12_Distributor_Agreement.txt: Upon expiration of the Initial Term of this Agreement, this Agreement will au... |
| cuad_08_notice | scope_win | EcoScienceSolutionsInc_20171117_8-K_EX-10.1_10956472_EX-10.1_Endorsement_Agreement.txt | VitalibisInc_20180316_8-K_EX-10.2_11100168_EX-10.2_Hosting_Agreement.txt: shall automatically renew beyond the Initial Term for successive one (I) year... | EcoScienceSolutionsInc_20171117_8-K_EX-10.1_10956472_EX-10.1_Endorsement_Agreement.txt: The term of this Agreement shall be for one (1) year commencing on the Effect... |
| cuad_09_notice | benchmark_ambiguity | VitalibisInc_20180316_8-K_EX-10.2_11100168_EX-10.2_Hosting_Agreement.txt | VitalibisInc_20180316_8-K_EX-10.2_11100168_EX-10.2_Hosting_Agreement.txt: shall automatically renew beyond the Initial Term for successive one (I) year... | VitalibisInc_20180316_8-K_EX-10.2_11100168_EX-10.2_Hosting_Agreement.txt: This Agreement shall automatically renew beyond the Initial Term for successi... |
| cuad_10_notice | scope_win | GpaqAcquisitionHoldingsInc_20200123_S-4A_EX-10.6_11951677_EX-10.6_License_Agreement.txt | VitalibisInc_20180316_8-K_EX-10.2_11100168_EX-10.2_Hosting_Agreement.txt: shall automatically renew beyond the Initial Term for successive one (I) year... | GpaqAcquisitionHoldingsInc_20200123_S-4A_EX-10.6_11951677_EX-10.6_License_Agreement.txt: Thereafter, the agreement shall automatically renew for successive five (5)-y... |

Akashik outperforms the strongest general-purpose semantic retrieval baseline on legal contract clause retrieval without embeddings.
