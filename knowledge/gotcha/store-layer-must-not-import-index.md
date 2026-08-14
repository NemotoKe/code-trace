---
id: store-layer-must-not-import-index
category: gotcha
captured: 2026-08-15
confidence: derived
source: D3a のレビューで発見。委譲先が store/db.py に index.sql を import していた
tags: [architecture, layering, delegation, review]
---

`store/` から `index/` を import させない。**Codex は放っておくとやる。**

```
index/  解析・書く  →  store/  境界  →  query/  読む
```

D3a で `store/db.py` の先頭に `from ..index.sql import table_accesses` が入り、
`write_index` の中で解析関数を呼んで「何を行にするか」を決めていた。
`index/pipeline.py` は `..store.db` を import するので、**パッケージ間の循環**になる。
`index/sql.py` がたまたま store を import しないから動いていただけ。

**なぜ委譲先がやるか:** プロンプトに「statements を渡して永続化しろ」と書くと、
渡された物から行を作る最短経路が「その場で展開関数を呼ぶ」になる。
**渡す物を「展開済みの組」と名指しする**と起きない。他の行種（`calls` は
`CallResolution`、`supertypes` は解決済みの組）は全部そうなっている。SQL だけ
そう書かなかったのが原因。

**二重計算も同時に生む。** `PipelineResult.sql_access_rows` と実際の行が、
同じ関数を別々に呼んで導かれていた。報告する数と保存する数が独立に出てくる形は、
いつか食い違う。

**構造テストは query/ しか見ていなかった** (`test_query_layer_boundary_is_...`)。
しかも `query/symbols.py` と `types.py` だけで、後から増えた `query/calls.py` は
一度も検査されていなかった。**層を足したら、その層を守るテストの対象一覧にも足す。**
現在は `store/db.py` と `query/*.py` 全部を見る。

**関連:** [[mutation-testing-is-the-gate]] / [[codex-tasks-must-be-small-and-concrete]]
