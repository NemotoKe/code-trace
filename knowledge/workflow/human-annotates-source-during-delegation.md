---
id: human-annotates-source-during-delegation
category: workflow
captured: 2026-08-13
confidence: stated
source: "あ、ごめん今ちょっと読んでてコメント入れてるから、無視していいよ"
tags: [review, working-tree, delegation, git]
---

人間は委譲が走っている最中に、同じ working tree のソースを読みながら**コメントを書き足す**。

したがって `git status` / `git diff` に出た変更が Codex のものだと決めつけない。**特にコメント
だけの差分は人間のものである可能性が高い。** 委譲のスコープ外のファイルが変更されていたら、
スコープ違反と断ずる前に確認する。

**やってはいけないこと:** 「スコープ外だから」と revert / checkout / stash する。人間の読解
メモを消す。

**理由:** 人間が明示。実際に一度、`codewiki/index/symbols.py` へのコメント追加を Codex の
スコープ逸脱として報告してしまった。

**効く場面:**

- 委譲の完了後に `git status` を見て差分を切り分けるとき。**Codex の担当ファイルと
  それ以外を先に分けてから読む**
- コミット前。`git add -A` で人間の作業中コメントを巻き込まないよう、委譲の成果物だけを
  明示的に stage する
- 逆方向のリスク: Codex は `workspace-write` で同じ tree に書く。人間が編集中のファイルを
  委譲スコープに含めない方が安全

**関連:** [[codex-tasks-must-be-small-and-concrete]]
