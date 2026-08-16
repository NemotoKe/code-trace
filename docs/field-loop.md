# 実コード投入と改善のループ

codewiki を実際の対象リポジトリに当て、効いているかを数字で出し、外れたものを
こちら側（開発環境）へ戻して直すまでの手順。

- **回す人:** 本人のみ
- **回す場所:** 実ソースのある環境（以下 **環境B**）
- **直す場所:** codewiki を開発している環境（以下 **環境A**）

環境A では実ソースを見られない。だから **数字と再現例だけが境界を渡る**。
この文書はその渡し方まで含めて手順にしてある。

---

## 0. 境界: 何が渡れるか

| 方向 | 渡れるもの |
|---|---|
| 環境A → 環境B | **git clone。** codewiki 本体はそのまま持ち込める |
| 環境B → 環境A | **集計値（件数・率）** と **人が手で書き直した合成例** |
| 環境B → 環境A | **渡せない:** 実ソースの断片 / FQN / ファイルパス / テーブル名 / カラム名 / SQL 本文 |

この制約から、測定の設計原則が 2 つ出る。

1. **集計は closed vocabulary でだけ割る。**
   `verb` `access` `outcome` `confidence` `form` と entry point の `kind` は値の集合が
   コードで固定されているので持ち出せる。**テーブル名やカラム名で割った集計は、件数だけでも
   持ち出せない。**
2. **再現例は環境B で再現を確認してから渡す。**
   合成し直した Java が環境B の codewiki で同じ症状を出すことを確かめる。
   再現しない合成例は、環境A で幽霊を追いかけることになるので有害。

---

## 1. 準備（初回のみ）

```bash
git clone <remote> codewiki
cd codewiki
python3 --version            # 3.9 以上
python3 -m pytest -q         # 全件通ること（1 件でも落ちたら測定に進まない）
git rev-parse --short HEAD   # 測定値と必ずセットで記録する
```

- **サードパーティ依存もネットワークアクセスも無い。** pip install は要らない
- **`python3 -m codewiki` は clone したディレクトリの中から実行する。**
  パッケージとしてインストールされていないので、別のディレクトリからだと
  `No module named codewiki` になる。外から叩くなら `PYTHONPATH=/path/to/codewiki`
- テストが落ちたら、その環境では道具が壊れている。**測定に進まない**

---

## 2. 索引を作る

```bash
TARGET=/path/to/target-repo
RUN=$HOME/codewiki-runs/$(date +%Y%m%d)
mkdir -p "$RUN"

python3 -m codewiki index "$TARGET" --out "$RUN/idx" --jobs 8 2>&1 | tee "$RUN/index.log"
git rev-parse HEAD > "$RUN/codewiki-commit.txt"
```

- **`--out` を対象リポジトリの中に置かない。** 中に置く場合は明示指定が必要（安全弁）
- 索引は `$RUN/idx/index.sqlite3` 1 ファイル
- 規模の目安（HAPI FHIR / Java 5,110 ファイル）: **51 秒 / 336MB**。
  桁が違うなら `--jobs` を調整する

`index.log` に出る数字はこの時点でしか出ない（DB に残らないものがある）ので、
**ログは必ず保存する。**

---

## 3. 量を測る（機械が数える。判断は要らない）

```bash
python3 -m codewiki stats --out "$RUN/idx" --json > "$RUN/stats.json"   # 持ち出す
python3 -m codewiki stats --out "$RUN/idx"                              # 画面で読む
```

**この JSON がそのまま持ち出し物になる。** 中身は件数と率だけで、識別子は 1 つも入らない。
GROUP BY するのは値の集合がコードで固定されている列だけ（`language` `kind` `confidence`
`form` `outcome` `verb` `access`）で、テーブル名やカラム名やパスは `COUNT(DISTINCT …)` の
中にしか現れない。`meta` も許可リスト経由で読むので、`repo_root`（向こうの絶対パス）は出ない。
この性質は `tests/test_stats_cli.py` で固定してある。

出る 9 群:

| 群 | 中身 |
|---|---|
| `files` | 言語別ファイル数 |
| `symbols` | 宣言の総数、確信度別、種別 |
| `imports` | 形式別・結果別、内部解決率 |
| `type_resolutions` | 結果別 |
| `supertypes` | 結果別、解決率 |
| `calls` | form 別・確信度別・その組、索引メソッド数、**解決された呼び出し先の数** |
| `sql` | アクセス / テーブル / メソッド、verb×access、カラム側、**テーブルは取れたがカラムが 0 だったアクセス** |
| `entrypoints` | kind 別、メソッド数 |

**`by_*` に `other` が出たら、語彙の外の値がその数だけある。** `entrypoints.by_kind.other`
が 0 でないなら、`ENTRYPOINT_RULES` に自分で足した kind が効いている証拠。名前は
（持ち出せないので）出ない。

**読み方:** 付録C の HAPI 基準値と比べる。ただし **HAPI はライブラリであってアプリではない**
ので、一致を期待しない。見るのは 2 つだけ。

| 見るもの | 意味 |
|---|---|
| **0 の行** | その機能が実コードで**まったく効いていない**。ここが最優先 |
| **桁が違う行** | 前提が違う。除外規則・ファイル配置・方言のどれかを疑う |

`files` の `java` が想定よりずっと少ないときは、`index.log` の
`skipped dir_excluded` / `glob_excluded` を見る。除外規則が実コードの
ディレクトリ構成を落としている可能性がある。

---

## 4. 主目的を測る: カラム → 入口の到達率

**このツールの存在理由はこれ。ここが 0 なら他の数字が良くても意味がない。**

```bash
python3 -m codewiki reach --out "$RUN/idx" --json > "$RUN/reach.json"
python3 -m codewiki reach --out "$RUN/idx" --depth 16 --json > "$RUN/reach-16.json"
```

対象は `sql_accesses` に出てくるメソッド全部。HAPI の 273 メソッドで 0.4 秒。
出力は件数だけなので**そのまま持ち出せる**。

| キー | 読み方 |
|---|---|
| `reach_rate` | **この 1 つが改善の指標。** 他の数字が良くてもここが 0 なら意味がない |
| `no_caller` | 呼び出し元が 1 つも無いメソッド数。ここが大きいなら問題は入口側ではなく呼び出し辺 |
| `truncated` | 深さ上限に当たった数。**0 でないなら `--depth` を上げた結果と比べる** |
| `depth_histogram` | 到達したものの最短深さ。右に偏るほど経路が長い |
| `entrypoint_kind_hits` | どの種類の入口から届いたか。`other` は自分で足した kind |

**必ず 2 つの深さで測る。** 既定は 8 で、HAPI ではすでに上限に当たっている（付録C）。
上限に当たるとその先に入口があっても見えない。`--depth 16` で数字が動くなら、それは
到達率の問題ではなく深さの問題。

**到達率が低いとき、原因はほぼ呼び出し辺にある。** 3-3 の 2 つの数字が上限を決めている。

```
索引されたメソッド数 M、呼び出し先として解決されたメソッド数 R のとき、
上に辿れる可能性があるのは高々 R / M。
```

**計測スクリプトを自作して判定を書き直さないこと。** `reach` は `trace-up --entrypoints` と
同じ関数を呼んでいるだけで、到達判定を書き直していない。同じ判断を書き直すと、ほぼ必ず
食い違い、そして**間違っているのは自作スクリプトの方**
（→ `knowledge/workflow/mutation-testing-is-the-gate.md`）。

---

## 5. 正しさを測る（ここだけ人手）

3 と 4 は「どれだけ出たか」しか見ていない。**出たものが正しいかは別の話。**

### 5a. 既知の正解（先にこっちをやる。10 件で足りる）

自分が答えを知っている経路を 10 本選び、ツールに同じ質問をする。

```bash
python3 -m codewiki column   <TABLE>.<COLUMN> --write --json --out "$RUN/idx"
python3 -m codewiki trace-up <期待される更新メソッドの FQN> --entrypoints --out "$RUN/idx"
```

| # | 質問 | 自分の答え | ツールの答え | 一致 |
|---|---|---|---|---|
| 1 | この画面はどのカラムを更新するか | | | |
| … | | | | |

**サンプリングより先にやる理由:** 無作為 20 件の統計より、**確実に知っている 1 件の外れ**の方が
情報量が多い。しかも自分の頭の中にしかない正解なので、他のどんな方法でも代替できない。

### 5b. 無作為抽出（5a が通ってから）

決定的に（seed を使わず、同じ DB なら同じ行が出るように）抜く。

```sql
-- SQL アクセス 20 件前後
SELECT method_fqn, verb, access, table_name, line FROM sql_accesses
 WHERE access_id % 41 = 0 ORDER BY access_id;

-- 入口 20 件前後
SELECT method_fqn, kind, reason FROM entrypoints
 WHERE entrypoint_id % 4 = 0 ORDER BY entrypoint_id;

-- 解決済み呼び出し 20 件前後
SELECT caller_fqn, target_fqn, confidence, reason FROM calls
 WHERE target_fqn IS NOT NULL AND call_id % 4337 = 0 ORDER BY call_id;
```

**割る数（41 / 4 / 4337）は HAPI の件数に合わせてある。** 自分の DB では
`件数 ÷ 20` で決め直す。件数は手順 3 の `stats` の `sql.accesses` と
`entrypoints.total` と `calls.by_confidence` にある。

1 行ずつ実ソースを開いて **正 / 誤 / 判定不能** を付ける。持ち出すのは 3 つの件数だけ。

**判定不能が過半なら、それは計測ではない。** 条件を狭めて取り直す。

---

## 6. 外れを分類する

外れた 1 件を、必ずこの表のどれか 1 つに割り当ててから先へ進む。
**分類しないまま「動かない」と持ち帰らない。** 直す場所が決まらない。

| 記号 | 症状 | 確認コマンド | 直す場所 |
|---|---|---|---|
| **A** | SQL 文自体が拾えていない | `column`/`table` が 0 件。`sql_accesses` にも無い | codewiki（文字列抽出） |
| **B** | SQL は拾えたがテーブル/カラムが出ない | `stats` の `sql.accesses_without_column` が 0 でない | codewiki（SQL 解析） |
| **C** | メソッドが索引に無い / 帰属が違う | `python3 -m codewiki symbol <name>` で引けない | codewiki（宣言抽出） |
| **D** | 呼び出し辺が無い | `callers <fqn>` が空 | codewiki（呼び出し解決）**最大の穴** |
| **E** | 辺はあるが確信度で落ちる | `callers` と `callers --confirmed` の差 | 使い方 or codewiki |
| **F** | 入口として認識されない | `entrypoints` にその FQN が無い | `ENTRYPOINT_RULES` に追加 |
| **G** | 深さ / 打ち切り | `reach` の `truncated` が 0 でない | `--depth` を上げて再実行 |
| **H** | 出るが間違い | 人が見て誤り | codewiki（偽陽性） |

上から順に確認する。**A が起きていると D 以降は判定できない**（そもそも起点が無い）。

D と F はよく取り違える。**`callers` が空なら D。`callers` は出るが `--entrypoints` で
消えるなら F。**

---

## 7. 合成例に書き直して持ち出す

分類ごとに「何を再現すればよいか」が違う。**実コードの構造のうち、症状を出している部分だけ**を
別物の名前で書き直す。

| 記号 | 合成例に残すもの |
|---|---|
| A | SQL 文字列の**組み立て方**（連結・定数・外部ファイル参照のどれか） |
| B | SQL 文の**形**だけ（句の種類と並び、結合、サブクエリ）。リテラル値は消す |
| C | 宣言の**形**（修飾子・generics・アノテーションの並び・入れ子・匿名クラス） |
| D / E | 呼び出し側と受け手の**宣言の形**（型・interface・DI・overload の有無） |
| F | 入口の**目印**（アノテーション名 / 基底クラス名 / メソッド名） |
| G | **数字だけ**（実際の深さ、必要だった `--depth`） |
| H | 誤った辺を作った**形** |

**F だけ注意:** 目印の名前そのものが必要になる。社内フレームワーク名が出せない場合は、
**仮名で渡す**。環境A では仮名で実装し、環境B で `ENTRYPOINT_RULES` の定数だけ本名に
差し替える。規則が 1 つの名前付き定数に集約してあるのはこのため。

### 置換規則

- パッケージは `com.example` に統一
- クラス / メソッド / テーブル / カラムは意味の無い別名（`Foo` `bar` `T1` `C1`）
- 業務用語・コメント・ファイルパスは消す
- リテラル値（ID・コード値・URL）は消す

### 持ち出し前チェック

1. 合成例を環境B に置いて `index` → **同じ症状が出ることを確認**
2. 出なければ、条件が落ちている。落ちた条件を足して 1 に戻る
3. 出たら、その Java と「期待 / 実際」を環境A へ渡す

**再現しない合成例は渡さない。**

---

## 8. 直す（環境A）

1 欠陥 = 1 合成 fixture = 1 unit。

- fixture は `tests/` に入れる。**これがそのまま回帰テストになる**
- 実装は Codex に委譲（`codex-cli-delegation`）。AC は 3 項目以内に割る
- 統合の関門は**変異テスト**。テストが通っただけでは証拠にならない
  （→ `knowledge/workflow/mutation-testing-is-the-gate.md`）
- 1 unit = 1 コミット

---

## 9. 再測定して比べる

```bash
cd codewiki && git pull && git rev-parse --short HEAD
python3 -m pytest -q
```

- **索引の中身が変わる unit のときだけ再索引する。** query / CLI だけの unit なら
  既存の `index.sqlite3` を使い回してよい
- 3 の SQL を全部取り直し、**前回との差だけ**見る
- 4 の到達率を取り直す。**この 1 行が改善の唯一の指標**

測定値には必ず `codewiki-commit.txt` を添える。commit を書かない数字は比較できない。

---

## 付録A. 記録テンプレート（環境B → 環境A へ渡す形）

`stats --json` の出力に、機械では出せない 3 つを足すだけ。

```json
{
  "date": "2026-MM-DD",
  "codewiki_commit": "xxxxxxx",
  "stats": { "...": "stats --json の出力をそのまま貼る" },
  "reach": { "methods": 0, "reached": 0, "rate": 0.0, "depth": 8 },
  "reach_deep": { "methods": 0, "reached": 0, "rate": 0.0, "depth": 16 },
  "sampling": { "known_answers": { "n": 10, "hit": 0 },
                "random": { "n": 20, "correct": 0, "wrong": 0, "undecidable": 0 } }
}
```

**`stats` の中身は識別子が入らないことが保証されている。**
手で足す 4 行に識別子を書かないことだけ気をつければよい。

---

## 付録B. この手順を楽にする未実装の道具

| 記号 | 内容 | 状態 |
|---|---|---|
| **M1** | `codewiki stats --out … [--json]` | **実装済み。** 手順 3 はこれ 1 本になった |
| **M2** | `codewiki reach --out … [--depth N]` | **実装済み。** 手順 4 もこれ 1 本。16 秒 → 0.4 秒 |
| **M3** | `codewiki sample <table> -n N` | 未実装。5b の抽出が固定手順になる。**識別子を含むので持ち出し不可**の警告付き |

手順 3 と 4 は機械が全部やる。**人手が要るのは手順 5 だけ**になった。

---

## 付録C. HAPI 基準値

**測定日 2026-08-16 / codewiki `e297eed`（C5 込み）/ HAPI FHIR / `--jobs 8` で 51 秒 / DB 336MB**

HAPI は**ライブラリであってアプリではない**。実コードの代理にはならない。
ここに置くのは「桁の目安」と「回帰の basis」としてだけ。

```
ファイル        java 5,110 / xml 1,021 / sql 91 / properties 41
宣言            59,292  (CONFIRMED 59,201 / POSSIBLE 91)
import          84,685  内部解決率 80.4%
型解決          resolved 222,212 / external 31,590 / unresolved 81,848
supertype       4,190   解決率 93.2%

呼び出し        576,710 行
  CONFIRMED     118,500
  POSSIBLE       31,775
  UNRESOLVED    426,329
  解決率 (receiver + bare)  42.8%
  form 別:
    receiver     CONFIRMED 86,699 / POSSIBLE 23,474 / UNRESOLVED 131,118
    bare         CONFIRMED 31,801 / POSSIBLE  8,407 / UNRESOLVED  69,596
    chained      全部 UNRESOLVED 163,750
    constructor  全部 UNRESOLVED  60,624
    method_ref   全部 UNRESOLVED   1,241
  索引メソッド 49,505 に対し、呼び出し先として解決されたもの 19,070 (38.5%)

SQL             アクセス 831 / テーブル 116 / メソッド 274
カラム          アクセス 1,898 / table.column 443 / メソッド 236
                テーブルは取れたがカラムが 0 だったアクセス 119 (14.3%)
入口            main 53 / servlet 17 / jaxrs 12

到達率          SQL に触れる 273 メソッド → 入口に到達 0 (0.0%)
  うち呼び出し元が 1 つでもあるもの      52 / 273
  上向きに到達したメソッドの総数      1,294
  到達した最大深さ                        8   ← 上限に当たっている
```

**到達率 0% の読み方。** HAPI はライブラリなので、JPA 経由の SQL と 82 個の入口
（大半がテスト・デモの `main`）が繋がっていないのは、ある程度まで正しい姿。
**機構が動いていないのではない。** 上向きトレースは深さ 8 の上限まで伸びており、
1,294 個のメソッドを踏んでいる。その先に入口が無いだけ。

### C5（bare 呼び出しの解決）前後

同じ HAPI に対する測定。**辺の解像度が到達率の上限を決める**ことがはっきり出ている。

| | C5 前 (`39edff6`) | C5 後 (`e297eed`) |
|---|---|---|
| CONFIRMED な呼び出し | 86,699 | 118,500 |
| 呼び出し先として解決されたメソッド | 10,757 (21.7%) | 19,070 (38.5%) |
| 呼び出し元がある SQL メソッド | 1 / 273 | 52 / 273 |
| 上向きに到達したメソッド総数 | 55 | 1,294 |
| 到達した最大深さ | 2 | 8 |
| 到達率 | 0.0% | 0.0% |

**解決率の表示が 45.6% → 42.8% と下がっている点に注意。** 分母が receiver だけから
receiver + bare に変わったため。分子は 40,102 増えている。**率が下がったことを
劣化と読まないこと。** 率の定義が変わったときは、必ず分母を確認する。

**まだ解決されていない form が 3 つある。** `chained`（163,750）、`constructor`
（60,624）、`method_ref`（1,241）は今も全部 UNRESOLVED で、合計 225,615 件ある。
実コードで到達率が伸びないときは、ここが次の候補。
