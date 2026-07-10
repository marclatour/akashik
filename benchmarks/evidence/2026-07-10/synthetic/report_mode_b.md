# Mode B Benchmark Report (Natural Language Queries)

| System   | Precision@1 | Efficiency | Provenance | Composite |
|----------|-------------|------------|------------|-----------|
| RAG      | 0.40 | 0.01 | 0.50 | 0.30 |
| GraphRAG | 0.00 | 0.00 | 0.00 | 0.00 |
| Akashik  | 0.90 | 0.13 | 0.90 | 0.67 |

## Gap Analysis
| Query ID | Mode A Akashik | Mode B Akashik | Gap  | RAG Mode B |
|----------|---------------|----------------|------|------------|
| medium_01 | 0.74 | 0.74 | 0.00 | 0.00 |
| medium_02 | 0.74 | 0.74 | 0.00 | 0.00 |
| medium_04 | 0.73 | 0.74 | -0.01 | 0.20 |
| medium_05 | 0.74 | 0.73 | 0.00 | 0.70 |
| medium_06 | 0.04 | 0.74 | -0.70 | 0.70 |
| medium_08 | 0.73 | 0.73 | -0.00 | 0.70 |
| hard_01 | 0.73 | 0.73 | 0.00 | 0.00 |
| hard_03 | 0.74 | 0.74 | 0.00 | 0.00 |
| hard_06 | 0.04 | 0.04 | 0.00 | 0.70 |
| hard_07 | 0.75 | 0.75 | 0.00 | 0.00 |

## Interpretation
- Akashik Mode B composite is 0.50-0.80; query normalization likely closes the gap.
- Akashik Mode B remains above RAG Mode B on composite.
