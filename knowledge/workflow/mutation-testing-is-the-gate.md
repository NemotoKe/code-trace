---
id: mutation-testing-is-the-gate
category: workflow
captured: 2026-08-13
confidence: stated
source: "正直、統合系は君がやった方が早かったりする？トークン節約のためなんだけど" / "やりたいようにskill直して、最適化して欲しい"
tags: [testing, verification, orchestration, cost]
---

統合フェーズの主関門は **オーケストレータ自身が回す変異テスト**。`integration-reviewer` ではない。

テストが通っただけでは何の証拠にもならない。**テストと実装を同じ worker が書いている**ので、
実装をなぞったテストでも通る。worktree を切って実装を故意に壊し、スイートが落ちるかを見る。

**実測（型階層 H1〜H3b）:**

| 作業 | 見つけた本物の欠陥 | コスト |
|---|---|---|
| integration-test-builder | 0 | Codex max 1 セッション |
| **変異テスト（自分）** | **1（唯一）** | スクリプト 2 本 |
| integration-reviewer（T1 時） | 実質 3 / 5。1 件は誤検知、並列テストの穴は見逃し | Codex max 1 セッション |

**効く場面:**

- `integration-reviewer` は**間違いが遠くまで伝播する所だけ**に絞る。他の unit が上に積む
  データ、スキーマ、出力が辺になる resolver。薄い CLI ラッパーには要らない
- `integration-test-builder` は残す。**永続するテストファイルを産む**から。ただしプロンプトは
  実装委譲と同じ規律で書く（契約を具体例で、スコープと非目標を明示、検証条件を指定）
- 生き残った変異は**必ず中身を読む**。等価変異（挙動が変わらない）はギャップではない。
  8 件中 2 件が等価だった
- 大規模コーパスの再計測は、**索引の中身が変わり得る unit だけ**。query / CLI の unit は
  既存の索引を使い回す

**関連:** [[codex-tasks-must-be-small-and-concrete]] / [[proceed-without-per-unit-approval]]
