---
id: same-size-mutation-leaves-stale-pyc
category: gotcha
captured: 2026-08-16
confidence: verified
source: 自分の実行で踏んだ（M2 の変異テストで、戻したはずのコードが動き続けた）
tags: [testing, mutation, python, cache, verification]
---

変異テストで**置換前後のバイト数が同じ変異**を入れて `git checkout -- .` で戻すと、
**戻した後も変異したコードが動き続ける。**

Python は `__pycache__/*.pyc` の有効性を**ソースの mtime（秒）とサイズ**だけで判定する。
`git checkout` は同じ秒に書き戻すので、サイズも同じなら「変わっていない」と見なされ、
変異版のバイトコードがそのまま使われる。

**実例（M2 `codewiki/query/reach.py`）:**

```
shallowest = min(   →   shallowest = max(      ← 3 文字対 3 文字。サイズが同じ
```

```
git status --short   → 何も出ない（クリーン）
grep shallowest      → min( と表示される
実際の出力            → max( の結果が出る
```

デバッグ用の `print` を 1 行足した瞬間（＝サイズが変わった瞬間）に正しい結果に戻った。
これで原因が確定した。

**何が壊れるか:** 変異が「捕捉された/生存した」の判定が両方向に狂う。

- 変異を入れた直後の実行が、**前のクリーンな .pyc** を使う → 実際は変異が走っておらず
  「テストが通った＝生存」と読んでしまう
- 逆に、戻した後の実行が**変異した .pyc** を使う → 無関係な後続の測定が汚染される

**手順:**

変異テストのループでは毎回これを入れる。

```bash
export PYTHONDONTWRITEBYTECODE=1
find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
pytest -q -p no:cacheprovider
```

**気づき方:** 同じコード・同じ入力なのに結果が違う、あるいは手計算と食い違う。
そのときは `git status` と `grep` を信じない。**ソースを読んで正しいはずなのに出力が
違うなら、実行されているのはそのソースではない。** サイズを変える 1 行（`print` など）を
足して確かめるのが一番速い。

**関連:** [[mutation-testing-is-the-gate]]
