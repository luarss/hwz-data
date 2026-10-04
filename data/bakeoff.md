| vendor | method | precision | recall | f1 | price_only_recall | latency | rows (pred/golden) | note |
|---|---|---|---|---|---|---|---|---|
| bizgram p1 | baseline_text | 0.00 | 0.00 | 0.00 | 0.00 | 0.6s | 0/194 | partial golden |
| bizgram p1 | gemini | 1.00 | 0.14 | 0.25 | 0.22 | 7.1s | 42/194 | partial golden |
| bizgram p1 | nvidia | 1.00 | 0.86 | 0.93 | 0.87 | 167.8s | 466/194 | partial golden |
| bizgram p1 | zai | 1.00 | 0.93 | 0.96 | 0.93 | 244.3s | 283/194 | partial golden |
| dynacore p2 | baseline_text | 0.00 | 0.00 | 0.00 | 0.00 | 1.5s | 0/176 | partial golden |
| dynacore p2 | gemini | 0.82 | 0.82 | 0.82 | 1.00 | 135.6s | 912/176 | partial golden |
| dynacore p2 | nvidia | 0.00 | 0.00 | 0.00 | 0.00 | 301.8s | 0/176 | RuntimeError: quarantined: invalid_response: no rows returned for a page with numbers |
| dynacore p2 | zai | 0.00 | 0.00 | 0.00 | 0.03 | 87.9s | 119/176 | partial golden |
| fuwell p2 | baseline_text | 0.84 | 1.00 | 0.92 | 1.00 | 0.5s | 135/114 | partial golden |
| fuwell p2 | gemini | 0.34 | 1.00 | 0.50 | 1.00 | 46.0s | 340/114 | partial golden |
| fuwell p2 | groq | 0.00 | 0.00 | 0.00 | 0.00 | 45.4s | 0/114 | RuntimeError: fell back to provider gemini |
| fuwell p2 | nvidia | 0.33 | 0.98 | 0.50 | 1.00 | 80.6s | 335/114 | partial golden |
| fuwell p2 | zai | 0.77 | 0.93 | 0.84 | 0.93 | 116.9s | 137/114 | partial golden |
| infinity p2 | baseline_text | 0.25 | 0.94 | 0.40 | 0.94 | 0.7s | 327/88 | partial golden |
| infinity p2 | gemini | 0.25 | 0.94 | 0.40 | 0.94 | 36.8s | 328/88 | partial golden |
| infinity p2 | groq | 0.00 | 0.00 | 0.00 | 0.00 | 41.4s | 0/88 | RuntimeError: fell back to provider gemini |
| infinity p2 | nvidia | 0.25 | 0.01 | 0.02 | 0.03 | 2.3s | 4/88 | partial golden |
| infinity p2 | zai | 0.00 | 0.01 | 0.01 | 0.05 | 250.6s | 308/88 | partial golden |
| laser p2 | baseline_text | 0.44 | 0.76 | 0.56 | 0.83 | 0.3s | 155/89 | partial golden |
| laser p2 | gemini | 0.46 | 0.96 | 0.63 | 0.99 | 17.3s | 183/89 | partial golden |
| laser p2 | groq | 0.00 | 0.00 | 0.00 | 0.00 | 52.8s | 0/89 | RuntimeError: fell back to provider gemini |
| laser p2 | nvidia | 0.15 | 0.36 | 0.21 | 0.78 | 34.3s | 212/89 | partial golden |
| laser p2 | zai | 0.83 | 0.79 | 0.81 | 0.81 | 72.4s | 84/89 | partial golden |
| pc_themes p2 | baseline_tesseract | 0.00 | 0.00 | 0.00 | 0.00 | 13.2s | 23/56 | partial golden |
| pc_themes p2 | gemini | 0.23 | 0.95 | 0.37 | 1.00 | 72.6s | 227/56 | partial golden |
| pc_themes p2 | groq | 0.09 | 0.29 | 0.14 | 0.77 | 18.6s | 174/56 | partial golden |
| pc_themes p2 | nvidia | 0.00 | 0.00 | 0.00 | 0.00 | 74.6s | 55/56 | partial golden |
| pc_themes p2 | zai | 0.20 | 0.36 | 0.26 | 0.45 | 148.7s | 99/56 | partial golden |
| techdeals p3 | baseline_text | 1.00 | 0.40 | 0.57 | 0.40 | 0.2s | 24/60 |  |
| techdeals p3 | gemini | 0.81 | 0.78 | 0.80 | 0.95 | 7.6s | 58/60 |  |
| techdeals p3 | groq | 0.37 | 0.37 | 0.37 | 0.97 | 20.4s | 59/60 |  |
| techdeals p3 | nvidia | 0.49 | 0.47 | 0.48 | 0.95 | 31.5s | 57/60 |  |
| techdeals p3 | zai | 0.00 | 0.00 | 0.00 | 0.00 | 25.7s | 0/60 | RuntimeError: fell back to provider gemini |
| tradepac p2 | baseline_tesseract | 0.00 | 0.00 | 0.00 | 0.00 | 10.3s | 2/84 | partial golden |
| tradepac p2 | gemini | 0.09 | 0.65 | 0.16 | 0.90 | 137.6s | 595/84 | partial golden |
| tradepac p2 | groq | 0.00 | 0.00 | 0.00 | 0.00 | 106.4s | 0/84 | RuntimeError: fell back to provider gemini |
| tradepac p2 | nvidia | 0.01 | 0.06 | 0.02 | 0.39 | 838.7s | 547/84 | partial golden |
| tradepac p2 | zai | 0.00 | 0.00 | 0.00 | 0.48 | 285.1s | 200/84 | partial golden |

Matrix rows (bizgram, dynacore) come from the second run with hidden-number filtering and the revised prompt, text only. Other rows come from the first run. Z.AI rows come from a separate pass. Gemini vision quota (20/day) was exhausted during the second run, so its matrix rows used flash-lite text. On 'partial golden' pages only part of the page is labelled, so precision and f1 are computed on predicted rows whose product matches a labelled product; rows column shows all predicted rows.
