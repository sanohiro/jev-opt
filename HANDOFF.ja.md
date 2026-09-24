# HANDOFF — jev-opt の引き継ぎ(2026-09-23)

この文書は、次に作業する人・エージェント(Claude でも Codex でも)が、経緯と現状と予定と作法を全部引き継げるように書いたもの。規約の短縮版は `AGENTS.md`(英語)。仕様は `SPEC.ja.md`、知見と判断の履歴は `docs/decisions.ja.md`(104 項目、番号で参照)、数値は `results.md`(章番号で参照、§169 まで)。この 3 つが正本で、本文書はそこへの案内図。

---

## 1. 何を証明したい実験か(オーナーの言葉)

**「Jev を使って速くする。」** 問いは 1 つ: 人または Claude がマークした関数を、Jev(TypeSafe AI の小さくて速くて安い判断モデル)が**ヒント**で最大限速くできるか。

- 基準は最強のビルド: `opt-level=3 + target-cpu=native + lto=fat + codegen-units=1 + PGO`。PGO の訓練は合成ワークロードで行い、profdata は全アームで共有(準備扱い)。
- ヒント = LLVM の関数属性とループ metadata。私たちの LLVM plugin がビルド中に付ける。対象のソースも `Cargo.toml` も**一切変えない**。
- 準備(profile、ホット箇所のマーク、候補の列挙)は賢い側(人・Claude・Codex)がやってよい。Claude は「人間の代理人」であってシステムの部品ではない。ただし準備側が site ごとにヒント候補を絞ることは**禁止**(それは Claude が最適化していることになる)。語彙は固定・全マーク共通。
- Jev は「いろいろやる」: site ごとにヒントを選ぶ → 適用してビルド → 測る → 結果を返す → また選ぶ、を繰り返し、最良の plan を残す。
- 測る相手は基準、oracle(全候補を実測した上限)、ランダム探索。Claude の予測は参考値であって正解ではない(実測で 8 問中 1 問しか当たらなかった。決定 86)。

## 2. オーナーとの会話で決まった「こうあるべき」(再議論しないこと)

| # | こうあるべき | 由来 |
|---|---|---|
| 1 | 速さだけは譲れない。他は委任。作りはなるべくシンプル。判断は Jev に最大限任せる。わかりやすく | 初日の方針 |
| 2 | 主題は「Jev のヒントで速くなるか」。訓練データ選定や対象探しで速くしても意味がない。主題を変えられるのはオーナーだけ | 決定 55・57・58。Claude が 2 度主題を差し替えて 2 度指摘された |
| 3 | 基準に PGO を入れる。「PGO 使えばいいじゃん」に「その上に乗った」と答えたい。Claude は一度外す提案をして間違えた | 決定 4、`~/.claude/.../jev-opt-pgo-pushback.md` |
| 4 | マークは「Jev の判断対象を単純にする」ための準備。人が直接指示してもよい。Claude が「不要」と切ったのは読み違え | 決定 57・58 |
| 5 | Jev の各判断は独立にオン・オフでき、機能ごとに効果を測る(記事で「この機能はこのぐらい」と書きたい) | 決定 39 |
| 6 | FP 再結合(出力が許容誤差内で変わる)は「今回は実験なので」見出しに含めてよいが、オプション扱い | 決定 56(現在は主線から外れている) |
| 7 | まず小さい対象で「正解が存在する」ことを実測してから Jev を当てる。jaq は大きすぎる | 決定 72。hintbench がこれ |
| 8 | Jev の答えを Claude の判断に近づける方法を探す。ただし正解は oracle | 決定 69・86 |
| 9 | 得た知見は「こうだったからこれはやらない」の形で記録する | 決定ログの運用(決定 20 以降ずっと) |
| 10 | 成果物(コード・コミット・PR・README・CLI・results)は英語、spec・決定ログ・引き継ぎ・説明は日本語。英語記事も書きたいが今は理解のため日本語 | 決定 20 |
| 11 | `work/` は凍結。zenn 記事はオーナーが後で書く | 2026-09-21 |
| 12 | Jev に送った request / response は全部ログに残す(本数・待ち時間・費用の集計も)。オーナーが読みたい | 決定 19 |
| 13 | profile と platform の情報が Jev に届いているか疑え(オーナーの勘。実際は薄かったが、効いたのは別の要因だった) | 決定 68・70 |
| 14 | 一旦停止と言われたら全部止める。再開はオーナーの指示で | 2026-09-22 |
| 15 | 検証は小さく作ってやる。jaq は最後。同じ結論を大物で確かめ直すのは無駄 | 決定 103、2026-09-24 |

## 3. 現状(2026-09-23 朝)

### 3.1 実証できたこと

- **機構は動く。** LLVM plugin(`plugin/jev/`)は、マークした関数とその中のループに対して、`inline(always)` / `inline(never)` / `align` / `unroll.count` / `vectorize.width` / `interleave.count` を付け、それが LLVM に消費されることを IR・機械語・remark で確認済み。plugin を載せただけでは基準のコード生成が 1 バイトも変わらない(実測)。
- **hintbench(正解を作った 8 カーネルの小さな対象)で、Jev のヒントで +6.3〜6.8%**(独立 4 バッチ、出力一致)。oracle の組み合わせ(+8.8%)の 71〜77%。同条件のランダムは 0%。Claude の一発予測どおりに付けたら負ける。有害な選択(k4 のループに幅 16 で −42%)はラウンド 1 で出たが速度ゲートが止め、ラウンド 2 で Jev 自身が捨てた(決定 88)。
- **Jev の一発回答(state 修正後、v4)は、関数属性では正解 7/8**(k2 の `inline(always)` +67.8% を含む)で Claude(3/8)を上回る。ループでは 0/4(決定 87)。
- **費用と待ち時間**: 1 ラウンド HTTP 2〜3 本、Choice 数十問、待ち時間は実験全体の 1% 前後、Hobby の無料枠で費用 0(定価でも 1 セント未満)。API は 503 のバーストがあり要求サイズにその日の状態として依存する。現行方針は固定 2 s ±20% のバックオフを試行回数(上限 200 回)と壁時計(600 s)の上限まで無改変で再送し、それでもフェーズが落ちたら半分の plan は組まない。この方針の前の Exp5 は 10 フェーズ中 5 喪失、方針を入れた Exp6 は 4 arm 合計 40 フェーズ中 0 喪失(決定 92・95)。

### 3.2 分かった限界(この基準の上で)

- **生きているヒントは 3 種だけ**: 強制インライン(`inline(always)`。定数特殊化が解けると桁違いに効く)、ベクトル幅、unroll 回数。`align` 3 種は 1 つも時計を動かさない。`inline`(inlinehint)と `cold` は **PGO 下で inliner が無視する**(LLVM 23.1.1 `InlineCost.cpp` で確認、決定 77)。語彙は v4(決定 84)。
- **4 つの実プログラム(toy / zopfli / oxipng / jaq)は、グローバルなヒントの掃引ではフラット(0〜2%)**(決定 37)。jaq の関数属性 oracle(v1)もフラット(決定 79)。v4 での再実行が進行中(§4)。
- **ループヒントの state は帰属が弱かった**(共有 std 行の remark を誤帰属)。plugin にベクトル化後の VF / IC / 存否を記録させる改修を実装済み(決定 90)、Exp6 で検証済み: `post_vectorize` の事実は判定行としてそのまま Jev に届いた(§156)が、k8 の幅 16 を浮かせる効果は無かった(決定 93)。
- **フィードバックはフィルタとして機能し、探索としては機能しない**(試したヒントについてしか語れない)。探索機構(未試行の site 上位 K に未試行候補だけの Choice)を実装済み(決定 89・90)、Exp5・Exp6 で検証済み: 探索は k3 の unroll 4 は拾ったが(決定 92)、再訪予算を足した Exp6 でも k8 の幅 16 には一度も届かなかった(決定 93)。
- **再訪予算の適格条件が衝突する**: 再訪は「このラウンドの argmax が `KEEP_DEFAULT`」の site にしか働かない。これは「argmax を上書きしない」という不変条件と同じ規則なので、Jev が誤った非 KEEP ヒントを選び続ける site(Exp6 rev の k8 ループ、`unroll_count_2` に固定)は一度も再訪の対象にならない。設計は変えず記録のみ(決定 93)。
- **同一入力でも Jev の答えは揺れ、n=1 の arm では 0.5 pt の機能効果は解像できない**: バイト一致の要求でも確率は最大 0.10 動き、拮抗した argmax が入れ替わった例もある(Exp6 ctl/rev の k4 ループ)。SystemOne の API に seed / temperature などの決定性パラメータは無い(https://docs.typesafe.ai/api.md、https://docs.typesafe.ai/sdk/python/api/clients/sync.md)。機能ごとの効果を語るには arm ごとに反復(n≥3)が要る(決定 94)。
- **hintbench の k5 の 2 モード(約 358〜362 ms と約 326〜333 ms)は argv[0] の長さで決まる**: 実行パスの長さ `len` の glibc チャンククラス `max(32, (len+23) & ~15)` が 32 の倍数(c96・c128・c160)なら遅く、そうでなければ(c80・c112・c144)速い。k8 も約 2% 連動。既存 344 脚で例外 0、A/A のみのパネル 31 脚で外れ 0、len 88|89 で段差、同一 inode でも長さで変わる(配置ではない)。機構(ヒープのオフセット)は p3 が予測どおりに交互せず未確定。ドライバの confirm とパネルの base / cand はパス名が長く c112、ラウンド / 最初の holdout / oracle は c96 だったのが決定 95 の分かれ方と A/A 不合格 4 本の原因。対策として bench.py が全ラベルを 80 バイト(クラス 96)の同一長パスから実行する(決定 97、`results.md` §161)。
- **測定**: jaq は同一バイナリでも 2〜4% 動く(A/A)。バッチ内 bootstrap の CI は較正が壊れており、MDE 超えは独立バッチで確認してから採用(決定 80)。hintbench はバッチ内では静か(oracle のヌルパネル 0.17 pt)だが、上記の k5/k8 モードは実行パス長のクラスで決まり、クラスの違うバッチ同士の比較は k5 で最大 26 pt ずれる(決定 95・97)。

### 3.3 進行中だったもの(3.4 で完了)

1. **jaq の関数属性 oracle、語彙 v4 での再実行**(`artifacts/jaq-search/oracle-A2/`)。前回は `inline(always)` が語彙に無く、1 Choice が 60 クロージャに波及していた。75 arm の計測は完了、担当が holdout と記録を仕上げている。結果は `results.md`「Oracle A2 (jaq)」と `docs/experiments/jaq-oracle-A2/` に入る。
2. **hintbench で探索付き Jev の再走**(`artifacts/hintbench-search/jev-v42-r5/`)。新 plugin で baseline を作り直し、`--explore 2` で 5 ラウンド。狙いは取りこぼした k8 の幅 16(+8.8%)と k3 の unroll 4(+4.4%)。結果は `results.md`「Experiment 5 (hintbench)」と `docs/experiments/hintbench/exp5.md`。

**両方の結果は、届いたら本文書 §3.4 と決定ログに追記する。届く前に引き継ぐ場合は、`results.md` の末尾と `docs/decisions.ja.md` の末尾、`git log` を見て最新を確認すること。**

### 3.4 最新結果(2026-09-23 昼、追記済み)

- **jaq 関数属性 oracle v4(決定 91)**: 実プログラムで初めて、確認済み・MDE 超・正方向の関数属性が 1 本(`Val::hash` に `inline(always)`、objsearch で +4.5%)。ただし 3 ケース集計は +1.7%、組み合わせは +0.2% で、jaq の見出しは依然フラット。jaq で時計を動かす関数属性は強制インライン(両方向)だけ。`results.md` §135〜§142。
- **hintbench 探索付き Jev(決定 92)**: **+7.4%(oracle の 84〜86%)**、Exp4 の +6.7%(77%)から前進。探索は k3 の unroll 4 を見つけたが、k8 の幅 16 は 1 回の探索で外して二度と聞かれず取り残し。API の 503 で 5 ラウンド中 3 ラウンドのどちらかのフェーズが落ちた。`results.md` §143〜§149。
- **Experiment 6(hintbench、4 arm、決定 93〜95)**: 語彙 v5 を採用。3 arm(ctl / rev / both)が訓練 +7.4〜7.8%(oracle の組み合わせ 1.0881 の 84〜88%)、pv だけ +5.2%(k8 ループで有害な選択を引いた)。再訪予算の機構は動く(both は再訪に成功)が、幅 16(k8)には一度も届かず、`post_vectorize` の未試行判定行も null(k8 の P は 0.01 → 0.02 止まり)。試行回数ベースの 503 対策で 4 arm 合計 40 フェーズ中 0 喪失(Exp5 は 10 中 5)。rev の +11% 台の読みは k5 の計測モードであって plan の効果ではなく、見出しは 1.0780 のまま。ドライバに新フラグ: `--vocab v5`、`--explore-revisit R`、`--pv-untried on|off`、設定キー `retries=200`、`retry_wall_budget_s=600`、`backoff_cap_s=5`、`phase_resend_max=2`。`results.md` §150〜§159、`docs/experiments/hintbench/exp6.md`。
- **hintbench の A/A のみパネル調査(決定 97)**: 7 パネル約 17 分、基準バイナリのコピーだけ。k5 のモードは argv[0] の長さのクラスで決まる(周期 32 バイト、31/31 脚、len 88|89 で段差)。ファイル配置・seed・CPU・スタック位置・SMT 負荷では変わらない。機構(ヒープのオフセット)は未確定。Exp6 の訓練比と holdout 比は oracle と同クラス(c96)、confirm とパネルは c112 か混在。`results.md` §161(クラスをまたぐ既存結果の脚注表)、`docs/experiments/hintbench/aa-study.md`。修正後の 3 脚 A/A で検証済み(§162)。
- **次にやること(§4 の表の 3a〜)**: 探索の適格条件の見直し、`inline(never)` でループが site 集合から落ちる件の理解、jaq / zopfli の 2 クラス A/A 確認、jaq ループ oracle、zopfli。
- **zopfli キャンペーン開始(2026-09-23 夜)**: 準備完了(決定 98・99、`results.md` §165〜166): 探索用訓練セット(search-*.dat、896 KiB × 3)、plugin off 基準は Stage 0 と `.text` 同一、A/A 訓練 0.2% / holdout 0.05%(geomean)、MDE 3%、マーク 6 本(93.4%)、site 5 本(`oracle.selected_keys_top6`)、語彙 v6。oracle 68 arm(6 マーク × 関数属性 12 + 5 site × ループ候補 55 + 組み合わせ 1)を 22:1x に起動、成果物 `artifacts/zopfli-search/oracle/`、ログ `artifacts/zopfli-search/oracle-run.log`。見込み最悪 10 h、期待はそれより短い(§166「4. Oracle command」「Cost estimate」)。記録(結果の書き起こし)は測定担当とは別のエージェントが oracle 完了後に行う。§167(`results.md`)に Jev vs ランダム(n=3 ずつ、6 走行)の事前登録を追記済み --- oracle の後、oracle と同じ 6 マーク / 5 site / 語彙 v6 の上で走らせる。
- **zopfli の oracle 結果(決定 100、2026-09-24 朝)**: 68 arm、正しさ 68/68、基準と同一 38(未計測)。**「良い」arm は 0/67**、有害 2(`squeeze.rs:275` の unroll 4 / 8、−3.6% / −8.3%)。関数属性 12 本は no-op 4、コード変化 8 のうち 7 が確認済みの負方向(−0.3〜−2.7%、MDE 未満)で、正は 1 本も無い。最良は `squeeze.rs:325` の `unroll.count=8`(訓練 +1.26% / +1.29%、holdout +1.33%)、組み合わせ(325 と 563 の unroll 8)は訓練 +1.81% / +2.06%、holdout +1.77%。いずれも MDE 3% 未満で「良い」ではない。Stage 0 の `-unroll-max-count=1`(+1.6%、`cache.rs:108`)に対応する arm は無い(`cache.rs:108` は上限規則で site 集合外、`unroll.disable` は届いた site で no-op)。WSL 再起動(05:53)でラウンド 68 が途切れ、`--resume` でラウンド 68 だけ再計測。`results.md` §168、`docs/experiments/zopfli/oracle.md`。§167 の 6 走行はこの後そのまま計測した(次の行)。
- **zopfli で Jev vs ランダム(各 n=3、決定 101、2026-09-24 昼)**: 6 走行(06:37〜11:54)のすべてで採用 plan は 0。代表値は 6 本とも基準の 1.0000 で、中央値の差は 0 pt。**n=3 で未解像(フラット)**。Jev の 15 plan のうち 14 本は基準より遅く(0.9656〜0.9974。残る 1 本は 1.0001 で CI が 1 をまたぐ)、6 本は両バッチとも −3% を超えた。中身は oracle の MDE 未満の損失か no-op(とくに `find_longest_match` の `inline(always)`)。有害 arm(`squeeze.rs:275` の unroll 4 / 8)は 0/15。平坦 site での KEEP 率は 80%(71 / 77 / 91%)で、Jev 自身が全問 KEEP に達したのは 1/3 走行(jev-r2 のラウンド 3〜5)だけ。基準を守ったのは速度ゲート。ランダムは有害な unroll 8 を 2 回引いた(0.9429、0.8803)が、どちらもゲートが棄却した。ラウンド 1 の要求は 3 対ともバイト一致し、max |ΔP| 0.07、argmax 反転 0。それでも強制選択の同点(0.07 / 0.07)で 1 走行の plan が変わった。ゲートウェイは 42 要求がすべて着地して喪失 0、費用 $0。holdout は全部 null arm(基準対基準)。`results.md` §169、`docs/experiments/zopfli/jev-vs-random.md`。
- 計測 protocol v2 を toy / hintbench で検証(§170、決定 104)。

## 4. 今後の計画(Claude の提案。オーナー未承認の部分は「提案」)

順序は「取りこぼしを埋める → 実プログラムで数字を出す → 記事」。機械は 1 つずつ。

| # | 作業 | 目的 | 目安 | 状態 |
|---|---|---|---|---|
| 1 | hintbench 探索付き Jev(Exp5) | 探索が k8 / k3 を拾い、oracle の組み合わせにどこまで届くか | 1.5 h | **済**(+7.4%、84〜86%。k3 は拾い k8 は取り残し。決定 92) |
| 2 | jaq 関数属性 oracle v4(A2) | `inline(always)` とクロージャ修正でフラットが変わるか | — | **済**(`Val::hash inline(always)` +4.5% が 1 本。見出しはフラット。決定 91) |
| 3 | **語彙 v5**: `align` を外す、`unroll.disable` を `interleave.count=1` と統合(決定 85)。**探索の予算**(同一 site の再訪、または未試行候補を Score で順位付け)、`post_vectorize` 判定行に「LLVM の選択であって隣に未試行の幅がある」を明記、503 の再送上限を増やす(決定 92) | oracle の無駄を減らし、k8 型の取り残しと API 落ちを潰す | 1 日 | **済**(v5、再訪予算、判定行、503 対策。Exp6 で評価。決定 93〜95) |
| 3a | 探索の適格条件の見直し: argmax が非 KEEP に固定された site(rev の k8 型)をどう再訪するか | 再訪予算が届かない site を無くす | — | **見送り(決定 103)**: hintbench の残差(k8 の幅 16 に Jev が P 0.01〜0.08 しか付けない)も実プログラムの見出し(天井が MDE 未満)も変えられない |
| 3b | arm ごとの反復(n≥3)で per-feature 効果を測る。または API 側に決定性が無いことを前提に規則を書き直す | 0.5 pt の機能効果を提案側の揺れと区別する(決定 94) | 3 倍の時間 | 済(決定 96、spec §2) |
| 3c | hintbench の A/A のみのパネル調査(基準のコピー数本、複数 seed、k5・k8 の mean_s を報告して計測モードの原因を探る) | 初回パネルを信用してよい条件を作る(決定 95) | jaq の前に、約 30 分 | **済**(argv[0] 長が鍵。bench.py を 80 バイト固定に。決定 97) |
| 3e | jaq / zopfli の A/A を 2 クラスで確認(約 10 分ずつ) | 実プログラムも argv[0] 長で動くかを確かめる(決定 97) | 約 20 分 | **済**(どちらも NULL。hintbench の k5 の長さ依存は対象固有。決定 99) |
| 3f | `--readout argmax`(全 KEEP のフェーズを空にする読み出し、決定 71)の arm を、天井の無い対象での対照として登録する | oracle の天井が MDE 未満の対象では `forced_top1` + `--explore 2` がどのラウンドでも基準を組めない構造上の限界を、別の読み出しで切り分ける(決定 102(b)) | — | **見送り(決定 103)**: 同じ理由(実プログラムの見出しを変えない) |
| 3d | `inline(never)` を付けたカーネルのループが同ラウンドの phase B の site 集合から落ちる件の理解 | 未調査のバグを潰す(exp6.md §7) | — | 提案 |
| 4 | jaq ループ oracle(重複除去、post_vectorize の事実で state を埋める) | jaq でループヒントの正解を得る | 約 9 h(夜間) | **見送り(決定 103)**: 検証は小さい対象で行う方針。jaq は最後(段階化した oracle と最終数字の 2 回のみ) |
| 5 | jaq で探索付き Jev 5〜8 ラウンド + ランダム | 記事の主数字。ノイズ 4% なので集計でのみ語る | jaq では jev n=3 + ランダム n=3 の 6 走行だけを回し、機能ごとのアブレーションは 1 走行 30 分の hintbench で行う。費用は 1 走行 5 ラウンドとして、Exp3 の実測(約 5 分/ラウンド、確認バッチ無し、`results.md` §102)なら約 3〜4 h、確認バッチ込み(未測定)なら数倍。最初の走行で壁時計を測ってから事前登録を確定する。 | 提案 |
| 6 | **zopfli を通す**: perf でマーク → oracle(fn + loop)→ Jev | 転移先。ノイズ 0.3% で静か、実プログラム。hintbench の勝ち筋(引数の定数特殊化)が出やすい | 8〜10 h | **済(決定 100・101)**: oracle は「良い」0/67、最良 +1.3%(`squeeze.rs:325` unroll 8)、組み合わせ +1.8%(holdout +1.77%)で、いずれも MDE 未満(`results.md` §168)。Jev vs ランダム(各 n=3)は採用 plan が 6 走行とも 0、代表値はすべて 1.0000 で、n=3 で未解像(§169)。 |
| 7 | jaq が薄ければ記事の主対象を zopfli に(オーナー判断) | 「効果が出る対象を探して回る」のではなく、既に測った 2 対象からの選択 | — | **要判断**(決定 101)。事実: jaq はフラット(関数属性 oracle の組み合わせ +0.2%、決定 91)。zopfli もフラット(oracle の天井 +1.8% < MDE 3%、Jev・ランダムとも採用 0、決定 100・101)。正の結果は hintbench の +7.4〜7.8%(決定 93)だけ。主対象の選択はオーナー判断 |
| 8 | 記事の骨格: hintbench で機構、実プログラムで転移、PGO 下で死ぬヒントの発見、測定の教訓 | zenn 記事(オーナーが書く)の素材 | — | 提案 |
| 9 | 英語版 `SPEC.md` の生成、`work/` の zenn 草稿の破棄または更新 | 英語記事の参照先 | 半日 | 提案 |

**やらないと決めたこと**(理由は決定ログ): 訓練データ選定を Jev に任せる(43〜54)、FP 再結合の主線化(56 → 主線外)、ループベクトル化ヒントだけの構成(v0.3)、Claude を正解の参照点にする(86)、`inline` / `cold` / `hot` を語彙に残す(77)、静的 Jev(全ループに問い合わせ、5)、llama2-rs 等の対象探し(57)。

## 5. 作法(ログ・記録・コミット)

- **決定ログ** `docs/decisions.ja.md`: 何かを「やる / やらない / 変える」と決めるたびに 1 項目追記。書式は「### N. 見出し」→ **知見**(観測と `results.md` の章番号)→ **判断** → **影響**(spec の節)。番号は連番、削除しない、間違いは新項目で訂正。
- **results.md**: 追記のみ。実験ごとに `##` 節。**全数値にそれを出したコマンド**。事前登録の規則(採用条件、MDE、打ち切り)は数値の前に書く。欠測を成功値で埋めない。
- **Jev ログ**: `artifacts/<target>-search/<run>/jev-log/` に JSONL(request / response 全体)と `.log`(1 問い合わせ 1 行 + 集計)。`docs/experiments/` にコピーを置くときは `.log` は `git add -f`(`*.log` が ignore されている)。
- **コミット**: 小さく、`git add <明示パス>`(`-A` 禁止。並行エージェントの未コミット分を巻き込む事故が 2 回起きた)。英語メッセージ、末尾に `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`(Claude が書いた場合。他のモデルは自分の行)。push はオーナーの指示で。
- **spec の更新**: 決定が溜まったらまとめて反映し、ヘッダの「反映済み決定 N〜M」を更新。「実測 / 仮説(ソース確認)/ 未測定」を区別して書く。
- **凍結物**: `scripts/jev_vocab.py` の文言、state テンプレート、`targets/*/sites.json` の site 集合、`jev-marks.txt`、`EXPECTED.md` §1〜§4。変えるときは新バージョンを足す(v1〜v4 が共存している理由)。
- **並行作業**: 計測は同時に 1 つ。実行中の bash スクリプトを編集しない。API だけの作業(prompt study、一発回答)は計測と並行してよい。
- **計測中は対象の入力ファイル / `targets/*/workloads/` に書き込まない(`gen.py` のような生成も含む)。** 2026-09-23 に計測中の書き換え(zopfli の holdout 入力の再生成)でパネル 1 本を無効にした(決定 99)。生成・再生成は計測の前後に行う。
- **止まった担当の見つけ方**(2 度起きた): サブエージェントが「バックグラウンド作業待ち」を繰り返しているのに `ps -eo cmd | grep -E 'bench.py|jev_search|cargo'` に何も無く、成果物ディレクトリの更新が 15 分以上止まっていたら、後処理で固まっている。計測は `rounds.jsonl` に残っているので、担当を止めて別の担当に「成果物から記録とコミットを仕上げる」だけを頼めばよい(計測のやり直しは不要)。長い掃引は「計測」と「記録・コミット」を別の担当に分けると安全。
- **検証は小さく作ってやる。** driver・探索機構・語彙・state・計測手順の検証は `toy` か `hintbench` だけで行う(数分〜30 分/走行)。実プログラム(jaq・zopfli・oxipng)で計測するのは、段階化した oracle(関数属性 → LLVM が実際に触るループだけ)と記事の最終数字の 2 回だけ。oracle が「良い」site を 1 つも見つけなかった対象では探索(Jev / ランダム)を走らせず「天井なし」で終える(**打ち切り規則**)。実プログラムで 1 時間を超える計測は、事前登録(何が分かるか・小さい対象で代替できないか・所要時間)を書いてオーナーの承認を得てから始める(決定 103)。
- **長い計測は `setsid nohup … &` で起動する**。待機ループで `pgrep -f` を使うときはパターンを `'[j]ev_search'` のように括弧書きにする(そのままだと待機ループを起動したシェル自身のコマンド行に自己一致し、30 分ほど止まったことがある)。
- **Jev ログを grep するときは JSONL の `.request.questions[].instructions` を見る。** 質問文は `state` にも `.log`(人間可読の要約)にも入らないので、そこを grep しても「送られていない」という誤読になる(results.md §156)。

## 6. 環境と落とし穴(実測で確認したもの。決定ログの番号付き)

- toolchain は `nightly-2026-09-21` / LLVM 23.1.1(`rust-toolchain.toml`)。LLVM 22 系の nightly は無い(8)。libLLVM は共有ライブラリで plugin をホストできる(9)。ヘッダは `scripts/fetch_llvm_headers.sh`(CMake 変数名 `LLVM_ABI_BREAKING_CHECKS`、tablegen 7 ターゲット、`libc/` 展開が必要。60)。
- remark は stderr のテキスト(`-pass-remarks*`)。YAML 出力は LLVM 23 に無く、`-Zremark-dir` は fat LTO で落とす(10)。inline の remark は**呼び出し側**の行に付くので callee 名で集計する(83)。共有 std 行の remark は複数ループが混在するので、ループの事実は plugin の `post_vectorize` を一次情報にする(83・90)。
- fat LTO では plugin のループ EP はマージ後段(`VectorizerStart`)、関数属性は pre-link(`PipelineStart`)。`PipelineStart` には PGO 付きでも ProfileSummary が無い(60)。
- `.text` は debuginfo の有無、C 依存(mimalloc の `__TIME__`)で変わる。比較は正規化命令列 + `nm -S`(`scripts/norm_code_diff.py`)。基準と同一の arm は計測しない(34・80)。
- `-hints-allow-reordering=false` を全アームに固定(幅ヒントが FP を再結合して出力を変える。13・40・60)。
- jaq は `strip = true` なので `CARGO_PROFILE_RELEASE_STRIP=none`、mimalloc(C)が cycles の 23% で不可視(30・59)。oxipng は 80% が C(28)。hintbench は `-Zcross-crate-inline-threshold=never` が必須(75)。
- perf は sudo 無しでも `scripts/perf_local.sh setup` で動く(59)。コールチェーンは取れない。
- `export TARGET=x` が必要(`TARGET=x source …` は効かない。31)。plan のパスは絶対(60)。marks の `#` は行頭のみコメント(63)。
- jaq のノイズは A/A で 2〜4%、ページ配置のドリフトあり。入力を小さくして反復、`--gap-ms 250`、`taskset -c 4`(33)。hintbench は A/A が 0.3% 以下で収まる日もあるが、k5 は同一バイナリで 2 つの計測モード(約 358〜362 ms と約 326〜333 ms)を持ち最大 26 pt 動く。モードは argv[0] の長さで決まる(決定 95・97、§3.2)。zopfli の 0.3% は Stage 0 時点の値で、同種のモード切替は未確認。
- timing バイナリの絶対パス長で k5 が約 9% 動く(glibc チャンククラスが 32 の倍数だと遅い)。bench.py が全ラベルを 80 バイト(クラス 96)に固定する(決定 97)。
- `bench.py` は timing 用の別名パスを 80 バイトに固定するため、リポジトリの絶対パスが 75 バイトを超えると全計測が開始前に失敗する(現状 27 バイト。長いパスに clone すると壊れる。決定 97)。
- クラス→モードの対応(c96 が遅い)はこの機械の glibc / カーネルでの実測。別の機械では `scripts/hintbench_aa_study/run.sh` を先に回し、クラス 96 が比較可能なクラスであることを確認してから信用する。
- Vercel AI Gateway: `POST https://ai-gateway.vercel.sh/typesafe/v1/systemone`、`model: typesafe-ai/jev`、Choice の `criteria` はオブジェクト、Score は配列(19)。503 がバーストで来る。
- site key は jaq では一意でない(13 key が 2〜9 ループに解決)。plan のエントリは「key への指示」(64)。
- Vercel/TypeSafe の 503 はその日の提供側の状態として要求サイズに単調依存する(固定の閾値ではない): phase A 85 KB は 0/6、B 51 KB は 4/18、探索 24 KB は 5/6 だったが、jaq の phase A(約 104 KB)は前日 5/5 だった。待ち時間ではなく試行回数で吸収する(2 s 固定 ±20% のバックオフ、上限 200 回 / 600 s、フェーズが落ちたら丸ごと再送し半分の plan は組まない。決定 92・95)。
- **採用 0 の走行では `best-plan.json` が書かれないのに、`summary.md` は「コピーした」と言う。** zopfli の Jev vs ランダム 6 走行はすべて採用 plan 0(基準のまま)で、`jev_search.py` は `best-plan.json` を一切出力しなかったが、`summary.md` の文言は「コピーした」ことになっている。driver の不整合として記録のみ(修正は未着手、決定 102(c))。読み手はこの文言を信用せず、まず実際にファイルがあるかを見ること。
- **zopfli の holdout バッチ 3 本で MDE が 8.9〜18.3% と出た**(A/A では 0.05% の対象で)。いずれも基準 vs 基準の null arm 同士の比較だったので採否や見出しには影響していないが、原因は未調査(`results.md` §169 の「非決定性」節)。
- **zopfli oracle のラウンド 68 は WSL 再起動(05:53)で計測が途切れ、`--resume` で再計測した(§168 参照)。再起動前に計測していたバイナリの sha256 は記録されておらず、「再起動前後で同一」という主張はビルドの決定性(同じ入力から同じバイトが出る)に依っていて、実測で突き合わせてはいない。**
- 新規の oracle は `--protocol v2`(決定 104)。hintbench では `--mde` 固定か `--reps-oracle 15`。

## 7. ファイル地図

```
SPEC.ja.md                 仕様(v0.5 + 決定 66〜102 反映)
AGENTS.md                  規約(英語)
HANDOFF.ja.md              この文書
results.md                 全計測(追記のみ、18 章超)
docs/decisions.ja.md       知見と判断(104 項目)
docs/search-driver.md      探索ドライバの説明(語彙 v1〜v5、state、読み出し、採用、探索、再訪、503)
docs/experiments/          実験ごとの記録(jaq-exp3, jaq-oracle-A/A2, hintbench/exp5.md, exp6.md, aa-study.md, jev-prompt-study/)
docs/fp-reassoc-target-scouting.md  FP 再結合の調査(主線外)
docs/jev-samples/          手で送った Jev の request/response の見本
plugin/jev/jev.cpp, plugin/README.md   LLVM plugin(off/dump/apply/apply-dump、post_vectorize)
plugin/probe/              EP の発火を調べる probe plugin
scripts/jev_search.py      探索ドライバ(proposer: jev|random|oracle、--vocab、--explore、--explore-revisit、--pv-untried、--readout)
scripts/jev_vocab.py       語彙と説明文(v1〜v5、凍結)
scripts/jev_oneshot.py     API だけで一発回答を取る
scripts/target_common.sh   対象ごとのビルドレシピ(toy/zopfli/oxipng/jaq/hintbench)
scripts/target_pgo_baseline.sh, target_aa.sh, target_headroom.sh   PGO 基準、A/A、掃引
scripts/bench.py           交互計測 + paired bootstrap(--shuffle, --gap-ms)
scripts/norm_code_diff.py  正規化命令列の比較(no-op 判定)
scripts/perf_local.sh, perf_hotness.py, perf_marks_profile.sh   perf の私設インストールとマーク選定
scripts/hintbench_oracle.sh, hintbench_exp4_score.py             hintbench の oracle と採点
scripts/jaq_sites.sh, jaq_sites_report.py                          jaq の site 列挙
targets/toy/               機構検証用 4 ループ
targets/hintbench/         正解のある 8 カーネル(EXPECTED.md = Claude の計測前予測と §5 の採点)
targets/jaq/               本命(submodule v3.1.1、jev-marks.txt 15 本、sites.json)
targets/zopfli/, oxipng/   Stage 0 のみ(フラット)。zopfli は転移先候補
jev-opt.toml               設定。.env に AI_GATEWAY_API_KEY(git 管理外)
artifacts/hintbench-search/exp6-{ctl,rev,pv,both}/  Experiment 6 の成果物(rounds.jsonl、jev-log/、holdout-batch2{,b}/)
work/                      凍結(旧 spec、レビュー、カタログ、zenn 草稿)
```

## 8. 記憶(Claude 専用)

Claude Code の記憶ディレクトリ `~/.claude/projects/-home-hiro/memory/` に `jev-opt-*.md` が 7 件(オーナーの優先事項、主題の読み方、PGO 外しの誤り、言語方針、toolchain の実測、設計判断の履歴、決定ログの運用)。Codex など他のエージェントはこれを読めないので、内容は本文書 §2・§5・§6 に写してある。

## 9. 最初にやること(次の担当へ)

1. `git log --oneline | head -20`、`tail -150 docs/decisions.ja.md`、`results.md` の末尾 2 節を読む。
2. §3.3 の進行中 2 件は完了済み(jaq 関数属性 oracle v4 は決定 91・`results.md`「Oracle A2 (jaq)」、hintbench 探索付き Jev は Exp5 決定 92 と Exp6 決定 93〜95、`docs/experiments/hintbench/exp5.md`・`exp6.md`)。新たに「進行中」を残した作業があれば、終わり次第ここと決定ログと §3.4 に追記する。
3. §4 の表で未着手なのは 3a(探索の適格条件の見直し)、3d(`inline(never)` の site 落ちの理解)、jaq ループ oracle。3e と zopfli(行 6)は済(決定 99〜101)。いずれもオーナーの承認を得て進める。
4. **オーナー判断待ち**: 記事の主対象(§4 の行 7)、`cache.rs:108` を足した zopfli の追加 site-set(Stage 0 の唯一のレバー。上限規則で今回の 5 site から漏れた。同じ 6 マークの上で、新しい事前登録として)、再訪の適格条件(3a)。zopfli の oracle と Jev vs ランダムは済んだ(決定 100・101、`results.md` §168・§169)。判断が出るまで、新しい計測は始めない。
5. 何かを「やらない」と決めたら、その理由を決定ログに書く。
