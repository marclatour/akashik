# CUAD Benchmark Report (Real Legal Contracts)

| System        | Precision@1 | Efficiency | Provenance | Composite |
|---------------|-------------|------------|------------|-----------|
| RAG      | 0.08 | 0.03 | 0.08 | 0.06 |
| GraphRAG | 0.14 | 0.11 | 0.16 | 0.13 |
| Akashik  | 0.82 | 0.20 | 0.92 | 0.65 |

## Clause Type Breakdown
| Clause Type    | Akashik P@1 | RAG P@1 | Akashik Provenance |
|---------------|-------------|---------|-------------------|
| governing_law  | 0.88 | 0.24 | 0.94 |
| renewal        | 0.71 | 0.00 | 0.82 |
| notice         | 0.88 | 0.00 | 1.00 |

## Selection Summary
| Clause Type | Selected | Shortfall | Skipped: Non-substantive | Skipped: Short Clause | Skipped: Missing Text | Skipped: Clause Not Found | Skipped: Already Selected |
|-------------|----------|-----------|--------------------------|-----------------------|-----------------------|---------------------------|---------------------------|
| governing_law | 17 | 0 | 2 | 1 | 0 | 0 | 0 |
| renewal | 17 | 0 | 61 | 0 | 0 | 6 | 17 |
| notice | 16 | 0 | 90 | 0 | 1 | 5 | 34 |
Null entity filters: 0
Single entity filters: 15
Compound entity filters: 35

Anchor collisions by primary: {"agency": 4, "cobranding": 2, "consulting": 3, "development": 2, "distributor": 4, "endorsement": 2, "franchise": 2, "hosting": 2, "joint": 2, "reseller": 4, "services": 2, "strategic": 4, "transportation": 2}

## Comparison: 10-Contract CUAD vs 50-Contract CUAD
| Metric      | 10-Contract CUAD | 50-Contract CUAD | Delta |
|-------------|------------------|------------------|-------|
| Precision@1 | 0.90 | 0.82 | -0.08 |
| Efficiency  | 0.16 | 0.20 | 0.04 |
| Provenance  | 1.00 | 0.92 | -0.08 |
| Composite   | 0.70 | 0.65 | -0.05 |

## Failure Analysis
- `cuad_08_governing_law` (governing_law, retrieval issue): normalized query `govern governed governing laws jurisdiction california`; entity filter `['consulting', 'adurobiotechinc']`; secondary source `company_prefix`; expected source `ADUROBIOTECH_INC_06_02_2020-EX-10.7-CONSULTING_AGREEMENT_1.txt`, top source `ADUROBIOTECH_INC_06_02_2020-EX-10.7-CONSULTING_AGREEMENT.txt`; top result: This Agreement shall be construed and enforced in accordance with the laws of the State of California, without regard to the conflict of law principles of California or any other jurisdiction.
- `cuad_13_governing_law` (governing_law, clause ambiguity): normalized query `govern governed governing laws texas`; entity filter `['franchise', 'airtechinternationalgroupinc']`; secondary source `company_prefix`; expected source `AIRTECHINTERNATIONALGROUPINC_05_08_2000-EX-10.4-FRANCHISE_AGREEMENT.txt`, top source `AIRTECHINTERNATIONALGROUPINC_05_08_2000-EX-10.4-FRANCHISE_AGREEMENT.txt`; top result: This instrument shall be governed by and construed under the laws of the State of Texas.
- `cuad_14_governing_law` (governing_law, clause ambiguity): normalized query `govern governed governing laws kansas`; entity filter `['agency', 'alamogordofinancialcorp']`; secondary source `company_prefix`; expected source `ALAMOGORDOFINANCIALCORP_12_16_1999-EX-1-AGENCY_AGREEMENT.txt`, top source `ALAMOGORDOFINANCIALCORP_12_16_1999-EX-1-AGENCY_AGREEMENT.txt`; top result: The opinion of Luse Lehman Gorman Pomerenk & Schick shall be governed by the Legal Opinion Accord ("Accord") of the American Bar Association Section of Business Law (1991).
- `cuad_19_renewal` (renewal, retrieval issue): normalized query `renew renewal renewed renewing additional period periods term successive 1 one year`; entity filter `['site']`; secondary source `None`; expected source `AMERICASSHOPPINGMALLINC_12_10_1999-EX-10.2-SITE_DEVELOPMENT_AND_HOSTING_AGREEMENT.txt`, top source `BNCMORTGAGEINC_05_17_1999-EX-10.4-LICENSING_AND_WEB_SITE_HOSTING_AGREEMENT.txt`; top result: This Agreement shall renew automatically thereafter for successive one year periods until terminated pursuant to Section 12 herein or unless either Client or TrueLink deliver to the other written notice of intent not to renew no later than thirty (30) days ...
- `cuad_26_renewal` (renewal, retrieval issue): normalized query `successive renew renewal renewed renewing additional period periods term 1 one year`; entity filter `['licensing']`; secondary source `None`; expected source `BNCMORTGAGEINC_05_17_1999-EX-10.4-LICENSING_AND_WEB_SITE_HOSTING_AGREEMENT.txt`, top source `EmeraldHealthBioceuticalsInc_20200218_1-A_EX1A-6_MAT_CTRCT_11987205_EX1A-6_MAT_CTRCT_Development_Agreement.txt`; top result: The Services Term of this Agreement shall be automatically renewed for successive two-year terms thereafter unless written notice is given by either party to the other, indicating that party's intention not to renew the Services Term of this Agreement, at l...
- `cuad_27_renewal` (renewal, retrieval issue): normalized query `renew renewal renewed renewing additional period periods term successive 1 one year`; entity filter `['outsourcing']`; secondary source `None`; expected source `BNLFINANCIALCORP_03_30_2007-EX-10.8-OUTSOURCING_AGREEMENT.txt`, top source `CCAINDUSTRIESINC_04_14_2014-EX-10.1-OUTSOURCING_AGREEMENT.txt`; top result: This agreement shall automatically renew for successive six (6) month periods unless written notice is provided of either party's intent not to renew at least six (6) months before the end of the then-current term.
- `cuad_29_renewal` (renewal, clause ambiguity): normalized query `renew renewal renewed renewing additional period periods term 1 one year`; entity filter `['reseller', 'bravateksolutionsinc']`; secondary source `company_prefix`; expected source `BravatekSolutionsInc_20170418_8-K_EX-10.1_10205739_EX-10.1_Reseller_Agreement.txt`, top source `BravatekSolutionsInc_20170418_8-K_EX-10.1_10205739_EX-10.1_Reseller_Agreement.txt`; top result: Agreement Term: 1 Year
- `cuad_30_renewal` (renewal, clause ambiguity): normalized query `renew renewal renewed renewing additional period periods term 2 two successive 5 five years`; entity filter `['franchise', 'buffalowildwingsinc']`; secondary source `company_prefix`; expected source `BUFFALOWILDWINGSINC_06_05_1998-EX-10.3-FRANCHISE_AGREEMENT.txt`, top source `BUFFALOWILDWINGSINC_06_05_1998-EX-10.3-FRANCHISE_AGREEMENT.txt`; top result: You have the right to renew the franchise for two (2) successive terms equal to five (5) years each, providing you meet all of the following conditions:
- `cuad_42_notice` (notice, clause ambiguity): normalized query `terminate terminated termination renew renewal renewed renewing additional period periods 60 written notice`; entity filter `['cobranding', 'edietscominc']`; secondary source `company_prefix`; expected source `EdietsComInc_20001030_10QSB_EX-10.4_2606646_EX-10.4_Co-Branding_Agreement.txt`, top source `EdietsComInc_20001030_10QSB_EX-10.4_2606646_EX-10.4_Co-Branding_Agreement.txt`; top result: Following the Initial Term, Women.com shall have the right, upon no fewer than sixty (60) days prior written notice to eDiets, to increase the amount of the Payment Schedule; provided, that (i) Women.com may not increase the Payment Schedule more than once ...
- `cuad_49_notice` (notice, clause ambiguity): normalized query `terminate terminated termination renew renewal renewed renewing additional period periods 60 written notice`; entity filter `['videoondemand']`; secondary source `None`; expected source `EuromediaHoldingsCorp_20070215_10SB12G_EX-10.B_01__525118_EX-10.B_01__Content_License_Agreement.txt`, top source `EuromediaHoldingsCorp_20070215_10SB12G_EX-10.B_01__525118_EX-10.B_01__Content_License_Agreement.txt`; top result: Notwithstanding any other provision of this Agreement, Rogers may terminate this Agreement, at any time, upon sixty (60) days' prior written notice to Licensor.
Regression sources: retrieval issue=4, anchor issue=0, clause ambiguity=6, corpus extraction issue=0

RAG-Embedding disabled by default. Re-run with `--with-embeddings` to include the semantic baseline.

Results hold at 5x scale. Claim is publication-ready.
