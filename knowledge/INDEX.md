# Knowledge Index

このプロジェクトで人間から渡された暗黙知。1 行 1 エントリ。

- `[workflow]` Codex への委譲はとにかく小さく割る（AC 3 項目以内）。タスクの大きさそのものが精度を落とす。加えて具体例と検証条件を必ず添える — [workflow/codex-tasks-must-be-small-and-concrete.md](workflow/codex-tasks-must-be-small-and-concrete.md) #codex #delegation #prompt
- `[gotcha]` `codex exec resume` は `--sandbox` を受け付けない。exit code では失敗を検知できないので stderr を見る — [gotcha/codex-resume-has-no-sandbox-flag.md](gotcha/codex-resume-has-no-sandbox-flag.md) #codex #cli #sandbox
- `[workflow]` 委譲中の working tree の差分を Codex のものと決めつけない。差分の中身から下手人は判定できないので聞く — [workflow/human-annotates-source-during-delegation.md](workflow/human-annotates-source-during-delegation.md) #review #git #delegation
- `[workflow]` unit ごとの承認を待たない。1 unit = 1 コミットで進める。ただし独立検証と報告は続ける — [workflow/proceed-without-per-unit-approval.md](workflow/proceed-without-per-unit-approval.md) #orchestration #autonomy #commit
- `[workflow]` 統合の主関門は自分で回す変異テスト。reviewer は伝播する所だけ。等価変異はギャップではない — [workflow/mutation-testing-is-the-gate.md](workflow/mutation-testing-is-the-gate.md) #testing #verification #cost
- `[gotcha]` 実測は `scan.analyzable` の返すファイルだけを対象にする。生の `os.walk` はビルド出力を数える — [gotcha/measure-with-scan-analyzable.md](gotcha/measure-with-scan-analyzable.md) #measurement #verification
- `[gotcha]` `store/` に `index/` を import させない。委譲先は放っておくとやる。渡す物を「展開済みの組」と名指しする — [gotcha/store-layer-must-not-import-index.md](gotcha/store-layer-must-not-import-index.md) #architecture #layering #review
- `[gotcha]` `codewiki/index/annotations.py` は作れない。`from __future__ import annotations` が名前を奪う。import 順で出たり消えたりする — [gotcha/index-package-shadows-annotations-name.md](gotcha/index-package-shadows-annotations-name.md) #python #imports #naming
