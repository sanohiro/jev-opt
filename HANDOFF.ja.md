# HANDOFF — jev-opt の引き継ぎ(2026-09-23)

この文書は、次に作業する人・エージェント(Claude でも Codex でも)が、経緯と現状と予定と作法を全部引き継げるように書いたもの。規約の短縮版は `AGENTS.md`(英語)。仕様は `SPEC.ja.md`、知見と判断の履歴は `docs/decisions.ja.md`(90 項目、番号で参照)、数値は `results.md`(章番号で参照)。この 3 つが正本で、本文書はそこへの案内図。

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

## 3. 現状(2026-09-23 朝)

### 3.1 実証できたこと

- **機構は動く。** LLVM plugin(`plugin/jev/`)は、マークした関数とその中のループに対して、`inline(always)` / `inline(never)` / `align` / `unroll.count` / `vectorize.width` / `interleave.count` を付け、それが LLVM に消費されることを IR・機械語・remark で確認済み。plugin を載せただけでは基準のコード生成が 1 バイトも変わらない(実測)。
- **hintbench(正解を作った 8 カーネルの小さな対象)で、Jev のヒントで +6.3〜6.8%**(独立 4 バッチ、出力一致)。oracle の組み合わせ(+8.8%)の 71〜77%。同条件のランダムは 0%。Claude の一発予測どおりに付けたら負ける。有害な選択(k4 のループに幅 16 で −42%)はラウンド 1 で出たが速度ゲートが止め、ラウンド 2 で Jev 自身が捨てた(決定 88)。
- **Jev の一発回答(state 修正後、v4)は、関数属性では正解 7/8**(k2 の `inline(always)` +67.8% を含む)で Claude(3/8)を上回る。ループでは 0/4(決定 87)。
- **費用と待ち時間**: 1 ラウンド HTTP 2〜3 本、Choice 数十問、待ち時間は実験全体の 1% 前後、Hobby の無料枠で費用 0(定価でも 1 セント未満)。API は 503 のバーストがあるが、指数バックオフと「無改変で再送」で取りこぼし 0。

### 3.2 分かった限界(この基準の上で)

- **生きているヒントは 3 種だけ**: 強制インライン(`inline(always)`。定数特殊化が解けると桁違いに効く)、ベクトル幅、unroll 回数。`align` 3 種は 1 つも時計を動かさない。`inline`(inlinehint)と `cold` は **PGO 下で inliner が無視する**(LLVM 23.1.1 `InlineCost.cpp` で確認、決定 77)。語彙は v4(決定 84)。
- **4 つの実プログラム(toy / zopfli / oxipng / jaq)は、グローバルなヒントの掃引ではフラット(0〜2%)**(決定 37)。jaq の関数属性 oracle(v1)もフラット(決定 79)。v4 での再実行が進行中(§4)。
- **ループヒントの state は帰属が弱かった**(共有 std 行の remark を誤帰属)。plugin にベクトル化後の VF / IC / 存否を記録させる改修を実装済み(決定 90)、hintbench で検証中(§4)。
- **フィードバックはフィルタとして機能し、探索としては機能しない**(試したヒントについてしか語れない)。探索機構(未試行の site 上位 K に未試行候補だけの Choice)を実装済み(決定 89・90)、検証中。
- **測定**: jaq は同一バイナリでも 2〜4% 動く(A/A)。バッチ内 bootstrap の CI は較正が壊れており、MDE 超えは独立バッチで確認してから採用(決定 80)。hintbench はバッチ間 0.17 pt と静か。

### 3.3 進行中(この文書を書いている時点)

1. **jaq の関数属性 oracle、語彙 v4 での再実行**(`artifacts/jaq-search/oracle-A2/`)。前回は `inline(always)` が語彙に無く、1 Choice が 60 クロージャに波及していた。75 arm の計測は完了、担当が holdout と記録を仕上げている。結果は `results.md`「Oracle A2 (jaq)」と `docs/experiments/jaq-oracle-A2/` に入る。
2. **hintbench で探索付き Jev の再走**(`artifacts/hintbench-search/jev-v42-r5/`)。新 plugin で baseline を作り直し、`--explore 2` で 5 ラウンド。狙いは取りこぼした k8 の幅 16(+8.8%)と k3 の unroll 4(+4.4%)。結果は `results.md`「Experiment 5 (hintbench)」と `docs/experiments/hintbench/exp5.md`。

**両方の結果は、届いたら本文書 §3.4 と決定ログに追記する。届く前に引き継ぐ場合は、`results.md` の末尾と `docs/decisions.ja.md` の末尾、`git log` を見て最新を確認すること。**

### 3.4 最新結果(追記欄)

(結果が届いたらここに書く)

## 4. 今後の計画(Claude の提案。オーナー未承認の部分は「提案」)

順序は「取りこぼしを埋める → 実プログラムで数字を出す → 記事」。機械は 1 つずつ。

| # | 作業 | 目的 | 目安 | 状態 |
|---|---|---|---|---|
| 1 | hintbench 探索付き Jev(Exp5) | 探索が k8 / k3 を拾い、oracle の組み合わせにどこまで届くか | 1.5 h | 進行中 |
| 2 | jaq 関数属性 oracle v4(A2) | `inline(always)` とクロージャ修正でフラットが変わるか | 済(仕上げ中) | 進行中 |
| 3 | **語彙 v5**: `align` を外す、`unroll.disable` を `interleave.count=1` と統合(ベクトル化済みループでは同一命令。決定 85) | oracle の arm 数と無駄な測定を減らす | 半日 | 提案 |
| 4 | jaq ループ oracle(重複除去、post_vectorize の事実で state を埋める) | jaq でループヒントの正解を得る | 約 9 h(夜間) | 提案 |
| 5 | jaq で探索付き Jev 5〜8 ラウンド + ランダム | 記事の主数字。ノイズ 4% なので集計でのみ語る | 2 h | 提案 |
| 6 | **zopfli を通す**: perf でマーク → oracle(fn + loop)→ Jev | 転移先。ノイズ 0.3% で静か、実プログラム。hintbench の勝ち筋(引数の定数特殊化)が出やすい | 8〜10 h | 提案 |
| 7 | jaq が薄ければ記事の主対象を zopfli に(オーナー判断) | 「効果が出る対象を探して回る」のではなく、既に測った 2 対象からの選択 | — | 要判断 |
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

## 6. 環境と落とし穴(実測で確認したもの。決定ログの番号付き)

- toolchain は `nightly-2026-09-21` / LLVM 23.1.1(`rust-toolchain.toml`)。LLVM 22 系の nightly は無い(8)。libLLVM は共有ライブラリで plugin をホストできる(9)。ヘッダは `scripts/fetch_llvm_headers.sh`(CMake 変数名 `LLVM_ABI_BREAKING_CHECKS`、tablegen 7 ターゲット、`libc/` 展開が必要。60)。
- remark は stderr のテキスト(`-pass-remarks*`)。YAML 出力は LLVM 23 に無く、`-Zremark-dir` は fat LTO で落とす(10)。inline の remark は**呼び出し側**の行に付くので callee 名で集計する(83)。共有 std 行の remark は複数ループが混在するので、ループの事実は plugin の `post_vectorize` を一次情報にする(83・90)。
- fat LTO では plugin のループ EP はマージ後段(`VectorizerStart`)、関数属性は pre-link(`PipelineStart`)。`PipelineStart` には PGO 付きでも ProfileSummary が無い(60)。
- `.text` は debuginfo の有無、C 依存(mimalloc の `__TIME__`)で変わる。比較は正規化命令列 + `nm -S`(`scripts/norm_code_diff.py`)。基準と同一の arm は計測しない(34・80)。
- `-hints-allow-reordering=false` を全アームに固定(幅ヒントが FP を再結合して出力を変える。13・40・60)。
- jaq は `strip = true` なので `CARGO_PROFILE_RELEASE_STRIP=none`、mimalloc(C)が cycles の 23% で不可視(30・59)。oxipng は 80% が C(28)。hintbench は `-Zcross-crate-inline-threshold=never` が必須(75)。
- perf は sudo 無しでも `scripts/perf_local.sh setup` で動く(59)。コールチェーンは取れない。
- `export TARGET=x` が必要(`TARGET=x source …` は効かない。31)。plan のパスは絶対(60)。marks の `#` は行頭のみコメント(63)。
- jaq のノイズは A/A で 2〜4%、ページ配置のドリフトあり。入力を小さくして反復、`--gap-ms 250`、`taskset -c 4`(33)。hintbench / zopfli は 0.3% 以下。
- Vercel AI Gateway: `POST https://ai-gateway.vercel.sh/typesafe/v1/systemone`、`model: typesafe-ai/jev`、Choice の `criteria` はオブジェクト、Score は配列(19)。503 がバーストで来る。
- site key は jaq では一意でない(13 key が 2〜9 ループに解決)。plan のエントリは「key への指示」(64)。

## 7. ファイル地図

```
SPEC.ja.md                 仕様(v0.5 + 決定 66〜89 反映)
AGENTS.md                  規約(英語)
HANDOFF.ja.md              この文書
results.md                 全計測(追記のみ、18 章超)
docs/decisions.ja.md       知見と判断(90 項目)
docs/search-driver.md      探索ドライバの説明(語彙 v1〜v4、state、読み出し、採用、探索)
docs/experiments/          実験ごとの記録(jaq-exp3, jaq-oracle-A/A2, hintbench/, jev-prompt-study/)
docs/fp-reassoc-target-scouting.md  FP 再結合の調査(主線外)
docs/jev-samples/          手で送った Jev の request/response の見本
plugin/jev/jev.cpp, plugin/README.md   LLVM plugin(off/dump/apply/apply-dump、post_vectorize)
plugin/probe/              EP の発火を調べる probe plugin
scripts/jev_search.py      探索ドライバ(proposer: jev|random|oracle、--vocab、--explore、--readout)
scripts/jev_vocab.py       語彙と説明文(v1〜v4、凍結)
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
work/                      凍結(旧 spec、レビュー、カタログ、zenn 草稿)
```

## 8. 記憶(Claude 専用)

Claude Code の記憶ディレクトリ `~/.claude/projects/-home-hiro/memory/` に `jev-opt-*.md` が 7 件(オーナーの優先事項、主題の読み方、PGO 外しの誤り、言語方針、toolchain の実測、設計判断の履歴、決定ログの運用)。Codex など他のエージェントはこれを読めないので、内容は本文書 §2・§5・§6 に写してある。

## 9. 最初にやること(次の担当へ)

1. `git log --oneline | head -20`、`tail -150 docs/decisions.ja.md`、`results.md` の末尾 2 節を読む。
2. §3.3 の進行中 2 件が終わっているか(`docs/experiments/hintbench/exp5.md`、`docs/experiments/jaq-oracle-A2/` の有無)を確認。終わっていれば決定ログに結果を追記し、§3.4 を埋める。
3. §4 の表の次の行(語彙 v5 → jaq ループ oracle → jaq Jev ラウンド → zopfli)を、オーナーの承認を得て進める。
4. 何かを「やらない」と決めたら、その理由を決定ログに書く。
