---
id: entry-point-markers-in-target-codebase
category: project
captured: 2026-08-15
confidence: stated
source: 「Servlet / JAX-RS, main メソッド / バッチ起動, フレームワークが別にあったりする、、」「コードに固定で埋め込む」
tags: [entrypoint, java, domain, scope]
---

対象コードベースの Entry Point は **Servlet / JAX-RS** と **main メソッド / バッチ起動**。
**Spring MVC は選ばれなかった**（`@RestController` 等は対象外）。

判定規則は**設定ファイルではなくコードに固定で埋め込む**、と本人が選択。

## 独自フレームワークは本人が足す

> フレームワークが別にあったりする、、
> 今はないから成果物を元に俺がカスタマイズするわ

目印は**聞かない**。本人が納品物を見て自分で足す、と決めている。

こちらの責任は**足しやすくしておくこと**だけ。判定規則は 1 つの名前付き定数に集約し、
「ここに annotation 名 / 親クラス名 / メソッド名を足せば増える」と読んで分かる形にする。
規則をコードのあちこちに散らさない。**再度この質問をしないこと。**

## HAPI FHIR で規則を作ってはいけない

検証用コーパスの HAPI は**ライブラリであってアプリではない**。実測:

```
RestController 1 / Controller 3 / RequestMapping 22   （5,103 ファイル中）
public static void main 53
WebServlet 12 / Path 36 / GET 15 / POST 10
```

HAPI に合わせた規則は実コードで空振りする。E1 で annotation を
「記録するだけ・判定しない」に切ったのはこのため。

**関連:** [[codex-tasks-must-be-small-and-concrete]]
