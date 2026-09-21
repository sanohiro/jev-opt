# jev-opt 実装仕様(正式採用版 v0.4、日本語正本)— ビルドオプションとして Jev に最適化の判断を任せる

> 英語版は接尾辞なしの `SPEC.md` として実装が落ち着いた時点で生成する。開発中の正本はこの `SPEC.ja.md`。
> **v0.3 は git 履歴の `3a41f49` 以前**(`git show 3a41f49:SPEC.ja.md`)。`work/` 配下(旧版・レビュー・カタログ・記事草稿)は今後メンテナンスしない。

v0.4 の方針は v0.3 と同じ4つ。**速さは追求する。作りはなるべくシンプルにする。判断は Jev に最大限任せる。わかりやすくする。** 最適化は対象のソースを書き換えずに行う。

v0.3 との違いは主仮説の交代である。v0.3 の主仮説「Jev にループ単位の最適化ヒントを選ばせる」は、toy / zopfli / oxipng / jaq の4対象すべてで **PGO + LTO + native の上に 0〜2% しか残っていない**ことが実測で分かった(`docs/decisions.ja.md` 37、`results.md` §12〜§61)。v0.4 は同じ枠組み(PGO 込み基準・ノイズフロア・事前登録の打ち切り規則・Jev は Choice だけ)を保ったまま、Jev に判断させる対象を入れ替える。

## 一枚で分かる jev-opt

**利用者の体験**: `cargo build --release` の代わりに `jev-opt build` を実行するだけ。Jev がそのプログラムと CPU に合わせて最適化の方針を選び、通常より速いバイナリが出る。ソースも `Cargo.toml` も一切変えない。Gentoo で USE フラグを付けてビルドするのと同じ感覚で、Jev 最適化をビルドオプションとして付ける。**PGO の訓練実行も内部で回す**: 計装ビルド → 訓練ワークロード実行 → `llvm-profdata merge` までを `jev-opt build` が面倒を見るので、利用者が意識するのはコマンド1つ。**訓練ワークロードを人が書く必要も無い**(それを選ぶのが機能 1)。

**Jev が決めること(機能ごとに独立したオン・オフ)**:

| 機能 | 内容 | 既定 | 切替 |
|---|---|---|---|
| **機能 1: PGO 訓練ワークロードの選定** | リポジトリ内の候補入力(tests / doc tests / benches / examples / README の CLI 例 / 利用者が置いたサンプル)から、PGO の訓練に使う集合とスケールを Jev が選ぶ | **ON** | `--no-select-training` で OFF |
| **機能 2: FP 再結合の許可判断** | ホットな浮動小数点リダクションごとに、再結合(と FMA 融合)を許してよいかを Jev が判断する。出力が変わりうるので明示的に有効化したときだけ動く | **OFF** | `--fp-reassoc` で ON |

機能は独立に測る。結果表は「機能 × 効果」の形にし、束ねた合計値を見出しにしない(`decisions.ja.md` 39)。将来機能を足すときも同じ規則。

**人が決めないこと**: 候補の取捨、グループの採否、スケール、FP site ごとの可否。判断が要るところはすべて Jev。決定的な規則は評価用の対照としてだけ存在し、製品の経路には無い。

**部品**: CLI `jev-opt`(候補を列挙し、Jev に聞き、cargo を起動し、検査する)、`jev-training.json`(機能 1 の決定。再現の単位)、LLVM plugin + `jev-plan.json`(**機能 2 のためだけ**に存在する。既定 OFF ではビルドされも読み込まれもしない)。

**速さの証明**: 機能ごとのアブレーション。機能 1 は「訓練集合を Jev が選んだ PGO ビルド」を、PGO なし・素朴訓練・決定的セレクタと同じ holdout で比べる。機能 2 は許可判断の有無で比べる。ノイズフロアを測った上で信頼区間を出し、最小効果量を超えなければ「速い」と言わない。「PGO を使えばいいじゃん」には「その PGO をどう訓練するかが利得の大半を決める」と答える(`results.md` §66、実測)。

**作る順序**: 機能 1 の CLI(Rust のみ、plugin 不要)を先に完成させる。Experiment 2 で「素朴解が既にそこそこ良いリポジトリ」でも余地があるかを測り、その結果で Jev の `criteria` を確定してから Jev アームを回す。機能 2 は別トラックで、plugin の EP probe から始める。

**対象の順序**: 機能 1 は jaq(検証済み)→ pulldown-cmark → CLI から走らせられるテストが無い対象1つ。機能 2 は llama2-rs → ebur128 → symphonia(§6.4)。

以下は実装者向けの詳細。

## 0. v0.3 からの決定事項

| 決定 | 内容 | 根拠 |
|---|---|---|
| ループ metadata ヒント方式を製品機能から外す | 4対象すべてで事前登録の打ち切り規則が「フラット」。機構は対象ごとに違う(toy = コストモデルが正しい、zopfli = early-exit バイト走査 67%、oxipng = C が 80% かつ既に最大幅、jaq = レキサの early-exit 探索が legality)。共通するのは「LLVM が見送った判断のうちヒントで動かせるものは、時間の支配要因ではない」 | decisions 37、`results.md` §12〜§61(実測) |
| 主仮説は「PGO 訓練ワークロードの選定」 | 動いたのは PGO(jaq で +19.5%)と FP 再結合の2つだけ。訓練集合の選び方だけで holdout 速度が大きく動くことを確認した | decisions 38・43、`results.md` §62〜§69(実測) |
| Jev の各判断は独立のオン・オフ。機能ごとに測る | 機能を束ねると個別の寄与が分からない。記事は「この機能はこのぐらいだった」の形にする | decisions 39 |
| plugin は機能 2 専用 | 製品の既定経路(機能 1 のみ)に C++ は要らない。plugin は `--fp-reassoc` を有効にしたときだけ使う | decisions 38(2)・40 |
| FP 再結合は FMF 方式のみ。幅 / enable ヒント経路は封鎖する | 幅・enable のヒントは `LoopVectorizeHints` を通って FP 再結合を許してしまう(ソース確認済み)。FMF なら影響範囲がフラグを立てた命令に限られ、VF はコストモデルに任せられる。全アームに `-hints-allow-reordering=false` を固定して既定経路の FP 安全性を構成上保証する | decisions 13(d)・40、`docs/fp-reassoc-target-scouting.md` §1 |
| 正しさは既定ビット一致、`--fp-reassoc` のときだけ許容誤差 | 両者を混ぜない。量子化・argmax・ソートを挟む出力は規則で strict | decisions 42、scouting §3 |
| 訓練後の profile 妥当性検査を必須にする | 3件の普通のテスト項目が計装バイナリのカウンタにヒープポインタを書き込み、ProfileSummary を壊して **PGO なしより 9.9% 遅い**バイナリを出した | decisions 47、`results.md` §63(実測) |
| T0 へのフォールバックを必須にする | 悪い訓練セットは無 PGO より遅い。「常に PGO、入力は何でも」にはできない | decisions 44、`results.md` §65〜§66(実測) |
| 候補のサイズは特徴量として使わない | jaq のプールでは入力バイト数と仕事量が逆相関(最重量 12 件の入力は 8 バイト)。バイト上位 10% での訓練は良い訓練の 19% しか回収しない | decisions 44、`results.md` §62・§68(実測) |
| セレクタはランキングでなく集合被覆 | ホットセットを単独で覆う候補は無い。判別に効くのは候補ごとの profile 形状 | decisions 45、`results.md` §68 |
| スケールのつまみを持つ | パラメトリックな候補(stdin で n を取る bench 等)のサイズも選択対象にする。リポジトリに大きな入力が無い場合、救うのは選定ではなく「既存候補をより大きく走らせる」こと | decisions 46 |
| 失格フィルタは依存名 grep では足りない | `cargo tree -e normal,build` の `cc` / `*-sys` 検出と wall-clock 帰属が要る(oxipng は時間の 8 割が C なのに `-e normal` の grep も `core::arch` の grep も no match だった) | decisions 28、`results.md` §42・§43(実測) |
| 以下は v0.3 から維持 | マークと proc macro は作らない(対象は Jev が選ぶ)/ 判断はビルド前、成果物が lock / 基準は PGO 込み / Jev のプリミティブは Choice のみ(Score・Noul は使わない)/ 全問い合わせを JSONL とテキストログに記録 / debuginfo=1 固定 / 対象ごとのディレクトリ分離 | decisions 2・3・4・19 |

## 言語方針

- **英語**: ソースコメント、コミットメッセージ、PR 本文、README、CLI のヘルプとログ。
- **日本語**: `SPEC.ja.md`、`docs/decisions.ja.md`、zenn 記事、開発ノート。開発中はこちらが正本。
- 実装が落ち着いた時点で `SPEC.md`(英語)を生成し、英語記事の参照先にする。日本語版を正本として更新し、英語版は生成物として追随させる。

理由: コミット履歴は後から英語化できないので最初から英語で書く。一方、設計判断の理解と議論は日本語の方が速く正確なので、仕様と記事は日本語で持つ。

## 1. 目的と結論の出し方

### 1.1 仮説

- **機能 1(仮説)**: PGO の利得の大半は「どの入力で訓練したか」に乗っており、リポジトリの中には良い訓練集合が存在するが、それを機械的な規則で見つけるのは難しい。候補の出自・内容・profile 形状と、利用者が書いた本番の説明1行を突き合わせる意味的な判断は Jev が上手くできる。
- **機能 2(仮説)**: 浮動小数点リダクションの再結合を許してよいかは、コードの意図(コメント、変数名、結果の消費され方)を読まないと決められない。コンパイラはこの判断をユーザーに丸投げ(`-ffast-math`)するか全面禁止するかの二択しか持たない。Jev は site ごとに正しく振り分けられる。

どちらも「コストモデルに無い判断」を Jev がするか、という v0.3 からの一貫した問いの別の切り口である。

### 1.2 結論は機能ごとのアブレーション表で出す

数値は**すべてプレースホルダ**であり、確定値は `results.md` の該当節から転記する。

**機能 1(既定 ON)**。アーム名は以降すべてこの名前を使う。`T0` = PGO なし(凍結レシピから profile フラグだけを外したもの)、`T_all` = リポジトリの全候補を素朴に1回ずつ(`--selector all`)、`T_cover` = 決定的セレクタ B = profile 形状の貪欲集合被覆(`--selector cover`)、`T_jev` = Jev がグループごとに選んだ集合(`--selector jev`、製品経路)、`T_samples` = 利用者が置いたサンプルだけ(`--selector samples-only`、参考)。

| 数値 | 意味 | 主張の重み |
|---|---|---|
| `T_jev` − `T0` | 「`cargo build --release` を `jev-opt build` に置き換えると速くなった」。機能 1 の体験値 | 見出し。これが最小効果量を超えなければ機能 1 の主張はしない |
| `T_jev` − `T_cover` | **Jev の選択**に価値があるか。同じ候補・同じグループの上で決定的規則と比べる | これが無ければ「選定に価値はあったが Jev 固有の寄与は未証明」 |
| `T_jev` − `T_all` | 「全部で訓練すればいいじゃん」との差 | 副次。`T_all` が既に良い対象でこそ意味がある(decisions 48) |
| 参考: `T_samples` − `T0` | 利用者がサンプルを1つ置くだけでどこまで回収できるか | 参考値。機能 1 の複雑さが割に合うかの判断材料 |

確定値: `results.md` §70〜(Experiment 2、**未測定**)。jaq でのオラクル上限(合成した本番相当入力で訓練した場合)は `results.md` §64〜§66 に実測があるが、**これは製品が到達できる上限ではない**(リポジトリの外から持ち込んだ入力なので)。見出しには使わない。

**機能 2(既定 OFF)**。

| 数値 | 意味 |
|---|---|
| (`--fp-reassoc` あり) − (なし) | 機能 2 の速度効果。同じ profdata・同じ global flags の上での差 |
| 許容誤差の使用率 | 成果物ごとに「予算の何%を使ったか」。ニアミスが見えるようにする(scouting §3) |
| `keep_strict` と判断した site の妥当性 | ebur128 の `filter.rs:335-336`(作者が「`sum()` を使うと C 版と丸めが変わる」と書いた箇所)を Jev が strict と判断できるか。**意図読解の実地テスト** |
| 参考: 許可した site の realization | remark の `CantReorderFPOps` がその DebugLoc から消えたか。消えていなければフラグは効いていない |

確定値: `results.md` §80〜(**未測定**)。

### 1.3 「Jev コンパイラが実現可能かも」と言うために集める証拠

1. **ヘッドルームの存在**(機能ごと)。機能 1 は Experiment 1 で jaq について実測済み(`results.md` §66)だが、`decisions.ja.md` 48 のとおり jaq は「テストが本番と構造的に別物」の極端な例なので、**素朴解が既にそこそこ良い対象でも余地があること**を Experiment 2 で確かめる必要がある(未測定)。
2. **判断の不均質性**: 候補グループ間で答えが割れること(機能 1)、site 間で strict / allow が割れること(機能 2)。一律の答えでよいなら「フラグを1個足せばよかった」で終わる。
3. **Jev / 決定的規則の比**: 探索ゼロの1回の Choice で、決定的セレクタをどれだけ上回るか。
4. **主比較が有意であること**: 集計速度比の信頼区間下限 > 最小効果量。
5. **転移**: 同じパイプラインを無改造で別の対象に適用して同傾向が出る。機能ごとに2対象以上(§6.4)。

## 2. 全体フロー

```
機能 1(既定 ON、plugin 不要)                   機能 2(既定 OFF、plugin 必要)
  pool   候補の列挙(6 出自 + samples_dir)        probe  EP 選定・off 等価性(§8.2)
    ↓    計装バイナリで1回ずつ走らせ、候補ごとの    dump   FP リダクションを持つホットループの
    ↓    profile 形状と wall を取る                       列挙(isReductionPHI、連鎖、消費先)
    ↓    (出自, profile 形状) でグループ化         Jev    site ごとに keep_strict /
  select Jev がグループごとに                             allow_reassoc(+ contract)を Choice
    ↓    include/exclude/scale_up を Choice       apply  該当連鎖の FP 命令に FMF を立てるだけ
    ↓    (1 HTTP request に全グループを同梱)      gate   決定性セルフチェック → 許容誤差ゲート
  train  訓練 → merge → profile 妥当性検査(§7.6)        (holdout 上で。訓練入力では判定しない)
  build  PGO ビルド + T0 ビルド
  check  フォールバック自己検査(§7.7)。noise floor 以上速くなければ T0 を出荷して記録
        │
  bench  機能ごとのアブレーション(§1.2)を凍結 holdout で1回
```

各段の終わりに go / no-go を判定し、判定と根拠を `results.md` に残す。

## 3. 固定環境(2026-09-21〜22 にこの機で実測)

| 項目 | 値 | 備考 |
|---|---|---|
| CPU | AMD Ryzen 9 5950X(znver3、2 CCD、AVX-512 無し) | WSL2 からは CCD トポロジが見えない(§10) |
| OS | WSL2 | governor / turbo を制御できない。ラベル順のシャッフルと A/A でドリフトを吸収 |
| rustc(pin) | `nightly-2026-09-21` = rustc 1.100.0-nightly (bba531001) / **LLVM 23.1.1** | `rust-toolchain.toml` で pin 済み(`components = ["llvm-tools-preview"]`)。LLVM 22 系の nightly は存在しない。本仕様の LLVM / rustc 内部の記述はこの toolchain での実測として読む |
| `-Zllvm-plugins` | pin 上で受理される | `--emit=metadata` では plugin を dlopen しないので、doctor の probe は **codegen を伴う emit** で行う(§12) |
| plugin ホスト | **libLLVM は共有ライブラリ**。`librustc_driver-*.so` が `libLLVM.so.23.1-rust-1.100.0-nightly` を動的リンクしている | **gate 0 は実施済み**(`results.md` Day 0 §2)。`libLLVM.so` に対して `_ZN4llvm11PassBuilder` **63 件**、**`DisableABIBreakingChecks` が定義**(アサーション OFF)、`_ZNSt` **1841 件**(libstdc++ が plugin 境界をまたぐ)。rustc のソースビルドは不要 |
| debuginfo | `-Cdebuginfo=1` で `linkageName` が出る | **全アームで =1 に固定する。** この toolchain では `.text` が debuginfo で変わる(`results.md` Day 0 §5) |
| strip | 対象によっては `CARGO_PROFILE_RELEASE_STRIP=none` への上書きが要る | 対象の `Cargo.toml` が `strip` を設定していると debuginfo が落ち、帰属も `.text` 比較もできなくなる。評価用バイナリは計測**直前**に `strip -s` する |
| `.text` の再現性 | **C 依存があると再現しない**(実測) | mimalloc の C が `__DATE__ __TIME__` を焼き込むので、同一構成の再ビルドでも `.text` が変わる。比較には `scripts/norm_code_diff.py`(全シンボルのアドレス正規化ハッシュ)を使う(decisions 34) |
| PGO 計装の盲点 | **C / アセンブラは計装に見えない**(実測) | Rust 側の profdata では C の寄与が 0 に見える。oxipng では「Rust が 98%」に見えて実測 16% だった(`results.md` §43)。失格フィルタは wall-clock 帰属で裏を取る(下記) |
| PMU | HW cycles の `perf_event_open` は成功。`perf` バイナリは未インストール | 主経路では使わない。wall-clock 帰属は `scripts/ipsample.c`(LD_PRELOAD の IP サンプラ)、または `valgrind --tool=callgrind` |
| remark | `-Cremark=all -Zremark-dir` は fat LTO でベクトル化 remark を落とす。`-pass-remarks-output` は LLVM 23.1.1 に存在しない | 採用: `-Cllvm-args=-pass-remarks*`。stderr にテキストで出るので**ビルドログそのものを成果物として保存する**。用途は診断と、機能 2 で `CantReorderFPOps` が消えたことの証拠取り。行に関数名は無い |

**失格フィルタ**(どの対象でも着手前に掛ける、`jev-opt doctor` が自動化):

1. `cargo tree --target <triple> -e normal,build` で `cc` / `*-sys` を検出する(`-e normal` だけでは降りない。`--target` で他プラットフォームの偽陽性を避ける)。
2. `grep -rlE 'core::arch|std::arch|_mm_|_mm256|target_feature|std::simd|packed_simd|wide' src/` で手書き SIMD を検出する。
3. **wall-clock 帰属**(`scripts/ipsample.c` か callgrind)で、検出した依存がホットパスに居るかを見る。Rust の profdata だけでは判定できない。C の時間占有が過半なら対象から降ろす。結果は `results.md` に必ず書く。**当たらなかったことも書く**(oxipng は 1・2 とも no match で、それでも時間の 8 割が C だった)。

**全アーム共通の凍結レシピ**(差分は各機能が導入するもののみ):

```
# cargo profile 環境変数(対象の Cargo.toml を変えずに release profile を上書き)
CARGO_PROFILE_RELEASE_OPT_LEVEL=3 CARGO_PROFILE_RELEASE_LTO=fat
CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 CARGO_PROFILE_RELEASE_DEBUG=1
CARGO_PROFILE_RELEASE_PANIC=<凍結値> CARGO_PROFILE_RELEASE_STRIP=none
# rustc フラグ(CARGO_ENCODED_RUSTFLAGS、区切りは \x1f)
# 以下 2 行は [project] fixed_rustflags に書く(§11。ここと §12 では再掲しない)
-Ctarget-cpu=native -Csymbol-mangling-version=v0
-Cllvm-args=-hints-allow-reordering=false                  # 全アーム固定(decisions 40a)
# 以下はアームごとに CLI が組み立てる
-Cprofile-use=<abs>/pgo/<target>/<arm>/merged.profdata     # T0 では付けない
-Cllvm-args=-pgo-warn-missing-function                     # 件数を数える。選定信号ではない
-Cllvm-args=-pass-remarks=.* -Cllvm-args=-pass-remarks-missed=.* -Cllvm-args=-pass-remarks-analysis=.*
# cargo 引数
--release --target x86_64-unknown-linux-gnu
```

- lto / codegen-units / debuginfo / panic / strip は RUSTFLAGS ではなく cargo の profile 環境変数で渡す(RUSTFLAGS に `-Clto=fat` を入れると cargo が付ける `-Cembed-bitcode=no` と衝突する)。これで対象の `Cargo.toml` を変えずに済む。`--target` の明示は必須(省略すると RUSTFLAGS が build script と proc-macro の host コンパイルにも載る)。
- `-Cprofile-generate` / `-Cprofile-use` は RUSTFLAGS で渡す(対応する cargo profile 環境変数は無い)。パスは必ず絶対パス。計装ビルドの `CARGO_TARGET_DIR` は `target/pgo-gen` に分ける。`llvm-profdata` は pin した toolchain の `llvm-tools-preview` 付属のものを使う(profraw のフォーマットは LLVM メジャーに紐づく)。
- **`-pgo-warn-missing-function` は選定の信号として使えない**(実測)。IR 計装は実行されない関数にもレコードを出すので、5 バイトの doc test 558 件で訓練した profile も 71 MiB の JSON で訓練した profile も警告 0 件になる(`results.md` §64)。dump ビルドと apply ビルドで件数が一致することの確認にだけ使う。
- **profdata の共有について。** v0.3 の「訓練実行は1回、profdata は全アームで共有」は、**機能 2 と、同一 profile 上での比較にだけ**当てはまる。機能 1 のアームは profdata そのものが変数なので共有しない。ただし機能 1 の全アームは**同じ計装バイナリ**を使い(入力以外で差が出ないようにする)、各アームの `merged.profdata` の sha256 を `run-manifest.json` に記録する。

## 4. 構成物

### 作るもの

| 名前 | 形式 | 責務 | 機能 |
|---|---|---|---|
| `jev-opt` | Rust 単体 binary | 全サブコマンド。候補列挙、候補ごとの計装実行、グループ化、Jev 問い合わせ、決定的セレクタ、訓練・merge・妥当性検査、cargo 起動、自己検査、集計、`results.md` 生成 | 1 / 2 |
| `pool.json` | CLI が生成 | 候補1件1エントリ(`id`, `source`, `origin`, `argv`, `stdin`, `cwd`, `input_paths`, `input_bytes`, dry run の status/rc/ms、`scale_param`、`poisons_profile`) | 1 |
| `candidate-profiles/` | CLI が生成 | 候補ごとの profile 形状(層別 share、データ経路÷起動経路、zero-count 関数)。生 profraw は保持しない | 1 |
| `groups.json` | CLI が生成 | グループ1件1エントリ(代表候補、件数、profile 形状、wall 合計、スケール可否) | 1 |
| `jev-training.json` | CLI が生成、**機能 1 の lock** | 選ばれたグループと scale、除外した汚染候補、`merged.profdata` の sha256、妥当性検査の結果、自己検査の結果とフォールバック判定、`answer_ref` | 1 |
| `libjevplugin.so` | LLVM pass plugin(C++) | `off` / `dump` / `apply` の3モード。FP リダクション site の列挙と FMF の付与のみ。状態なし、ネットワークなし。**機能 2 専用で、既定 OFF ではビルドも dlopen もされない** | 2 |
| `sites.json` | plugin → CLI | FP リダクションを持つ site のレコードと hotness | 2 |
| `jev-plan.json` | CLI → plugin、**機能 2 の lock** | site ごとの `keep_strict` / `allow_reassoc` / `allow_reassoc_and_contract` | 2 |
| `apply-report-*.json` | plugin → CLI | site ごとの適用結果 | 2 |
| `llvm-knobs.json` | 生成データ | pin した LLVM に実在する cl::opt の全集合。**LLVM 23.1.1 用**。生成は必ずリポジトリ内で行う(`scripts/gen_llvm_knobs.sh`) | 共通 |
| `jev-opt.toml` | 設定 | §11 |
| `artifacts/jev-log/<target>/<run-id>.jsonl` / `.log` | CLI が追記 | Jev への全リクエストとレスポンスの生ログ(1行1問い合わせ)と、人が読む集計ログ | 共通 |

`jev-training.json` と `jev-plan.json` はどちらも**内容の sha256 を id に持ち、それ自体が再現の単位**である。手で送った Jev の request / response の見本は `docs/jev-samples/`(git 管理)に置く。

### 作らないもの

proc-macro crate、source scanner、broker、Unix socket プロトコル、decision lock ディレクトリ、手書きの capability registry、cargo subcommand 化、Score / Noul、ループ metadata を扱う plugin モード(§14)。ビルドの入出力になる JSON はすべて片方向・追記なし。Jev ログの JSONL はビルドの入力には一切ならない。variant ごとに `CARGO_TARGET_DIR` を分け、必ず clean build する(cargo は環境変数の変更で再コンパイルしないため)。

## 5. Jev の使い方

**原則: 判断が要るところは全部 Jev に聞く。人や固定規則で決めるのは「候補を機械的に列挙すること」と「測ること」だけ。** 決定的セレクタは評価の対照アームとしてのみ存在し、`jev-opt build` の製品経路には入らない。

- プリミティブは **Choice のみ**。Vercel AI Gateway の TypeSafe 互換 API(`https://ai-gateway.vercel.sh/typesafe/v1/systemone`、`Authorization: Bearer $AI_GATEWAY_API_KEY`、`"model": "typesafe-ai/jev"`)を REST で呼ぶ。request は `state`(文字列)と `questions`(名前 → `{type: "choice", instructions, criteria: {候補名: 説明}}`)、response は `answers.<名前>.{choice, probabilities, confidence}` と `usage`、`provider_metadata.gateway.cost`。
- **Choice の `criteria` はオブジェクト**(候補名 → 説明)。Score の `criteria` は配列で、object を渡すと `invalid_request`(実測)。本仕様は Choice しか使わない。
- 同一 request 内の複数 question は独立・並列に評価される。したがって**機能 1 の全グループの question は1つの HTTP request に同梱する**。機能 2 の全 site も同様。HTTP 回数は機能あたり1回で済み、Choice の回数は変わらない。state が大きくなりすぎる場合だけ分割し、分割したことを記録する。
- 1問い合わせ = 1 Choice。候補は 255 以下。同一 request 内の question に相互依存を持たせない。**state の書き方で答えが変わる**(実測、`docs/jev-samples/01-*`)ので、state の書式は測定条件と同じ扱いで**事前に凍結**し、変更したら再測定する。
- API 障害・timeout・不正応答は**安全側の既定**に落として理由を記録する(機能 1 はそのグループを exclude、機能 2 は `keep_strict`)。オフライン問い合わせなので timeout 60 秒、retry 3 回で構わない。
- **全リクエストとレスポンスを JSONL で記録する。** `artifacts/jev-log/<target>/<run-id>.jsonl` に1行1問い合わせで `{ts, target, feature: "training"|"fp", request, response, http_status, latency_ms}` を追記する。`request` / `response` は送受信した JSON 全体をそのまま入れる。**`Authorization` ヘッダは記録しない。** lock ファイルの `answer_ref` は `<run-id>.jsonl#<行番号>` を指す。
- **人が読むテキストログも出す。** `.log` に1問い合わせ1行(`ts  feature  question 数  http_status  latency_ms  input_tokens  output_tokens  cost`)、終わりに集計行(HTTP 本数、Choice 総数、待ち時間の合計・平均・最大、トークン合計、費用合計、ビルド全体に対する Jev 待ちの割合)。同じ集計を `results.md` のビルドコスト表に転記する。
- `jev-opt doctor` は `GET /typesafe/v1/models` で `typesafe-ai/jev` が利用可能なことを確認する。Jev は Hobby の無料枠で動く(応答約 150 ms、定価でも1回 1 万分の 2 セント前後)。キーは `.env`(git 管理外)。

## 6. 対象

### 6.1 対象の妥当性判定(対象1本あたり最初の半日)

1. **失格フィルタ**(§3)。C 依存と手書き SIMD を検出し、当たったら wall-clock 帰属で裏を取る。
2. 凍結レシピでビルドが通ること、上流テストが通ること、**出力が決定論的であること**(同一入力を2回走らせてビット一致)。決定論的でない対象は正しさゲートが成立しないので降ろす。
3. **A/A** を必須で走らせ、ノイズフロアと最小効果量を出す(§10)。機能ごとの要件(§6.3)を満たすかを見る。

### 6.2 4対象で分かったこと(すべて実測、`results.md`)

これは **v0.4 の対象選定の前提知識**であって、v0.4 が追う方式の測定結果ではない。

- **PGO は大きい**: jaq で凍結レシピ下の PGO 有無が +19.5%(読み書きケースは +39%)。ループヒントで動く幅(0〜2%)と1桁違う(decisions 32、`results.md` §57〜§60)。
- **訓練集合の選択がその大半を決める**: jaq では、リポジトリの全候補で素朴に訓練した PGO は T0 に対して +3.3% にしかならない一方、本番相当の入力で訓練すると +21.6% になった(`results.md` §65)。
- **悪い訓練セットは無 PGO より遅い**: リポジトリの bench 一式で訓練すると T0 より 7.8% 遅い。インタプリタの dispatch だけが積極的にインライン化され、holdout が使うデータ経路のコードが縮む(`results.md` §66・§67)。
- **入力サイズは効かない**: jaq のプールの中央値は 5 バイト、最重量 12 件の入力は 8 バイト(内部でデータを生成する)。バイト上位 10% で訓練しても 19% しか回収しない(`results.md` §62・§66)。プール全 1185 件のドライランは 9.4 秒なので、**候補ごとに計装 profile を取るのは安い**。
- **3件の普通のテストが profile を壊す**: 大きな整数の `tostring` を含む3件が `num_bigint` の1ブロックに 4e13(mimalloc のアリーナポインタの値)を書き、ProfileSummary の全パーセンタイルがそこに乗って **T0 より 9.9% 遅い**バイナリが出た。出荷バイナリでは不可視(`results.md` §63)。
- **FP 再結合の対象は薄い**: 純 Rust・手書き SIMD なし・長い単一アキュムレータの ordered リダクションを持つプログラムは少ない。FP スループットを気にする人は既に手で最適化している(scouting §2)。

### 6.3 機能ごとの対象要件

- **機能 1**: (a) リポジトリから機械的に取り出せる候補が数十件以上あること、(b) CLI から走らせられること(または利用者が `samples_dir` に入力を置けること)、(c) 本番相当の holdout を凍結できること、(d) 出力が決定論的であること。**素朴解(`T_all`)が既にそこそこ良い対象を意図的に混ぜる**(decisions 48)。
- **機能 2**: (a) 長い単一アキュムレータの f32/f64 リダクションがホットであること、(b) 純 Rust で手書き SIMD が無いこと、(c) 数値の成果物を出せること(量子化前の値をダンプできること)、(d) 決定論的であること。IIR、3〜4 要素の内積、要素毎の演算、手展開済みの部分和には効かない(scouting §1)。

### 6.4 対象の順序

**機能 1**:

| 対象 | 位置づけ | 理由 |
|---|---|---|
| jaq | **検証済みの1本目** | プール抽出器・汚染検出・アーム構築・holdout が既にある(`results.md` §62〜§69)。ただし「テストが本番と構造的に別物」の極端な例なので、この対象だけで製品主張はしない(decisions 48) |
| pulldown-cmark | **2本目(本命)** | CommonMark spec テストが fixture で、テストが本番に近い。**素朴解が既に良いところでも余地があるか**を見る。ここで余地が無ければ機能 1 の適用範囲は「テストと本番が別物のリポジトリ」に限定される、と正直に報告する |
| CLI から走らせられるテストが無い対象1つ | **3本目** | `jev-opt/samples/` 経路の検証。ライブラリ crate に薄いドライバを書かずに、利用者がサンプル入力を置くだけで機能 1 が回ることを確かめる |

**機能 2**:

| 対象 | 位置づけ | 理由 |
|---|---|---|
| llama2-rs | **1本目(機構の証明)** | `matmul` / `inner_product` が長さ 288〜4096 の ordered f32 リダクションで実行時間の 9 割。C 依存なし、手書き SIMD なし、温度 0 で決定的。成果物は logits のダンプ(トークン列は argmax を挟むので使えない)。`RAYON_NUM_THREADS=1` で固定 |
| ebur128 | **2本目(正しさゲートと strict 判定の設計)** | `filter.rs:307` の `sum += x*x`(f64)。出力が数個の数値なので許容誤差の定義が自明。**作者が「`sum()` を使うと C 版と丸めが変わる」と書いた箇所がある**ので、Jev の strict 判定の実地テストになる。時間の相当部分は再結合できない IIR なので、カバレッジは部分的 |
| symphonia | **3本目(実プログラム)** | 全ワークスペースに `core::arch` / `std::simd` が 0 件。ただし MP3 の合成は要素毎で reduction が薄く、IMDCT は固定長バタフライなので、**効かないことが予想される**。`symphonia-check` は外部デコーダを呼ぶので、PCM を出す薄い CLI が要る |

toy / zopfli / oxipng の結果は `results.md` への参照のみとし、v0.4 の対象には入れない。

## 7. 機能 1: PGO 訓練ワークロードの選定(既定 ON)

`jev-opt build` は、既定でこの機能を有効にして走る。

**OFF(`--no-select-training` または `[features] select_training = false`)のときの挙動は1つに固定する**: `samples_dir` に入力があればそれだけで訓練して PGO ビルドを出し、無ければ **PGO を行わず `T0` を出荷する**。**素朴訓練(全候補)を暗黙の既定にしない**(悪い訓練セットは無 PGO より遅いため。§6.2)。`--selector all` は評価用のアームとしてのみ存在する。どちらになったかは常に標準出力に1行で出す。

### 7.1 候補プールの列挙(`jev-opt pool`)

**機械的に列挙するだけで、ここに判断は無い。** リポジトリが自分でプログラムを駆動している場所を模倣する。jaq での実装が `scripts/jaq_pool_extract.py`(1185 件を抽出、107 件が抽出不能)。

| 出自 | どこから | 何をするか |
|---|---|---|
| `test` | `tests/*.rs` の assert マクロ | 入力とパラメータがリテラルのものを取り出し、CLI 経由で走らせる |
| `doctest` | doc / manual 内のコード例 | リポジトリ自身の doc test ランナーを模倣する |
| `doccli` | README / manual 内の `$ ... \| <bin> ARGS` 行 | shlex で分解し、(producer → bin)に還元できるパイプラインだけを採る |
| `clitest` | 実バイナリを起動するゴールデンテスト | 引数と入力をそのまま採る。`cwd` を保つ |
| `bench` | `benches/`、`bench.sh` 等 | リポジトリのベンチランナーが渡すパラメータを模倣する |
| `example` | `examples/` | 実行可能なものだけ |
| `samples` | `[project] samples_dir`(既定 `jev-opt/samples/`) | **利用者が任意で置く本番相当の入力。** 無くてもよい |

**パラメトリック候補**は、入力ではなくパラメータ(stdin の n、`--size` 引数など)で仕事量が決まるものを指す。リポジトリ自身がそのパラメータを振っている場合(jaq の `bench.sh` は n を 7〜1048576 で振る)、**その値域を `scale_param` として候補に記録する**。リポジトリに大きな入力が無いとき、救うのは選定ではなくスケールである(decisions 46)。抽出できなかった候補は件数と理由を記録する(「1185 / 1292 件を抽出、43 件はシェル制御が要る、64 件は引数が Rust 式」)。**抽出率を成功値で埋めない。**

### 7.2 候補ごとの観測(`jev-opt pool`、続き)

1. まず素のバイナリで全候補をドライランし、タイムアウト(既定 10 秒)で終わらないものを落とす。所要時間と入力バイト数を記録する。
2. **計装バイナリで全候補を1回ずつ走らせ、候補ごとに `LLVM_PROFILE_FILE` を分けて profraw を取る。** jaq では 1185 件のドライランが 9.4 秒(実測)なので、この工程は安い。
3. 各 profraw から **profile 形状**を計算して `candidate-profiles/` に保存する(生の profraw は保持しない)。形状は4つ: **層別 share**(crate / モジュール接頭辞ごとのブロックカウント share 上位 N 件)、**データ経路 ÷ 起動経路の比**(起動・引数解析・コンパイル・初期化の層に対するデータ処理層のカウント比。固定コストしか払わない候補はこれが小さい。**判別に最も効く**、`results.md` §68)、**zero-count 層**、**wall**。
4. **汚染候補の検出**: 候補ごとの profraw の最大ブロックカウントが `wall秒 × 5e9` を超えるものを `poisons_profile` として `pool.json` に記録する。**候補はプールから消さない**(セレクタが見られる必要がある)が、訓練からは常に除外する。

### 7.3 グループ化(`jev-opt pool`、続き)

候補を **(出自, profile 形状)** で機械的にグループ化する。数十個(目標 20〜60)になるようにする。

- 出自は §7.1 の7種。profile 形状は、層別 share ベクトルを離散化してクラスタリングする(既定は上位層の share を 3 段階に量子化して完全一致で束ねる。規則は `[selector]` に凍結する)。
- グループの**代表候補**は、そのグループの中で wall が中央値のものを1件選ぶ。スケール可否はグループ属性にする(グループ内の候補がすべて `scale_param` を持つときだけ scale_up が選べる)。

**グループ化そのものに判断は無い**(規則は事前に凍結して `results.md` に書く)。Jev が見るのはグループであって 1185 件の生の候補ではない。1 HTTP request に収まる量にするための工程である。

### 7.4 Jev の Choice(`jev-opt select --selector jev`)

**1 HTTP request に全グループの question を同梱する。** グループ1つにつき Choice 1回。

**state**(共通部分、凍結書式): 利用者が `jev-opt.toml` に書く**本番の説明1行**(`[project] usage`。例: `"数十 MB の JSON ファイルをフィルタして標準出力に流す"`)— これが Jev の意味的判断の土台であり、**機能 1 で利用者に求める唯一の入力**である。加えて対象の説明(crate 名、バイナリ名、依存の主な層)、プール全体の統計(件数、出自別内訳、wall 合計、入力バイト分布)。**入力バイト数は「仕事量の指標ではない」と明記する**(jaq では逆相関。実測、`results.md` §62)。

**question ごとの `instructions`**(グループ1つ分): 代表候補の**内容そのもの**(フィルタ文 / 引数 / 入力の説明。長い入力は先頭と形の要約)、出自、件数、wall 合計、profile 形状(層別 share 上位、データ経路÷起動経路の比、zero-count 層)、スケール可否と値域。

**`criteria`**(Choice の候補、オブジェクト):

| 候補名 | 説明 |
|---|---|
| `include` | このグループの全候補を訓練に1回ずつ使う |
| `exclude` | 使わない |
| `scale_up` | パラメータを値域の上端付近に上げて使う。**そのグループがスケール可能なときだけ `criteria` に載せる**(適用できない選択肢を提示しない) |

**除外されたグループの扱い**: 除外は記録するだけで、性能への寄与は個別には測らない(全グループの単独アブレーションは費用が合わない)。`T_all` との差が全体としてそれを価格付けしている。**安全側の既定**: 応答が無い / confidence が閾値未満 / 不正応答のグループは `exclude`。理由を記録する。

### 7.5 決定的セレクタ B(`--selector cover`、評価専用)

Jev と同じグループの上で、**測定も Jev の答えも見ない**事前登録の規則で選ぶ。

- **被覆対象**: 全候補の profile を合算した和集合プロファイルの上位 K 層(既定 K = 20)。**オラクル(本番相当の入力で取った profile)は使わない**(使うと B が不当に強くなり対照として成立しない)。
- **規則**: 未被覆の層のカウントが最大になるグループを貪欲に選び、被覆率が閾値(既定 0.9)に達するか wall 合計が予算(既定 60 秒)に達したら止める。スケール可能なグループは被覆に寄与する場合に上端で使う。閾値と予算は **Jev の答えを見る前に** `[selector]` に凍結する。

これは「profile 形状の貪欲集合被覆」であり、**未測定**。Jev の価値はこの B との差で測る(§1.2)。B が Jev と同等以上なら、「選定には価値があったが Jev 固有の寄与は未証明」と報告する。

### 7.6 訓練・merge・妥当性検査(`jev-opt train`)

1. 選ばれたグループの全候補を**計装バイナリで1回ずつ**走らせる(`scale_up` のグループはパラメータを上げて走らせる)。`poisons_profile` の候補は常に除外する。アーム間で計装バイナリを変えない。
2. `llvm-profdata merge` でマージする。
3. **profile 妥当性検査(必須)**: `llvm-profdata show` を1回走らせ、**どのブロックカウントも `訓練の wall 秒 × 5e9` を超えないこと**を確かめる。超えていたら、どの候補が原因かを二分探索で特定し(`jev-opt pool --scan` と同じ機構)、その候補を除外して再マージし、除外した事実を `jev-training.json` に記録する。検査を通らないまま PGO ビルドに進んではいけない。
4. `--detailed-summary` の全パーセンタイルと上位関数の share を `jev-training.json` に記録し、`-Cprofile-use` で PGO ビルドを行う。`-pgo-warn-missing-function` の件数も記録する(**判定には使わない**、§3)。

### 7.7 フォールバック自己検査(`jev-opt build` の最終段、必須)

悪い訓練セットは無 PGO より遅い(実測、`results.md` §66)。したがって `jev-opt build` は**必ず T0 も建てて比べる**。

1. **自己検査用 holdout を切る**: 訓練に使っていない候補(`exclude` されたグループの代表、または `samples_dir` の未使用分)から数件を選ぶ。**`samples_dir` を訓練に使う経路(機能 1 OFF、および `--selector samples-only`)では、サンプルを1件必ず holdout 側に取り置く。** サンプルが1件しか無い等で holdout が作れない場合は自己検査を行わず、**その事実を警告として出した上で T0 を出荷する**(検査できないものを速いと言わない)。
2. **ノイズフロアを測る**: T0 のバイナリを2ラベルにして A/A を走らせ、集計速度比の信頼区間半幅を取る。
3. **判定**: PGO バイナリの集計速度比の信頼区間下限が `max(2 × A/A 半幅, 3%)` を超えなければ、**T0 を成果物として出荷する。**
4. **常に記録する**: どちらを出荷したか、両者の数値、holdout に使った候補を `jev-training.json` に書き、標準出力に1行で出す。フォールバックは失敗ではないので非ゼロ終了にはしない。

この自己検査は製品の安全装置であって、§1.2 のアブレーション(凍結した評価用 holdout で行う)とは別物である。混ぜて報告しない。

### 7.8 `jev-training.json`(機能 1 の lock)

```
schema_version, training_id(内容の sha256),
basis{ toolchain, target, build_flags_sha, instrumented_binary_sha, pool_sha, groups_sha },
selector: "jev"|"cover"|"all"|"samples-only",
usage: "<[project] usage の 1 行>",
groups[]: { group_id, source, n_candidates, decision: "include"|"exclude"|"scale_up",
            scale_value: int|null, confidence: float|null, answer_ref },
excluded_poisoning[]: { candidate_id, max_block_count, reason },
profdata{ sha256, total_count, max_block_count, wall_s, sanity: "pass"|"repaired",
          summary_percentiles{…}, top_functions[] },
selfcheck{ holdout_candidates[], aa_halfwidth, ratio, ci_lo, ci_hi, mde,
           shipped: "pgo"|"t0", reason }
```

## 8. 機能 2: FP 再結合の許可判断(既定 OFF)

`--fp-reassoc` を明示したときだけ有効になる。**出力が変わりうる**ので、既定経路とは正しさゲートを共有しない(decisions 42)。

### 8.1 機構(ソース確認済み、実測は未)

`LoopVectorize.cpp:8028` が `canVectorizeFPMath` に失敗すると `CantReorderFPOps`(「cannot prove it is safe to reorder floating-point operations」)を出して諦める。通す道は2つで、`LoopVectorizationLegality.cpp:1273-1297` の `if (!Requirements->getExactFPInst() || Hints->allowReordering()) return true;` がそれである。

- **ヒント経路は使わない。** `LoopVectorizeHints` は幅と enable を cl::opt と同じフィールドに読み込み、`allowReordering()` は両者を区別しない。つまり幅を明示しなくても `vectorize.enable=true` だけで FP 再結合が許される(ソース確認済み、**未測定**)。これを構成上塞ぐため、**全アームに `-Cllvm-args=-hints-allow-reordering=false` を固定する**(§3)。
- **採用するのは FMF 経路。** `RecurrenceDescriptor::isRecurrenceInstr` は連鎖の命令が `reassoc` を持たないときにだけ `ExactFPMathInst` を記録する。したがって対象ループの `fadd` / `fmul` / `fmuladd` 連鎖に `reassoc` を立てれば、`getExactFPInst()` が null になって `canVectorizeFPMath` が最初の行で true を返す。**幅も enable も付けず、VF はコストモデルに任せられる**(ソース確認済み、**未測定**)。
- `contract` は別判断(FMA 融合)。`isConditionalRdxPattern`(select 下の条件付き加算)は `isFast()` の全フラグを要求するので `reassoc` だけでは届かない。**影響範囲の正直な扱い**: FMF は後段の SLP / InstCombine / DAGCombine にも残るので、スカラのエピローグも再結合されうる。この点は Jev に渡す state にも書く。詳細は `docs/fp-reassoc-target-scouting.md` §1。

### 8.2 plugin

- **モード**: 環境変数 `JEV_MODE=off|dump|apply`、`JEV_PLAN=/abs/jev-plan.json`、`JEV_PLAN_SHA=<sha256>`(不一致なら即エラー)、`JEV_REPORT_DIR=/abs/dir`、`JEV_PGO_PROFILE_SHA`。module の `!llvm.module.flags` に `ProfileSummary` が無ければ `-Cprofile-use` が抜けているので両モードともエラーで止める。plan を `-Cllvm-args` 経由で渡さない(plugin の dlopen はコマンドライン解析の後なので、plugin が登録した cl::opt には値が入らない)。
- **extension point**: 第1候補は `registerVectorizerStartEPCallback`(inlining と loop canonicalization の後、LoopVectorize の直前)。代替は `LoopOptimizerEndEP` / `OptimizerEarlyEP` / `FullLinkTimeOptimizationEarlyEP`。**決め打ちせず probe の実測で固定する**(§13)。
- **fat LTO の2段**: pre-link とマージ後の2回 module 最適化が走る。どちらで発火しても壊れないよう、適用済みマーカ(`jev.applied` 相当の metadata)で冪等にする(「最初に到達した段で適用し、以降はスキップ」)。report は共有1ファイルに追記せず、`$JEV_REPORT_DIR/<module-id>-<stage>-<pid>.json` を1モジュール1ファイルで書いて CLI がマージする(pre-link 段は並行するため)。
- **dump が出すもの**: 各ループヘッダ PHI に `RecurrenceDescriptor::isReductionPHI` を1回呼び、**FP リダクションを持つ site だけ**を出す(export は確認済み: `nm -D libLLVM.so | grep isReductionPHI`)。recurrence kind、累算器の型、`hasExactFPMath()`、連鎖の命令数、trip count、hotness(`BlockFrequencyAnalysis` の `getBlockProfileCount(header)` × ループ本体の命令数)。
- **apply がやること**: plan で許可された site の連鎖の FP 命令に `setHasAllowReassoc`(と、指定があれば `setHasAllowContract`)を立てる**だけ**。幅も enable も interleave も付けない。`PreservedAnalyses::all()` で返す。
- **ビルド**: LLVM ライブラリを一切リンクしない(静的リンクすると cl::opt 二重登録で dlopen 時に abort)。`-fPIC -shared -fno-rtti -fno-exceptions -DNDEBUG -std=c++17`。ヘッダは LLVM 23.1 の upstream tarball から `ninja intrinsics_gen` で生成ヘッダだけ作る。ABI マクロは `DisableABIBreakingChecks` 側に合わせ、互換な libstdc++ でビルドする(§3 の gate 0)。
- **off 等価性**: plugin 未ロード vs ロード + `JEV_MODE=off` で正規化コードハッシュ(`scripts/norm_code_diff.py`)の一致を必須ゲートにする。`.text` の生ハッシュは C 依存があると再現しない(§3)。

### 8.3 site key

生成器は dump / apply 共通コードのみ。同じ profdata・同じ flags でビルドするので inlining が一致し、dump で得た key は apply でそのまま解決する。key は次を連結した sha256 の先頭16桁 + 可読サフィックス: (1) `owner_fn` = そのループを最終的に含む関数の `DISubprogram::getLinkageName()`(v0 mangled なので単相化引数が名前に入り generic は自動的に区別される)、(2) `inline_chain` = ループ本体の命令の `DILocation` → `inlinedAt` 鎖の linkageName 列(外→内)、(3) `leaf_loc` = 最内フレームの (file, line, col)、(4) `loop_fingerprint` = ループ本体の全命令の (leaf linkageName, line) のソート済み集合のハッシュ、(5) `depth` = ループ木の深さ。

apply 時に同じ key が2つ以上に解決したら `ambiguous`、0個なら `vanished`。どちらも別のループへ移さず記録する。発生件数そのものが設計の健全性メトリクス。

### 8.4 Jev への問い方

ホットな FP リダクション site ごとに Choice 1回、**全 site を1 HTTP request に同梱**。

**state**: ループ本体 ±20 行のソース、外側の関数シグネチャと doc コメント、**ループ内のコメントを逐語で**(ebur128 の作者コメントがこれで届く)、recurrence kind と累算器の型、trip count と hotness、crate とモジュールパス、**結果がどう消費されるか**(返る / 保存される / N 桁で表示される / 比較される / ハッシュされる / argmax・ソート・量子化に食われる)、FMF が後段にも残るという影響範囲。

**`criteria`**: `keep_strict` / `allow_reassoc` / `allow_reassoc_and_contract`。応答が無い・confidence が閾値未満・state が欠けている場合の既定は `keep_strict`。

**strict 側 / 許容側の信号**は scouting §4 の列挙をそのまま `instructions` の本文に入れる(補償加算、丸めや C 参照実装に関するコメント、ハッシュ・`==`・`total_cmp`、金額の語彙、離散分岐への入力 / 信号エネルギーや RMS、推論の内積、畳み込みタップ、直後に量子化される値)。`allow_reassoc_and_contract` は、連鎖が mul+add で、利用者が FMA を許可しており、ソースが明示的に `mul_add` を使っていない場合にのみ選ばせる(明示的な `mul_add` は意図的な丸めの選択である)。

**決定的セレクタ(アーム B)**は同じ site 集合に対し、測定も Jev の答えも見ない事前登録規則で選ぶ(例: 「ループ内コメントに丸め関連語が無く、結果が離散分岐に入らないなら `allow_reassoc`」)。規則は `[selector]` に凍結する。

### 8.5 正しさゲート

- **既定経路(`--fp-reassoc` なし)はビット一致ゲートのまま。** `--fp-reassoc` のときだけ許容誤差ゲートを使い、**両者を混ぜて報告しない。**
- 手順は (1) **決定性セルフチェック**(基準バイナリで各ワークロードを2回走らせ、成果物がビット一致すること。落ちたらその対象はどのゲートにも乗せられない)、(2) 成果物種別の宣言(`[fp.tolerance]`。**未宣言はビット一致**)、(3) **holdout** 上で基準と候補を比較(訓練入力では判定しない)。
- 成果物種別ごとの既定許容値(`f64_array` / `f32_array` / `pcm_f32` / `pcm_s16` / `image_u8` / `numbers` / 離散出力)は scouting §3 の表を既定値とし、`jev-opt.toml` で上書きできる。**基準は真値ではない**(木状加算のほうが普通は正確)ので、このゲートは誤差ではなく乖離を測る。記事でもそう書く。
- **離散増幅が罠**: argmax、閾値、`sort_by(partial_cmp)`、u8 量子化は 1 ULP を目に見える差にする。浮動小数点が離散判断に入る site は**量子化前の値を比較する**(トークンではなく logits をダンプする)。ダンプできない site は**規則で `keep_strict`**。
- 記録: どの site にどのフラグを立てたか、その DebugLoc から `CantReorderFPOps` が消えたか(消えていなければフラグは効いていない)、成果物ごとの指標・観測値・閾値・**予算の使用率**、フラグを立てた site のうち profile 上で実際に走ったもの。
- **site 規則が一次防御、ゲートは二次**(decisions 35)。ゲートは実行されたコードしか守らない。

### 8.6 schema(抜粋)

`sites.json`(plugin dump → CLI):
```
schema_version, toolchain{…}, target{…}, build_flags_sha, pgo_profile_sha,
hotness_stage: "prelink"|"lto", total_score,
sites[]: { key, owner_fn, inline_chain[], leaf{file,line,col}, depth,
           recurrence_kind, accum_type, chain_len, has_exact_fp_math,
           trip_count: int|null, hotness{header_count, body_inst_count, score, share},
           consumer_hint: str|null }
```

`jev-plan.json`(CLI → plugin、機能 2 の lock):
```
schema_version, plan_id, basis{ sites_sha, pgo_profile_sha, toolchain, target, build_flags_sha },
selector: "jev"|"rule-<name>"|"all-strict",
entries[]: { key, decision: "keep_strict"|"allow_reassoc"|"allow_reassoc_and_contract",
             confidence, answer_ref }
```

`apply-report-*.json`: `{ plan_id, module_id, stage, results[]: { key, outcome: "applied"|"vanished"|"ambiguous"|"skipped_idempotent", n_instructions, reason } }`。

`basis` のいずれかが現在のビルド条件と不一致なら plugin はエラーで止まる(警告にしない)。

## 9. 参考比較: 素の release ビルドとの差

機能ごとのアブレーションとは別に、「`cargo build --release` を `jev-opt build` に置き換えるだけでどれだけ速くなるか」という体験の数値を1つ出す。

- **参考アーム R**: 対象リポジトリの release profile をそのまま使い、`jev-opt` の上書きを一切しないビルド。`-Ctarget-cpu=native` も fat LTO も `codegen-units=1` も PGO も付けない。対象の `Cargo.toml` が既に `lto` や `codegen-units` を設定していればそれが効くので、**実効の opt-level / lto / codegen-units を `results.md` に明記する**。
- 測定は holdout の同じ交互実行に1ラベル足すだけ。
- **表示規則**: この差には LTO・native・PGO の寄与が含まれるので、機能の効果とは必ず分けて出す。「`jev-opt build` に置き換えると X% 速い。そのうち機能 1 の寄与は Y%」という形で並べ、X を Jev の効果として語らない。

## 10. 評価手順(全機能共通)

- **主指標**: end-to-end wall time。ケースごとの速度比を事前固定重みの幾何平均で集計し、交互実行の pair を単位に bootstrap で 95% 信頼区間を出す。
- **ノイズフロア**: holdout の前に、**同一バイナリを2ラベルにした A/A** を同一手順で走らせ、その信頼区間半幅をノイズフロアとする(jaq では同一 profdata から建てた `T_real` / `T_realB` がこれ。`results.md` §65)。**最小効果量(MDE)** = `max(2 × A/A の半幅, 3%)`。集計速度比の信頼区間下限がこれを超えない限り「改善」と書かない。
- **信用できる粒度**: jaq の実測では**集計は約 1%、単一ケースは約 3% まで**しか信用できない(`results.md` §58 の in-sweep null パネル)。単一ケースの ±3% は語らない。
- **ラベル順はローテートでなくシャッフルする。** ローテートだと隣接ラベルの A/A がラウンド内のドリフトを過小評価する(`results.md` §69 が次の実験への申し送りとして挙げた点)。
- **in-sweep null パネルを必須にする。** 正規化コードハッシュ(`scripts/norm_code_diff.py`)が基準と一致したラベルを、その run の中の追加の null 対照として使う。専用のノイズプローブは信用しない(jaq では「ノイズプローブ」のつもりだったアラインメントのフラグが +1.32%、単一ケースで +3.42% 動いた。`results.md` §58・§60)。
- **測定条件**: `taskset` で物理コア1つに固定し、SMT 兄弟を空ける。**`lscpu -e` の出力を記録に残す**(WSL2 からはホストの CCD トポロジが見えないので「単一 CCD 内」は主張しない)。ASLR は有効のまま。n(既定 15〜50)、warmup(既定 3〜5)、trimming 規則を holdout 前に config で凍結し、事後変更した run は無効。
- **jaq 型の対象の測定**: 大きな入力1本ではなく**小さい入力を複数回**並べ、`--gap-ms 250` の整定ギャップを入れる。72 MiB の配列1本では RSS 1.2 GiB で同一バイナリ・同一入力が二峰になり、A/A 半幅が 13% まで悪化した(`results.md` §55、実測)。
- **同時に1対象しか測らない**(別対象のビルドを並走させると A/A 半幅が 0.3% → 1.7% に悪化した。実測)。**実行中の共有スクリプトを in-place で編集しない**(bash が途中から読み直して落ちる。実測)。
- **holdout は凍結後1回のみ**。結果を見てから候補・セレクタ・重み・n を変えた場合は新 seed で再生成し、全実行履歴を `results.md` に列挙する。**機能 1 では、訓練に使った候補を holdout に入れてはいけない**(製品の自己検査 holdout も同様、§7.7)。
- **退行**: ケース集合と重みは事前凍結し、退行ケースは集計に含めたまま最大値と件数を `results.md` 冒頭に置く。試した全アーム・全世代を列挙し、採用しなかったものも残す。
- **正しさ(ゲートであり、時間より先に読む)**: 上流テストと holdout の出力一致。既定経路はビット一致、`--fp-reassoc` のときだけ許容誤差(§8.5)。**一致しないアームは、速度をどれだけ改善していても採用せず、集計にも入れない**(別枠に「正しさ違反」として記録する)。読む順序を規則にする理由は、v0.3 の掃引で最大の「高速化」が答えの違うバイナリだったため(`results.md` §13)。
- **帰属**: 基準と候補の最終バイナリを `scripts/norm_code_diff.py` でシンボル単位に比較し、変化した関数が profile の何%を占めるかを報告する。機能 1 では「どの層が縮み、どの層が膨らんだか」がそのまま説明になる(`results.md` §67 の形式を踏襲する)。
- **事後帰属(任意)**: 差が出た場合に限り、`scripts/ipsample.c` か callgrind でシンボル別の時間を取る。無ければこの節を省略し、「事後帰属は未実施」と書く。主張の成否はこの節に依存しない。
- **コスト**: ビルド時間(fresh / cache 別、n ≥ 3 の中央値)には**計装ビルド・候補のドライラン・候補ごとの計装実行・訓練実行・merge・妥当性検査・T0 ビルド・自己検査**をすべて含める(`jev-opt build` 1回の体感時間がこれを含むため)。Jev の呼出し回数・待機時間・費用を事前登録した予算と照合する。
- **記録**: `run-manifest.json` に toolchain、CPU、`lscpu -e` と `taskset` のコア、flags、config の SHA、データ hash、**各アームの `merged.profdata` の sha256**、`training_id` / `plan_id`、正規化コードハッシュ、**全アームの出力 checksum**、時間サンプル、費用をまとめる。`results.md` は記録から生成し、欠測を成功値で埋めない。

## 11. 設定ファイル `jev-opt.toml`

```toml
[project]
repo = "…/jaq"            # 対象。切り替え時はここだけ変える
bin = "jaq"
target = "x86_64-unknown-linux-gnu"
usage = "数十 MB の JSON ファイルをフィルタして標準出力に流す"  # 機能 1 で利用者に求める唯一の入力
samples_dir = "jev-opt/samples"   # 任意。本番相当の入力を置くと候補プールに入る
profile_env = { OPT_LEVEL = "3", LTO = "fat", CODEGEN_UNITS = "1", DEBUG = "1",
                PANIC = "unwind", STRIP = "none" }   # CARGO_PROFILE_RELEASE_*
fixed_rustflags = ["-Ctarget-cpu=native", "-Csymbol-mangling-version=v0",
                   "-Cllvm-args=-hints-allow-reordering=false"]

[features]
select_training = true    # 機能 1。既定 ON。--no-select-training で OFF
                          # OFF のとき: samples_dir があればそれで訓練、無ければ PGO 無し(T0)。§7
fp_reassoc = false        # 機能 2。既定 OFF。--fp-reassoc で ON

[selector]                # 決定的セレクタ(評価専用)。Jev の答えを見る前に凍結する
grouping_rule   = "source+quantized-layer-share-3"
cover_top_k     = 20
cover_threshold = 0.9
cover_budget_s  = 60
fp_rule         = "…"     # 機能 2 のアーム B の規則

[pgo]
pool_dir = "…/targets/<target>/pool"   # pool.json、candidate-profiles/、groups.json
arms_dir = "…/pgo/<target>/arms"       # アームごとの profraw と merged.profdata
llvm_profdata = ""        # 空なら pin した toolchain から解決
dryrun_timeout_s = 10
sanity_ipc = 5e9          # ブロックカウント上限 = 訓練 wall 秒 × この値(§7.6)
reuse = true              # 既存の pool / profdata があれば再利用する

[evaluation]
holdout = ["cases/holdout/*.json"]   # 凍結。訓練には絶対に使わない
weights = { … }                      # holdout 前に凍結
repetitions = 15
warmup = 3
gap_ms = 250              # 整定ギャップ(§10)
label_order = "shuffle"   # rotate ではない(§10)
trim_rule = "none"
min_effect_size = "max(2*aa_halfwidth, 0.03)"
cpu_pin = "4"
seed = 20260921

[budget]
max_groups = 60
max_requests_per_build = 4   # 実際は機能あたり 1 HTTP request
request_timeout_s = 60
api_cost_budget_usd = 5.0
max_training_wall_s = 120

[artifacts]
remarks_dir = "…/remarks/<target>"
jev_log_dir = "…/artifacts/jev-log/<target>"

[fp.tolerance]            # 機能 2 のときだけ使う。未宣言の成果物はビット一致(既定値は scouting §3)
f64_array = { max_rel = 1e-12, max_ulp = 64 }
f32_array = { max_rel = 1e-6, max_ulp = 256 }
numbers = { max_rel = 1e-9 }

[jev]
base_url = "https://ai-gateway.vercel.sh/typesafe"
endpoint = "/v1/systemone"    # POST。GET /v1/models で利用可能モデルを確認
model = "typesafe-ai/jev"
api_key_env = "AI_GATEWAY_API_KEY"   # 値は .env か環境変数。リポジトリには置かない
```

凍結すべき値はすべてここにあり、SHA を `run-manifest.json` に記録する。`[features]` の既定値は CLI の既定と一致していなければならない。

## 12. CLI

| コマンド | 内容 |
|---|---|
| `jev-opt doctor` | toolchain 記録(解決後の `rustc -vV`)、**失格フィルタ**(§3。`cargo tree -e normal,build` の `cc` / `*-sys`、手書き SIMD の grep、当たったら wall-clock 帰属)、`llvm-tools-preview` と `llvm-profdata` の存在と LLVM メジャー一致、`llvm-knobs.json` 生成、テキスト remark の取得確認、Jev 疎通。`--fp-reassoc` を使う場合のみ gate 0(`libLLVM.so` に対する `nm -D`)と `-Zllvm-plugins` の probe。**probe は codegen を伴う emit で行う**(`--emit=metadata` では plugin を dlopen しないので probe にならない) |
| `jev-opt pool` | 機能 1 の (1)(2)(3): 候補列挙 → ドライラン → **候補ごとの計装実行と profile 形状** → 汚染候補の検出 → グループ化。`pool.json` / `candidate-profiles/` / `groups.json` を書く。`--scan` で汚染候補の二分探索だけを回す |
| `jev-opt select` | 訓練集合を決める。`--selector jev|cover|all|samples-only`。`jev-training.json` の `groups[]` までを書く。`jev` は 1 HTTP request、`cover` は決定的、`all` と `samples-only` は評価用 |
| `jev-opt train` | 選ばれた集合で訓練実行 → `llvm-profdata merge` → **profile 妥当性検査**(§7.6)→ `merged.profdata`。汚染があれば除外して再マージし記録する |
| `jev-opt build` | **製品経路。** 利用者は `cargo build --release` の代わりにこれ1つを打つ。内部で `pool` → `select` → `train` → PGO ビルド → T0 ビルド → **フォールバック自己検査**(§7.7)を一括実行する。`--no-select-training` で機能 1 を切る(`samples_dir` があればそれで訓練、無ければ PGO 無しで `T0` を出す。§7)。`--fp-reassoc` で機能 2 を足す(plugin dump → Jev → apply → 許容誤差ゲート)。ゲートに落ちたら plan を採用せず、フォールバック先のバイナリを出し、却下の事実を記録して**警告付き成功**で返す(利用者は常に正しいバイナリを受け取る) |
| `jev-opt bench` | 全アーム(§1.2)、交互実行、ラベル順シャッフル、bootstrap、in-sweep null パネル、帰属 diff、`results.md` 生成 |

cargo への組み込みは「CLI が環境変数を組んで `cargo build --release --target …` を exec する」だけ。`.cargo/config.toml` は使わない(RUSTFLAGS 系と上書き競合し、variant 切替で状態が残る)。

```
CARGO_TARGET_DIR=target/<variant>
CARGO_PROFILE_RELEASE_LTO=fat CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1
CARGO_PROFILE_RELEASE_DEBUG=1 CARGO_PROFILE_RELEASE_STRIP=none …
# <fixed_rustflags> に -Ctarget-cpu=native / -Csymbol-mangling-version=v0 /
#   -Cllvm-args=-hints-allow-reordering=false が入っている(§11)
CARGO_ENCODED_RUSTFLAGS="<fixed_rustflags>\x1f-Cprofile-use=/abs/pgo/<target>/<arm>/merged.profdata\x1f-Cllvm-args=…"
# --fp-reassoc のときだけ追加:
#   …\x1f-Zllvm-plugins=/abs/libjevplugin.so
#   JEV_MODE=apply JEV_PLAN=/abs/jev-plan.json JEV_PLAN_SHA=<sha> JEV_REPORT_DIR=/abs/reports/<variant>
cargo build --release --target x86_64-unknown-linux-gnu
```

**対象ごとのディレクトリ分離と toolchain の明示**:

- 成果物は対象ごとのサブディレクトリに分ける: `targets/<target>/pool/`、`pgo/<target>/arms/<arm>/`、`remarks/<target>/`、`artifacts/jev-log/<target>/`(複数対象を回すと衝突するため)。計測用バイナリは計測直前に `strip -s` する(ビルド時は `STRIP=none`)。
- **`jev-opt` が spawn する cargo / rustc の環境に `RUSTUP_TOOLCHAIN=nightly-2026-09-21` を明示的に入れる。** `rust-toolchain.toml` はこのリポジトリ配下にしか効かず、対象は別ディレクトリにある。pin を信用せず、解決後の `rustc -vV` を `run-manifest.json` に記録する。

## 13. 実装順序とゲート

各 day は目安。ゲートを通らなければ次に進まず、判定を `results.md` に残す。**機能 1(Rust のみ)と機能 2(C++)は別トラックで、依存しない。**

### 済(v0.3 期。すべて `results.md` に記録済み)

- **環境の確定**(`results.md` Day 0 §1〜§6): toolchain pin、**gate 0**(§3。`libLLVM.so` に対して実施済みなので機能 2 トラックで再実施しない)、remark 機構の選定、`.text` の debuginfo 依存、`llvm-knobs.json` 生成(2689 ノブ)。
- **測定手順の確立**(`results.md` §8〜§10・§46・§55): A/A、MDE、交互実行、bootstrap、正規化コードハッシュ、整定ギャップ、`scripts/ipsample.c`。**4対象の否定結果**(§12〜§61): toy / zopfli / oxipng / jaq。§14 に要約。
- **Experiment 1(jaq、機能 1 の上限測定)**(§62〜§69): 候補プール抽出(1185 件)、汚染候補の検出、8 アーム、holdout 1 回、帰属。

### 機能 1 トラック

**day 1〜2: `pool`** — 候補列挙器(6 出自 + samples)、ドライラン、候補ごとの計装実行と profile 形状、汚染検出、グループ化。jaq で `scripts/jaq_pool_extract.py` の結果を再現できることをゲートにする(1185 件、9.4 秒、汚染 3 件)。
**day 3: `train` と `build`(機能 1 のみ)** — 訓練 → merge → 妥当性検査 → PGO ビルド → T0 ビルド → 自己検査。`--selector all` と `--selector cover` で jaq を通し、`T_all` が `results.md` §65 の値を再現することをゲートにする。
**day 4: Experiment 2(pulldown-cmark)** — `T0` / `T_all` / `T_cover` と、本番相当入力による参考上限を測る。**ここで「素朴解が既に良い対象でも余地がある」かが決まる。** 余地が MDE 未満なら、機能 1 の適用範囲を限定して報告し、Jev アームに進む前にユーザー判断を仰ぐ。
**day 5: Jev の `criteria` 確定と `select --selector jev`** — Experiment 2 の帰属(何が profile を良くしたか)を見てから state と criteria を書き、凍結する。`docs/jev-samples/` に見本を置く。
**day 6: Jev アームの実験** — jaq と pulldown-cmark で `T_jev` を測り、§1.2 の表を埋める。
**day 7: 第 3 対象**(CLI から走らせられるテストが無い対象)で `samples_dir` 経路を検証する。

### 機能 2 トラック

**day 3(C++ 開始)**: LLVM 23.1 の upstream tarball からヘッダ生成 → **probe plugin**(全 EP callback を登録し、発火時に EP 名 / module / 関数数 / `isvectorized` 件数をログ)→ toy を lto=off / thin / fat / fat+PGO でビルドして EP 選定表を作る。**これが EP 選定の唯一の根拠。** 併せて off 等価性(正規化コードハッシュ一致)を確認する。
**day 4**: dump モード。`RecurrenceDescriptor::isReductionPHI` で FP リダクション site を列挙し、site key と hotness を出す。llama2-rs で「既知のホットループが上位に来る」ことを検算にする。
**day 5**: apply モード(`setHasAllowReassoc` / `setHasAllowContract`)。llama2-rs の `matmul` に手書き plan でフラグを立て、(a) その DebugLoc から `CantReorderFPOps` が消えること、(b) 機械語に `vaddps` 系が現れること、(c) logits が基準から乖離すること、の三重で consumed を確認する。**これが FMF 経路の初の実測。**
**day 6**: 許容誤差ゲート、決定性セルフチェック、成果物比較器。llama2-rs で速度と乖離を測る。
**day 7**: Jev 接続(state 凍結、1 request に全 site)。**ebur128 で `filter.rs:335-336` の作者コメント箇所を `keep_strict` と判断できるか**を見る。これが機能 2 の意味的判断の実地テスト。
**day 8(任意)**: symphonia。効かないことが予想されるので、結果がフラットでもそのまま報告する。

**失敗時の分岐**(機能 2): dlopen で abort → LLVM を静的リンクしている(リンク指定を全部外す)。LTO 段でどの EP も発火しない → pre-link 段で適用する(冪等性設計がそのまま使える)。正規化コードハッシュ不一致(off 等価性)→ plugin が off でもパイプラインを変えている(差分関数を特定するまで進まない)。FMF を立てても `CantReorderFPOps` が消えない → 連鎖の同定が間違っている(`--emit=llvm-ir` でフラグを目視する)。

## 14. スコープ外(別テーマとして扱い、成功と混同しない)

- **検証済みで採用しなかった方式: ループ metadata ヒントを Jev に選ばせる(v0.3 の主仮説)。** 5つのヒントファミリー(幅 / 有効化、predication、interleave、unroll count、distribute)を、グローバルノブの掃引で「どの次元が動くか」を測り、動いた次元について plugin でループ単位のヒント(site 単位の plan)を Jev に選ばせる、という構成だった。toy / zopfli / oxipng / jaq の4対象で事前登録の掃引と打ち切り規則を適用した結果はすべて「フラット」で、PGO + LTO + native の上に残っていたのは 0〜2% だった。`-force-vector-width` はグローバルにもメタデータ経路でも FP 再結合を誘発して**出力を変える**副作用を持つことも分かった。機構・数値・各対象での理由は `results.md` §12〜§61、判断は `decisions.ja.md` 12〜14・21〜24・29〜31・37。v0.4 はこの方式を製品機能から外し、plugin は機能 2(FP 再結合)のためだけに作る。**ヒントの掃引も、その結果に基づくグローバル設定の選択も、製品の工程には無い。**
- HashMap を線形探索に変える、JSON 用 kernel を手書きする、SWAR を明示的に生成する、といった意味変換。
- inline / noinline / cold / optsize 等の関数属性。
- パス挿入(unswitch、fusion、interchange 等)、AVX-512 幅選択(この機に無い)。
- **PGO を使わない静的 Jev**(profile を取らず全ループに問い合わせる方式)。site 数がそのまま問い合わせ回数になり費用と待機時間が成立しない。
- 34ファミリーのカタログは `work/jev_opt_patterns.md` に将来候補として残す(メンテナンスしない)。
- マークなし driver の一般化、他言語への展開。

## 付録: 実装者(Codex)への開始プロンプト

> `SPEC.ja.md` v0.4 に従って実装する。順序は §13 のとおりで、**機能 1(Rust のみ、plugin 不要)と機能 2(C++)は別トラック**である。各 day の終わりにゲート判定を `results.md` に書き、通らなければ次に進まず報告する。
>
> **Jev が決めることは機能ごとに独立したオン・オフ**(§0、§1.2)。機能 1 = PGO 訓練ワークロードの選定(既定 ON、`--no-select-training` で OFF)、機能 2 = FP 再結合の許可判断(既定 OFF、`--fp-reassoc` で ON)。効果は機能ごとのアブレーションで測り、束ねた合計を見出しにしない。
>
> **機能 1 の要点**: 候補の列挙・ドライラン・候補ごとの計装 profile・グループ化は**機械的な工程で判断を含まない**。判断はグループごとの `include` / `exclude` / `scale_up` の Choice だけで、**1 HTTP request に全グループを同梱**する。入力サイズは特徴量として使わない(実測で逆相関)。訓練後の **profile 妥当性検査**(どのブロックカウントも wall 秒 × 5e9 以下)と、**T0 へのフォールバック自己検査**は省略可能にしない。悪い訓練セットは無 PGO より遅い。
>
> **機能 2 の要点**: 実装は **FMF 方式のみ**(該当連鎖の FP 命令に `reassoc` / `contract` を立てるだけ。幅も enable も付けない)。全アームに `-Cllvm-args=-hints-allow-reordering=false` を固定する。既定経路はビット一致ゲート、`--fp-reassoc` のときだけ許容誤差ゲートで、両者を混ぜない。量子化前の値を比較できない site は規則で `keep_strict`。
>
> **正しさは時間より先に読む。** 一致しないアームは、速度をどれだけ改善していても採用せず集計にも入れず、別枠に記録する。**測定**(§10): 同時に1対象、実行中の共有スクリプトを編集しない、ラベル順はシャッフル、正規化コードハッシュ(`scripts/norm_code_diff.py`)、in-sweep null パネル、MDE = max(2 × A/A 半幅, 3%)、集計は約 1%・単一ケースは約 3% まで信用できる。
>
> **対象の順序**(§6.4): 機能 1 は jaq → pulldown-cmark → CLI テストの無い対象1つ。機能 2 は llama2-rs → ebur128 → symphonia。対象の切り替えは `jev-opt.toml` の `[project]` と `[evaluation]` の差し替えだけで済むようにし、コードに対象依存の分岐を置かない。
>
> **言語方針**: ソースコメント、コミットメッセージ、PR 本文、README、CLI のヘルプとログは**英語**。`SPEC.ja.md` と `docs/decisions.ja.md` は日本語で、開発中はそちらが正本。**toolchain は `nightly-2026-09-21`(LLVM 23.1.1)に pin してある。** spawn する cargo / rustc には `RUSTUP_TOOLCHAIN` を明示し、解決後の `rustc -vV` を `run-manifest.json` に記録する。Jev への request / response は JSONL に全件記録する(§5)。LLVM / rustc 内部に関する本仕様の記述のうち、`results.md` に実測が記録されているものはこの toolchain での実測値であり、それ以外は pin 上で確認する検査項目として扱う(断定ではない)。
>
> 最初に返すもの: **jaq に対する `jev-opt pool` の結果**(候補件数と出自別内訳、ドライランの所要時間、汚染候補の検出、グループ数と各グループの profile 形状)。`results.md` §62〜§63 の値を再現できるかがゲート。
