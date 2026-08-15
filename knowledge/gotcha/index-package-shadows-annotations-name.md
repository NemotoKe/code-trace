---
id: index-package-shadows-annotations-name
category: gotcha
captured: 2026-08-15
confidence: measured
source: E1 で codewiki/index/annotations.py を作らせたら import できなかった
tags: [python, imports, naming, packaging]
---

`codewiki/index/` に **`annotations.py` という名前のモジュールは作れない。**

このプロジェクトは全モジュールの先頭に `from __future__ import annotations` を書く。
`codewiki/index/__init__.py` にもある。これが**パッケージオブジェクトに `annotations` 属性を束縛する**。

```python
>>> from codewiki.index import annotations as A
>>> type(A)
<class '__future__._Feature'>     # モジュールではない
```

`from package import name` は、submodule を import するより先に**既存の属性を優先する**。
`pipeline.py` は全 extractor をこの形で取る（`from . import resolution, scan, sql, ...`）ので、
`annotations` を足した瞬間に `_Feature` が入り、最初の `annotations.extract(...)` で落ちる。

**最悪なのは import 順に依存すること。** 誰かが `import codewiki.index.annotations` を
直接実行すると、import 機構が属性を submodule で上書きするので、**そこから先は動く**。
テストの実行順で出たり消えたりする。

**対処:** 名前を変える（`annotation_refs.py` にした）。`__init__.py` から
`from __future__ import annotations` を消すのは、他の全モジュールと不揃いになるので採らない。

**同種の危険な名前:** `__future__` が公開する識別子全部。
`generator_stop` / `division` / `print_function` / `unicode_literals` /
`absolute_import` / `with_statement` / `nested_scopes` / `generators`。

**関連:** [[store-layer-must-not-import-index]]
