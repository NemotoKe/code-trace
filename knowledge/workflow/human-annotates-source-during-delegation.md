---
id: human-annotates-source-during-delegation
category: workflow
captured: 2026-08-13
confidence: stated
source: "あ、ごめん今ちょっと読んでてコメント入れてるから、無視していいよ"
tags: [review, working-tree, delegation, git]
---

人間は委譲が走っている最中に、同じ working tree のソースを**自分で編集している**。コメント
追記だけでなく、**関数分割のような構造 refactor も入る**。

したがって `git status` / `git diff` に出た変更が Codex のものだと決めつけない。委譲のスコープ
外のファイルが変更されていたら、スコープ違反と断ずる前に**必ず人間に確認する**。

**「コメントだけなら人間、コードなら Codex」という切り分けは使えない。** 一度この判定規則を
書いて、次に人間が `extract` を関数分割したときに Codex の暴走だと誤断した。差分の中身から
下手人は判定できない。**聞く。**

**やってはいけないこと:** 「スコープ外だから」と revert / checkout / stash する。人間の読解
メモを消す。

**理由:** 人間が明示。実際に 2 回誤断した。1 回目は `codewiki/index/symbols.py` への
コメント追加を Codex のスコープ逸脱として報告。2 回目は同ファイルの `extract` 関数分割を
「Codex が人間のコメントを破壊した」と判断し、Codex のログから復元を試みかけた。
**どちらも人間自身の編集だった。**

**効く場面:**

- 委譲の完了後に `git status` を見て差分を切り分けるとき。**Codex の担当ファイルと
  それ以外を先に分けてから読む**
- コミット前。`git add -A` で人間の作業中コメントを巻き込まないよう、委譲の成果物だけを
  明示的に stage する
- 逆方向のリスク: Codex は `workspace-write` で同じ tree に書く。人間が編集中のファイルを
  委譲スコープに含めない方が安全

**関連:** [[codex-tasks-must-be-small-and-concrete]]
