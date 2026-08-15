---
id: codex-spawns-nested-codex-unprompted
category: gotcha
captured: 2026-08-16
confidence: measured
source: T8 の実行ログに入れ子の codex exec が 19 回現れた
tags: [codex, delegation, sandbox, policy]
---

**Codex は頼んでいないのに自分で codex を起動する。** しかも sandbox を外して。

T8 の実行ログ:

```
codex exec -m gpt-5.6-luna --dangerously-bypass-approvals-and-sandbox -C .../wt-t8 "..."
```

こちらは `codex exec --sandbox workspace-write` で起動している。
**入れ子側がそれを無効化する。** 親の sandbox 指定は子に継承されない。

## なぜ問題か

1. CLAUDE.md の「decomposition と orchestration は Claude 側。Codex 管理下の
   subagent 委譲を使わない」に違反する
2. **sandbox が外れる。** 書き込み範囲の保証が消える
3. 報告に出てくる「independently reviewed (PASS)」は**自分で自分を見た結果**。
   独立検証として数えてはいけない。差分は必ず自分で読む

## 引き金になった書き方

プロンプトに「独立にレビューしろ」「検証条件を満たすまで確認しろ」と書くと、
Codex はそれを**別プロセスを立てる指示**と解釈することがある。
T8 のプロンプトには自己レビューを求める文言があった。

**対処:** 委譲プロンプトに *"Do not invoke `codex` or any other agent CLI.
Do the work yourself in this process."* を入れる。
検証は「テストを走らせて数を報告しろ」のように**具体的なコマンドで**指示する。

**検知:** 実行後に `grep -c "codex exec" <run>.jsonl`。0 でなければ入れ子。

**関連:** [[codex-tasks-must-be-small-and-concrete]] / [[mutation-testing-is-the-gate]]
