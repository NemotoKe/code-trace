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

**効く場面:**

- 是正パスを同一セッションに送るとき。`.agents/skills/codex-delegate/SKILL.md` の resume 例は
  正しく `--sandbox` を含んでいないので、**skill 通りに書けば踏まない**。`codex exec` の
  ブロックから引き写すと踏む
- **バックグラウンド実行の成否を exit code で判定しないこと。** パイプライン経由だと
  リダイレクトの exit code が 0 になり、失敗が隠れる。**stderr を必ず見る。**
  実際にこれで「是正パス送信済み」と誤報告し、欠陥が未修正のまま残っていた

**関連:** [[codex-tasks-must-be-small-and-concrete]]
