---
id: framework-supertypes-are-always-external
category: gotcha
captured: 2026-08-16
confidence: measured
source: E3 の servlet 判定が HAPI 全体で 0 件になった
tags: [supertypes, resolution, entrypoint, framework]
---

**フレームワークの基底クラスは、必ず `outcome='external'` / `target_fqn=NULL` になる。**
解決済み FQN を条件にした判定は、そのフレームワークに対して**永久に 0 件**を返す。

```
sqlite> SELECT name, outcome, target_fqn, COUNT(*) FROM supertypes
        WHERE name LIKE '%HttpServlet%' GROUP BY 1,2,3;
HttpServlet | external | NULL | 6
```

`javax.servlet` / `jakarta.servlet` は jar で来る。解析対象のソースに定義が無いので
`resolution` は当然 external にする。**これは解決器の欠陥ではない。**
欠陥なのは「解決済みでなければ辿らない」判定の側。

`codewiki/query/calls.py` の `_ancestor_types` は
`outcome='resolved' AND target_fqn IS NOT NULL` で絞る。**メソッド解決には正しい**
（外部型のメンバは索引に無いので辿っても何も無い）。これを**継承マーカーの判定に流用すると壊れる。**

**使い分け:**

| 目的 | 見る列 | outcome |
|---|---|---|
| 祖先のメソッドを探す | `target_fqn` | `resolved` のみ |
| 「この型は X を継承しているか」 | `name` の単純名 | **全部**（external / unresolved 含む） |

登り（どの内部型が親か）には解決済みの辺が要る。**印の照合には要らない。**
両方を混ぜないこと。

**実測（HAPI）:** 直接 `HttpServlet` を名乗る型 6 → 推移的に 31 → servlet の入口 17 件。
`name` で照合するまで 0 件だった。

**関連:** [[entry-point-markers-in-target-codebase]] / [[store-layer-must-not-import-index]]
