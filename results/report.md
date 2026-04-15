# Benchmark Report

| System        | Precision@1 | Efficiency | Provenance | Composite | Easy | Medium | Hard |
|---------------|-------------|------------|------------|-----------|------|--------|------|
| RAG      | 0.78 | 0.01 | 0.78 | 0.55 | 0.70 | 0.53 | 0.40 |
| GraphRAG | 0.78 | 0.14 | 0.96 | 0.62 | 0.75 | 0.54 | 0.57 |
| RAG-Embedding | 0.26 | 0.01 | 0.57 | 0.25 | 0.25 | 0.28 | 0.20 |
| Akashik  | 0.96 | 0.43 | 0.96 | 0.80 | 1.00 | 0.73 | 0.64 |

Difficulty columns are average composite scores by difficulty.

Gate status: PASS

## RAG-Embedding vs Akashik Disagreements
| Query ID | Category | Expected Source | RAG-Embedding Top | Akashik Top |
|----------|----------|-----------------|-------------------|-------------|
| easy_01 | scope_win | meridian_harbor_notice_two.txt | meridian_harbor_notice_one.txt: during training because the benchmark depends on older facts remaining visibl... | meridian_harbor_notice_two.txt: Current Meridian Harbor policy assigns green badges to Gate 6. |
| easy_02 | scope_win | meridian_rail_schedule_b.txt | meridian_rail_schedule_a.txt: Meridian Rail Schedule A is a synthetic station notice included to test retri... | meridian_rail_schedule_b.txt: Current Meridian Rail schedule sends Train Atlas from Platform 5 at 20:05. |
| easy_03 | benchmark_ambiguity | lantern_gallery_catalog.txt | lantern_gallery_catalog.txt: The Lantern Gallery catalog is a synthetic museum document designed for retri... | lantern_gallery_catalog.txt: The River Glass exhibit opens at 09:30 in the Meridian Lantern Gallery. |
| easy_04 | scope_win | lantern_gallery_update.txt | lantern_gallery_catalog.txt: which makes this catalog a useful baseline for amendment queries. A second ga... | lantern_gallery_update.txt: The blue copper compass now sits on Shelf 14 in Atlas Room. |
| easy_05 | benchmark_ambiguity | atlas_field_manual_red.txt | atlas_field_manual_red.txt: in the comparison chart but not in the red procedure. Those neighboring sente... | atlas_field_manual_red.txt: The Atlas Pine survey packet uses amber ribbon and sample code R17. |
| easy_06 | benchmark_ambiguity | atlas_field_manual_silver.txt | atlas_field_manual_silver.txt: but not in the silver procedure. Those rival values are kept in separate sent... | atlas_field_manual_silver.txt: The Atlas Pine survey packet uses silver ribbon and sample code S19. |
| easy_07 | benchmark_ambiguity | northwind_clinic_brief.txt | northwind_clinic_brief.txt: the Lantern desk receives new patients, stamps Indigo 3 on the paper band, an... | northwind_clinic_brief.txt: Northwind Clinic assigns triage card Indigo 3 to the Lantern desk. |
| easy_08 | benchmark_ambiguity | copper_reserve_digest.txt | copper_reserve_digest.txt: Copper Reserve Digest is a synthetic infrastructure report included to widen ... | copper_reserve_digest.txt: Copper Reserve Digest records Pump Seven at Atlas Basin with pressure 41. |
| medium_01 | benchmark_ambiguity | meridian_harbor_notice_two.txt | meridian_harbor_notice_two.txt: Meridian Harbor Notice Two is the formal amendment that replaced the earlier ... | meridian_harbor_notice_two.txt: Current Meridian Harbor policy sets the dawn inspection window at 05:40. |
| medium_02 | benchmark_ambiguity | meridian_rail_schedule_b.txt | meridian_rail_schedule_b.txt: written to be quoted exactly. The explanatory block says the later departure ... | meridian_rail_schedule_b.txt: Current Meridian Rail schedule loads archive trunks at Dock Letter E. |
| medium_03 | benchmark_ambiguity | lantern_gallery_catalog.txt | lantern_gallery_catalog.txt: catalog remained authoritative until a signed update expressly replaced the p... | lantern_gallery_catalog.txt: Curator Leda North signs the Aurora guide card. |
| medium_04 | benchmark_ambiguity | lantern_gallery_catalog.txt | lantern_gallery_catalog.txt: which makes this catalog a useful baseline for amendment queries. A second ga... | lantern_gallery_catalog.txt: The blue copper compass sits on Shelf 12 in Atlas Room. |
| medium_05 | benchmark_ambiguity | atlas_field_manual_red.txt | atlas_field_manual_red.txt: Atlas Field Manual Red is a synthetic survey guide included to create near-id... | atlas_field_manual_red.txt: The Atlas Pine moisture tray rests on Rack C4 beside the Meridian moss jars. |
| medium_06 | scope_win | atlas_field_manual_silver.txt | atlas_field_manual_red.txt: Atlas Field Manual Red is a synthetic survey guide included to create near-id... | atlas_field_manual_silver.txt: The Atlas Pine moisture tray rests on Rack C6 beside the Meridian moss jars. |
| medium_07 | benchmark_ambiguity | northwind_clinic_brief.txt | northwind_clinic_brief.txt: the Lantern desk receives new patients, stamps Indigo 3 on the paper band, an... | northwind_clinic_brief.txt: Atlas Ward opens the Meridian recovery room at 07:45. |
| medium_08 | scope_win | copper_reserve_digest.txt | atlas_field_manual_red.txt: crews ask about the amber packet, code R17, or the C4 tray rack. It repeats t... | copper_reserve_digest.txt: Lantern turbine line Beta holds reserve key code 8841. |
| hard_01 | scope_win | meridian_harbor_notice_two.txt | meridian_harbor_notice_one.txt: during training because the benchmark depends on older facts remaining visibl... | meridian_harbor_notice_two.txt: Current Meridian Harbor policy assigns green badges to Gate 6. |
| hard_02 | benchmark_ambiguity | meridian_harbor_notice_two.txt | meridian_harbor_notice_two.txt: Meridian Harbor Notice Two is the formal amendment that replaced the earlier ... | meridian_harbor_notice_two.txt: Current Meridian Harbor policy routes Lantern crates through Atlas Terminal E... |
| hard_03 | benchmark_ambiguity | meridian_harbor_notice_two.txt | meridian_harbor_notice_two.txt: Meridian Harbor Notice Two is the formal amendment that replaced the earlier ... | meridian_harbor_notice_two.txt: Current Meridian Harbor policy sets the dawn inspection window at 05:40. |
| hard_04 | scope_win | meridian_rail_schedule_b.txt | meridian_rail_schedule_a.txt: Meridian Rail Schedule A is a synthetic station notice included to test retri... | meridian_rail_schedule_b.txt: Current Meridian Rail schedule sends Train Atlas from Platform 5 at 20:05. |
| hard_05 | scope_win | meridian_rail_schedule_b.txt | meridian_rail_schedule_a.txt: Meridian Rail Schedule A is a synthetic station notice included to test retri... | meridian_rail_schedule_b.txt: Current Meridian Rail schedule keeps the Lantern shuttle at Bay 4. |
| hard_06 | both_wrong | lantern_gallery_update.txt | lantern_gallery_catalog.txt: The Lantern Gallery catalog is a synthetic museum document designed for retri... | lantern_gallery_catalog.txt: The River Glass exhibit opens at 09:30 in the Meridian Lantern Gallery. |
| hard_07 | scope_win | lantern_gallery_update.txt | lantern_gallery_catalog.txt: which makes this catalog a useful baseline for amendment queries. A second ga... | lantern_gallery_update.txt: The blue copper compass now sits on Shelf 14 in Atlas Room. |
