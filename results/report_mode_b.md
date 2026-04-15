# Mode B Benchmark Report (Natural Language Queries)

| System   | Precision@1 | Efficiency | Provenance | Composite |
|----------|-------------|------------|------------|-----------|
| RAG      | 0.40 | 0.01 | 0.50 | 0.30 |
| GraphRAG | 0.00 | 0.00 | 0.00 | 0.00 |
| Akashik  | 0.00 | 0.00 | 0.00 | 0.00 |

## Gap Analysis
| Query ID | Mode A Akashik | Mode B Akashik | Gap  | RAG Mode B |
|----------|---------------|----------------|------|------------|
| medium_01 | 1.00 | 0.00 | 1.00 | 0.00 |
| medium_02 | 1.00 | 0.00 | 1.00 | 0.00 |
| medium_04 | 0.79 | 0.00 | 0.79 | 0.20 |
| medium_05 | 1.00 | 0.00 | 1.00 | 0.70 |
| medium_06 | 1.00 | 0.00 | 1.00 | 0.70 |
| medium_08 | 1.00 | 0.00 | 1.00 | 0.70 |
| hard_01 | 1.00 | 0.00 | 1.00 | 0.00 |
| hard_03 | 1.00 | 0.00 | 1.00 | 0.00 |
| hard_06 | 1.00 | 0.00 | 1.00 | 0.70 |
| hard_07 | 1.00 | 0.00 | 1.00 | 0.00 |

## Interpretation
- Akashik Mode B composite is below 0.50; semantic fallback is required for 0.2.0.
- RAG Mode B is above Akashik Mode B; document this natural language retrieval gap.
