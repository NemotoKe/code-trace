---
id: target-source-not-visible-here
category: environment
captured: 2026-08-16
confidence: stated
source: 「ここからの作業が、実ソースをみるってなると、このPCとこのアカウントだとできないんだ」
tags: [environment, measurement, target-codebase, scope]
---

**対象の実ソース（codewiki が本来向けられている Java リポジトリ）は、この PC / この
アカウントからは見られない。** 開発しているこの環境と、実ソースのある環境は別物。

したがって:

- **実コードに当てた実測は、こちら側では一切できない。** 「実際どうなっているか」を
  確かめる作業は全部、向こう側で人間の手で回る
- **HAPI FHIR は実ソースの代理ではない。** ライブラリであってアプリなので、
  entry point も SQL も実コードとは別物になる（→ [[entry-point-markers-in-target-codebase]]）。
  HAPI の数字は回帰の basis であって、品質の証拠ではない
- こちら側が出せるのは**仮説と道具**まで。数字は向こうから戻ってくるまで存在しない

**効く場面:**

- 「実コードで測って報告して」という形の unit を切りかけたとき。**切れない。**
  代わりに「向こうで測れる形にする unit」に変換する
- 実測値を根拠に設計判断をしようとしたとき。手元にある数字が HAPI 由来なら、
  それが実コードでも成り立つ保証はないと明示する
- 委譲プロンプトに実測を要求するとき。対象は HAPI か合成 fixture しかない

**関連:** [[what-crosses-the-air-gap]] / [[measure-with-scan-analyzable]]
