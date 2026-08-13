# Knowledge Index

このプロジェクトで人間から渡された暗黙知。1 行 1 エントリ。

- `[workflow]` Codex への委譲はとにかく小さく割る（AC 3 項目以内）。タスクの大きさそのものが精度を落とす。加えて具体例と検証条件を必ず添える — [workflow/codex-tasks-must-be-small-and-concrete.md](workflow/codex-tasks-must-be-small-and-concrete.md) #codex #delegation #prompt
- `[gotcha]` `codex exec resume` は `--sandbox` を受け付けない。exit code では失敗を検知できないので stderr を見る — [gotcha/codex-resume-has-no-sandbox-flag.md](gotcha/codex-resume-has-no-sandbox-flag.md) #codex #cli #sandbox
- `[workflow]` 委譲中の working tree の差分を Codex のものと決めつけない。差分の中身から下手人は判定できないので聞く — [workflow/human-annotates-source-during-delegation.md](workflow/human-annotates-source-during-delegation.md) #review #git #delegation
- `[workflow]` unit ごとの承認を待たない。1 unit = 1 コミットで進める。ただし独立検証と報告は続ける — [workflow/proceed-without-per-unit-approval.md](workflow/proceed-without-per-unit-approval.md) #orchestration #autonomy #commit
