---
id: codex-resume-has-no-sandbox-flag
category: gotcha
captured: 2026-08-12
confidence: verified
source: 自分の実行で踏んだ（codex-cli 0.147.0）
tags: [codex, cli, delegation, sandbox]
---

`codex exec resume` は `--sandbox` を受け付けない。`codex exec` からコピーして付けると
**即座に終了する**。サンドボックスは `-c sandbox_mode=workspace-write` で渡す。

```bash
# 動かない
codex exec resume <ID> --sandbox workspace-write --json -m gpt-5.6-luna -

# 動く
codex exec resume <ID> --json -m gpt-5.6-luna -c sandbox_mode=workspace-write -
```

**理由:** `codex exec resume` のオプション集合が `codex exec` と異なる。`--json` は共通だが
`--sandbox` は resume 側に無い。

**`-C` / `--cd` も無い。** worktree を分けて並行委譲していると、初回は
`codex exec -C <worktree>` で投げられるのに、是正パスで同じ `-C` を付けると
`error: unexpected argument '-C' found` で即死する。resume は**その worktree に
`cd` してから**投げる。zsh なら `( cd <worktree> && cat <abs prompt> | codex exec resume ... )`。

```bash
# 動かない — resume に -C は無い
codex exec resume <ID> -C /path/to/wt-x --json -m gpt-5.6-luna -

# 動く
( cd /path/to/wt-x && cat /abs/fix.md | codex exec resume <ID> --json -m gpt-5.6-luna \
    -c model_reasoning_effort=xhigh -c sandbox_mode=workspace-write - )
```

worktree のルートは trusted 扱いなので、上の 24 行目の「repo ルートから起動する」制約とは
矛盾しない。禁じられているのは **git working tree の外**（scratchpad 直下など）から投げること。

**同じ理由で踏むもう 1 つ:** `codex` は**リポジトリルートから起動する**。scratchpad に `cd`
してからパイプで渡すと `Not inside a trusted directory and --skip-git-repo-check was not
specified.` で即終了する。プロンプトファイルは絶対パスで `cat` する。

```bash
# 動かない — cwd が git repo でない
cd /tmp/.../scratchpad && cat fix.md | codex exec resume <ID> ...

# 動く — repo ルートのまま、絶対パスで渡す
cat /tmp/.../scratchpad/fix.md | codex exec resume <ID> ...
```

**効く場面:**

- 是正パスを同一セッションに送るとき。`.agents/skills/codex-delegate/SKILL.md` の resume 例は
  正しく `--sandbox` を含んでいないので、**skill 通りに書けば踏まない**。`codex exec` の
  ブロックから引き写すと踏む
- **バックグラウンド実行の成否を exit code で判定しないこと。** パイプライン経由だと
  リダイレクトの exit code が 0 になり、失敗が隠れる。**stderr を必ず見る。**
  実際にこれで「是正パス送信済み」と誤報告し、欠陥が未修正のまま残っていた。
  trusted-directory エラーでも同じく exit 0 になり、2 度目を踏んだ

**関連:** [[codex-tasks-must-be-small-and-concrete]]
