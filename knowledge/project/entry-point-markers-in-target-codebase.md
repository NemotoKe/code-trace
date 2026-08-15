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

## 未解決の穴（本人が明言）

> フレームワークが別にあったりする、、

社内・独自フレームワークの入口がある。**その目印はまだ聞けていない。**
固定埋め込みなので、そのフレームワークの入口は現状 1 件も当たらない。

対応: 判定規則を**1 つの名前付き定数に集約**しておく。目印（annotation 名 /
親クラス名 / メソッド名）を教われば 1 行追加で済む。設計をばらけさせないこと。

**次に聞くべきこと:** そのフレームワークで、入口のクラスやメソッドに必ず付く物は何か。
annotation か、継承する基底クラスか、決まった名前のメソッドか。

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
