| case | tools called | tools | hit@3 | recall@3 | RR | ctx precision | faithful | ctx recall | relevancy | first failure |
|---|---|---|---|---|---|---|---|---|---|---|
| backup | search_docs | pass | yes | 1.00 | 1.00 | 1.00 | 0.67 | 1.00 | 1.00 | faithfulness |
| two-laptops | search_docs | pass | yes | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | - |
| restore | search_docs | pass | yes | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | - |
| config-keys | search_docs | pass | yes | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | - |
| pipe-colors | search_docs | pass | yes | 0.50 | 0.50 | 0.50 | 0.00 | 0.00 | 1.00 | retrieval |
| dry-run-import | search_docs | pass | yes | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | - |
| issue-212 | get_issue | pass | - | - | - | 1.00 | 1.00 | 1.00 | 1.00 | - |
| issue-231 | get_issue | pass | - | - | - | 1.00 | 1.00 | 1.00 | 1.00 | - |
| token-leak | get_issue | FAIL | NO | 0.00 | 0.00 | 1.00 | 0.50 | 0.00 | 1.00 | tools |
| thanks | none | pass | - | - | - | - | - | - | 1.00 | - |

7/10 cases pass every stage. Tools 9/10, hit@3 6/7, recall@3 0.786, MRR 0.786, mean faithfulness 0.796.
