---
id: do-not-flatten-sql-before-analyzing
category: gotcha
captured: 2026-08-16
confidence: measured
source: R2 の read 数が Codex 1,566 / 自分 1,554 で一貫して 12 ずれた
tags: [measurement, sql, verification]
---

計測スクリプトで **`" ".join(lit.statement.split())` をしてはいけない。**
`--` コメントは**行末まで**なので、複数行の文を 1 行に潰すと**以降が全部コメントになる。**

```
生の statement で数えた read : 1566   ← pipeline が実際に使う値
1 行に潰して数えた read      : 1554   ← 計測スクリプト
```

```
SqlUtilTest.java:19         生=1  潰し=0
    select\n  *\n   -- COMMENT\n  FROM FOO;
HapiFhirJpaMigrationTasks:216  生=10 潰し=0
    SELECT CASE WHEN EXISTS (\n SELECT 1\n FROM sys.indexes i ...
```

`pipeline.py` は `lit.statement` を**そのまま**渡す。計測も生のまま渡すこと。
潰すのは**表示するときだけ**（CLI の 100 字切り詰めなど）。

**このセッションで実害が出たのは read 列の計測だけ**だった（表名・書き込み列は
`--` コメントの影響を受けにくく、831 / 332 は生でも潰しでも同じ）。
だが「たまたま一致していた」だけで、方法としては最初から間違っていた。

**一般則:** 計測は**本番と同じ入力**を関数に渡す。整形は結果を出す直前だけ。
食い違いを見つけたら、まず自分のスクリプトの入力を疑う。

**関連:** [[mutation-testing-is-the-gate]]（「使い捨ての計測スクリプトを疑う」の 6 件目）
