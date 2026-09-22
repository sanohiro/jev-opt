# jev-opt 実装仕様(v0.5、日本語正本)— マークした関数を Jev がヒントで速くする

実験の問いは **「人または Claude がマークした関数を、Jev がヒントで最大限速くできるか」** の一点である。v0.3(ループヒントのグローバル掃引)と v0.4(PGO 訓練データ選定・FP 再結合)は git 履歴(`git show c58545d:SPEC.ja.md` が v0.4、その中の参照 `3a41f49` が v0.3)と `docs/decisions.ja.md` に残っており、否定結果と経緯はそちらを参照する。v0.5 は決定 58 の 4 項目にそのまま戻したもので、それ以外は仕様から落とす。本文は決定 66〜80 を反映済み(語彙 v3、state v3、読み出し規則、採用規則、対象の順序)。決定 60・62・75〜78 は実装状況として参照する。決定事項の一覧表はこの仕様には置かず `docs/decisions.ja.md` を正本とする。方針は 4 つ: **速さは追求する / 作りはシンプルにする / 判断は Jev に任せる / わかりやすくする。** 最適化は対象のソースを書き換えずに行う。本文中の主張は **実測 / 仮説(ソース確認のみ)/ 未測定** を明示する。

## 1. 一枚で分かる

### (1) マーク: 速くしたい関数を人または Claude が指定する

- perf の上位を見て、速くしたい関数を選ぶ。**方法は問わない**(人が読んで決めてもよい)。**ビルドの工程には組み込まない。** Claude は人間の代理人であってシステムの部品ではない。
- 形は 2 つ、どちらでも受ける。(a) `jev-marks.txt` — 1 行 1 関数、Rust のパス名(`jaq_core::interpret::run`)。(b) 対象ソース中の `#[jev_opt::optimize]` 属性 — CLI がソースを走査してマークに変換する。
- **解決は CLI 側で行う**(plugin は Rust のパス名を知らない)。`dump` は**全関数**の表と**全ループ**を出し、CLI が `rustc-demangle` で demangle してマークに一致するものだけを site に残す。generic は全単相化にマッチさせる。解決件数 0 の行はエラーで止める。

### (2) ヒントの一覧は固定・全マーク共通

| 種別 | ヒント | 値域 | 適用先 |
|---|---|---|---|
| 関数属性 | `inline(always)` / `inline(never)` / `align=N` | N ∈ {16, 32, 64} | マークされた関数(LLVM 属性 `alwaysinline` / `noinline` / `align`) |
| ループ | `unroll.count=N` / `unroll.disable` | N ∈ {2, 4, 8} | マーク内の各ループ(`llvm.loop.*` metadata) |
| ループ | `vectorize.width=N` / `interleave.count=N` | width ∈ {2, 4, 8, 16}、interleave ∈ {1, 2, 4} | 同上 |
| コンパイラ設定 | `-Cllvm-args` の少数のノブ | `llvm-knobs.json` から事前選定(決定 31 で動いた SLP 閾値・アラインメント系) | ビルド全体に 1 つ。マーク単位ではない |

- **`KEEP_DEFAULT`(=「何もしない」)を常に候補に含める。** 候補から外すと Jev は定数回答(関数は一律に同じインライン候補、ループは全部 `unroll.disable`)になる(決定 70(d)、v2 語彙での実測)。語彙はラウンド 1 の前に凍結し、途中で足さない。足した場合は再測定する。
- **語彙 v3(決定 77)。`inline`(inlinehint)と `cold` は語彙から外した。** このレシピ(`-Copt-level=3` + PGO + fat LTO)では、inliner は callee の属性を読んだ直後に **callsite の hotness クラスで閾値を代入上書きする**ので inlinehint は実質不活性(`InlineCost.cpp:2137` で読み `:2154` で破棄)。`cold` の閾値 45 を使う `else if`(`:2163〜2179`)は callsite が hot / locally hot / cold のいずれかに分類された時点で到達不能。`hot` は `InlineCost.cpp` に一度も現れず、そもそも inliner の入力ではない。`alwaysinline`(`:3209`)と `noinline`(`:3242`)は cost model が作られる前に決着するので profile に免疫(以上 **ソース確認**、LLVM 23.1.1、`docs/experiments/hintbench/inline-attrs-under-pgo.md` §7)。**実測**でも、hintbench では `inline` / `cold` を付けても remark の閾値が動かず(`results.md` §103〜§109)、jaq の関数属性 oracle では **90 arm 中 48 本が基準と命令列同一**だった(`inline` 10/15、`cold` 9/15、`align=16` 15/15。決定 79)。plugin の後段で `PGOInstrumentationUse` が hot 関数へ inlinehint を付けるので plugin の `inline` は冗長でもある。`inline(always)` が実際に速くするかは **未測定**(toy で属性が inline 判断を駆動する remark と出力一致を確認しただけ。決定 78)。**ループのヒントは v2 から不変。**
- 一覧は全マークで同じ。site ごとに候補を絞る作業(それは最適化そのもの)は**しない**。

### (3) Jev がいろいろやる

1. マークされた関数と、その中のループを site として列挙する(`dump`)。
2. **site ごとに Jev が Choice を 1 回**、(2) の一覧から 1 つ選ぶ。関数フェーズとループフェーズでそれぞれ 1 request(**1 request / phase**)。
3. plugin が plan を適用してビルドする(ソースは触らない)。
4. 測る(§7 の手順)。
5. 結果(site ごとの選択、集計速度比と 95% 信頼区間、採用 / 不採用)を state に入れて次の Choice へ。
6. 決めた回数(初期 **5 ラウンド**)繰り返し、**最良の plan を残す**。

- **読み出し規則(決定 71)**: driver は argmax だけを使わない。site を `1 − P(KEEP_DEFAULT)` の降順に並べ、**全 site が `KEEP_DEFAULT` でも首位 site の最良の非既定候補を 1 件だけ試す**(空 plan では結果のフィードバックが生まれず、探索が止まる)。これは「動く探索」であって「正しい探索」ではなく、正しさは oracle が決める(**未測定**)。
- **state / 語彙 v3**(`state-v3-2026-09-22` / `v3-2026-09-22`、commit `7fe1a92` で凍結)の要点: (a) 質問文は V2(「変えるべきか」ではなく「この workload でこの関数を速くする可能性が最も高いヒントはどれか」)、(b) `KEEP_DEFAULT` は中立に記述する(基準の再現であって消極的選択ではない)、(c) **関数フェーズの選択肢の説明にだけ適用条件を書く**(効く形・逆効果の形・no-op の形。ループフェーズに同じ文を置くと唯一機構のあるループの選択が壊れる)、(d) **両フェーズに機械的な判定行**(size / copy / trip / hotness / lanes / legality / inline budget を、state が数値で持っているものを読み上げた形で置く)、(e) **platform ブロック**(`lscpu`、キャッシュ、`-march=native` の解決先、レジスタ幅)、(f) **1 request / phase**。ループフェーズは v2 と byte 単位で同一なので、v2/v3 の差がループ site に出たら語彙以外が原因。
- 根拠(決定 70・73、実測): 聞き方 18 通り × 9 site × 3 回で、**聞き方は confidence(0.35〜0.93)を大きく動かすが結論はほとんど動かさない**。効いたのは (c) の適用条件つき**記述**と (d) の**判定行**だけで、9 site 中 8 が Claude の参照判断と一致、24/27 で安定した。同じ文でも state のブロックに置くと 100% KEEP、`criteria` の中に置くと選ぶ — **置き場所が本質**。`KEEP_DEFAULT` を外す「**強制**」は定数回答を招き「触るな」が正解の site を落とすので誤った聞き方。**remark は外さない**(外すとベクトル化不能ループへの vectorize 質量が 0.02〜0.11 → 0.23〜0.44 に跳ねる)。platform / profile の構造化と 1 問 1 request は選択を 1 site も変えなかった(記録のためブロックは残す)。ただしこの 8/9 は不活性候補(`inline`)を含む v2 の数字なので、**v3 で取り直す**(未測定)。

### (4) 測る

基準と Jev の最終 plan を比べる。補助として **oracle**(全候補を機械的に回した上限)と**ランダム探索**(同ラウンド数)を同じ手順で回し、Jev が賢く探せているかを見る。

## 2. 問いと結論の出し方

| 指標 | 定義 | 値 |
|---|---|---|
| **主指標** | Jev の最終 plan − 基準(集計速度比、95% 信頼区間つき) | TBD |
| **主指標(判断の質)** | **Claude の参照判断との一致率**(完全一致 / 同族 / 不一致、3 回反復の安定性)。決定 69 | TBD |
| 補助 | Jev ÷ oracle(oracle の何割を取れたか) | jaq の関数属性では**計算不能**(分母がノイズと区別できない。決定 79) |
| 補助 | Jev vs ランダム探索(同ラウンド数、同 site 集合) | TBD |
| 参考 | 待ち時間・費用(Jev 呼出しの合計) | TBD |

- **基準**: PGO + LTO + `-Ctarget-cpu=native` で固定。**PGO の訓練は合成ワークロードで行い、準備扱いとする**(全アーム・全ラウンドで同一の `merged.profdata` を共有し、その sha256 を記録する)。訓練集合の選び方は主題から外した(決定 55、§10)。
- **oracle**: 候補の直積は指数なので回さない。定義は **(a) site ごとの 1 因子掃引**(各 site で候補 1 つだけを既定から変え、他は `KEEP_DEFAULT`)+ **(b) 各 site の最良を組み合わせた 1 本**。(b) が (a) の最良を下回ることは起こりうるので、oracle = (a) と (b) を含む全アームの最良とし、そのことを結果に明記する。ビルド数は Σ(site 数 × 候補数) + 1 なので、**マークは数〜十数関数に抑え**(決定 57)、`[search] max_sites` を凍結して oracle のビルド数を事前に記録する。
- **参照判断そのものを実測で検証する。** 一致率(上の主指標)は Claude の判断が正しいことを前提にできない。jaq の関数属性 oracle では **Claude の `inline(never)` 2 件はどちらも効かず、Jev の 107 件の `KEEP_DEFAULT` は関数属性については正しかった**(決定 79、実測)。以後、参照判断は oracle の実測の正解と突き合わせてから一致率の分母に使う。
- **ノイズと最小効果量**: holdout の前に同一バイナリを 2 ラベルにした **A/A** を同一手順で回す。**jaq の A/A はおよそ 4%(実測)。** ただし**バッチ内 bootstrap CI の較正は破れている**(同一バイナリで 90 回中 41 回 1 を除外する。決定 80、§7)ので、**ノイズは「同じペアを独立したバッチで k 回測ったときのバッチ間の散らばり」で定義する**。MDE = `max(2 × A/A 半幅, 0.03)` を超えない限り「速い」と書かない。集計は約 1%、単一ケースは約 3% までしか信用できない(実測、`results.md` §58)。
- **採用規則(決定 80 a)**: **1 バッチで決めない。** MDE を超えた arm は**独立した別バッチ**(同じ 2 本のバイナリ、同じ条件、新しいシャッフル seed)で再測定し、**両方のバッチで CI が 1 を同じ符号で除外したときだけ採用する**。1 バッチの「CI 下限 > 最良」だけでは、この n ではノイズが通る(jaq で 3 本が通り、holdout で 3 本とも符号反転。実測)。
- **no-op の arm は計測しない(決定 80 b)**: apply 後のバイナリを基準と比べ、**正規化命令列と `nm -S` のシンボル表が両方とも同一**なら `identical` として**計測せず**「基準と同一」(ratio 1.0、CI なし)と記録する。命令列は同一でシンボルが動いただけのもの(`align=N` が効いたときの形)は `layout` として**計測する**。plugin の apply レポートは関数属性に `skipped_idempotent` の判定を持たず常に `consumed` を返すので、no-op はバイナリ側でしか判定できない。
- **正しさ**: 出力の**ビット一致**。幅・interleave のヒントが FP の順序を変えないよう、**全アームに `-Cllvm-args=-hints-allow-reordering=false` を固定する**(`vectorize.width` / `.enable` は `LoopVectorizeHints` を通って FP 再結合を許す。決定 13 は `-force-vector-width` で checksum が変わることを実測、決定 40 は metadata 経路も同じ実装であることをソースで確認。**metadata 経路は仮説、封鎖の効果は未測定**)。一致しないアームは速くても採用せず、集計にも入れない。

## 3. 固定環境(2026-09-21〜22 にこの機で実測)

| 項目 | 値 | 備考 |
|---|---|---|
| CPU / OS | AMD Ryzen 9 5950X(znver3、2 CCD、AVX-512 なし) / WSL2 | governor・turbo を制御できず、CCD トポロジも見えない。シャッフルと A/A で吸収する |
| rustc(pin) | `nightly-2026-09-21` = rustc 1.100.0-nightly (bba531001) / **LLVM 23.1.1** | `rust-toolchain.toml` で pin 済み(`components = ["llvm-tools-preview"]`)。本仕様の LLVM 内部の記述はこの toolchain での話 |
| plugin ホスト | **libLLVM は共有ライブラリ。gate 0 は実施済み**(`results.md` Day 0 §2) | `libLLVM.so.23.1-rust-1.100.0-nightly` に `_ZN4llvm11PassBuilder` 63 件、`DisableABIBreakingChecks` 定義済み(アサーション OFF)、`_ZNSt` 1841 件。rustc のソースビルドは不要 |
| `-Zllvm-plugins` | pin 上で受理される | `--emit=metadata` では dlopen されないので、probe は **codegen を伴う emit** で行う |
| debuginfo | `-Cdebuginfo=1` に全アーム固定 | `linkageName` が要る。この toolchain では `.text` が debuginfo の有無で変わる |
| strip | `CARGO_PROFILE_RELEASE_STRIP=none` に上書き | 対象が `strip` を設定していると帰属も比較もできない。計測用バイナリは**計測直前**に `strip -s` |
| `.text` の再現性 | **C 依存があると再現しない**(実測) | `__DATE__`/`__TIME__` の焼き込みで同一構成でも変わる。比較は `scripts/norm_code_diff.py`(アドレス正規化ハッシュ) |
| remark | `-Cllvm-args=-pass-remarks*` を採用。stderr にテキストで出る | `-Cremark=all` は fat LTO でベクトル化 remark を落とし、`-pass-remarks-output` は 23.1.1 に存在しない。**ビルドログそのものを成果物として保存する**。行に関数名は無い |
| perf | **`perf` バイナリは未インストール(未測定)** | マーク選定の入力なので `doctor` の確認項目にする。無い場合の代替は `scripts/ipsample.c`(LD_PRELOAD の IP サンプラ)か callgrind。plugin の hotness は perf ではなく PGO の分岐重みから取る(決定 6) |

**全アーム共通の凍結レシピ**(差分は plan だけ):

```
# cargo profile 環境変数(対象の Cargo.toml を変えない)
CARGO_PROFILE_RELEASE_OPT_LEVEL=3 CARGO_PROFILE_RELEASE_LTO=fat
CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 CARGO_PROFILE_RELEASE_DEBUG=1
CARGO_PROFILE_RELEASE_PANIC=<凍結値> CARGO_PROFILE_RELEASE_STRIP=none
# CARGO_ENCODED_RUSTFLAGS(区切りは \x1f)。前半は [project] fixed_rustflags
-Ctarget-cpu=native -Csymbol-mangling-version=v0
-Cllvm-args=-hints-allow-reordering=false        # 全アーム固定(§2)
-Cprofile-use=<abs>/pgo/merged.profdata          # 全アーム・全ラウンドで同一
-Cllvm-args=-pass-remarks=.* -Cllvm-args=-pass-remarks-missed=.*
-Zllvm-plugins=<abs>/libjevplugin.so             # dump / apply のとき
# cargo 引数
--release --target x86_64-unknown-linux-gnu
```

- lto / codegen-units / debuginfo / panic / strip は RUSTFLAGS ではなく cargo の profile 環境変数で渡す(RUSTFLAGS の `-Clto=fat` は cargo が付ける `-Cembed-bitcode=no` と衝突する)。`--target` の明示は必須(省略すると build script と proc-macro の host コンパイルにも載る)。
- `-Cprofile-use` は RUSTFLAGS、パスは絶対。`llvm-profdata` は pin した toolchain 付属のものを使う。`RUSTUP_TOOLCHAIN` を spawn 先に明示し、解決後の `rustc -vV` を記録する。
- **コンパイラ設定のヒント(ノブ)も `CARGO_ENCODED_RUSTFLAGS` で渡す。** plugin 経由にはしない。
- variant ごとに `CARGO_TARGET_DIR` を分け、必ず clean build する(cargo は環境変数の変更で再コンパイルしない)。

## 4. 部品

### 作るもの

| 名前 | 形式 | 責務 |
|---|---|---|
| `jev-opt` | Rust 単体 binary | マークを読み、plugin の `dump` でマーク内のループを列挙し、Jev に聞き、plan を書き、cargo を起動し、測り、ログを書く |
| `libjevplugin.so` | LLVM pass plugin(C++) | `off` / `dump` / `apply` の 3 モード。状態なし、ネットワークなし |
| `jev-marks.txt` | 人 / Claude が書く | 1 行 1 関数。`#[jev_opt::optimize]` 属性からも生成できる |
| `jev-plan.json` | CLI → plugin、**再現の単位** | site ごとのヒント 1 つ。内容の sha256 を `plan_id` に持つ |
| `sites.json` | plugin → CLI | 関数表 + マーク内ループの site レコード |
| `apply-report-*.json` | plugin → CLI | site ごとの適用結果(1 モジュール 1 ファイル) |
| `llvm-knobs.json` | 生成データ(**済**) | pin した LLVM に実在する cl::opt の全集合(2689 件)。`scripts/gen_llvm_knobs.sh` |
| `jev-opt.toml` | 設定 | §8 |
| `artifacts/jev-log/<run-id>.jsonl` / `.log` | CLI が追記 | Jev への全 request / response の生ログと、人が読む集計(本数・待ち時間・費用) |

### 作らないもの

broker と Unix socket プロトコル、source scanner を越える proc macro(**属性形式を使うなら関数名を読むだけの空マクロ crate は必須**だが、それ以上は作らない。対象の `Cargo.toml` に依存を 1 行足す。マークは準備工程なので許容する)、Score / Noul、cargo subcommand 化、訓練データ選定、対象探しの失格フィルタ、FP 再結合の機構、**ゲート不合格時に基準バイナリを返す製品向けの代替経路**(これは実験なので、落ちた plan は単に捨てて記録する)。ビルドの入出力になる JSON はすべて片方向・追記なし。Jev ログはビルドの入力に一切ならない。

## 5. plugin

- **モード**: 環境変数 `JEV_MODE=off|dump|apply`、`JEV_PLAN=/abs/jev-plan.json`、`JEV_PLAN_SHA=<sha256>`(不一致なら即エラー)、`JEV_REPORT_DIR=/abs/dir`、`JEV_PGO_PROFILE_SHA`。`!llvm.module.flags` に `ProfileSummary` はループ EP(マージ後段)では必須で、無ければ `-Cprofile-use` が抜けているとして止める。関数属性 EP(PipelineStart)には PGO 付きでも `ProfileSummary` が無いので、そこでは検査しない(決定 60(c)、実測)。plan は `-Cllvm-args` では渡さない(plugin の dlopen はコマンドライン解析の後で、plugin が登録した cl::opt には値が入らない)。
- **extension point**: **toy の実測で確定済み(決定 60)。** 関数属性は `PipelineStartEP`(pre-link、CGU ごと 1 回)、ループ metadata は `VectorizerStartEP`(fat LTO のマージ後段、LoopVectorize の直前)で consumed。pre-link は ThinLTO pre-link 相当でベクトル化前に止まる。
- **dump が出すもの**: (a) **関数表** — 全関数の `DISubprogram::getLinkageName()`(v0 mangled なので単相化引数が名前に入る)とソースパス。CLI のマーク解決に使う。(b) **全ループ** — site key、トリップカウント(ループヘッダ − バックエッジ = 脱出回数。決定 36)、hotness(`BlockFrequencyAnalysis` の `getBlockProfileCount(header)` × 本体命令数)、ループ本体のソース範囲。**絞り込みは CLI 側**なので plugin はマークを読まない。`jev-opt baseline` を `JEV_MODE=dump` で建てれば `sites.json` は追加ビルド 0 で得られる。
- **apply がやること**: plan のヒントを、関数属性は `addFnAttr`、ループは `llvm.loop.*` metadata で付けるだけ。`PreservedAnalyses::all()` で返す。`fn_attrs.inline` の **`always`**(= `alwaysinline`)は **`noinline` を先に外し**(両立は verifier エラー)、`optnone` の callee は**スキップして報告する**。`alwaysinline` は inline 後に callee がモジュールから消えることがある(`AlwaysInliner.cpp:120-129`)ので、dump と正規化コードハッシュがそれに耐えること。`callee_present` は **3 値**(fat LTO の pre-link では依存 crate 側のプロセスから callee の存否が観測できないので `null` = 未観測)。関数属性には `skipped_idempotent` の判定が無く、付けた属性は LLVM が使ったかどうかに関わらず `consumed` を返すので、**no-op の判定はバイナリ側で行う**(§2)。plugin は v1 / v2 の再現用に `inline: "hint"` と `cold: true` を受理し続ける(語彙が提示しないだけ)。
- **site key**: 次を連結した sha256 の先頭 16 桁 + 可読サフィックス。(1) `owner_fn` = そのループを最終的に含む関数の linkage name、(2) `inline_chain` = 本体命令の `DILocation` → `inlinedAt` 鎖の linkage name 列(外→内)、(3) `leaf_loc` = 最内フレームの (file, line, col)、(4) `loop_fingerprint` = 本体全命令の (leaf linkage name, line) のソート済み集合のハッシュ、(5) `depth`。生成器は dump / apply 共通コードのみ。apply 時に同じ key が 2 つ以上に解決したら `ambiguous`、0 個なら `vanished`。別のループへ移さず記録する。**件数そのものが設計の健全性メトリクス。**
- **冪等性**: fat LTO では pre-link とマージ後の 2 回 module 最適化が走る。適用済みマーカ(`jev.applied` 相当の metadata)で「最初に到達した段で適用し、以降はスキップ」にする。report は共有 1 ファイルに追記せず `$JEV_REPORT_DIR/<module-id>-<stage>-<pid>.json` に書き、CLI がマージする(pre-link 段は並行する)。
- **off 等価性**: plugin 未ロード vs ロード + `JEV_MODE=off` で正規化コードハッシュ(`scripts/norm_code_diff.py`)が一致することを必須ゲートにする。生の `.text` ハッシュは使わない(§3)。
- **ビルド**: LLVM ライブラリを一切リンクしない(静的リンクすると cl::opt 二重登録で dlopen 時に abort)。`-fPIC -shared -fno-rtti -fno-exceptions -DNDEBUG -std=c++17`。ヘッダは LLVM 23.1 の upstream tarball から `ninja intrinsics_gen` で生成ヘッダだけ作る。ABI マクロは `DisableABIBreakingChecks` 側に合わせ、互換な libstdc++ でビルドする(§3 の gate 0、**済**)。

**関数属性とループ metadata を同じ plan に入れるときの注意。** site key は inlining の結果に依存するので、`inline(always)` / `inline(never)` を変えるとマーク内の別のループの key が変わったり消えたりする。したがって片方だけでは足りず、どちらかを取る: (a) **2 段** — 関数属性だけを先に適用してビルドし、その構成で再 dump してからループヒントを選ぶ(1 ラウンドが 2 ビルドになる)。(b) **ラウンド分離** — 関数属性を決めるラウンドとループヒントを決めるラウンドを分け、後者では前者の結果を固定する。どちらでも `jev-plan.json` の `basis` に **key を dump したときの関数属性集合の sha** を入れ、不一致なら plugin はエラーで止める(警告にしない)。初期実装は (b)(単純で、`vanished` 件数がそのまま前提崩れの検知になる)。

## 6. Jev の使い方

- プリミティブは **Choice のみ**。Vercel AI Gateway の TypeSafe 互換 API(`https://ai-gateway.vercel.sh/typesafe/v1/systemone`、`Authorization: Bearer $AI_GATEWAY_API_KEY`、`"model": "typesafe-ai/jev"`)を REST で呼ぶ。request は `state`(文字列)と `questions`(名前 → `{type: "choice", instructions, criteria: {候補名: 説明}}`)、response は `answers.<名前>.{choice, probabilities, confidence}` と `usage`、`provider_metadata.gateway.cost`。**Choice の `criteria` はオブジェクト**(配列を渡すと `invalid_request`。実測)。
- **question はマーク内の site ごとに 1 つ**(関数属性なら関数、ループヒントならループ)。**コンパイラ設定のノブはビルド全体に 1 つ**なので、疑似 site `__build__` に対する question を 1 ラウンドに 1 つ足す(候補は `KEEP_DEFAULT` + 各ノブ値)。同一 request 内の question は独立・並列に評価されるので、**1 フェーズの全 site を 1 HTTP request に同梱する**(関数フェーズ / ループフェーズで 1 本ずつ = **1 request / phase**)。HTTP 回数はラウンドあたり 2 回。1 問 1 request にしても選択は 1 site も変わらなかった(決定 70(b)、実測)。state が大きすぎるときだけ分割し、分割したことを記録する。
- **state の書式(凍結する)= v3**(§1 (3)、`docs/search-driver.md`): (1) 関数のソース(ループ site は本体 ±20 行と外側関数のシグネチャ)、(2) profile 上の share(その site が全実行時間の何 % か)、(3) remark の要約(その site について LLVM が何を見送ったか。**外さない**)、(4) **前ラウンドまでの結果表**(ラウンド番号、その site に選んだヒント、そのビルド全体の速度比と信頼区間、採用 / 不採用)、(5) **platform ブロック**、(6) 各 question に付く**判定行**、(7) 関数フェーズの選択肢に付く**適用条件**。**state の書き方で答えが変わる**(実測、`docs/jev-samples/01-*`、決定 19・70・73)ので、書式と語彙は測定条件と同じ扱いで同時に凍結し(`--vocab` が両方を選ぶ)、変更したら再測定する。
- `criteria` は §1 (2) の一覧そのまま。**`KEEP_DEFAULT` を必ず含める。** 応答なし・timeout・不正応答・confidence が閾値未満のときは安全側の既定として `KEEP_DEFAULT` を採り、理由を記録する。オフライン問い合わせなので timeout 60 秒、retry 3 回でよい。
- **全 request / response を JSONL に記録する。** `artifacts/jev-log/<run-id>.jsonl` に 1 行 1 問い合わせで `{ts, round, request, response, http_status, latency_ms}`。送受信した JSON をそのまま入れる。**`Authorization` ヘッダは記録しない。** `jev-plan.json` の各 entry は `<run-id>.jsonl#<行番号>` を `answer_ref` に持つ。
- **人が読むテキストログも出す。** `.log` に 1 問い合わせ 1 行(`ts round question数 http_status latency_ms input_tokens output_tokens cost`)、末尾に集計(HTTP 本数、Choice 総数、待ち時間の合計・平均・最大、トークン合計、費用合計、実験全体に対する Jev 待ちの割合)。同じ集計を `results.md` に転記する。
- `doctor` は `GET /typesafe/v1/models` で `typesafe-ai/jev` が使えることを確認する。Jev は Hobby の無料枠で動く(応答約 150 ms、定価でも 1 回 1 万分の 2 セント前後。実測)。キーは `.env`(git 管理外)。

## 7. 評価手順

- **主指標**: end-to-end wall time。ケースごとの速度比を事前固定重みの幾何平均で集計し、交互実行の pair を単位に bootstrap で 95% 信頼区間を出す。
- **ノイズフロアと MDE**: §2。A/A は holdout の前に同一手順で回す。
- **バッチ内 bootstrap CI の較正は破れている(実測、決定 80)。** jaq の 90 arm の掃引で、同一バイナリに対する in-run A/A の CI が **90 回中 49 回 1 を覆わなかった**。専用 null パネル(同一バイナリ 4 本)の最大差は 0.77 pt にとどまるのに、掃引内の no-op ビルド 48 本は 4.67 pt に散らばり、うち 20 本の CI が 1 を除外した。バッチ内の再スケールでは救えない。したがって **CI は 1 バッチでは採否に使わず、§2 の確認バッチ規則に従う**。事前登録の「CI 下限 > 最良」だけでは足りず、jaq では 3 本が通って holdout で 3 本とも符号反転した。
- **ラベル順はローテートでなくシャッフルする**(ローテートだと隣接ラベルの A/A がラウンド内のドリフトを過小評価する)。
- **in-sweep null パネルを必須にする。** 正規化コードハッシュが基準と一致したラベルを、その run の中の追加の null 対照として使う。専用のノイズプローブは信用しない(jaq では「ノイズプローブ」のつもりだったアラインメントのフラグが集計 +1.32%、単一ケース +3.42% 動いた。実測)。
- **測定条件**: `taskset` で物理コア 1 つに固定し SMT 兄弟を空ける。`lscpu -e` を記録に残す(WSL2 からはホストの CCD が見えないので「単一 CCD 内」は主張しない)。ASLR は有効のまま。n(既定 15〜50)、warmup(3〜5)、trimming 規則を凍結し、事後変更した run は無効。
- **jaq 型の対象**: 大きな入力 1 本ではなく**小さい入力を複数回**並べ、`--gap-ms 250` の整定ギャップを入れる(72 MiB の配列 1 本では RSS 1.2 GiB で同一バイナリ・同一入力が二峰になり、A/A 半幅が 13% まで悪化した。実測)。
- **同時に 1 対象しか測らない**(別対象のビルドを並走させると A/A 半幅が 0.3% → 1.7% に悪化した。実測)。**実行中の共有スクリプトを in-place で編集しない**(bash が途中から読み直して落ちる。実測)。
- **探索ラウンドと最終 holdout を分ける。** ラウンド中の測定は探索用のケース集合で行い、**holdout は最良 plan が確定してから 1 回だけ**回す。holdout のケースと重みはラウンド開始前に凍結する。見てから条件を変えた場合は新 seed で再生成し、全実行履歴を `results.md` に列挙する。
- **正しさは時間より先に読む**(§2)。v0.3 の掃引では最大の「高速化」が答えの違うバイナリだった。
- **帰属**: 基準と候補の最終バイナリを `scripts/norm_code_diff.py` でシンボル単位に比較し、変化した関数が profile の何 % を占めるかを報告する。ヒントが実際に消費されたことは apply-report と remark の消失で裏を取る。
- **退行**: ケース集合と重みは事前凍結し、退行ケースは集計に含めたまま最大値と件数を `results.md` 冒頭に置く。採用しなかったアームも全部列挙する。
- **記録**: `run-manifest.json` に toolchain、CPU、`lscpu -e` と `taskset` のコア、flags、config の SHA、`merged.profdata` の sha256、`plan_id`、正規化コードハッシュ、**全アームの出力 checksum**、時間サンプル、Jev の費用をまとめる。`results.md` は記録から生成し、欠測を成功値で埋めない。

## 8. 設定と CLI

```toml
[project]
repo   = "…/jaq"
bin    = "jaq"
target = "x86_64-unknown-linux-gnu"
marks  = "jev-marks.txt"
profile_env = { OPT_LEVEL = "3", LTO = "fat", CODEGEN_UNITS = "1",
                DEBUG = "1", PANIC = "unwind", STRIP = "none" }
fixed_rustflags = ["-Ctarget-cpu=native", "-Csymbol-mangling-version=v0",
                   "-Cllvm-args=-hints-allow-reordering=false"]

[workloads]
pgo_train = ["workloads/train/*.sh"]   # 合成。準備扱い、1 回だけ回して共有する
search    = ["cases/search/*.json"]    # ラウンド中の測定に使う
holdout   = ["cases/holdout/*.json"]   # 凍結。最良 plan 確定後に 1 回だけ

[evaluation]
weights         = { … }
repetitions     = 15
warmup          = 3
gap_ms          = 250
label_order     = "shuffle"    # rotate ではない(§7)
trim_rule       = "none"
min_effect_size = "max(2*aa_halfwidth, 0.03)"
cpu_pin         = "4"
seed            = 20260921

[search]
rounds    = 5               # 初期値
max_sites = 40              # 超えたらエラー。oracle のビルド数を有限に保つ(§2)
hints     = "…"             # §1 (2) の一覧。ラウンド 1 前に凍結
knobs     = ["…"]           # llvm-knobs.json から選んだノブ。同上
stage     = "separate"      # 関数属性ラウンドとループラウンドを分ける(§5)
vocab     = "v3"            # 語彙と state 書式は 1 つの測定条件(§1 (3))

[jev]
base_url            = "https://ai-gateway.vercel.sh/typesafe"
endpoint            = "/v1/systemone"
model               = "typesafe-ai/jev"
api_key_env         = "AI_GATEWAY_API_KEY"
request_timeout_s   = 60
api_cost_budget_usd = 5.0

[artifacts]
remarks_dir = "…"
jev_log_dir = "…"
```

凍結すべき値はすべてここにあり、SHA を `run-manifest.json` に記録する。

| コマンド | 内容 |
|---|---|
| `jev-opt doctor` | toolchain 記録(解決後の `rustc -vV`)、`llvm-tools-preview` と `llvm-profdata` の LLVM メジャー一致、`llvm-knobs.json` 生成、テキスト remark の取得確認、**`perf` の有無**(無ければ代替を提示)、Jev 疎通、gate 0 と `-Zllvm-plugins` probe(**codegen を伴う emit** で行う) |
| `jev-opt baseline` | 合成ワークロードで PGO を訓練 → `llvm-profdata merge` → 基準ビルド → A/A → ノイズフロアと MDE を凍結する。`merged.profdata` はここで作った 1 本を以降すべてで共有する |
| `jev-opt mark` | perf(または代替)の上位を関数単位で表示し、人が選ぶのを助ける。`jev-marks.txt` の雛形を書く。Claude が書く場合も同じ形式。**ビルドの工程ではない** |
| `jev-opt search` | ラウンドを回す。`dump` → 提案 → plan → ビルド → 測定 → 結果を state へ、を `rounds` 回。`--proposer jev\|random\|oracle` でアームを切り替える。最良 plan と全ラウンドのログを残す |
| `jev-opt bench` | 最良 plan / 基準 / oracle / random を holdout で交互実行、シャッフル、bootstrap、in-sweep null パネル、帰属 diff、`results.md` 生成 |

cargo への組み込みは「CLI が環境変数を組んで `cargo build --release --target …` を exec する」だけ。`.cargo/config.toml` は使わない(RUSTFLAGS と上書き競合し、variant 切替で状態が残る)。

## 9. 対象の順序と実装順序

**対象の順序(決定 72)**: **正解が存在するはずの小さな対象を jaq の前に置く。** `targets/hintbench/` — 8 カーネルの crate で、語彙の各ヒントが効くはずの構造を意図して作ってある(`EXPECTED.md` に計測前の Claude の期待ヒントと機構が書いてある)。site は 12(関数 8 × 5 候補 + ループ 4 × 11 候補 = v3 で 85 arm、約 3 時間)。ループ site の凍結規則は「ループヒントが検証対象のマークのみ、マーク内で hotness 最大の key 1 本」(決定 76)。**`-Zcross-crate-inline-threshold=never` は hintbench の固定フラグ**(無いと rustc の MIR inliner が 8 カーネル中 6 つを LLVM に届く前に消す。`-Cprofile-use` は MIR のハッシュで照合するので計装ビルドにも同じフラグが要る。決定 75、実測)。ただし **8 カーネル中 4 つは意図どおりに作れていない**(K4 / K5 は基準が既に VF 8 × IC 4 で幅も interleave も余地なし、K2 の `inline` と K7 の `cold`(いずれも v3 で語彙から外した)は不活性。決定 74、実測)ので、「正解が存在する」こと自体はまだ **仮説**。

1. **plugin**(C++)— **済**。EP を toy の実測で確定し、off 等価性(未ロード / off / 空 plan で `.text` と出力がビット一致)と手書き plan の消費を確認(決定 60)。`alwaysinline` 分岐も追加し、toy で `always inline attribute at callsite` の remark と出力一致を確認済み(決定 78)。
2. **探索ドライバ** — **済**(Python 実装、決定 62・65、`docs/search-driver.md`)。マーク解決、plan 生成、ビルド、測定、state 組み立て、Jev 接続、`--proposer` 3 種。語彙 v3 実装済み。
3. **jaq の関数属性 oracle** — **済**(90 arm、7.4 時間)。**フラット**で、MDE を超えるものは実質ゼロ(決定 79)。**jaq のループ oracle(176 arm、約 14 時間)は未**。
4. **hintbench の oracle** — 全候補を機械的に回して**実測の正解**を得る。同時に `EXPECTED.md` の **Claude の予測を採点**する(Claude の参照判断の精度そのものの測定)。
5. **Jev v3 を hintbench に当てる** — state / 語彙 v3 で 1 request / phase。**実測の正解との一致率**(§2 の主指標)を測る。
6. **jaq に戻る** — ループ oracle → `search --proposer oracle|random|jev` → `bench`。§2 の表を埋める。

**済(基盤)**: toolchain pin、gate 0、`llvm-knobs.json`(2689 ノブ)、remark 機構の選定、`.text` の debuginfo 依存、測定手順一式(A/A、MDE、交互実行、bootstrap、正規化コードハッシュ、整定ギャップ、`scripts/ipsample.c`)。いずれも `results.md` Day 0 と §8〜§10・§46・§55 に記録済み。

**失敗時の分岐**: dlopen で abort → LLVM を静的リンクしている(リンク指定を全部外す)。LTO 段でどの EP も発火しない → pre-link 段で適用する(冪等性設計がそのまま使える)。off 等価性が崩れる → plugin が off でもパイプラインを変えている(差分関数を特定するまで進まない)。ヒントを付けても remark が変わらない → 付与先の同定が間違っている(`--emit=llvm-ir` で目視する)。

## 10. スコープ外

以下は本実験の主題ではない。別テーマとして扱い、成功と混同しない。**PGO の訓練ワークロードを選ぶこと**(経緯と数値は `docs/decisions.ja.md` 38・43〜55、`results.md` §62〜§69。v0.5 では合成ワークロードでの PGO を準備として固定する)、**浮動小数点の再結合を許す判断**(`decisions.ja.md` 40〜42・56。v0.5 は全アームで再結合を封鎖する側に固定)、**効果の出る対象を探して回ること**(`decisions.ja.md` 57・58。対象は hintbench → jaq に固定する。決定 72)、**v0.3 のヒント 5 ファミリーのグローバル掃引**(4 対象すべてフラットだった。`decisions.ja.md` 12〜14・21〜24・29〜31・37、`results.md` §12〜§61)、**語彙から外したヒント** — `inline`(inlinehint)と `cold` はこのレシピの下で inliner に対して不活性、`hot` はそもそも inliner の入力ではなく Rust の表層構文も無い(決定 77、`docs/experiments/hintbench/inline-attrs-under-pgo.md` §7。plugin は v1 / v2 の再現用に受理を残すだけ)。**callsite 文字列属性 `function-inline-threshold` / `function-inline-cost`**(クラス B・C・D で閾値を外から動かせる唯一の経路だが、plugin は関数を marking する設計なので、将来の site 種別の話であって語彙の話ではない)、意味変換(HashMap を線形探索に変える等)、パス挿入(unswitch / fusion / interchange)、AVX-512 幅選択(この機に無い)、PGO を使わない静的 Jev(全ループに問い合わせる方式は費用と待ち時間が成立しない)、他言語への展開。

## 言語方針

- **英語**: ソースコメント、コミットメッセージ、PR 本文、README、CLI のヘルプとログ。
- **日本語**: `SPEC.ja.md`、`docs/decisions.ja.md`、zenn 記事、開発ノート。開発中はこちらが正本。
- 実装が落ち着いた時点で `SPEC.md`(英語)を生成物として追随させる。

理由: コミット履歴は後から英語化できないので最初から英語で書く。設計判断の理解と議論は日本語の方が速く正確なので、仕様と記事は日本語で持つ。
