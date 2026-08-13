---
id: proceed-without-per-unit-approval
category: workflow
captured: 2026-08-13
confidence: stated
source: "随時コミット分けて、どんどん進めてって、。俺の承認なしでいいよ"
tags: [orchestration, commit, autonomy, reporting]
---

unit ごとに人間の承認を待たない。**1 unit = 1 コミットで分けて、そのまま次に進む。**

**やめないこと:**

- unit ごとの報告（実装内容 / 変更ファイル / テスト結果 / AC / 重点確認箇所 / 残課題）
- **独立検証。** Codex の完了報告を信用せず AC を 1 件ずつ自分で実行する。承認が外れた分、
  ここが唯一の関門になる
- 設計判断を報告に明記すること。事後に読んで異議を出せる状態を保つ

**それでも止めて聞く場合:**

- 元の要求の範囲を出る変更（新しい能力の追加、合意した分割の変更）
- 巻き戻しにくい操作、外部に出る操作
- 人間の未コミット作業に触る必要が出たとき → [[human-annotates-source-during-delegation]]

**理由:** 人間が明示。レビューが追いつかない時期は「T2 終わったら止めて」と指示していたので、
承認の要否は固定ではなく**人間が都度切り替える**。勝手に戻さない。

**関連:** [[codex-tasks-must-be-small-and-concrete]]
