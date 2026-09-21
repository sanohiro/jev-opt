# jev-opt 実装仕様(正式採用版 v0.3、日本語正本)— ビルドオプションとして Jev にコンパイラの最適化方針を選ばせる

> 英語版は接尾辞なしの `SPEC.md` として実装が落ち着いた時点で生成する。開発中の正本はこの `SPEC.ja.md`。`work/` 配下(旧版・レビュー・カタログ・記事草稿)は今後メンテナンスしない。

旧版は `work/jev_opt_spec_v0.2.md`、その問題点は `work/jev_opt_review.md`。v0.3 の方針は4つ。**速さは追求する。作りはなるべくシンプルにする。判断は Jev に最大限任せる。わかりやすくする。** 最適化はコードを書き換えず、コンパイラへのヒントで行う。

## 一枚で分かる jev-opt

**利用者の体験**: `cargo build --release` の代わりに `jev-opt build` を実行するだけ。Jev がそのプログラムと CPU に合わせてコンパイラの最適化方針を選び、通常より速いバイナリが出る。ソースは一切変えない。Gentoo で USE フラグを付けてビルドするのと同じ感覚で、Jev 最適化をビルドオプションとして付ける。**PGO の訓練実行も内部で回す**: 計装ビルド → 訓練ワークロード実行 → `llvm-profdata merge` までを `jev-opt build` が面倒を見るので、利用者が意識するのはコマンド1つ。訓練ワークロードは設定ファイル `jev-opt.toml` の `[workloads] training` に書いておく。

**Jev が決めること(2つだけ)**:

1. **ビルド全体のコンパイラ設定**を候補から1つ選ぶ(例: byte 処理のベクトル幅を最大化する設定を使うか)。
2. **ホットなループごとのヒント**を候補から1つ選ぶ(例: このループはベクトル幅 32、あのループは既定のまま)。「既定のまま」を選べるので、どこを触るかも Jev が決めている。

**人が決めないこと**: 対象関数の選定、ヒントの選択、設定の選択。判断が要るところはすべて Jev。固定規則は評価用の対照としてだけ存在し、製品の経路には無い。

**部品(3つ)**: CLI `jev-opt`(Jev に聞いて plan を書き、cargo を起動する)、LLVM plugin(plan を読んでループにヒントを付けるだけ)、plan ファイル(Jev の決定。これが再現の単位)。

**速さの証明**: PGO 込みの最強ビルド(`O3 + target-cpu=native + lto=fat + codegen-units=1 + PGO`)との差を、ノイズフロアを測った上で信頼区間付きで出す。この基準を超えなければ「速い」と言わない。「PGO を使えばいいじゃん」には「その PGO の上に乗った」と答える。

**作る順序**: まず PGO 基準(計装ビルド → 訓練実行 → profdata → PGO 基準ビルド)を作り、コードを書かずに「余地があるか」をその上で測る(Stage 0)。次に plugin 無しで Jev にビルド設定を選ばせる(Stage 1)。それから plugin を足して、Jev にループ単位のヒントを選ばせる(Stage 2)。製品の `jev-opt build` は PGO 基準に Stage 1 と Stage 2 の決定を重ねる。

**対象の順序**: 各 Stage を **toy crate → zopfli → jaq** の順に適用する。toy crate(lib + bin の2 crate、lib 側に素朴な `for` ループと `iter().filter().count()`)はパイプラインを end-to-end に通すための検証用で、性能主張には一切使わない。最初の実対象は zopfli(純 Rust、依存ほぼ無し、byte ループと整数 reduction を持つ、秒オーダーでノイズ比が良い、出力が決定論的)。f64 reduction も持つが、FP 再結合の合法性でヒントの射程外と分かったので狙わない(§6.2)。jaq は本命で記事の対象だが、パイプラインが toy と zopfli で通ってから入る(§6.4)。

**ホットなループの取り方**: 基準が PGO 込みなので、hotness は外部プロファイラではなく **PGO の分岐重み**から取る。plugin の dump モードが各ループヘッダのプロファイルカウント(`!prof` 由来)とループ本体の命令数を読み、その積を hotness score として `sites.json` に直接書く。「同じ profile を基準と Jev の両側に」が文字通り成立し、IP → site の突合も別プロファイラも主経路には要らない。perf / callgrind は §10 の事後帰属だけに使う。

以下は実装者向けの詳細。

## 0. v0.2 からの決定事項

| 決定 | 内容 | 理由 |
|---|---|---|
| マークを廃止 | `#[jev_opt::optimize]`、proc macro、source scanner、token hash、source diff gate を削除。対象は Jev が選ぶ | Jev は速くて安い。マークは自動化の先送りであり、debuginfo で照合できるなら不要。「ソースを一切変えない」が自動で成立し、将来のマークなし driver と同じ形になる |
| 判断はビルド前 | CLI がビルド前に Jev へ問い合わせて `jev-plan.json` を出す。ビルドは通常の `cargo build --release`。plugin は plan を適用するだけで、状態もネットワークも持たない | broker、Unix socket、rustc 内オンライン問い合わせ、計装 IR 上での判断、decision lock の replay がすべて消える。plan が lock そのもの |
| 基準は PGO 込み。訓練実行は1回、profdata は基準と Jev で共有 | 基準 = `opt-level=3 + target-cpu=native + lto=fat + codegen-units=1 + PGO`。Jev 版 = 同じもの + Jev のヒント。計装ビルド → 訓練ワークロード実行 → `llvm-profdata merge` は Stage 0 で1回だけ行い、得た `merged.profdata` を基準ビルドと Jev ビルドの両方に `-Cprofile-use` で渡す | 主張を「最強のビルド(PGO 込み)に Jev を足したらさらに速くなった」にする。「PGO を使えばいいじゃん」に「その PGO の上に乗った」と答えられる。profile 無しの基準と profile 有りの Jev を比べるのも、Jev だけ profile 無しにするのも不公平なので、同一 profdata で揃える。共有できる理由は、PGO の profile 照合がソース由来の早い段(関数の PGO 名とハッシュ)で行われるのに対し、Jev のヒントは VectorizerStart(inlining 後、ベクトル化直前)の遅い段で効くため、同じ profdata が両アームにそのまま合うから。アームごとの PGO サイクルは不要 |
| 2段階実装 | 第1段階は plugin 無しで完結(Jev がビルド全体のコンパイラ設定を1つ選ぶ)。第2段階で plugin を足し、Jev が場所とループ単位のヒントを選ぶ | 第1段階だけで体験・評価手順・Jev 接続が end-to-end で回る。C++ を書く前に「余地があるか」「Jev が選べるか」が分かる |
| ファミリーは5つ | loop metadata で制御でき、既定 O3 パイプラインが消費するもののみ: 幅/有効化、predication、interleave、unroll count、distribute | 34ファミリーの大半はパス挿入が必要か、site 単位の制御面が LLVM に無い。inline 系属性は他の site の照合キーを壊すので第2段階からは外す |
| Score / Noul は使わない | Choice のみ | 判定に使わない値を記録する仕組みを持たない |
| hotness は PGO の分岐重みから取る | ループヘッダのプロファイルカウント × ループ本体の命令数。plugin の dump モードが `sites.json` に直接書く。perf / callgrind、`llvm-symbolizer` / `addr2line` による **IP → site の突合**は主経路から削除し、§10 の事後帰属だけに残す(`addr2line` 自体は、プロファイラを使わない §7 Stage 1 の remark 帰属(DebugLoc → 関数)でも使う。そこでも IP → site の突合はしない) | 基準が PGO 込みになったので、plugin は各ループの `!prof` を直接見られる。「同じ profile を基準と Jev の両側に」が文字通りになり、外部プロファイラの導入もサンプル数の心配も突合の失敗も主経路から消える。代償は §8.3 に明記する |
| 対象の順序は toy → zopfli → jaq | 各 Stage を toy crate(パイプライン検証専用)→ zopfli(最初の実対象)→ jaq(本命・記事の対象)の順に適用する | jaq はインタプリタ層が厚く、パイプラインの不具合と対象の性質を切り分けにくい。toy で配管を通し、zopfli で実プログラムの手順を固めてから jaq に入る。zopfli と jaq で §1.3-5 の転移証拠も同時に揃う |

## 言語方針

- **英語**: ソースコメント、コミットメッセージ、PR 本文、README、CLI のヘルプとログ。
- **日本語**: `SPEC.md`、zenn 記事、開発ノート(`work/` 以下)。開発中はこちらが正本。
- 実装が落ち着いた時点で `SPEC.en.md` を生成し、英語記事の参照先にする。日本語版を正本として更新し、英語版は生成物として追随させる。

理由: コミット履歴は後から英語化できないので最初から英語で書く。一方、設計判断の理解と議論は日本語の方が速く正確なので、仕様と記事は日本語で持ち、公開用の英語は後から生成する。

## 1. 目的と結論の出し方

### 1.1 仮説

`O3 + native + Fat LTO + PGO` は、PGO があっても候補を実測して選んでいるわけではない。profile は branch weight と block frequency という入力として使われるだけで、最終的なベクトル幅・interleave・unroll の決定はコストモデルとヒューリスティックの見積もりのままである。コード、入力分布、CPU を踏まえた別の選択を Jev が一発で選ぶことで、この「最強のビルド」の判断にさらに上積みできるか。

### 1.2 結論は3段に分けて報告する

| 数値 | 意味 | 主張の重み |
|---|---|---|
| (PGO + Jev) − PGO | 「最強のビルド(PGO 込み)に Jev を足したらさらに速くなった」。プロファイル情報の再配達ではなく、コストモデルに無い判断をしているか | 記事の見出しであり主比較。これが最小効果量を超えなければ他の主張はしない |
| (PGO + Jev) − (PGO + 固定規則) | Jev の**選択**に価値があるか。同じ候補集合を決定的 selector で選んだ場合との差 | これが無ければ「追加パスに価値はあったが Jev 固有の寄与は未証明」 |
| 参考: (PGO + Jev) − 素の `cargo build --release`(O3 のみ、native も LTO も PGO も無し。実効値の定義は §9) | 「`cargo build --release` を `jev-opt build` に置き換えるだけでどれだけ速くなるか」という体験の数値 | 参考値。PGO と LTO と native の寄与を含むので、Jev 自身の効果とは必ず分けて表示する(§9) |

加えて第2段階では、site ごとに最良を選んだ場合(oracle)の集計速度比を実験専用モードで測り、「Jev は1回の Choice で oracle の何%を取ったか」を報告する。oracle の値は Jev の入力に一切入れない。

**PGO 有りでは Jev の優位が縮むことを先に書いておく。** profile が無ければ LLVM は trip count をほとんど知らないが、PGO 有りでは branch weight から推定 trip count と block frequency を得る。つまり「このループは短い/長い」という情報は LLVM も持っており、Jev に渡す trip count は LLVM が見ているものと同じ値になる。そこから来ていた優位は消える。残るのは、コストモデルに載っていない判断 —— 入力分布の偏りや累算器の型から来るベクトル幅の選択、コードサイズとスループットの引き換え、この CPU のマイクロアーキテクチャ事情 —— だけである。その残差で勝てば主張は強く、負ければ「hint 方式は PGO の上には上積みできない」を hint 方式の限界として報告する。どちらでも報告する。

### 1.3 「Jev コンパイラが実現可能かも」と言うために集める証拠

1. **ヘッドルームの存在**: PGO 基準の上で、グローバル設定1つで集計速度比を最小効果量の2倍以上動かす次元が最低1つある。
2. **不均質性**: 上位 site 間で最適設定が異なり、oracle − 一律最良 ≥ 最小効果量の2倍。これが無ければ「フラグを1個足せばよかった」で終わり、コンパイラの必要性は主張できない。
3. **Jev / oracle 比**: 探索ゼロの1回の Choice で oracle の何%を取ったか。決定的 selector の同比と並べる。
4. **主比較が有意であること**: 主比較 (PGO + Jev) − PGO の集計速度比の信頼区間下限 > 最小効果量。基準が既に PGO 込みなので、これがそのまま「プロファイル情報の再配達ではなく、コストモデルに無い判断をしている」証拠になる。
5. **転移**: 同じパイプラインを無改造で別の対象プログラムに適用して同傾向が出る。1プログラム1マシンでは「コンパイラ」を主張できない。対象の順序が toy → zopfli → jaq(§6.4)なので、**zopfli と jaq がそのまま転移の2本**になる。3本目(oxipng / symphonia)は余力がある場合のみ。

## 2. 全体フロー

対象の順序は **toy crate → zopfli → jaq**。下の Stage 0 → 1 → 2 を、この順に対象を進めながら適用する(§6.4)。

```
Stage 0  準備・PGO 基準の作成・ヘッドルーム探索(jev-opt のコードは 0 行。対象の toy crate と補助スクリプトは除く)
  計装ビルド(-Cprofile-generate)→ 訓練ワークロード実行 → llvm-profdata merge → merged.profdata
    ※ 訓練実行はここ1回だけ。この profdata を以降の全アーム(基準・selector・Jev・oracle・掃引の全構成)で共有する
  PGO 基準ビルド(-Cprofile-use、第2段階では plugin dump モード + remarks)
  失格フィルタ(手書き SIMD の有無)とテキスト remark の取得確認 → 対象の妥当性判定(§6.1)
  RUSTFLAGS でグローバル設定を振り(全構成に同じ -Cprofile-use を付ける)、時間が動く次元を特定
        │
Stage 1  グローバル plan(plugin 無し)
  Jev が候補設定集合から 1 つを Choice → RUSTFLAGS に付けて PGO ビルド → 4 アーム評価
        │
Stage 2  site plan(plugin あり)
  PGO 基準ビルドの plugin dump で全ループの site 一覧 + hotness(ループヘッダのプロファイルカウント × 本体命令数)
  → インタプリタ層 share のゲート(jaq に進む時点、§6.1)→ 不均質性ゲート(手書き plan)
  → Jev が site ごとにヒントを Choice → 同じ profdata + 同じ global_flags で plugin apply ビルド → 評価
```

各 Stage の終わりに go / no-go を判定し、判定と根拠を `results.md` に残す。Stage 0 で余地が無ければ次の対象へ進む、または対象を差し替える(§6.4)。

## 3. 固定環境(2026-09-21 にこの機で実測)

| 項目 | 値 | 備考 |
|---|---|---|
| CPU | AMD Ryzen 9 5950X(znver3、2 CCD、AVX-512 無し) | `prefer-vector-width` と zmm 幅選択は候補から消える |
| OS | WSL2 | governor / turbo を制御できない。構成順序のラウンドロビン交互化 + A/A でドリフトを吸収 |
| rustc(pin) | `nightly-2026-09-21` = rustc 1.100.0-nightly (bba531001) / **LLVM 23.1.1** | `rust-toolchain.toml` で pin 済み(`components = ["llvm-tools-preview"]`)。**LLVM 22 系の nightly は存在しない**ので、当初想定の「stable(LLVM 22.1.2)と同じ LLVM メジャーの nightly を pin する」は成立しなかった。本仕様の LLVM / rustc 内部の記述はこの toolchain での実測として読む。stable 1.96.0 も残してあるので LLVM メジャー間の A/B は後から可能だが、profraw のフォーマットは LLVM メジャーに紐づくので profdata は共有できない |
| `-Zllvm-plugins` | pin 上で受理される(存在しない `.so` を渡すと dlopen 失敗のエラーになり、unknown-flag にはならない) | ただし `--emit=metadata` では plugin を dlopen しないので成功してしまう。doctor の probe は **codegen を伴う emit** で行う(§12) |
| plugin ホスト | **libLLVM は共有ライブラリ**。`librustc_driver-*.so` は `libLLVM.so.23.1-rust-1.100.0-nightly` を動的リンクしており、`PassBuilder` シンボルは libLLVM 側に 63 件(librustc_driver 側は 15 件) | **gate 0 は実施済み**(§8.1、results.md Day 0 §2)。シンボルは `librustc_driver` ではなく `libLLVM.so` に対して読む。`DisableABIBreakingChecks` が定義(= アサーション OFF)、`_ZNSt` 1841 件。ヘッダと ABI マクロは §8.1 |
| debuginfo | `-Cdebuginfo=1` で `linkageName` が出る(stable 1.96.0 での確認。pin 上で再確認する検査項目) | =2 に上げる必要なし。**全アームで debuginfo=1 に固定する**(この toolchain では `.text` が debuginfo で変わる。下記) |
| PMU | HW cycles の perf_event_open は成功。`perf` バイナリは未インストール | **主経路では使わない。** hotness は PGO の分岐重みから取る(§8.2)。perf(無ければ `valgrind --tool=callgrind --dump-instr=yes`、決定論的で inline 帰属あり)は §10 の事後帰属(シンボル別の cycle 差分)専用で、未導入でも Stage 0〜2 は動く。callgrind の場合「cycle 差分」は「Ir 差分」に読み替える |
| remark | `-Cremark=all -Zremark-dir` は CGU 別 YAML を出すが、**fat LTO ではベクトル化 remark が 1 件も入らない**(マージ後モジュールの `*.lto.opt.yaml` が 0 バイト)。lto=off なら出る。`-pass-remarks-output` / `-pass-remarks-filter` は **LLVM 23.1.1 に存在しない**(`--lto-pass-remarks-*` は受理されるが何も書かない) | 採用: `-Cllvm-args=-pass-remarks=.*` / `-pass-remarks-missed=.*` / `-pass-remarks-analysis=.*`。stderr にテキストで出るので、**ビルドログそのものを remark 成果物として保存する**。ファイルに書かないので `-Cllvm-args` のプロセスグローバル性による truncate 競合は起きず、両 crate の rustc プロセスの stderr が同一ビルドログに入る。代償(remark 行に関数名が無い)は §7 |

PGO 基準ビルドの固定フラグ(全アーム共通、差分は Jev 由来のもののみ):

```
# cargo profile 環境変数(対象の Cargo.toml を変えずに release profile を上書き)
CARGO_PROFILE_RELEASE_OPT_LEVEL=3 CARGO_PROFILE_RELEASE_LTO=fat
CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 CARGO_PROFILE_RELEASE_DEBUG=1
CARGO_PROFILE_RELEASE_PANIC=<凍結値>
# rustc フラグ(CARGO_ENCODED_RUSTFLAGS、区切りは \x1f)
-Ctarget-cpu=native -Csymbol-mangling-version=v0
-Cprofile-use=<abs>/pgo/<target>/merged.profdata
-Cllvm-args=-pgo-warn-missing-function
-Cllvm-args=-pass-remarks=.* -Cllvm-args=-pass-remarks-missed=.* -Cllvm-args=-pass-remarks-analysis=.*
# remark は stderr に出るので、ビルドログを remarks/<target>/<variant>-build.log に保存する(§12)
# cargo 引数
--release --target x86_64-unknown-linux-gnu
```

profdata の作り方(Stage 0 で1回だけ。以降は使い回す):

```
# 1. 計装ビルド。plugin も remarks も付けない。CARGO_TARGET_DIR=target/pgo-gen
#    cargo profile 環境変数(opt-level / lto / codegen-units / debug / panic)は基準と同じものを渡す
CARGO_ENCODED_RUSTFLAGS="-Ctarget-cpu=native\x1f-Csymbol-mangling-version=v0\x1f-Cprofile-generate=<abs>/pgo/<target>/profraw"
cargo build --release --target x86_64-unknown-linux-gnu
# 2. [workloads] training を計装バイナリで実行 → <abs>/pgo/<target>/profraw/*.profraw
# 3. マージ(pin した toolchain の llvm-tools-preview 付属のものを使う)
llvm-profdata merge -o <abs>/pgo/<target>/merged.profdata <abs>/pgo/<target>/profraw
```

- lto / codegen-units / debuginfo / panic は RUSTFLAGS ではなく cargo の profile 環境変数で渡す。RUSTFLAGS に `-Clto=fat` を入れると、profile 側で LTO が無効な場合に cargo が付ける `-Cembed-bitcode=no` と衝突して rustc がエラーになる。profile 環境変数なら対象の `Cargo.toml` を変えずに済み、「ソースも Cargo.toml も変えない」が構成上成立する。
- `--target` の明示は必須。省略すると RUSTFLAGS が build script と proc-macro の host コンパイルにも載り、plugin が macro ビルド内で動く。
- `panic` 戦略、frame pointer、strip、リンカは探索次元に入れず1本に凍結して run-manifest に記録する。
- 最終バイナリは評価前に strip する。**debuginfo は全アームで `=1` に固定する。** この toolchain では debuginfo=0 と =1 で `.text` が一致しない(ハッシュだけでなくセクションサイズも関数順序も変わる。results.md Day 0 §5)ので、「debuginfo が `.text` を変えない」ことを確かめる手順は成立せず、行わない。`objcopy -O binary --only-section=.text` のハッシュ比較は、**debuginfo が一致するビルド同士**(plugin 未ロード vs ロード + `JEV_MODE=off`、§8.1)でのみ行う。ビルド自体は決定論的なので、同条件なら `.text` ハッシュは一致する。§7 の機械語帰属は strip 前・debuginfo=1 のバイナリに対して行う。
- `-Cprofile-generate=<dir>` / `-Cprofile-use=<abs .profdata>` は RUSTFLAGS(`CARGO_ENCODED_RUSTFLAGS`)で渡す。対応する cargo profile 環境変数は無い。パスは必ず絶対パス。計装ビルドでも `--target` の明示は必須で(build script / proc-macro を計装しないため)、`CARGO_TARGET_DIR` は `target/pgo-gen` に分ける。
- `llvm-profdata` は `rustup component add llvm-tools-preview` で入る、pin した toolchain 付属のものを使う。profraw のフォーマットは LLVM メジャーに紐づくので、システムの LLVM の `llvm-profdata` でマージしてはいけない。
- **基準アームと Jev アームは、同じ profdata・同じ global_flags・同じ debuginfo・同じ panic 戦略でビルドする。** 差分は plugin が付ける loop metadata(plan)だけ。`merged.profdata` の sha256 を `run-manifest.json` と `jev-plan.json` の `basis.pgo_profile_sha` に記録する。
- **PGO 基準ビルドには `-Cllvm-args=-pgo-warn-missing-function`(既定オフ)を明示的に付け、警告件数を数える。** toy では `no profile data available for function` / `hash mismatch` / `^warning: ` がいずれも 0 件だった(results.md Day 0 §4)。ただし toy で `-Cprofile-use` が掛かるのは対象 crate だけで std は既ビルドの rlib として来るので、この 0 は「対象コードについての 0」であり、大規模プログラムでの証拠ではない。**dump ビルドと apply ビルドでこの警告件数が一致すること**が「同じ profdata が両アームにそのまま合う」の実証になる。hash mismatch の警告(`-pgo-warn-mismatch`、既定オン)は 0 件であることを別途確認する。
- **profdata は再現する。** toy では、同じ計装バイナリで訓練実行をやり直して別ディレクトリにマージしても `merged.profdata` の sha256 がバイト一致した(results.md Day 0 §4)。再現しない対象に当たったら、その時点で原因を記録してから先へ進む。

## 4. 構成物

### 作るもの

| 名前 | 形式 | 責務 |
|---|---|---|
| `jev-opt` | Rust 単体 binary | 全サブコマンド。cargo 起動、PGO の計装ビルド / 訓練実行 / `llvm-profdata merge`、Jev 問い合わせ、決定的 selector、集計、`results.md` 生成。事後帰属(§10)で perf / callgrind を呼ぶのは任意で、無ければその節だけ省略する |
| `libjevplugin.so` | LLVM pass plugin(C++) | `off` / `dump` / `apply` の3モード。site 列挙、**PGO 分岐重みからの hotness 算出**、loop metadata の付与、冪等性チェック、report 出力。状態なし、ネットワークなし。第2段階で作る |
| `sites.json` | plugin → CLI | 全ループの site レコードと hotness(plugin が dump で直接書く)。CLI は remark 分類だけを書き戻す |
| `jev-plan.json` | CLI → plugin | Jev(または selector)の決定。これが lock |
| `apply-report-*.json` | plugin → CLI | site ごとの適用結果 |
| `llvm-knobs.json` | 生成データ | `rustc -Cllvm-args=--help-list-hidden` から機械生成した、pin した LLVM に実在する cl::opt の全集合。**LLVM 23.1.1 用**。22.x 由来のノブ表は使わない(実例: `-pass-remarks-output` は 23.1.1 に無い) |
| `remark-reason-map.json` | 手書きデータ | remark の自由文字列 → `legality / unsupported / cost / unknown`。**LLVM 23.1.1 専用**で、初期値は results.md Day 0 §6 の9件(legality 4 / unsupported 5)。理由文字列は LLVM メジャーで変わる(例: 「early exiting block」が 23.1.1 では「Incorrect number of successors from early exiting block」)ので、toolchain ごとに作り直す。未知は必ず `unknown` |
| `jev-opt.toml` | 設定 | §11 |
| `artifacts/jev-log/<target>/<run-id>.jsonl` | CLI が追記 | Jev への全リクエストとレスポンスの生ログ。1行1問い合わせ。`jev-plan.json` の `answer_ref` はこのログの行を指す(§5、§12) |

手で送った Jev の request / response の見本は `docs/jev-samples/`(git 管理)に置く。API の形を確認するときはまずここを見る。

### 作らないもの(v0.2 から削除)

proc-macro crate、source scanner、broker、Unix socket プロトコル、decision lock ディレクトリ、`off/online/replay` モード、`max_concurrent_requests`、手書きの capability registry、cargo subcommand 化、Cargo 再実行追跡の `option_env!` トリック、比較動画、Score / Noul。

ビルドの入出力になる JSON は3種(`sites.json` / `jev-plan.json` / `apply-report-*.json`)で、すべて片方向・追記なし。Jev ログの JSONL はこれとは別系統の追記専用の記録で、ビルドの入力には一切ならない。variant ごとに `CARGO_TARGET_DIR` を分け、必ず clean build する。cargo は環境変数の変更で再コンパイルしないため。

## 5. Jev の使い方

**原則: 判断が要るところは全部 Jev に聞く。人や固定規則で決めるのは「候補を機械的に列挙すること」と「測ること」だけ。** 決定的 selector は評価の対照アームとしてのみ存在し、`jev-opt build` の製品経路には入らない。

- プリミティブは Choice のみ。Vercel AI Gateway の TypeSafe 互換 API(`https://ai-gateway.vercel.sh/typesafe/v1/systemone`、`Authorization: Bearer $AI_GATEWAY_API_KEY`、`"model": "typesafe-ai/jev"`)を REST で呼ぶ。request は `state`(文字列)と `questions`(名前 → `{type: "choice", instructions, criteria: {候補名: 説明}}`)、response は `answers.<名前>.{choice, probabilities, confidence}` と `usage`、`provider_metadata.gateway.cost`。費用は Gateway 経由で課金され、レスポンスの `cost` をそのまま費用記録に使う。
- 同一 request 内の複数 question は独立・並列に評価される。したがって Stage 2 の「上位 N site 各1回の Choice」は **1つの HTTP request に N 個の question として同梱**できる(state は共通部分 + site ごとの差分を question の `instructions` に入れる)。HTTP 回数は global 1回 + site まとめ1回の計2回で済み、Choice の回数は変わらない。state が大きくなりすぎる場合だけ分割する。
- `jev-opt doctor` は `GET /typesafe/v1/models` で `typesafe-ai/jev` が利用可能なことを確認する。
- 1問い合わせ = 1 Choice。候補は 255 以下。同一 request に複数 question を入れる場合、相互依存を持たせない。
- **`criteria` の形は question の型で違う。** Choice の `criteria` は**オブジェクト**(候補名 → 説明)、Score の `criteria` は**配列**(順序付き段階の説明)。Score に object を渡すと `invalid_request` になる(実測)。本仕様は Choice しか使わないが、見本を書き換えるときに踏むので記録しておく。
- **Jev への全リクエストとレスポンスを JSONL で記録する。** `artifacts/jev-log/<target>/<run-id>.jsonl` に1行1問い合わせで `{ts, target, stage: "global"|"sites", request, response, http_status, latency_ms}` を追記する。`request` / `response` は送受信した JSON 全体をそのまま入れる。**`Authorization` ヘッダは記録しない**(ヘッダ自体を記録対象にしない。本文に API キーは含まれない)。`jev-plan.json` の `answer_ref` は `<run-id>.jsonl#<行番号>` を指し、`results.md` からこのログファイルへの参照を残す。実際に何を送って何が返ったかを後から読めることを要件とする。
- **人が読むテキストログも出す。** `artifacts/jev-log/<target>/<run-id>.log` に、1問い合わせごとに1行(`ts  stage  question 数  http_status  latency_ms  input_tokens  output_tokens  cost`)、実行の終わりに集計行(**HTTP リクエスト本数、Choice の総数、Jev 待ち時間の合計と平均・最大、トークン合計、費用合計**)を書く。同じ集計を `results.md` のビルドコスト表にも転記する。ビルド全体の所要時間に対する Jev 待ち時間の割合を一緒に出す。
- Jev への入力(state): 対象関数のソース(Stage 2 と製品経路では hotness 上位、Stage 1 単体では remark が `cost` を出した関数。§7)、CPU 情報(model、features、cache)、hotness(PGO 分岐重み由来の share と推定 trip count、§8.5。Stage 1 単体では無し)、remark の理由分類、候補の説明。IR そのものは渡さない。
- 候補には常に `KEEP_DEFAULT`(基準の判断を維持)を含める。第2段階で site ごとの Choice に `KEEP_DEFAULT` があることが、Jev が「場所を選ぶ」ことに相当する。別の site 選択 Choice は持たない。
- API 障害・timeout・不正応答は `KEEP_DEFAULT` に落として理由を記録する。オフライン問い合わせなので timeout 60 秒、retry 3 回で構わない。
- **1ビルドあたりの問い合わせ回数は「global 1回 + 上位 N site 各1回」**(N は初期 20)で二十数回。探索ループもマークも別途の site 選択 Choice も無い。「どこを見るか」は dump の hotness 上位が決め、「どこを触るか」は各 site の Choice に含まれる `KEEP_DEFAULT` が決める。
- 費用・回数・待機時間を記録し、site 数からの外挿(§1.3-5)に使う。

## 6. Stage 0: 準備・PGO 基準の作成・ヘッドルーム探索

`jev-opt` のコードは書かない(対象の toy crate と day 0 の補助スクリプトは除く)。CLI の最初のサブコマンド `doctor` / `baseline` / `headroom` はこの手順の自動化に過ぎない。対象は toy crate → zopfli → jaq の順に進める(§6.4)。toy はパイプライン検証専用なので、Stage 0 では「手順が通ること」だけを見て、打ち切り規則と(§6.1-2 の失格フィルタ以外の)妥当性判定は適用しない。

### 6.1 対象の妥当性判定(対象1本あたり最初の半日)

1. PGO 基準を作る: 計装ビルド → 訓練ワークロード実行 → `llvm-profdata merge` → `-Cprofile-use` で PGO 基準ビルド(§3)。hotness はこの PGO 基準ビルドの **plugin dump モード**から得る。PGO 後のインライン構造の上で `!prof` を読むので、後段の site key と定義上そのまま対応する。別プロファイラの実行も IP → site の突合も行わない。
2. `cargo tree -e normal | grep -iE 'memchr|simd|wide|std_detect'` と `grep -rlE 'core::arch|_mm_|_mm256|target_feature' src/` を実行する。手書き SIMD で既に最適化された処理はヘッドルームが無い。**この失格フィルタはどの対象でも day 0 に掛ける**(plugin を要さない)。
3. テキスト remark(`-pass-remarks*`)がビルドログに出ること、各行に `file:line:col` の DebugLoc が入っていることを確認する。fat LTO では `-Cremark=all` の YAML にベクトル化 remark が入らないので、YAML の有無は判定に使わない(§3)。
4. **インタプリタ層 share のゲート(jaq に進む時点で適用する)**: dump の hotness を使い、「ループを含まない関数」と「間接呼出し・`Rc` の参照カウント・`IndexMap` / `BTreeMap` 探索・アロケーションが支配的な関数」のプロファイルカウント × 命令数の合計が `total_score`(§8.5)に占める割合を出す。この層にはどのヒントも届かない。**70% を超えていたら対象差し替えを検討する。** これは命令数重みの推定であって cycle 実測ではないので、桁の判断にだけ使う(perf があれば併用してよいが必須にしない)。plugin dump を要するのでこのゲートは Stage 2 の入口にあり、toy と zopfli では適用しない。

### 6.2 仮説と、pin した toolchain(LLVM 23.1.1)の toy での実測結果

以下は **toy で 23.1.1 実測により確認済み**(results.md Day 0 §6)。4ループはいずれも fat LTO で `toy::main` にインライン展開された上での観測で、zopfli と jaq のテキスト remark で再確認または棄却する。

- **byte 探索ループ**(`position(|c| c == b'"' || c == b'\\' || c < 0x20)` 型、toy の `find_special`)は**合法性**で落ちる。実測の理由文字列は「Incorrect number of successors from early exiting block」と「Loop contains an unsupported switch」の2つで、機械語も 15 命令・ベクタレジスタ 0 のスカラループ。**仮説は成立。** loop metadata は合法性を持ち上げないので5ファミリーの射程外。ただしグローバルノブ `-enable-early-exit-vectorization`(§6.3 群 1)だけはこの形に効きうる唯一のレバーで、未検証。`vectorize.enable=true` を付けても変わらないという 22.x 時代の記述は、23.1.1 では再実行していない。
- **byte 集計ループ**(`filter(..).count()` 型、toy の `count_quotes`)は累算器が `i64` のため既定 **VF 4 × IC 4**。実測では `vpmovzxbq` で 1 反復 16 バイト、`ymm` 累算器4本を `vpaddq` で回す。**「既定 VF=4」という仮説の前半は成立。** byte 幅の累算器なら 1 反復 32 バイトにできるはずで、その 1 レジスタあたり 8 倍の差が `vectorize.width=32` / `-vectorizer-maximize-bandwidth` の狙い目として 23.1.1 でも残っている。**hint で実際に VF が上がるか、上がって速くなるかは未測定**(ヘッドルーム掃引の課題)。この機で最も期待値の高いヒントである点は変わらない。
- **素朴な添字 reduction**(toy の `sum_indexed`、`for i in 0..v.len()` で `u32` を `u64` に足す)も **VF 4 × IC 4**。`vpmovzxdq` で 1 反復 16 バイト。`count_quotes` と同じ「累算器の型が幅を決める」話の一段弱い版。
- **f64 reduction はヒントの射程外**(toy の `dot_f64`)。ループベクトライザは「cannot prove it is safe to reorder floating-point operations」で拒否し、SLP が乗算だけをベクトル化して(`vmulpd`、1 反復 8 double)、加算は `vaddsd` の順序付き鎖のまま残る。**`vectorize.width` は FP の再結合を許可しないので、5ファミリーのどの hint でもこのループは動かない。**
- したがって **zopfli の f64 reduction 仮説は撤回する。** zopfli で狙うのは (a) LZ77 のマッチ長比較などの **byte ループ**(幅と interleave)と (b) **整数 reduction** に限る。Huffman コスト計算の f64 reduction に幅・interleave・unroll の余地があるという v0.3 までの想定は、上の `dot_f64` と同じ合法性で落ちるとみて候補から外す(§6.4)。
- jaq で余地があるのは (a) 集計系 reduction ループ(整数のもの)、(b) 不変モード分岐の unswitch、(c) ホットループ内 callee の inline 判断。(b)(c) は第2段階の loop metadata では扱えないため、jaq で第2段階の効果が薄い可能性を最初から織り込む。

### 6.3 ヘッドルーム探索の行列(1日)

- 全ノブを `CARGO_ENCODED_RUSTFLAGS` で渡す(区切りは `\x1f`)。`-Cllvm-args` は cl::opt でプロセスグローバルだが、bin crate だけに渡すと依存 crate の pre-link パイプライン(inlining、SLP、LICM)に効かない。`-Ctarget-feature` は関数属性として各 crate に焼き込まれるので bin だけでは無効。したがって全構成で全 crate を再ビルドする。
- 一次読み取りはテキスト remark の diff。ビルドログから `remark:` 行を抜き、**ソートしてから** diff する(複数の rustc プロセスが同一 stderr に交互に書くので行順は決定論的ではない。行の集合は決定論的でノイズゼロ)。判定が変わったループが無い構成は実測を省略する。二次読み取りは代表3ワークロードの実測。
- ノブ名と既定値は `llvm-knobs.json` から取り、手で書かない。
- **掃引の全構成に同じ `-Cprofile-use=<merged.profdata>` を付ける。** ヘッドルームは PGO 基準の上にどれだけ残っているかを測るものであり、PGO 無しで動く次元が PGO 有りでも動くとは限らない(特に unroll と inline は PGO が既に触っている)。profdata は Stage 0 の最初に作った1つを使い回すので訓練実行は増えないが、`-Cprofile-use` はビルド1本を重くするので掃引のビルドコストは上がる。

| 群 | ノブ | 値域 | site 単位の等価ヒント |
|---|---|---|---|
| 0 | `-align-all-nofallthru-blocks` | 0, 5 | なし。**ノイズフロア測定専用**、最初に実行 |
| 1 | `-vectorizer-maximize-bandwidth` | off, on | `vectorize.width` |
| 1 | `-force-vector-width` | 0, 8, 16, 32 | `vectorize.width` |
| 1 | `-force-vector-interleave` | 0, 1, 2, 4 | `interleave.count` |
| 1 | `-prefer-predicate-over-epilogue` | 3値 | `vectorize.predicate.enable` |
| 1 | `-runtime-memory-check-threshold` | 8, 24, 128 | `vectorize.enable=true` で閾値が昇格(部分等価) |
| 1 | `-enable-early-exit-vectorization` | off, on | なし(グローバルのみ) |
| 2 | `-inline-threshold` | 225, 325, 500, 1000 | site 単位の等価ヒントは無し(関数属性は §14 でスコープ外)。グローバル設定としてのみ候補に入る |
| 2 | `-unroll-threshold` / `-unroll-max-count` / `-unroll-runtime` | 数値、on/off | `unroll.count` / `unroll.runtime.disable` |
| 3 | `-enable-loop-distribute` | off, on | `distribute.enable` |
| 3 | `-slp-threshold` / `-unswitch-threshold` / `-enable-loop-flatten` / `-enable-gvn-hoist` | 数値、on/off | なし |
| 4 | `-Ctarget-feature=+prefer-256-bit` / `+prefer-128-bit`、`-Ctarget-cpu=x86-64-v3` | 3値 | なし。znver3 では動く見込み薄 |

実行順序は群 0 → 1 → 2 → 3 → 4。ユニーク構成は約30。`-Cprofile-use` 込みのフル再ビルドを1本3分(zopfli はこれより軽く、jaq で3分)と見て、対象1本あたり約1.5時間。

**打ち切り規則(事前登録)**: 群 1〜3 を通して、(a) 集計速度比の信頼区間下限が最小効果量を超える構成が無く、**かつ** (b) どのケースでも単体ケースの改善が最小効果量を超える構成が無ければ、「この対象は hint 方式でフラット」と記録して対象を差し替える。(a) を満たさず (b) を満たす場合は、site 選択性に価値がある可能性があるので続行する。グローバル掃引は上限でも下限でもないので、この非対称な規則にする。

### 6.4 対象の順序

各 Stage を次の順に適用する。どの対象でも、着手前に §6.1-2 の失格フィルタを掛ける。

| 対象 | 位置づけ | 理由 |
|---|---|---|
| toy crate(lib + bin の2 crate) | **パイプライン検証** | lib 側に素朴な `for` ループと `iter().filter().count()` を置き、bin から呼ぶ(§13 day 3 の構成をそのまま使う)。ビルドが数秒なので、計装 → 訓練 → profdata → dump → plan → apply → bench の配管を end-to-end で回して壊れている箇所を切り分けられる。**性能主張には使わない**(ヘッドルーム判定も打ち切り規則も適用しない) |
| zopfli(Rust crate + CLI) | **最初の実対象** | 純 Rust、依存ほぼゼロ、ビルドが軽い。LZ77 マッチ長比較(byte ループ)と整数 reduction があり、実行が秒オーダーでノイズ比が良い。Huffman コスト計算の f64 reduction は、§6.2 の `dot_f64` 実測(FP 再結合の合法性で loop vectorizer が拒否)により**ヒントの射程外と判断して狙わない**。出力が決定論的で正しさ検査が自明。実プログラムの手順(ワークロード定義、A/A、掃引、site 絞り込み)をここで固める |
| jaq | **本命(記事の対象)** | JSON 処理の実ユーザーがいる。インタプリタ層が厚いので、進む時点で §6.1-4 の 70% ゲートを掛ける。超えていたら jaq は本命から降ろし、zopfli を主対象として報告する |
| oxipng | 差し替え・転移候補 | PNG フィルタが純粋な byte ループで vectorize 余地が明確。実ユーザーのいる CLI。libdeflate feature を切り、rayon をシングルスレッドに固定する |
| symphonia(薄い再生 CLI) | 差し替え・転移候補 | f32 の IMDCT / フィルタバンクの内側ループが長く VF・interleave・unroll の余地が最大。ただし FP の reduction 部分は §6.2 の `dot_f64` と同じ理由で射程外の可能性があるので、着手時に remark で確認する。ビルドはやや重い |

除外: ripgrep、simd-json、blake3、base64、bytecount(手書き SIMD 済み)、I/O 律速の CLI。

zopfli と jaq の2本で §1.3-5 の転移証拠は揃う。oxipng / symphonia は、jaq がフラットだった場合の差し替え先、または余力がある場合の3本目。対象を降ろす判断はその対象の Stage 0 の終わりに1回だけ行い、理由を `results.md` に残す。

## 7. Stage 1: グローバル plan(plugin 無し)

Jev が PGO 基準の上に重ねるビルド全体のコンパイラ設定を1つ選ぶ。これだけで「オプションを付けたら速いバイナリ」の体験、評価手順、Jev 接続、費用測定が end-to-end で回る。

- **候補集合**: §6.3 で remark diff か実測のどちらかを動かしたノブの単独設定と、その少数組合せ。`KEEP_DEFAULT` を含めて 255 以下。候補の説明にはノブの意味と方向を書き、掃引の実測値は書かない。
- **Jev への入力**: CPU 情報、remark 分類の集計(何個のループが cost で見送られたか等)、候補集合、および**remark が `cost` 理由を出したループを含む関数のソース**。Stage 1 は plugin 無しで完結するので hotness はまだ無い。hotness による順位付けはしない(件数が多い場合は remark の出現順で上限を切り、切ったことを記録する)。関数の特定方法は次項。製品経路(§12 `jev-opt build`)では手順 (2) の dump が先に走るので、そこでは hotness 上位で並べ替えた同じ関数集合を渡してよい。この差は `jev-plan.json` の `answer_ref` に入力の出どころとして記録する。
- **関数の特定は機械語から行う(23.1.1 の実測を受けた変更)**。採用したテキスト remark には DebugLoc(`file:line:col`)はあるが**関数名が無く**、構造化フィールドも無い(関数名を持つ YAML は fat LTO 段で空。§3)。しかもインライン後のイテレータループの DebugLoc は `library/core/src/slice/iter/macros.rs` など std 側を指すので、**「remark の DebugLoc → 関数名」は直接には成立しない**。代わりに次の手順で帰属させる。
  1. strip 前・debuginfo=1 のバイナリの DWARF 行テーブル(`llvm-dwarfdump --debug-line`、または `objdump --dwarf=decodedline`)を引き、remark の `file:line` に対応するアドレス集合を得る。
  2. 各アドレスを `addr2line -i -f -p -C -e <bin>` でインライン鎖に展開し、**最外の(対象 crate 側の)関数**に帰属させる。シンボルは v0 mangling なので `-C` か `rustfilt` で復元する。
  3. 同じ std の `file:line:col` は**バイナリ内の複数のインライン実体に共有される**(std 自身のループも含む)ので、帰属の結果は1つの関数ではなく**候補集合**になる。同一 DebugLoc の remark 行の結論が全て同じ(例: 全て「vectorized, VF 4」)なら候補集合の全員に帰属させ、結論が割れていれば `ambiguous` として記録し件数を出す。remark 行どうしを個別のインライン実体に対応付ける手がかりはテキストには無い。
  toy ではこの方式の原型が `scripts/toy_loop_attribution.sh`(`toy::main` の全命令を歩いてインライン鎖を解き、toyloops の関数ごとに分類する)。**Stage 2 の plugin dump は IR を直接読むので、site 列挙と hotness はこの問題の影響を受けない**(影響を受けるのは remark 分類の書き戻しだけ。§8.3)。
- **アーム**: A = PGO 基準、B = PGO + 決定的 selector(測定を見ない事前登録規則。例: 「maximize-bandwidth を on にする」1本)、C = PGO + Jev、oracle = 訓練ワークロード上の掃引最良(これも PGO 込み)。**4アームすべてが同じ `merged.profdata` を `-Cprofile-use` で使い、訓練実行は追加で行わない。** 掃引は訓練ワークロードでのみ行い、holdout は4アーム + 参考アーム R(§9)を一度だけ測る。
- **判定**: C − A、C − B、C / oracle 比。C − A が最小効果量を超えなければ第2段階に進む前に候補集合と入力を見直す(1回まで)。

## 8. Stage 2: site plan(plugin あり)

### 8.1 plugin

- **モード**: 環境変数 `JEV_MODE=off|dump|apply`、`JEV_PLAN=/abs/jev-plan.json`、`JEV_PLAN_SHA=<sha256>`(読み込んだファイルのハッシュと不一致なら即エラー)、`JEV_REPORT_DIR=/abs/dir`、`JEV_PGO_PROFILE_SHA=<merged.profdata の sha256>`(dump では `sites.json` に書き、apply では `basis.pgo_profile_sha` と照合して不一致なら即エラー)。加えて module の `!llvm.module.flags` に `ProfileSummary` が無ければ `-Cprofile-use` が抜けているので、両モードともエラーで止める。`-Cllvm-args` 経由で plan を渡さない。plugin の dlopen はコマンドライン解析の後なので、plugin が登録した cl::opt には値が入らない。
- **extension point**: 第1候補は `registerVectorizerStartEPCallback`。inlining と loop canonicalization の後、LoopVectorize の直前で、site 照合と metadata 付与を1本の FunctionPass で行う。代替は `LoopOptimizerEndEP` / `OptimizerEarlyEP` / `FullLinkTimeOptimizationEarlyEP`。**どれを使うかは決め打ちせず、probe plugin(§13 day-1)の実測で固定する。**
- **fat LTO の2段**: rustc は crate ごとの pre-link パイプラインとマージ後の LTO パイプラインの2回 module 最適化を走らせる。どちらで vectorize が起きるかは probe のログと `-Csave-temps` の bitcode の `llvm.loop.isvectorized` 件数で確定する。設計はどちらに転んでも壊れないよう、次の冪等性で解く。
- **冪等性(二重適用防止の主手段)**: 付与前に対象 `!llvm.loop` を走査し、付けようとしているキーが既にある、`llvm.loop.isvectorized` がある、自前マーカ `jev.applied` がある、のいずれかなら何もせず理由付きで report に記録する。「最初に到達した段で適用し、以降はスキップ」。`llvm.loop.isvectorized` が既に立っているループは必ずスキップし、その件数を report のトップレベルに出す(EP が遅すぎたことの一次診断)。`!llvm.loop` 内の未知エントリは LLVM が無視するので `jev.site` / `jev.applied` を同居させられる。`llvm.loop.` 接頭辞は使わない。
- **dump モードの hotness**: FunctionAnalysisManager から `BlockFrequencyAnalysis` を要求し、ループヘッダの `getBlockProfileCount()`(`!prof function_entry_count` でスケールした絶対カウント)を読む。関数相対の `getBlockFrequency` は関数をまたいで比較できないので使わない(診断値としてのみ記録)。解析を要求しても変換はしないので `PreservedAnalyses::all()` のままでよい。
- **付与するもの**: loop metadata のみ。`vectorize.enable`、`vectorize.width`、`interleave.count`、`vectorize.predicate.enable`、`unroll.count`、`unroll.disable`、`distribute.enable`。`PreservedAnalyses::all()` で返す。関数属性は付けない。
- **report**: 共有1ファイルに追記しない。`$JEV_REPORT_DIR/<module-id>-<stage>-<pid>.json` を1モジュール1ファイルで書き、CLI がマージする。pre-link 段は複数スレッドで並行するため。
- **ビルド**: LLVM ライブラリを一切リンクしない(静的リンクすると cl::opt 二重登録で dlopen 時に abort)。`-fPIC -shared -fno-rtti -fno-exceptions -DNDEBUG -std=c++17`。ヘッダは `rustc -vV` の LLVM メジャーと同じ upstream tarball(この pin では **LLVM 23.1**)から `cmake -S llvm -B b -DLLVM_TARGETS_TO_BUILD=X86 -DLLVM_ENABLE_ASSERTIONS=OFF` + `ninja -C b intrinsics_gen` で生成ヘッダだけ作る(ビルドしない、数分)。
- **gate 0 は実施済み**(results.md Day 0 §2)。この nightly は libLLVM を `librustc_driver` に静的リンクしておらず、`librustc_driver-*.so` が `libLLVM.so.23.1-rust-1.100.0-nightly` を動的リンクしている。したがって **gate 0 のシンボルは `librustc_driver` ではなく `libLLVM.so` に対して読む**。実測値は次の3つ。
  - `_ZN4llvm11PassBuilder` **63 件**(`librustc_driver` 側は 15 件)。plugin ホストとして成立する。
  - **`DisableABIBreakingChecks` が定義されている** = このLLVM はアサーション OFF でビルドされている。plugin 側も ABI breaking checks を有効にせずビルドし(上の `-DLLVM_ENABLE_ASSERTIONS=OFF` と揃う)、シンボルは `libLLVM.so` に対して解決させる。
  - `_ZNSt` **1841 件** = libstdc++ のシンボルが plugin 境界をまたぐ。plugin は互換な libstdc++ でビルドする。
- **off 等価性**: plugin 未ロード vs ロード + `JEV_MODE=off` で `.text` セクションのハッシュ一致を必須ゲートにする。binary 全体のハッシュは build-id で必ず異なる。**両辺は debuginfo を含む全ビルド条件を揃える**(この toolchain では debuginfo が変わると `.text` が変わるため。§3)。

### 8.2 site key

**生成器は plugin の dump / apply 共通コードのみ。** PGO 基準ビルド(`-Cprofile-use` + Stage 1 の global_flags)を `dump` モードで行い、全ループの site レコードを出す。apply ビルドは同じ profdata・同じ global_flags なので inlining が一致し、dump で得た site key と inline chain はそのまま解決する。plan に書いた key は、同じ生成器が apply 時に再計算するので「解決できない」は原理的に起きない(F面の属性を混ぜない限り)。hotness も同じ dump が同じループに対して直接書くので、外部プロファイラとの突合という工程そのものが無い。

key の構成(この順で連結し sha256 の先頭16桁 + 可読サフィックス):

1. `owner_fn`: そのループを最終的に含む関数の `DISubprogram::getLinkageName()`(v0 mangled)。v0 は単相化引数が名前に入るので generic は自動的に区別される。
2. `inline_chain`: ループ本体のいずれかの命令の `DILocation` → `inlinedAt` チェーンから得た linkageName 列(外→内)。closure は独立の DISubprogram を持つのでそのまま要素になる。全命令に location を要求しない。
3. `leaf_loc`: 最内フレームの (file, line, col)。イテレータチェーンでは `core::iter::*` になるのが正常。
4. `loop_fingerprint`: ループ本体の全命令の (leaf linkageName, line) のソート済み集合のハッシュ。「三番目のループ」型のインデックスは使わない。
5. `depth`: ループ木の深さのみ。

apply 時に同じ key が2つ以上に解決したら `ambiguous`、0個なら `vanished`。どちらも別のループへ移さず記録する。発生件数そのものが設計の健全性メトリクス。

**hotness は dump が同時に書く。** 各 site について `header_count`(ループヘッダの `getBlockProfileCount()`)、`body_inst_count`(ループに属しサブループには属さないブロックの命令数。入れ子で二重計上して share の合計が 1 を超えるのを防ぐ)、`score = header_count × body_inst_count` を `sites.json` に出し、全 site の score 合計ではなく**全関数の全ブロックについて `プロファイルカウント × 命令数` を合計した `total_score`** をトップレベルに書く。`share = score / total_score`。エントリカウントが無い関数は `header_count = null` として hotness 未帰属に数え、その件数も出す。

**hotness は単一の段の dump からだけ取る。** dump は `<module-id>-<stage>-<pid>.json` を1モジュール1ファイルで出すので(§8.1)、prelink と LTO の両方を足すと同じループを二重計上し、`total_score` の意味が壊れる。§13 の probe で選んだ適用段(`apply_stage: "first_match"` が実際に当たる段)の dump だけを hotness の出どころとする。LTO 段で発火するなら1モジュール・最終 inlining・1つの total でそのまま完結する。pre-link 段に落ちる場合(§13 の失敗時分岐)は CLI が crate ごとのモジュール総和を取って `total_score` とし、その旨を `sites.json` の `hotness_stage` に記録する。サンプル数を稼ぐための反復や最小実行時間の要件は無い(profdata は Stage 0 の訓練実行1回から来る)。

### 8.3 候補 site の絞り込みと不均質性ゲート

前提: Stage 2 の全アーム(基準、selector、Jev、oracle-probe)は**すべて PGO 込み・同一 profdata(`-Cprofile-use`)・同一 global_flags(Stage 1 で選ばれたもの)**でビルドし、dump も同じ条件で取る。これで site ヒントの効果だけを分離でき、かつ dump と apply で inline chain が一致するので site key が解決する。記事の見出しになる主比較 (PGO + Jev) − PGO は、Stage 1 + Stage 2 を合わせたビルドと、同じ profdata で作った PGO 基準ビルドとの差。

1. hotness は dump が既に書いているので、CLI は remark 分類だけを `sites.json` に書き戻す。**テキスト remark と site レコードの結合キーは `leaf_loc`(file, line, col)1つだけ**である(採用した remark 機構に関数名が無いため。§3、§7)。同じ `leaf_loc` に複数の site が当たることはインライン後のイテレータループでは普通に起きるので、その場合は remark の結論が全て同じならその全 site に同じ分類を書き、割れていれば `remark_reason: "unknown"` とし、衝突した site 数を `sites.json` のトップレベル(`remark_ambiguous_sites`)に出す。理由が `legality` / `unsupported` に**一意に**分類された site は **Jev に見せる前に除外**する。ヒントで変わらないものに問い合わせるのは費用の無駄。`unknown` の site は除外しない。
2. `share`(§8.2)上位 N(初期 20)を候補 site とする。候補 site の share 合計 S と理論上限 1/(1−S) を報告し、上限 − 1 < 最小効果量の2倍なら「対象選定段階で null」として記録し、Jev を呼ばない。**この S は cycle の実測ではなく「プロファイルカウント × 命令数」による推定**であり、命令ごとのレイテンシ、キャッシュミス、分岐予測失敗、ベクトル化済みブロックの実コストを反映しない。したがって 1/(1−S) は cycle ベースの上限より楽観にも悲観にも振れうる粗い目安で、桁の判断(「候補が全体の数%しか押さえていない」)にだけ使い、効果量の予測には使わない。これが perf を主経路から外した代償で、境界付近(上限 − 1 が最小効果量の2〜3倍)なら perf / callgrind で一度だけ裏を取ってよい。
3. **不均質性ゲート**(実験専用モード、丸1日): 上位 K(6〜10)site × 設定 M(4〜6)の手書き plan で単一 site 変種をビルドし、`best_uniform`(一律最良)と `oracle`(site ごと最良)の集計速度比を出す。oracle − best_uniform < 最小効果量の2倍なら、この対象では per-site 判断そのものに価値が無いので Jev を呼ばず、対象差し替えか Stage 1 の結果のみで報告する。
4. ゲートを通ったら、Jev への問い合わせに進む。oracle の値は Jev の入力に入れない。

### 8.4 Jev への問い方

- 候補 site ごとに Choice を1回。候補 = `KEEP_DEFAULT` + その site に適用可能な recipe(初期は幅 8/16/32、interleave 1/2/4、predicate on、unroll 2/4/8、distribute on の組合せから、§6.3 で動いた次元だけ、最大 8〜12 個)。
- 入力: その関数のソース、site の位置(可読サフィックス)、hotness、trip count(取れれば)、remark の理由分類、CPU 情報。
- 決定的 selector(アーム B)は同じ候補 site リストと同じ recipe 集合に対し、測定を見ない事前登録規則で選ぶ(例: 「i8 reduction なら幅 32、それ以外 KEEP_DEFAULT」)。
- `forced: true` の recipe(幅の明示指定)はコストモデルを迂回する force である旨を plan に記録する。合法性は LoopVectorize の legality 解析がそのまま守るので、ヒントは意味の主張を捏造しない。

### 8.5 schema

`sites.json`(plugin dump → CLI):
```
schema_version, toolchain{rustc, llvm, plugin_abi, mangling}, target{triple, cpu, features},
build_flags_sha, pgo_profile_sha,
hotness_stage: "prelink"|"lto",   // hotness を取った段。混ぜない(§8.2)
total_score: int,          // その段の全関数の全ブロックの (プロファイルカウント × 命令数) の合計。share の分母
unattributed_sites: int,   // entry count が無く header_count=null になった site 数
remark_ambiguous_sites: int, // leaf_loc が衝突して remark 分類を一意に決められなかった site 数(§8.3)
sites[]: { key, owner_fn, inline_chain[], leaf{file,line,col}, loop_fingerprint, depth,
           stage: "prelink"|"lto", already_vectorized: bool,
           trip_count: int|null,   // PGO の branch weight 由来。LLVM も同じ値を見ている
           has_calls, has_reduction,
           hotness{ header_freq: int|null,      // 診断用。関数相対の getBlockFrequency
                    header_count: int|null,     // getBlockProfileCount(header)。絶対カウント
                    body_inst_count: int,       // ループに属しサブループには属さないブロックの命令数
                    score: int|null,            // header_count × body_inst_count
                    share: float|null },        // score / total_score。すべて plugin が dump で書く
           remark_reason: "legality"|"unsupported"|"cost"|"unknown"|null }  // CLI が埋める
```

`jev-plan.json`(CLI → plugin、これが lock):
```
schema_version, plan_id(内容の sha256),
basis{ sites_sha, pgo_profile_sha, toolchain, target, build_flags_sha, global_flags: [str] },
selector: "jev-choice"|"keep-default"|"deterministic-<name>"|"oracle-probe",
entries[]: { key, family: "H01"|"H03"|"H04"|"H05"|"H10",
             loop_md{ vectorize.enable, vectorize.width, interleave.count, vectorize.predicate.enable,
                      unroll.count, unroll.disable, distribute.enable },   // 各 null 可
             forced: bool, apply_stage: "first_match",
             answer_ref }   // "<run-id>.jsonl#<行番号>"。Jev ログの当該行を指す。入力の出どころ(§7)は
                            // その行の request に丸ごと入っているので、別フィールドは持たない
budget{ max_sites, max_code_growth_ratio }
```

`apply-report-*.json`(plugin → CLI):
```
plan_id, module_id, stage, already_vectorized_total,
results[]: { key, outcome: "consumed"|"attached"|"vanished"|"ambiguous"|"already_vectorized"|"skipped_idempotent", reason }
```

`consumed` の一次証拠は remark ではなく、変換後 IR での metadata の消費(`llvm.loop.isvectorized` の出現等)。

プロファイルの sha は `basis.pgo_profile_sha` 1つだけ。`-Cprofile-use` に渡す `merged.profdata` の sha256 であり、hotness もここから来るので別系統のプロファイル hash は持たない。**`pgo_profile_sha` は必須で `null` を許さない**(基準が常に PGO 込みで、hotness の出どころでもあるため)。`basis` のいずれかが現在のビルド条件と不一致なら plugin はエラーで止まる(警告にしない)。

## 9. 参考比較: 素の release ビルドとの差

主比較 (PGO + Jev) − PGO とは別に、「`cargo build --release` を `jev-opt build` に置き換えるだけでどれだけ速くなるか」という体験の数値を1つ出す。

- **参考アーム R**: 対象リポジトリの release profile をそのまま使い、`jev-opt` の上書きを一切しないビルド。`-Ctarget-cpu=native` も fat LTO も `codegen-units=1` も PGO も付けない。対象の `Cargo.toml` が既に `lto` や `codegen-units` を設定していればそれが効くので、**実効の opt-level / lto / codegen-units を `results.md` に明記する**(この数値はそれに強く依存する)。
- 測定は holdout の同じ interleaved 実行に1アーム足すだけ。専用の手順も専用の plan も作らない。
- **表示規則**: この差には PGO・LTO・native の寄与が含まれるので、Jev の効果とは必ず分けて出す。「`jev-opt build` に置き換えると X% 速い。そのうち Jev の寄与は主比較の Y%」という形で並べ、X を Jev の効果として語らない。

## 10. 評価手順(全 Stage 共通)

- **主指標**: end-to-end wall time。ケースごとの速度比を事前固定重みの幾何平均で集計し、交互実行の pair を単位に bootstrap で 95% 信頼区間を出す。
- **ノイズフロア**: holdout の前に基準バイナリを2ラベルとして同一手順で測る A/A 実行を必須とし、その信頼区間半幅をノイズフロアとする。
- **最小効果量**: max(2 × A/A の半幅, 3%)。集計速度比の信頼区間下限がこれを超えない限り「改善」と書かない。
- **測定条件**: `taskset` で単一 CCD 内の物理コアに固定し SMT 兄弟を空ける。構成順序をラウンドロビンで交互化する(連続で流すと後半が熱で遅くなる)。ASLR は有効のまま。n(初期 50)、warmup(初期 5)、trimming 規則を holdout 前に config で凍結し、事後変更した run は無効。
- **holdout は凍結後1回のみ**。結果を見てから候補・selector・重み・n を変えた場合は新 seed で再生成し、全実行履歴を `results.md` に列挙する。訓練ワークロード(PGO の訓練実行、掃引、不均質性ゲート)と holdout は分離する。holdout のケースは profdata の生成に一切使わない。
- **退行**: ケース集合と重みは事前凍結し、退行ケースは集計に含めたまま最大値と件数を `results.md` 冒頭に置く。試した全アーム・全 plan 世代を列挙し、採用しなかったものも残す。
- **帰属**: 基準と Jev の最終バイナリをシンボル単位で正規化 diff し、変化した関数を「plan の site を含む / 含まない」に分類して件数を報告する。plan の site に機械語差分が無ければ時間差は noise として扱う。`apply-report` の consumed / planned が `min_decision_realization`(初期 0.7)未満の run は性能主張の根拠に使わない。
- **事後帰属(任意)**: 主比較で差が出た場合に限り、`perf`(無ければ `valgrind --tool=callgrind`)で基準バイナリと Jev バイナリのシンボル別 cycle(callgrind なら Ir)を取り、差分が plan の site を含む関数に集まっているかを見る。**これが perf の唯一の用途**で、hotness の取得にも site 選定にも使わない。perf も callgrind も無ければこの節を省略し、`results.md` に「事後帰属は未実施」と書く。主張の成否はこの節に依存しない。
- **正しさ**: 上流テストと holdout の出力一致。両 variant で同じ方法で stdout を破棄し、正しさ検査と時間計測を分ける。
- **コスト**: ビルド時間(fresh / cache 別、n ≥ 3 の中央値)には**計装ビルド・訓練実行・`llvm-profdata merge` の時間を含める**(`jev-opt build` 1回の体感時間がこれを含むため)。Jev の呼出し回数(global 1回 + 上位 N site 各1回で二十数回)、待機時間、費用を事前登録した予算と照合する。
- **記録**: `run-manifest.json` に toolchain、CPU、flags、config の SHA、データ hash、`merged.profdata` の sha256(全アームで同一であることの証拠)、plan_id、binary の `.text` hash、時間サンプル、report、費用をまとめる。`results.md` は記録から生成し、欠測を成功値で埋めない。

## 11. 設定ファイル `jev-opt.toml`

```toml
[project]
# 対象の切り替えはこの [project] と [workloads] の差し替えだけで済む。
# toy → zopfli → jaq の順に、repo / bin / [workloads] を入れ替えて同じ手順を回す(§6.4)。
# コードにも他の節にも対象依存の分岐を置かない。
repo = "…/jaq"            # 対象。切り替え時はここだけ変える
bin = "jaq"
target = "x86_64-unknown-linux-gnu"
profile_env = { OPT_LEVEL = "3", LTO = "fat", CODEGEN_UNITS = "1", DEBUG = "1", PANIC = "unwind" }  # CARGO_PROFILE_RELEASE_*
fixed_rustflags = ["-Ctarget-cpu=native", "-Csymbol-mangling-version=v0"]

[pgo]
profraw_dir   = "…/pgo/<target>/profraw"          # -Cprofile-generate の出力先(絶対パス。対象ごとに分ける、§12)
profdata      = "…/pgo/<target>/merged.profdata"  # -Cprofile-use に渡す。全アーム共通
llvm_profdata = ""                       # 空なら pin した toolchain の llvm-tools-preview から解決
reuse         = true                              # 既存 profdata があれば計装ビルドと訓練実行を省略する

[artifacts]
remarks_dir = "…/remarks/<target>"        # テキスト remark を含むビルドログ(§3、§12)
jev_log_dir = "…/artifacts/jev-log/<target>"  # Jev の request / response の JSONL(§5)

[workloads]
training = ["cases/train/*.json"]   # PGO の訓練実行にもこれを使う(掃引、不均質性ゲートと同じ集合)。hotness もこの profdata 由来
holdout  = ["cases/holdout/*.json"] # PGO の訓練には絶対に使わない
weights  = { … }          # holdout 前に凍結

[evaluation]
repetitions = 50
warmup = 5
trim_rule = "none"
min_effect_size = "max(2*aa_halfwidth, 0.03)"
allowed_regression_per_case = 0.02
cpu_pin = "0-7"           # 単一 CCD
min_decision_realization = 0.7

[budget]
max_sites = 20
max_requests_per_build = 40   # 実際は global 1 回 + 上位 N site 各 1 回で二十数回
request_timeout_s = 60
api_cost_budget_usd = 5.0
max_code_growth_ratio = 1.10

[selector]
arm_b_rule = "…"          # Jev の結果を見る前に書く

[jev]
base_url = "https://ai-gateway.vercel.sh/typesafe"   # Vercel AI Gateway の TypeSafe 互換 API
endpoint = "/v1/systemone"                             # POST。GET /v1/models で利用可能モデルを確認
model = "typesafe-ai/jev"
api_key_env = "AI_GATEWAY_API_KEY"                     # 値は .env か環境変数。リポジトリには置かない
```

8 セクション。凍結すべき値はすべてここにあり、SHA を run-manifest に記録する。

## 12. CLI

| コマンド | 内容 |
|---|---|
| `jev-opt doctor` | toolchain 記録(解決後の `rustc -vV` をそのまま記録し、LLVM メジャーを確認)、gate 0(§8.1。`librustc_driver` ではなくそれが動的リンクしている `libLLVM.so` に対して `nm -D` を読む)、`llvm-tools-preview` と `llvm-profdata` の存在確認(LLVM メジャーが rustc と一致すること)、`llvm-knobs.json` 生成、テキスト remark の取得確認(`-pass-remarks*` の行がビルドログに出ること)、`-Zllvm-plugins` の probe、Jev 疎通。**`-Zllvm-plugins` の probe は codegen を伴う emit(`--emit=obj` など)で行う。** `--emit=metadata` ではフラグは受理されるが plugin を dlopen しないので、存在しない `.so` を渡しても成功してしまい、probe にならない(results.md Day 0 §1) |
| `jev-opt headroom` | Stage 0: A/A + 最小効果量確定、グローバル掃引、打ち切り判定 |
| `jev-opt baseline` | **PGO 基準を丸ごと作る**: 計装ビルド(`-Cprofile-generate`)→ `[workloads] training` の訓練実行 → `llvm-profdata merge` → `-Cprofile-use` で PGO 基準ビルド(第2段階では plugin dump モード + remarks)→ `.text` 等価性検査 → dump が書いた `sites.json`(hotness 込み)の回収 → remark 分類の書き戻し → coverage 判定。外部プロファイラは呼ばない。`--reuse-profdata`(既定 on)で既存 profdata があれば計装と訓練をスキップする(掃引や再 dump で訓練を繰り返さないため)。専用の `jev-opt pgo` は作らない。工程が1コマンドに収まる方がシンプルで、「訓練は1回」が構造的に保証される |
| `jev-opt plan` | Jev または selector で `jev-plan.json` を出力。`--selector jev-choice|keep-default|deterministic-<name>|oracle-probe`、`--global`(Stage 1)/ `--sites`(Stage 2) |
| `jev-opt build` | 製品経路。利用者は `cargo build --release` の代わりにこれ1つを打つ。内部で次を一括実行する: (1) 計装ビルド → 訓練実行 → `llvm-profdata merge` → `merged.profdata`(`baseline`)、(2) その profdata で PGO 基準ビルド(plugin dump モード + remarks)。dump が `sites.json` に hotness(PGO 分岐重み由来)まで書く、(3) ビルドログのテキスト remark を読んで理由分類を `sites.json` に書き戻す(結合キーは `leaf_loc`、§8.3)、(4) `plan --global` で Jev に1回問い合わせて global_flags を決める。製品経路ではここで既に dump が済んでいるので、§7 の「remark `cost` 理由の関数」ではなく hotness 上位の関数ソースを渡す、(5) `plan --global` が `KEEP_DEFAULT` 以外を選んだら**同じ profdata + 新しい global_flags で再 dump**(`baseline --with-global --reuse-profdata`)。plugin は `basis.global_flags` の不一致で止まるので、条件は「inlining が変わったか」ではなく「global_flags が変わったか」で判定する、(6) `plan --sites` で上位 N site に各1回問い合わせ、(7) 同じ profdata + 同じ global_flags + plan で PGO + Jev ビルド。Jev への問い合わせは global 1回 + site N 回の二十数回。`apply-report` を回収し実現率を判定する。plugin は `basis.global_flags` / `basis.pgo_profile_sha` と現在のビルド条件が不一致なら止まる |
| `jev-opt bench` | 全アーム、interleaved、bootstrap、帰属 diff、`results.md` |

cargo への組み込みは「CLI が環境変数を組んで `cargo build --release --target …` を exec する」だけ。`.cargo/config.toml` は使わない(RUSTFLAGS 系と上書き競合し、variant 切替で状態が残る)。

```
CARGO_TARGET_DIR=target/<variant>
CARGO_PROFILE_RELEASE_LTO=fat CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 CARGO_PROFILE_RELEASE_DEBUG=1 …
CARGO_ENCODED_RUSTFLAGS="<fixed_rustflags>\x1f-Cprofile-use=/abs/pgo/<target>/merged.profdata\x1f<Stage 1 の global_flags>\x1f-Zllvm-plugins=/abs/libjevplugin.so\x1f-Cllvm-args=…"
JEV_MODE=apply JEV_PLAN=/abs/jev-plan.json JEV_PLAN_SHA=<sha> JEV_REPORT_DIR=/abs/reports/<variant>
JEV_PGO_PROFILE_SHA=<merged.profdata の sha256>
cargo build --release --target x86_64-unknown-linux-gnu
```

**対象ごとのディレクトリ分離と toolchain の明示**(day 0 で判明した運用上の注意):

- 成果物は対象ごとのサブディレクトリに分ける: `pgo/<target>/`(profraw と `merged.profdata`)、`remarks/<target>/`(テキスト remark を含むビルドログ)、`artifacts/jev-log/<target>/`(Jev の JSONL、§5)。day 0 の toy スクリプトはリポジトリ直下の `pgo/` を `rm -rf` するので、対象を複数回すとそのままでは衝突する。
- **`jev-opt` が spawn する cargo / rustc の環境に `RUSTUP_TOOLCHAIN=nightly-2026-09-21` を明示的に入れる。** `rust-toolchain.toml` はこのリポジトリ配下にしか効かず、zopfli や jaq は別ディレクトリにあるので、対象側の `rust-toolchain.toml` か利用者の default が勝ってしまう。pin を信用せず、**解決後の `rustc -vV` を `run-manifest.json` に記録する**。
- Jev への request / response は `artifacts/jev-log/<target>/<run-id>.jsonl` に1行1問い合わせで追記する(`{ts, target, stage, request, response, http_status, latency_ms}`。§5)。`Authorization` ヘッダは記録しない。`jev-plan.json` の `answer_ref` は `<run-id>.jsonl#<行番号>` を指し、`results.md` にこのログへの参照を残す。手で送った見本は `docs/jev-samples/`(git 管理)に置く。

利用者向けの `--jev` オプション(cargo subcommand の薄いラッパ)は、結果が出た後に被せる。

## 13. 実装順序とゲート

各 day は目安。ゲートを通らなければ次に進まず、判定を `results.md` に残す。

**対象**: day 0〜2 は **toy crate と zopfli** で回す(手順の確立と、実プログラムでの Stage 0 / Stage 1 の結果)。**jaq は day 4 以降**、plugin dump が動いて §6.1-4 の 70% ゲートを掛けられるようになってから入る。day 3 の EP 選定と apply 試験は toy 専用。day 4〜6 の Stage 2 は toy(配管の検証)→ zopfli → jaq の順。

**day 0(CLI と plugin は書かない。対象: toy → zopfli)**
1. **済(results.md Day 0 §1)**: nightly を pin。`rust-toolchain.toml` で `nightly-2026-09-21`(rustc 1.100.0-nightly / **LLVM 23.1.1**)。LLVM 22 系の nightly は存在しないので「stable と同じ LLVM メジャー」の pin は断念し、LLVM 内部の記述はこの toolchain で取り直す(§3)。`rustup component add llvm-tools-preview`(`llvm-profdata` がこれに入る)。perf(無ければ callgrind)は**任意**で、§10 の事後帰属にしか使わない。無くても day 0〜6 は進む。
2. **済(toy。results.md Day 0 §4)/ zopfli は未**。**PGO 基準を作る**: 計装ビルド(`-Cprofile-generate`、plugin も remarks も無し、`CARGO_TARGET_DIR=target/pgo-gen`)→ `[workloads] training` を計装バイナリで実行 → pin した toolchain の `llvm-profdata merge` → `merged.profdata`。sha256 を記録する(toy は `4a054099…`。訓練実行をやり直してもバイト一致した)。**この profdata は以降の全アーム(基準・selector・Jev・oracle・掃引の全構成)で共有し、訓練実行は二度と行わない。**
3. **済(toy。results.md Day 0 §4)/ zopfli は未**。`-Cprofile-use=<merged.profdata>` を付けて PGO 基準ビルドが通ることと、正しさ検査(上流テストと出力一致)を確認する。`-Cllvm-args=-pgo-warn-missing-function` を明示して警告件数を数える(toy は 0 件)。インタプリタ層 share のゲート(§6.1-4)は plugin dump を要するので、jaq に進む day 4 以降に掛ける。toy と zopfli には掛けない。
4. **済(toy。results.md Day 0 §3, §6)/ zopfli は未**。失格フィルタ(memchr / SIMD、§6.1-2)、テキスト remark の取得確認(YAML ではない。§3)。
5. A/A 実行(PGO 基準バイナリで)→ 最小効果量。群 0〜3 の掃引(**全構成に同じ `-Cprofile-use` を付ける**。群 1 が動かなくても群 2〜3 まで回す。inline 判断は群 2 で最も余地がありそうだが、PGO が既に inline を触っている点に注意)。toy では手順が通ることだけを見て、A/A と打ち切り規則は zopfli から適用する。
6. 群 4 の掃引、§6.3 の打ち切り規則で判定(zopfli に対して)。対象を降ろす判断はここで1回だけ。

day 0 の追加実施分(すべて **済**、results.md Day 0): `targets/toy/` の作成(lib + bin の2 crate、4ループ。§6.4)、**gate 0**(§8.1。`libLLVM.so` に対して実施したので day 3 の項目 9 は再実施しない)、**remark 機構の選定**(§3。3方式を試して `-pass-remarks*` を採用)、**`.text` ハッシュの debuginfo 依存性の確認**(§3。debuginfo 0/1 で不一致)、§6.2 の4ループ所見。**未実施**: A/A とノイズフロア、群 0〜4 の掃引、zopfli 一式(項目 5・6)。

**day 1〜2(Stage 1、Rust のみ、対象: toy → zopfli)**
7. `jev-opt` の doctor / headroom / baseline / plan --global / build / bench。Jev 接続。`baseline` に PGO の計装 → 訓練 → merge を内包する。
8. toy で 7 の end-to-end を1周させて配管を確認してから、zopfli で 4アーム(A / B / C / oracle、すべて PGO 込み・同一 profdata)+ 参考アーム R(§9)を holdout で1回測り、C − A、C − B、C / oracle、R との差を報告。

**day 3(probe、C++ 開始、対象: toy。gate 0 は day 0 で実施済み)**
9. **済(results.md Day 0 §2)**: gate 0。この nightly は libLLVM を共有ライブラリで持つので、`librustc_driver-*.so` ではなくそれが動的リンクしている `$(rustc --print sysroot)/lib/libLLVM.so.23.1-rust-1.100.0-nightly` に対して `nm -D` を読む。結果は `_ZN4llvm11PassBuilder` 63 件(> 0)、`DisableABIBreakingChecks` が定義(アサーション OFF)、`_ZNSt` 1841 件(libstdc++ が plugin 境界をまたぐ)。plugin の ABI マクロと libstdc++ をこれに合わせる(§8.1)。
10. LLVM **23.1** の upstream tarball からヘッダを生成(§8.1)。
11. **probe plugin**: 全 EP callback を登録し、発火時に EP 名 / module / 関数数 / `isvectorized` 件数をログ。LLVM ライブラリ非リンク。
12. **toy crate**(§6.4 の検証用対象。lib を依存にした bin の2 crate 構成で、lib 側に素朴な `for` ループと `iter().filter().count()` を置き bin から呼ぶ。day 0〜2 で既に Stage 0〜1 を通してある同じ crate を使う)を lto=off / thin / fat / **fat+PGO** でビルドし、「どの EP がどの段で発火するか」の表を作る。**これが EP 選定の唯一の根拠。** `fat+PGO` 構成では次の4点を必ず確認する: (a) 選んだ EP が `-Cprofile-use` と共存し、PGO の profile 適用より**後**で発火すること、(b) 同じ profdata で dump ビルドと apply ビルドを行い、**dump で得た site key が apply で全件解決する**こと(`vanished` / `ambiguous` が 0)、(c) profile に照合できた関数数(または `-pgo-warn-missing-function` の警告件数)が dump ビルドと apply ビルドで一致すること、(d) `basis.pgo_profile_sha` を意図的に食い違わせると plugin がエラーで止まること。(a)(c) はこの day 3 で確認する。(b)(d) は site key 生成と dump モードを要するので、項目 15 の時点で同じ toy crate に対して行う。(b)(c) が「訓練実行1回・profdata 共有」設計の実証であり、取れなければアームごとの PGO サイクルに戻す。
13. apply 試験: toy の特定関数の全ループに `vectorize.width=8` をハードコードし、`--emit=llvm-ir` の metadata、objdump の ymm 変化、テキスト remark で consumed を三重確認。
14. off 等価性: `.text` ハッシュ一致。

**失敗時の分岐**
- gate 0 が 0 → **この pin では起きないことが確定した**(results.md Day 0 §2)。`[llvm] link-shared = true` 相当(libLLVM を共有ライブラリとして配る)が既に出荷時の構成で、`libLLVM.so` に `PassBuilder` シンボルが 63 件ある。したがって **rustc のソースビルドは不要**。この分岐を再評価するのは pin を変えたときだけ。
- dlopen で abort: LLVM を静的リンクしている。リンク指定を全部外す。
- LTO 段でどの EP も発火しない: pre-link 段で適用(冪等性設計がそのまま使える)。pre-link で `isvectorized` が既に立っているなら、`lto=thin, cgu=1` を基準にする案を検討し、基準変更を `results.md` 冒頭に明記。それも不可なら Stage 1 の結果のみで報告。
- `.text` 不一致: plugin が off でもパイプラインを変えている。差分関数を特定するまで進まない。

**day 4〜6(Stage 2、対象: toy → zopfli → jaq)**
15. dump モード、site key、hotness(`BlockFrequencyAnalysis` の `getBlockProfileCount` × 本体命令数、§8.2)、`sites.json`、remark 分類の書き戻し、legality 除外、coverage 判定。dump は PGO 基準ビルド(`-Cprofile-use` + Stage 1 の global_flags)で取る。まず toy で項目 12 の (b)(d) と、hotness が既知のホットループに集中すること(toy はどのループが回るか自明なので、これが hotness 定義の検算になる)を確認してから zopfli に進む。
16. jaq を対象に加える。**ゲートを先に掛ける**: jaq の計装 → 訓練 → profdata → PGO 基準ビルド(dump モード)まで進めた時点で、dump の hotness から §6.1-4 のインタプリタ層 share を出す。70% 超ならここで jaq を本命から降ろし(掃引の1.5時間を使う前に)、zopfli を主対象として報告する。通れば jaq で Stage 0(掃引・打ち切り判定)→ Stage 1 → Stage 2 を回す。
17. 不均質性ゲート(手書き plan、K × M ビルド。全構成 PGO 込み・同一 profdata)。通らなければ Jev を呼ばず報告。
18. plan --sites(Jev / selector)、build、bench。3アーム + oracle + 参考アーム R(§9)を holdout で1回。zopfli と jaq の両方で回し、§1.3-5 の転移証拠にする。

## 14. スコープ外(別テーマとして扱い、ヒントの成功と混同しない)

- HashMap を線形探索に変える、JSON 用 kernel を手書きする、SWAR を明示的に生成する、といった意味変換。
- inline / noinline / cold / optsize 等の関数属性。他 site の inline chain を変えて site key を壊すため、第2段階の plan に入れない。将来やるなら「属性だけ入れたビルドで dump をやり直す第2世代 plan」として別サイクル。
- パス挿入(unswitch、fusion、interchange 等)、cl::opt しか制御面が無いノブの site 単位適用、AVX-512 幅選択(この機に無い)。
- 34ファミリーのカタログは `work/jev_opt_patterns.md` に将来候補として残す。本仕様は5ファミリーのみ扱う。
- **PGO を使わない静的 Jev**(profile を取らず、全ループについて Jev に問い合わせる方式)。site 数がそのまま問い合わせ回数になり、jaq 規模でも数百〜数千回に達して費用・待機時間が成立しない。本仕様は dump が PGO 分岐重みから出す hotness 上位で「どこを見るか」を絞り、各 site の `KEEP_DEFAULT` で「どこを触るか」を決める。
- マークなし driver の一般化、他言語への展開。Stage 2 の CLI + plugin がその入口であり、汎用 driver を実装済みとは呼ばない。

## 付録: 実装者(Codex)への開始プロンプト

> `jev_opt_spec.md` v0.3 に従って実装する。順序は §13 のとおりで、day 0 は `jev-opt` のコードを書かずに(対象の toy crate と補助スクリプトは除く)手順を実行し、結果を `results.md` に記録すること。各 day の終わりにゲート判定を書き、通らなければ次に進まず報告する。特に day 4 の不均質性ゲートが通らない場合は、実装を進めず判定と根拠だけを返す。day 0 は実施済みで、結果は `results.md` の Day 0 にある。
>
> **基準は PGO 込み**(`O3 + target-cpu=native + lto=fat + codegen-units=1 + PGO`)であり、Jev 版は同じものに Jev のヒントを足したもの。訓練実行は Stage 0 の1回だけで、得た `merged.profdata` を基準・selector・Jev・oracle・掃引の全構成に `-Cprofile-use` で共有する。アームごとの PGO サイクルは回さない。`llvm-profdata` は pin した toolchain の `llvm-tools-preview` 付属のものを使う。主比較は (PGO + Jev) − PGO、副次は (PGO + Jev) − (PGO + 固定規則)、参考値として素の `cargo build --release` との差(§9)。
>
> **hotness は perf ではなく PGO の分岐重みから取る。** plugin の dump モードが、ループヘッダの `getBlockProfileCount()`(絶対カウント)× ループ本体(サブループを除く)の命令数を hotness score として `sites.json` に直接書く。IP → site の突合も外部プロファイラも主経路には無い。`addr2line` は §7 の Stage 1 remark 帰属(DebugLoc → 関数)と §10 の事後帰属にだけ使い、IP → site の突合には使わない。perf / callgrind は §10 の事後帰属専用で、未導入でも全 day が進む。
>
> **対象の順序は toy crate → zopfli → jaq**(§6.4)。day 0〜2 は toy と zopfli で回し、jaq は day 4 以降に入れる。toy はパイプライン検証専用で性能主張には使わない。対象の切り替えは `jev-opt.toml` の `[project]` と `[workloads]` の差し替えだけで済むようにし、コードに対象依存の分岐を置かない。
>
> **言語方針**(「言語方針」節): ソースコメント、コミットメッセージ、PR 本文、README、CLI のヘルプとログは**英語**。`SPEC.md` と開発ノートは日本語で、開発中はそちらが正本。
>
> **toolchain は `nightly-2026-09-21`(LLVM 23.1.1)に pin してある。** spawn する cargo / rustc には `RUSTUP_TOOLCHAIN` を明示し、解決後の `rustc -vV` を run-manifest に記録する(§12)。remark は `-Cllvm-args=-pass-remarks*` の**テキスト**で取り、ビルドログを成果物として保存する(YAML は fat LTO 段で空。§3)。Jev への request / response は JSONL に全件記録する(§5)。
>
> 作るものは §4 の一覧に限る。broker、proc macro、registry の手書き JSON、cargo subcommand は作らない。plan の受け渡しは環境変数、ビルドは `CARGO_ENCODED_RUSTFLAGS` + 明示 `--target` + variant 別 `CARGO_TARGET_DIR`。LLVM / rustc 内部に関する本仕様の記述のうち、`results.md` の Day 0 に実測が記録されているものはこの toolchain(nightly-2026-09-21 / LLVM 23.1.1)での実測値であり、それ以外は pin 上で確認する検査項目として扱う(断定ではない)。pin を変えたら両方とも取り直す。
>
> 最初に返すもの: **zopfli** に対する day 0 の結果(`merged.profdata` の sha256 と計装ビルド + 訓練実行の所要時間、PGO 基準ビルドが通ったこと、失格フィルタ、テキスト remark の取得可否、A/A の半幅と最小効果量、群 0〜1 の掃引結果と打ち切り判定)。toy の day 0 は `results.md` の Day 0 に記録済み。インタプリタ層の share は plugin dump が要るので day 0 では返さない(jaq を入れる day 4 以降のゲート)。
