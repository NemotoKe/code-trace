---
id: measure-with-scan-analyzable
category: gotcha
captured: 2026-08-14
confidence: verified
source: 自分の実行で踏んだ（C1 / C2a の HAPI 実測値が全部ずれていた）
tags: [measurement, hapi, scan, verification]
---

実測スクリプトで対象ファイルを列挙するときは **`scan.scan()` + `scan.analyzable()` を使う**。
生の `os.walk` で `*.java` を拾うと**ビルド出力を数える**。

HAPI FHIR の内訳:

```
target/ 配下の .java   1,094      ← Maven のビルド出力。生成コードとコピー
target/ を除いた .java 5,112
全部                   6,206
scan.analyzable        5,110      ← index が実際に見るのはこれ
```

**やってはいけないこと:** 委譲プロンプトで「HAPI に対して実行して報告せよ」とだけ書く。
Codex は使い捨てスクリプトで `os.walk` を書くので、`target/` が混ざる。

```
C1 が報告した値   638,286 sites / 6,206 files
正しい値          576,433 sites / 5,103 files      ← 10.6% 過大
```

**効く場面:**

- 委譲プロンプトに実測を要求するとき。**「`scan.analyzable` が返すファイルだけを対象にせよ」
  と明記する。** ファイル数の期待値（HAPI なら 5,110）も書いておけば、ずれた時点で気づける
- 自分で検証スクリプトを書くとき。`os.walk` の除外リストに `target` を足すだけでは、
  `.mvn/wrapper` のようなものが残る
- 数字を commit message に書く前に、ファイル数が過去の unit と一致しているか見る。
  ずっと 5,110 だったものが 6,206 になっていたら、それが手掛かり
  （2026-08-17 以前は 5,103。生成扱いの 7 ファイルを解析対象から外していたため →
  [[keep-generated-files-in-the-index]]）

**関連:** [[mutation-testing-is-the-gate]]
