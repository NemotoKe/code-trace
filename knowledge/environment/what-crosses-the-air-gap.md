---
id: what-crosses-the-air-gap
category: environment
captured: 2026-08-16
confidence: stated
source: 持ち込み=「git clone できる」/ 持ち出し=「集計値 + 手で書き直した合成例」/ 実行者=「自分だけ」
tags: [environment, measurement, security, workflow]
---

開発環境（ここ）と実ソース環境の間を渡れるものは、方向ごとに決まっている。

| 方向 | 渡れるもの |
|---|---|
| ここ → 実ソース環境 | **git clone できる。** codewiki 本体はそのまま持ち込める |
| 実ソース環境 → ここ | **集計値（件数・率）と、人が手で書き直した合成例まで** |
| 実ソース環境 → ここ | **渡れない:** 実ソースの断片、FQN、ファイルパス、テーブル名、カラム名、SQL 本文 |

回すのは**本人だけ**。同僚配布や監査提出は現時点で想定しない。

**効く場面:**

- 実測用の出力を設計するとき。**識別子を含む出力は持ち出せない。**
  集計は closed vocabulary（`verb` / `access` / `outcome` / `confidence` / `form` /
  entry point の `kind`）でだけ割る。テーブル名やカラム名で割った集計は、
  件数であっても持ち出せない
- 欠陥報告を受け取るとき。手元に来るのは**合成し直された Java** であって実コードではない。
  再現しないときに「実物を見せて」は言えない。合成例に落ちていない条件を質問で埋める
- 新版を届けるとき。**git pull で足りる。** zip を作る手順は要らない
- 到達率などを「向こうで測ってもらう」形に設計するとき。人手の手間が全部そのまま
  本人のコストになる。判断が要る作業は最小限に、機械が数える所は機械に寄せる

**関連:** [[target-source-not-visible-here]] / [[mutation-testing-is-the-gate]]
