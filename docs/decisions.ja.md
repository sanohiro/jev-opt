# 知見と判断の記録(jev-opt)

「何が分かったから、何をする / しないことにしたか」を時系列で残す。数値と再現コマンドは `results.md` にあり、ここではそこへの参照だけ置く。仕様の正本は `SPEC.ja.md`。

書式: **知見**(観測した事実と根拠)→ **判断**(それを受けて決めたこと)→ **影響**(spec のどこが変わったか)。

---

## 2026-09-21

### 1. v0.2 仕様は実装に入れなかった
- **知見**: v0.2 は plugin の extension point が未定義、マーク↔IR 対応が「inlining 前」前提(Rust のイテレータループは inlining 後にしか存在しない)、Jev の判断入力が計装 IR、測定手順(ノイズフロア・最小効果量・対照)が欠落。詳細は `work/jev_opt_review.md`。
- **判断**: v0.3 として書き直す。`work/` 配下(旧版・レビュー・カタログ・記事草稿)は凍結し、以後メンテナンスしない。
- **影響**: `SPEC.ja.md` 全体。

### 2. マークと proc macro を廃止した
- **知見**: 対象関数は debuginfo(DISubprogram の linkageName と DILocation の inlinedAt 鎖)で照合でき、Jev は安いのでホット箇所の選定も任せられる。マークは自動化の先送りにすぎず、proc macro から LLVM 属性を出す手段も無い。
- **判断**: `#[jev_opt::optimize]`、source scanner、token hash、source diff gate、Codex によるマーク付与を全部やめる。対象のソースも Cargo.toml も一切変えない。
- **影響**: spec §0、§8.2。

### 3. Jev の判断はビルド前、plugin は適用するだけ
- **知見**: rustc 内でオンライン問い合わせをすると broker・socket・decision lock・replay が必要になり、計装 IR 上での判断という問題も生む。
- **判断**: CLI がビルド前に Jev に聞いて `jev-plan.json` を書く。plugin は plan を読んでループに metadata を付けるだけで、状態もネットワークも持たない。plan が再現の単位。
- **影響**: spec §0、§4、§8.1。

### 4. 基準に PGO を入れる(一度外したが戻した)
- **知見**: profile を持たない基準と、profile を使う Jev 版を比べるのは不公平。「PGO 使えばいいじゃん」に答えられない。
- **判断**: 基準 = `O3 + native + fat LTO + cgu=1 + PGO`。Jev にも同じ profile を渡す。訓練実行は1回で profdata を全アームで共有する(PGO の照合は早い段、Jev のヒントはベクトル化直前の遅い段なので同じ profdata が合う)。
- **影響**: spec §0、§1、§3、§9。

### 5. 静的 Jev(全ループに問い合わせ)はやらない
- **知見**: profile 無しだと候補が全ループになり、jaq 規模で数百〜数千回の問い合わせになる。
- **判断**: PGO の分岐重みでホット上位 N(初期 20)に絞る。問い合わせは「全体設定1回 + 上位 N ループ各1回」。
- **影響**: spec §5、§14。

### 6. hotness は perf でなく PGO の分岐重みから取る
- **知見**: この WSL2 には `perf` が無く、perf との突合(symbolizer)は損失がある。PGO 込みになったので plugin の dump モードが各ループの分岐重みを直接読める。
- **判断**: hotness = ヘッダのブロック頻度 × ループ本体の命令数を dump が書く。perf は事後の帰属分析にだけ任意で使う。カバレッジ推定は cycles でなくカウントベースになる代償を受け入れる。
- **影響**: spec §6.1、§8.2、§8.5。

### 7. 対象の順序は toy → zopfli → jaq
- **知見**: ユーザーは小さいもので試したい。jaq はインタプリタ層(動的ディスパッチ、Rc、map 探索)が支配的な可能性があり、そこにはヒントが届かない。
- **判断**: toy(2クレート構成)でパイプラインを通し、zopfli を最初の実対象、jaq を本命にする。jaq に進む前にインタプリタ層の占有率ゲート(70%)を置く。
- **影響**: spec §6.4、§13。

### 8. pin は nightly-2026-09-21 / LLVM 23.1.1
- **知見**: LLVM 22 系の nightly は存在しない。spec の LLVM 内部記述は stable 1.96(LLVM 22.1.2)での観測だった。`results.md` Day 0 §1。
- **判断**: 23.1.1 に pin し、22 での観測はすべて toy で再検証する。`llvm-knobs.json` と `remark-reason-map.json` は 23.1.1 用に作る。
- **影響**: spec §3。

### 9. rustc をソースからビルドする必要は無い
- **知見**: この nightly は libLLVM を共有ライブラリで持ち、`libLLVM.so.23.1` が PassBuilder のシンボルを公開している(63 件)。アサーション OFF(`DisableABIBreakingChecks`)。`results.md` Day 0 §2。
- **判断**: gate 0 は通過。plugin は LLVM 23.1 の upstream tarball から生成したヘッダでビルドし、LLVM ライブラリはリンクしない。「gate 0 が 0 なら rustc ソースビルド」の分岐は削除。
- **影響**: spec §8.1、§13 day 3。

### 10. remark は stderr のテキストで取る
- **知見**: `-Cllvm-args=-pass-remarks-output=` は LLVM 23 に存在しない。`-Cremark=all -Zremark-dir` は fat LTO でベクトル化 remark を全部落とす(lto=off なら出る)。動いたのは `-pass-remarks=.* -pass-remarks-missed=.* -pass-remarks-analysis=.*` のテキスト出力。ただし関数名が付かない。`results.md` Day 0 §5。
- **判断**: テキスト remark を採用し、ビルドログを remark 成果物として保存。ループの関数への帰属は DWARF 行テーブル + `addr2line -i -f -p` で解く(Stage 1)。Stage 2 の plugin は IR を直接読むので不要。
- **影響**: spec §3、§6.1、§7。

### 11. `.text` は debuginfo の有無で変わる
- **知見**: debug=0 と debug=1 で `.text` のサイズも関数順序も変わった。`results.md` Day 0 §6。
- **判断**: 全アームを debuginfo=1 に固定。`.text` ハッシュは同条件のビルド同士(plugin 未ロード vs `JEV_MODE=off`、掃引の足切り)でのみ比較する。ビルド自体は決定論的で、同条件なら一致する。
- **影響**: spec §3、§8.1。

### 12. byte 数えループで幅 32 を強制すると 2.2 倍遅い(主要仮説の棄却)
- **知見**: VF 32 自体は出る(`vpcmpeqb ymm`)。しかし累算器が i64 のままなので 32 バイトのマスクを 3 段拡張して 8 本の ymm に `vpaddq` する形になり、拡張ツリーに支配される。LLVM は reduction 型を縮めない。117.6 ms → 259.4 ms。`results.md` Day 0 §14。
- **判断**: 「byte 幅の累算器で 1 反復 32 バイト」はこのヒントでは手に入らない。i64 累算の byte ループに幅を上げる候補を「有望」と扱わない。VF 4 を選んだコストモデルは正しかった。
- **影響**: spec §6.2、§1.3。

### 13. 幅の強制は浮動小数点の出力を変える(正しさの問題)
- **知見**: `-force-vector-width` を付けると、基準では「FP の順序変更が安全と証明できない」で拒否されていた f64 内積がベクトル化され、checksum が変わった。幅の明示要求が「ユーザーが望んだ」判定を作り、FP 再結合を許す経路がある。`-vectorizer-maximize-bandwidth` 単体には副作用なし。`results.md` Day 0 §13。
- **判断**: 「ヒントは意味の主張を捏造しない」という前提は誤りだった。(a) FP reduction を含む site には幅ヒントを付けない(dump が `has_fp_reduction` を出す)、(b) `jev-opt build` は最終バイナリの出力 checksum を基準と比較する正しさゲートを必須にし、落ちたら plan を捨てて基準バイナリを警告付きで返す、(c) plugin ができたら loop metadata 経由でも同じかを `dot_f64` で測る、(d) LLVM 23.1.1 に実在する `-hints-allow-reordering=false` を全アーム共通フラグの候補として実測する。
- **影響**: spec §5.1、§8.3、§8.4、§10、§12。

### 14. early-exit の探索ループはヒントの射程外
- **知見**: `position(|c| ...)` 型のループは「early exiting block の後続数が不正」「unsupported switch」の合法性で落ちる。`-enable-early-exit-vectorization` は 23.1.1 で既定 ON であり、それでも届かない。`results.md` Day 0 §5、§10。
- **判断**: remark の理由が legality / unsupported に分類される site は Jev に見せる前に除外する(費用と正しさの両面)。
- **影響**: spec §6.2、§8.3。

### 15. f64 の reduction は zopfli でも狙わない
- **知見**: 12 と 13 から、f64 reduction は合法性で拒否され、幅を強制すると出力が変わる。
- **判断**: zopfli の Huffman コスト計算(f64)を狙う仮説を撤回。zopfli では byte ループと整数 reduction に絞る。symphonia(f32 主体)も同じ制約が付く。
- **影響**: spec §6.2、§6.4。

### 16. toy は hint 方式でフラット、最小効果量は 3%
- **知見**: A/A のノイズフロアは 0.2〜1.2%、MDE は床の 3% が効く。正しさが通る 23 構成で改善側の最大は +1.03%。動いた構成はすべて劣化か正しさ違反。`results.md` Day 0 §9〜§17。
- **判断**: toy の結論は性能主張に使わない(仕組み検証用)。ただし打ち切り規則は「出力が基準と一致する構成だけ」を対象にしないと誤判定する(素直に読むと幅強制が「余地あり」に見える)ので、規則に正しさの前提条件を入れる。remark diff(cost 数値マスク)と `.text` ハッシュの両方を足切りに使う。
- **影響**: spec §6.3、§10。

### 17. WSL2 では CCD が見えない
- **知見**: `lscpu -e` が L3 を1つとして報告し、ホストの CCD 構成は観測できない。
- **判断**: 「単一 CCD 内の物理コア」を「物理コア1つに `taskset` で固定し、SMT 兄弟を空ける」に緩める。governor と turbo も制御できないので、構成順序のラウンドロビン交互化と A/A でドリフトを吸収する。
- **影響**: spec §10、§11。

### 18. Jev は Hobby の無料枠で動く
- **知見**: Vercel AI Gateway の TypeSafe 互換 API 経由で `typesafe-ai/jev` が使える。応答約 150 ms、無料枠で費用 0(定価でも1回 1 万分の 2 セント前後)。カード登録は無料枠の利用条件。`docs/jev-samples/`。
- **判断**: Pro 化もクレジット購入も不要。キーは `.env`(git 管理外)。
- **影響**: spec §5、§11。

### 19. Jev API の形式と、state の書き方で答えが変わること
- **知見**: Choice の `criteria` はオブジェクト(候補名 → 説明)、Score の `criteria` は順序付き配列(object を渡すと `invalid_request`)。同一 request 内の question は独立・並列に評価される。同じループでも state に「LLVM は既に VF=4×IC=4 でベクトル化済み」と書くと既定維持に寄り、書かないと幅 32 に寄った。`docs/jev-samples/01-*`。
- **判断**: 上位 N site の Choice は1つの HTTP request に同梱する(HTTP は global 1回 + site まとめ1回)。Jev に渡す state の書式は事前に固定して測定条件と同じ扱いで凍結する。Score / Noul は使わない(判定に使わない値を記録する仕組みを持たない)。全問い合わせを JSONL と人が読むテキストログに記録し、本数・待ち時間・トークン・費用の集計を残す。
- **影響**: spec §5、§12。

### 20. 言語方針
- **知見**: ユーザーは英語記事も書きたいが、いまは理解のために日本語で読みたい。コミット履歴は後から英語化できない。
- **判断**: コード、コミット、PR、README、CLI 出力は英語。`SPEC.ja.md`、この記録、チャットでの説明は日本語。英語版 spec は接尾辞なしの `SPEC.md` として後で生成。
- **影響**: spec「言語方針」節。

### 21. zopfli もグローバルなヒントではフラット
- **知見**: 32 構成すべて出力一致、集計で 2% を超えた構成なし。唯一の実効は `-unroll-max-count=1` の +1.6%(信頼区間は 1 を除外、本物)。ノブは効いている(interleave 1 で zopfli の 3 ループが IC4→IC1)のに時間が動かない。上位関数の 67% はデータ依存の early-exit なバイト走査(LZ77 マッチ比較、ハッシュ鎖)で、ベクトル化の対象にならない。最大の関数のループは既に VF16×IC4。`results.md` §19〜§30。
- **判断**: 事前登録の打ち切り規則の答えは「フラット、対象差し替え」。規則どおり記録した。zopfli の Huffman(f64)を狙う仮説に続き、「byte ループと整数 reduction に余地」という予測も外れた。
- **影響**: spec §6.2、§6.4(判断待ち)。

### 22. zopfli の Stage 2(site 単位ヒント)の上限は約 +1.6%。plugin は作らない
- **知見**: cost で落ちたホット 2 ループを調べた。`hash.rs:150` は cost 判定が正しい(平均トリップ 0.95 回。1 回未満のループにプロローグは払えない)。`cache.rs:108` は cost ではなく「ループ回数を計算できない」解析失敗で、幅ヒントは構造的に届かない(幅を強制しても機械語が 1 バイトも変わらない)。届くのは unroll だけで、その次元の全レンジ(×8 展開→展開なし)を使っても +1.6%。`results.md` §31。
- **判断**: zopfli のために plugin を作らない(2〜3 日かけて上限が MDE の半分)。「延期」ではなく「やらない」。
- **影響**: spec §13 day 3〜6 の対象を zopfli から外す(判断待ち)。

### 23. `cost` 分類の site が自動的に「余地あり」ではない
- **知見**: `hash.rs:150` は cost かつホットだが、平均トリップ 0.95 回でコストモデルの判断が正しい。
- **判断**: Stage 2 の site 絞り込みで、`cost` 分類には trip count のゲートを入れる(dump が `trip_count` を出す)。cost かつ trip count が小さい site は Jev に見せない。
- **影響**: spec §8.3(判断待ち)。

### 24. LLVM 23.1.1 の remark の読み方の罠 2 つ
- **知見**: (1) cost 判定は `loop not vectorized: …` の前置き形ではなく独立した analysis remark(`the cost-model indicates that vectorization is not beneficial`)で出る。前置き形だけ読むと cost が 0 件に見え、Jev に渡す対象がまるごと消える。(2) スカラ unroll には remark が出ない。唯一効いたノブの remark 差分が 2 行だった。`results.md` §23、§27。
- **判断**: `remark-reason-map.json` は両形式を持つ。掃引の足切りは remark diff と `.text` ハッシュの両方が必要で、どちらも単独では十分でない。
- **影響**: spec §4、§6.3、§7(判断待ち)。

### 25. 失格フィルタは「ホットパスにあるか」で判定する
- **知見**: `cargo tree` の grep は `simd-adler32` に当たるが、profdata で見ると 117 関数すべて実行回数 0(gzip 固定で zlib 経路が dead)。素直に読むと zopfli は失格になる。
- **判断**: 依存名の grep だけで失格にせず、profdata の実行回数で「ホットパスにある手書き SIMD か」を見る。
- **影響**: spec §6.1(判断待ち)。

### 26. remark の DebugLoc → 関数の帰属は実対象では曖昧
- **知見**: 6067 決定行のうち 1328 が多重帰属。`core/src/iter/range.rs:1103` の 1 箇所が 29 関数に共有される。一意に決まったのは数本。
- **判断**: Stage 1 の remark ベースの関数選定は一意に決まった部分集合だけに頼り、残りは `ambiguous` として件数報告。Stage 2 の plugin dump(IR を直接読む)の相対的価値が上がる。
- **影響**: spec §7(判断待ち)。

### 27. 最小効果量 3% の床は「方針」であって「測定限界」ではない
- **知見**: zopfli の A/A は半幅 0.3% 以下。`.text` が同一の構成同士も ±0.5% に収まる。+1.6% を退けているのは測定ノイズではなく、jaq の ms オーダーの配置ノイズを警戒して置いた 3% の床。
- **判断**: 「PGO+LTO+native の上で +1〜2% を『速くなった』と呼ぶか」はユーザーの判断事項として提示する(2026-09-21 時点で未決)。
- **影響**: spec §10(判断待ち)。

## 2026-09-22

### 28. oxipng は実行時間の 8 割が C の libdeflate。失格フィルタは偽陰性だった
- **知見**: v9.1.5 では libdeflate(C、AVX-512 の手書きカーネル込み)が必須依存で、feature では外せない。Rust 側の PGO 計装は C を見ないので profile 上は「Rust の byte フィルタが 98%」に見えるが、LD_PRELOAD の IP サンプラで実測すると Rust は時間加重 16%。`cargo tree -e normal` と `core::arch` の grep はどちらも no match で、`-e normal,build` で `cc` / `-sys` を見ないと検出できない。`results.md` §40〜§49。
- **判断**: 失格フィルタは「依存名 grep + profdata の share」では不十分。`cargo tree -e normal,build` の `cc` / `*-sys` 検出と、wall-clock 帰属(perf / callgrind / `scripts/ipsample.c`)を必須にする。spec §6.4 の oxipng 行(「libdeflate を切る」)は事実誤認なので差し替える。oxipng は規則どおり降ろす。
- **影響**: spec §6.1、§6.4(要修正)。

### 29. oxipng の残り 16% も既に VF 32 × IC 4。改善ゼロ、劣化 2 件
- **知見**: 37 構成すべて出力一致。改善した構成はゼロ。実在した効果は `-unroll-max-count=1` −1.2% と `-unroll-count=4` −2.4% の劣化のみ。zopfli の最良ノブ(unroll 上限 1、+1.6%)が oxipng では劣化。ホットな byte フィルタは既に `vpsubb ymm` × 4 で 1 反復 128 バイト。
- **判断**: 「byte ループなら幅の余地がある」は成り立たない。予測するのは累算器 / 結果型で、結果が byte なら初めから VF 32、累算器が i64 なら幅を上げても遅くなる(toy)。どちらも「余地なし」。候補集合は 1 本のリストにできない(4 例目)。
- **影響**: spec §6.2、§7。

### 30. jaq は 70% ゲートを通過したが、塞いでいるのは別の壁だった
- **知見**: インタプリタ層(グルー)の share は点推定 39%(下限 31、上限 62)で 70% 未満。しかし profile の 43% は hifijson の JSON レキサで、最ホットループ(全体の 22.5%、文字列処理ケースでは 37.7%)は `position(|c| matches!(c, b'\\' | b'"' | 0..=0x1F))` の early-exit バイト探索。拒否理由は toy が予言した 2 文字列そのまま(`unsupported switch` / `Incorrect number of successors from early exiting block`)で **legality**。cost で落ちたホットループは共有 DebugLoc に埋もれて帰属不能。平均スキャン長はケースにより 4〜41 バイト。`results.md` §50〜§61。
- **判断**: jaq で Stage 2 を投じる価値は薄い。「本命が落ちた」ではなく本プロジェクト最強の否定結果として扱う。対象選定の基準は「インタプリタが薄いか」ではなく「連続データ上の counted loop があるか」にすべきだった。
- **影響**: spec §6.1-4、§6.4、§13(要修正)。

### 31. jaq もフラット。掃引の最大改善は SLP 閾値で +2.1%、それより効いたのはアラインメント
- **知見**: 32 構成すべて出力一致。最小効果量 4.2% を超えたのは `-unroll-count=4` の −5.0% の劣化だけ。改善側の最大は `-slp-threshold=100` の +2.1%。ノイズプローブのつもりだった `-align-all-nofallthru-blocks=5` が +1.3%(補正後の単一ケースで +3.4%)で、42 命令のホットループを持つ対象では**アラインメントがどのベクトライザノブより効く**。zopfli で唯一効いた unroll 系は jaq では share の 0.05% しか書き換えない。
- **判断**: 群 0 は「ノイズプローブ」として使えない。代わりに正規化機械語がベースラインと一致した構成群(in-sweep null パネル)を必須にする(今回 5 ラベル得られ、A/A の 2 ラベルより良い推定だった)。
- **影響**: spec §6.3、§10。

### 32. 参考: PGO 単体で jaq は +19.5%
- **知見**: 凍結レシピ下で PGO の有無だけを比べると +19.5%(読み書きケースは +39%)。MDE の 4.7 倍、掃引の最大ノブの約 10 倍。
- **判断**: この基準の上でヒントが動かせる幅(0〜2%)と、PGO が動かす幅(20%)は 1 桁違う。方針の再検討材料として記録。
- **影響**: 方針判断(未決)。

### 33. jaq の測定はページ配置のドリフトで難しい
- **知見**: 72 MiB の配列 1 本だと RSS 1.2 GiB で同一バイナリ・同一入力が 930 / 1280 ms の二峰に(A/A 半幅 13%)。同一 sha256 のバイナリ 4 コピーが平均で 4.5% ばらつく(THP / ページ配置)。入力を小さくして複数回並べ、250 ms のギャップを入れて半幅 2.1%、MDE 4.2%。**3% の床でなく実測ノイズが効いた初の対象。** 集計は約 1%、単一ケースは約 3% まで信用できない。
- **判断**: jaq の性能主張は集計値で行い、単一ケースの ±3% は語らない。同時に複数対象を測らない(oxipng と同時走行で A/A 半幅が 0.3% → 1.7% に悪化)。実行中の共有スクリプトを in-place 編集しない(bash が途中から読み直して落ちた)。
- **影響**: spec §10。

### 34. `.text` ハッシュは C 依存があると再現しない
- **知見**: mimalloc の C が `__DATE__ __TIME__` を焼き込むので、同一構成の再ビルドでも `.text` が変わる。`scripts/norm_code_diff.py`(全シンボルのアドレス正規化ハッシュ)なら同一構成の 2 ビルドで一致する。
- **判断**: 掃引の足切りは正規化コードハッシュにフォールバックする。「ビルドは決定論的」は pure Rust の前提付き。
- **影響**: spec §3、§6.3。

### 35. 正しさゲートは「実行されたコード」しか守らない
- **知見**: jaq には FP 再結合を拒否された箇所が 10 件(libm の三角関数)あるが、3 ケースがそこを実行しないので幅を強制しても出力は一致した。
- **判断**: 出力 checksum ゲートは一次防御にならない。site 規則(`has_fp_reduction` に幅を付けない)を一次防御にし、ゲートは二次。
- **影響**: spec §8.4、§10。

### 36. トリップカウントの求め方
- **知見**: `Block counts[0]` を entry count とみなす方法は profile によっては 0 になり不健全。ループヘッダ − バックエッジ = 脱出回数、から求めるべき。
- **判断**: `scripts/interp_share.py` / `cost_hot_loops.py` の方法に統一。zopfli の `hash.rs:150` の「平均トリップ 0.95」は同法で取り直して再引用する。
- **影響**: spec §8.3、§8.5。

### 37. 4 対象の総括: PGO + LTO + native の上で、ループヒントの余地は 0〜2%
- **知見**: toy / zopfli / oxipng / jaq のすべてで事前登録の打ち切り規則が「フラット」。機構は対象ごとに違う: toy は単純すぎてコストモデルが正しい、zopfli は early-exit バイト走査(67%)、oxipng は C(80%)と既に最大幅、jaq は JSON レキサの early-exit 探索(legality)。共通するのは「LLVM が見送った判断のうちヒントで動かせるものは、時間の支配要因ではない」こと。
- **判断**: ループ metadata ヒントを Jev に選ばせる、という現行の主仮説は、この基準の上では速さを出せないと判断する。plugin(Stage 2)はどの対象でも作らない。次の方針はユーザーの判断事項(未決)。
- **影響**: spec 全体(方針決定後に改訂)。

### 38. 方針転換: Jev の判断対象を「ループヒント」から「PGO の訓練ワークロード選定」へ。FP 再結合はオプション
- **知見**: 37 の総括。ヒントの面は空で、動いたのは PGO(+19.5%)と FP 再結合(2.6 倍、出力が変わる)の 2 つだけ。
- **判断**(ユーザー決定 2026-09-22): (1) 主軸は「Jev がリポジトリ内の候補(tests / examples / fixtures 等)から PGO の訓練に使う入力を選ぶ」。`cargo build --release` → `jev-opt build` で訓練データを人が書かずに PGO の効果を得る。まず jaq で Jev 抜きの上限(素朴な選び方で訓練した PGO と、本番に近い入力で訓練した PGO の差)を測り、MDE 4% 以上の差があるかを確認する。(2) 「Jev がループ単位で FP の再結合を許すか判断する」は、結果が良くても**オプション機能**とし既定では無効(コストとリスクが高い可能性があるため)。数値系の対象を別に選んで検証する。plugin はこの (2) のためだけに作る。
- **影響**: spec 全体を方針決定後に改訂(未着手)。

### 39. Jev の各判断は独立にオン・オフできる機能にし、機能ごとに効果を測る
- **知見**: ユーザーは最終的に「この機能はこのぐらいだった」を記事にしたい。機能を束ねると個別の寄与が分からない。
- **判断**(ユーザー決定 2026-09-22): `jev-opt build` の Jev 判断はすべて独立のフラグにする。(1) PGO 訓練ワークロード選定は既定 ON(`--no-select-training` 等で OFF)、(2) FP 再結合の判断は既定 OFF(`--fp-reassoc` で ON)。評価は機能ごとのアブレーション(ON/OFF の差)を同じ holdout で測り、結果表は「機能 × 効果」の形にする。将来機能を足すときも同じ規則。
- **影響**: spec §1(結論の出し方)、§11(設定)、§12(CLI)。方針改訂時に反映。

### 40. FP 再結合の機構: `vectorize.enable=true` 単独でも FP の順序変更が許される。実装は FMF 方式にする
- **知見**: LLVM 23.1.1 のソースで確認。`LoopVectorizeHints` は `llvm.loop.vectorize.width` / `.enable` を `-force-vector-width` と同じフィールドに読み込み、`allowReordering()` は両者を区別しない。したがってメタデータ経路も cl::opt と同じく FP 再結合を許す(実測は未)。しかも**幅を付けず `vectorize.enable=true` を付けるだけ**で同じ経路に入る。`-hints-allow-reordering=false` で全域封鎖できる。別の狙い撃ち機構として、対象ループの FAdd/FMul 連鎖に `reassoc` フラグ(FMF)を立てれば、幅もコストモデルも触らずにリダクションだけ再結合可能になる。`docs/fp-reassoc-target-scouting.md` §1。
- **判断**: (a) 既定経路(ヒント機能を将来復活させる場合も含む)では全アームに `-hints-allow-reordering=false` を固定し、幅 / enable ヒントが FP を変えないことを構成上保証する。(b) FP 再結合オプションは幅ヒントでなく **FMF 方式だけ**で実装する(影響範囲がフラグを立てた命令に限られ、VF はコストモデルに任せられる)。(c) spec の「FP reduction に幅ヒントを付けない」規則は `vectorize.enable` にも広げる。
- **影響**: spec §8.1、§8.4(改訂時)。

### 41. FP 再結合の対象は llama2-rs と ebur128。「純 Rust・手書き SIMD なし・長い FP リダクション」の母集団は薄い
- **知見**: 効くのは長い単一アキュムレータの ordered f32/f64 リダクションだけ。IIR、3〜4 要素の内積、要素毎の演算、手展開済みの部分和には効かない。候補調査の結果、llama2-rs(内積 288〜4096 長が実行時間の 9 割、C なし、SIMD なし、決定的)と ebur128(f64 の `sum += x*x`、出力が数値、しかも作者が「`sum()` を使うと C 版と丸めが変わるので使うな」とコメントした箇所があり、Jev の strict 判定の実地テストになる)が最良。symphonia は清潔だがリダクションが薄い。rubato / rustfft / candle などは手書き SIMD で除外。FP スループットを気にする人は既に手で最適化しているので、母集団自体が薄い(知見 29・37 のパターンの再現)。
- **判断**: 第 1 対象 llama2-rs(機構の証明)、第 2 対象 ebur128(正しさゲートと strict 判定の設計)。symphonia は 3 番目。
- **影響**: spec §6.4(改訂時)。

### 42. FP オプションの正しさゲートは許容誤差方式。離散化を挟む出力は strict
- **知見**: 出力の種類ごとに許容値が要る(f64 配列、f32、PCM の SNR、画像の PSNR、テキスト中の数値の相対誤差)。argmax・閾値・量子化・ソートを挟む出力は小さな差が離散的に増幅されるので比較できない。基準は真値ではない(木状加算の方が普通は正確)。
- **判断**: 既定経路はビット一致ゲート、`--fp-reassoc` 時のみ許容誤差ゲートで両者を混ぜない。手順は決定性セルフチェック → 成果物種別の宣言(未宣言はビット一致)→ holdout で比較。量子化前の値を比較できない site は規則で `keep_strict`。Jev の Choice は `keep_strict` / `allow_reassoc` / `allow_reassoc_and_contract` の 3 択、既定 strict。工数は 2 対象で約 6〜9 人日。
- **影響**: spec §8.4、§10、§12(改訂時)。

### 43. jaq では PGO の訓練セットの選び方に 17.7% の余地がある(機能 1 の仮説は成立)
- **知見**: 本番に近い入力で訓練した PGO(T_real、+21.6%)と、リポジトリの全テスト・ドキュメント例で素朴に訓練した PGO(T_all、+3.3%)の差は holdout で **+17.7%**、MDE 3% の 6 倍。PGO の利得の 85% が訓練セットの選択に乗っている。`results.md` §62〜§69。
- **判断**: 「Jev が訓練ワークロードを選ぶ」は追う価値がある。ループヒント方向(0〜2%)とは桁が違う。
- **影響**: spec を新方針で全面改訂(着手)。

### 44. 「大きい入力を選ぶ」も「リポジトリの bench を使う」も自明解ではなく、後者は PGO なしより遅い
- **知見**: jaq のプール 1185 件に大きな入力は無い(中央値 5 バイト、最大 2 KB)。入力バイト数と仕事量は逆相関(最重量の bench 12 件は入力 8 バイト)。バイト上位 10% で訓練(T_big)は T_real の 19% しか回収しない。リポジトリの bench 一式で訓練(T_bench)は **PGO なしより 7.8% 遅い**(インタプリタの dispatch だけが積極的にインライン化され、holdout が使う JSON 経路が潰れる)。素朴に全部で訓練 + 本番入力の和集合は T_real とほぼ同じ(希釈 −1%、MDE 未満)。
- **判断**: (a) サイズは特徴量として使わない。(b) セレクタは「不適切なものを除く」より「代表入力を見つける」が主務(recall 重視)。(c) `jev-opt build` は「常に PGO、入力は何でも」にできない。悪い訓練セットは無 PGO より遅いので、holdout 相当の自己検査で T0(PGO なし)へフォールバックできる仕組みが要る。
- **影響**: spec §7(改訂時)、§12。

### 45. 判別するのは候補ごとの profile の形。候補単位の観測は安い
- **知見**: プール全 1185 件のドライランは 9.4 秒。候補ごとに計装 profile を取れる。判別に効くのは「データ経路(hifijson / jaq_json)の counts ÷ 起動・コンパイル経路(load / compile)の counts」「どの層に触るか」で、`-pgo-warn-missing-function` や zero-count 関数数は無価値(5 バイトの入力でもレキサは通るので警告 0)。ホットセットを単独で覆う候補は無く、選定は**ランキングでなく集合被覆**。
- **判断**: セレクタの入力は候補ごとの profile 形状 + 出自 + 内容。決定的セレクタ(アーム B)は「profile 形状の貪欲集合被覆」にする。Jev の価値はそれを上回れるか(利用者の本番説明との意味的照合、代表性の判断、スケール決定)で測る。
- **影響**: spec §7、§8(改訂時)。

### 46. スケールのつまみが到達可能集合を桁違いに広げる
- **知見**: jaq の bench は n を stdin で取り、`bench.sh` 自身が n を 7〜1048576 で振っている。リポジトリに大きな入力が無い場合、救うのは選定ではなく「既存候補をより大きく走らせる」こと。
- **判断**: セレクタは候補の選択だけでなく、パラメトリックな候補のサイズ / 反復回数も選べるようにする。利用者が任意で置くサンプル入力(`jev-opt/samples/`)も候補プールに含める。
- **影響**: spec §7(改訂時)。

### 47. 3 件のテスト項目が PGO のカウンタを破壊する(profile の妥当性検査が必須)
- **知見**: 大きな整数の `tostring` を含む 3 件(うち 2 件は普通の単体テスト)が、`num_bigint` の 1 ブロックに 4e13 のカウントを出す(mimalloc の arena ポインタの値)。ProfileSummary の全パーセンタイルがこの 1 ブロックに乗り、プログラム全体が cold 扱いになり、**PGO なしより 9.9% 遅い**バイナリが出る。出荷バイナリでは不可視。
- **判断**: `jev-opt build` は訓練後に profile の妥当性検査(どのブロック数も wall time × 妥当な IPC を超えない)を必須にし、汚染候補を除外して記録する。コストは `llvm-profdata show` 1 回。
- **影響**: spec §12(改訂時)。

### 48. 結果の限界: jaq は「テストが本番と構造的に別物」なケース
- **知見**: 17.7% が出るのは、リポジトリの入力(インタプリタの単体テスト)と本番(数十 MB の JSON)が別物だから。テストが本番ワークロードそのものである対象(fixture を持つコーデック、spec テストを持つパーサ)では余地はずっと小さく、フラットもあり得る。
- **判断**: 次の対象は「素朴解が既にそこそこ良いリポジトリ」を意図的に選ぶ(製品主張はそこでも余地があることを要求する)。候補: pulldown-cmark(CommonMark spec テストが fixture、本番は大きな文書)など。
- **影響**: spec §6.4(改訂時)。

### 49. jaq のリポジトリ内だけで到達できる PGO の上限は +8%。「リポジトリから選ぶ」ことの価値は測定不能
- **知見**: 1182 候補を 1 つずつ profile して(72 秒)6 通りの訓練集合を作った。最良は決定的な貪欲集合被覆(B_cover)で PGO なし比 +8.1%。全候補で素朴に訓練(T_all)は +6.6% で、差 1.4% は MDE 4.1% 未満。本番のシンボル(`read::parse`、`write_until`)を実行する候補はプール中 **1 件**だけ(`--slurp` で JSON ファイルを読む doc の CLI 例)で、カウントも極小。`results.md` §70〜§79。
- **判断**: 「Jev がリポジトリから訓練入力を選ぶ」は、代表入力が無いリポジトリでは価値を出せない。選定機構の役割は速さではなく**ガードレール**(リポジトリでは無理と判定し、悪い訓練セットの出荷を止める)。
- **影響**: spec §7 の主務を書き換える(未着手)。

### 50. 人間の判断も profile 形状のマッチも、PGO なしより 8% 遅い訓練集合を選んだ
- **知見**: 「本番に近い候補」として人間(エージェント)が選んだ集合(E_expert)と、profile 形状の機械マッチ(B_shape)は独立に同じ候補(スケールした to-fromjson bench)を選び、どちらも **PGO なしより約 8% 遅い**。理由は本番と「同じ関数」が同じシンボルではないこと: file 引数だと `SliceLexer`、stdin だと `IterLexer` の別 instantiation、さらに `parse` は CGU ごとに 5 複製あり、本番と `fromjson` は別の複製を実行する。crate / 層レベルの指標(hifijson の share、データ経路÷起動、分類の signature)は全部これに騙された。
- **判断**: Jev に見せる特徴量は層レベルではなく **シンボル単位(CGU 修飾込み)**。「代表に見える」判断は形状レベルでは当たらない。
- **影響**: spec §7.3〜7.4(未着手)。

### 51. 効くのは 2 段ゲート: profile の汚染検査 → 参照 hot set に対するシンボル単位の zero-count
- **知見**: 2 実験 12 アームで、汚染検査を通過したうち、参照 hot set(20 シンボル)に 1 つでも zero-count を持つアームは**例外なく** PGO なしより遅く、持たないアームは例外なく速い。汚染アーム(T_allraw)は zero が 0 個なのに遅いので順序は汚染検査が先。どちらも `llvm-profdata show` 1 回で計測不要。
- **判断**: `jev-opt build` のフォールバックは「holdout 計測」でなく、この 2 段ゲートで機械的に判定できる(計測より安く、決定的)。残る課題は参照 hot set をどこから得るか(利用者サンプルの profile、または初回の本番実行)。
- **影響**: spec §7.6、§12(未着手)。

### 52. 利用者のサンプル 1 ファイル(2 MiB)で本番相当の利得をほぼ全回収
- **知見**: 2 MiB の JSON 1 ファイルを 3 つのフィルタで訓練(0.2 秒)すると PGO なし比 +21.8%、71 MiB の T_real(+22.3%)との差は A/A の範囲内。
- **判断**: `jev-opt/samples/` はフォールバックではなく**機能 1 の本体**。製品の見出しは「サンプルを 1 つ置けば +22%、リポジトリだけなら最良 +8%(素朴訓練と区別できず)」の形になる。Jev の判断対象は「候補の取捨」から「**サンプルをどう走らせるか**」(file 引数か stdin か、どのフィルタ / フラグで、何回)へ移す必要がある。呼び出し方が code path(lexer の instantiation)を選ぶことは 50 で実証済み。
- **影響**: spec §7 全体(未着手)。

### 53. スケールのつまみは効かない。壊れた run を選ばないために exit status が必須
- **知見**: bench の n を 16 倍にしても ProfileSummary は percentile なので相対重みしか変わらず、E_expert のスケール有無で −0.7%(逆符号、MDE 未満)。`ack.jq` は n=2^20 で 19 ms でスタックオーバーフローし、wall time だけ見る probe は壊れた run を「軽い」と誤認する。
- **判断**: 決定 46 のスケール期待は撤回。スケールは残すが降格(相対重みの調整のみ)。候補実行は exit status を必ず見る。
- **影響**: spec §7.2、§7.5(未着手)。

### 54. Experiment 1 の帰属(§67)は誤りだった
- **知見**: `write_until` 42→84 命令は損害ではない(T_real 相当の S_sample1 も 84)。`BufWriter::write` 229→45 は勝つアームにも共通。機械語の形はどのアームが勝つかを説明しない。予測 9 件中 3 件が外れ、最大の外れ(上限 1.10〜1.16 と予測して実測 0.92)は hot-set share で外挿したため。
- **判断**: 帰属と予測は per-symbol zero-count を根拠にし、share での外挿はしない。
- **影響**: results.md §67 に訂正済み。

### 55. 主題の再確認: 実験の問いは「Jev が出すヒントで速くなるか」。訓練データ選定への差し替えは趣旨から外れていた
- **知見**: ユーザーの指摘(2026-09-22)。速くなる手段は何でもよいのではなく、Jev のヒントで速くなるかが主題。profile の取得、ホット箇所の特定・マーク、候補の列挙は人手や別の LLM でよい(準備)。Claude は「ループヒントの余地 0〜2%」という測定から主題そのものを「Jev が訓練データを選ぶ」に差し替えたが、それは Jev のヒントではなく、そこで出た +22% は Jev の高速化ではない。
- **判断**: 主題をヒントに戻す。基準は PGO + LTO + native で固定。訓練データ選定(決定 43〜54)は主題から外し、準備の一部(合成ワークロードでの PGO)として扱う。ヒントの語彙を、ループ metadata 5 種から**実際に動いた次元**へ広げる: FP 再結合(FMF)、関数属性(inline / noinline / cold / hot / align)、unroll、ループ metadata。plugin はこの語彙を適用するために作る。
- **影響**: spec v0.5 へ改訂(着手)。決定 38・39 の「機能 1 = 訓練データ選定」は撤回、機能の切替とアブレーションの規則(39)は維持。

### 56. FP 再結合ヒントは見出しに含めてよい(今回は実験)
- **知見**: FP 再結合は出力が許容誤差内で変わる。ユーザーは「今回は実験だから」見出しに含めることを了承(2026-09-22)。
- **判断**: 第 1 の対象とヒント族の組は llama2-rs × FP 再結合。以降 jaq × 関数属性・アラインメント、zopfli × unroll。各組で、手書き plan による site ごとの oracle → Jev の Choice → 決定的規則、の順に測り「Jev は oracle の何%を一発で取ったか」を主指標にする。出力の検査は種別ごとの許容誤差(llama2-rs は logits のダンプ)。
- **影響**: spec §1、§6、§7〜8(改訂時)。

### 57. 主題の再確認(2 回目): 準備は賢い側がやり、Jev がその判断に耐えられるかを測る
- **知見**: ユーザーの指摘(2026-09-22)。v0.2 の「Codex / Claude がホット箇所にマークを差し込む」は自動化の先送りではなく、**Jev の判断対象を単純にするための準備**だった。profile と静的解析、人手を含めて準備側は賢くてよい。問いは「小さくて速くて安い Jev が、単純化された判断に耐えられるか」。効果の出る対象を探して回ること(llama2-rs 等)は主題ではなく、効果を出すのに賢いモデルが要るなら Codex 案の方が賢いという話になる。Claude はマーク差し込みを「不要」と切ったときにこの意図を読み違えた。
- **判断**: (1) 準備 = Claude(または Codex)が profile と静的解析からホット箇所を数〜十数箇所に絞り、各箇所に具体的ヒント候補(3〜8 個、根拠付き)を列挙し、自分の本命も記録する。plugin の site key でソースを変えずに済ませるが、属性としてソースに書く形も許容。(2) Jev は箇所ごとに Choice 1 回(`KEEP_DEFAULT` 必須)。(3) アームは 基準 / Jev / strong-LLM の本命 / 決定的規則 / oracle。(4) 主指標は Jev − 基準、Jev ÷ oracle、Jev vs strong-LLM(同等なら費用と待ち時間で Jev の勝ち)。(5) 対象は zopfli(ノイズ 0.3%、箇所単位の判断の質)→ jaq(本命、集計で語る)。llama2-rs は参考に降格し、準備作業を中止。
- **影響**: spec v0.5(改訂中)。決定 56 の対象順序は撤回。

### 58. 最終形(ユーザーの元の設計に戻す): 人 / Claude が場所を指し、Jev がヒントでいろいろやる
- **知見**: ユーザーの説明(2026-09-22)。v0.2 のマークは「場所の特定は大変なので、最適化が必要と思う関数に Claude(人間の代理人)がマークを付け、Jev がそこを最大限最適化するためにいろいろやる」設計だった。Claude はシステムの部品ではなく人間の肩代わりで、人が直接指示してもよい。Jev だけの完全自動最適化は時間がかかりすぎるので場所は人側に置いた。Claude が箇所ごとにヒント候補を絞る形(決定 57)は Claude が最適化していることになり、これも読み違え。
- **判断**: 実験は 4 項目だけ。(1) **マーク**: 速くしたい関数を Claude または人が指定する(perf の上位を見る。方法は問わない、ビルドに組み込まない)。形は関数名のファイル 1 つ、または `#[jev_opt::optimize]` 属性、どちらでも。(2) **ヒントの一覧は固定**: 関数属性(inline / inline(never) / cold / align)、ループのヒント(unroll 回数、ベクトル幅、interleave)、コンパイラ設定。全マークで同じ一覧を Jev に渡す。(3) **Jev がいろいろやる**: マークされた関数とその中のループごとに Jev がヒントを選ぶ → 適用してビルド → 測る → 結果を Jev に返す → また選ぶ、を決めた回数繰り返し最良を残す。(4) **測る**: 基準と Jev の最終 plan。補助として全候補を機械的に回した oracle とランダム探索を置き、Jev が賢く探せているかを見る。適用手段は LLVM plugin 1 本(ソースは触らない)。対象は jaq、profile は perf。FP 再結合、訓練データ選定、対象探し、フォールバック設計は外す。
- **影響**: spec v0.5 を 4 項目で短く書き直す(着手)。v0.4 は破棄。

### 59. perf は WSL2 で動く。profdata ベースのホット一覧はマーク先としては使えなかった
- **知見**: sudo 無しでも `apt-get download` + `dpkg-deb -x` で perf を私設 prefix に置けば動く(`scripts/perf_local.sh`)。PMU は本物(cycles と cpu-clock が一致)。ただしコールチェーンは取れない(フレームポインタ無し、DWARF 展開も 2 割しか解けない)。同じバイナリでも profdata の上位と perf の上位はほぼ別物: `write_until` は fat LTO で `read::parse` にインライン化されてシンボルとして消え(22.5% → self 0%)、`read::parse` は 7% → 29%、mimalloc(C)は 4% → **23%**(Rust の計装に映らない)。block count は小さくて超高頻度の本体を過大評価する。`results.md` §80〜§86。
- **判断**: マーク先の選定は perf の self / reach で行う(決定 6 の「hotness は PGO 分岐重みから」は plugin 内のループ順位付けの話で、マーク選定には使わない)。jaq のマークは 15 関数(read 経路 4、filter / interpreter 5、write 経路 3、object 機構 3)、バイナリ内 user cycles の 61%、Rust 部分の 79% を覆う。残りの大半は mimalloc の C で plugin が触れる IR が無い。マークにヒントの示唆は書かない。
- **影響**: spec §1(1)、§8 `doctor` / `mark`。

### 60. plugin は動く。EP は関数属性 = PipelineStart、ループ = VectorizerStart で確定
- **知見**: toy で実測。fat LTO のマージ後段で plugin はロードされるが、発火するモジュール EP は `FullLinkTimeOptimization{Early,Last}` だけで、pre-link は ThinLTO pre-link 相当でベクトル化前に止まる。ループ metadata は `VectorizerStartEP`(マージ後段)で consumed、関数属性は `PipelineStartEP`(pre-link、CGU ごと 1 回)で consumed。off 等価性(未ロード / off / 空 plan)は `.text` と出力がビット一致。`-hints-allow-reordering=false` を付けると `dot_f64` に幅ヒントを載せても出力不変、付けないと出力が変わる(決定 40 の実測確認)。dump の trip count は既知の正解を再現。`results.md` Day 3。
- **判断**: (a) `-Cllvm-args=-hints-allow-reordering=false` を基準含む全アームに固定。(b) ヘッダ生成は `LLVM_ABI_BREAKING_CHECKS`(変数名の罠)、tablegen 7 ターゲット、`libc/` 展開、未定義シンボルゲート付き(`scripts/build_plugin.sh`)。(c) ProfileSummary の有無で止めない(PipelineStart には無い)。
- **影響**: spec §3、§5。

### 61. site の帰属は `loop_in_mark` だけを Jev に渡す。関数属性は先、ループは属性適用後に取り直す。ジェネリックは全単相化に適用
- **知見**: 「ループ内の命令の inlinedAt 鎖がマーク関数に届く」だけだと、マーク関数がインラインされた**呼び出し側のループ**(driver の繰り返し)も拾い、site が倍になる。`inline(never)` を入れるとその関数のループ key だけが変わり、他のマークの key は不変(toy)。`unroll.count` はベクトル化後のループに載る。
- **判断**: (a) Jev に渡すのは `loop_in_mark`(マーク関数の中のループ)のみ、`mark_in_loop` は除外。(b) ラウンドは 2 段: 関数属性のラウンド → 属性を適用した IR から `apply-dump` でループを取り直し → ループのラウンド。(c) ジェネリック関数名のマークは全単相化に適用する(人の意図に合わせる。`ambiguous` は報告のみ)。(d) 語彙の注記: スカラループを unroll したいときは同じ site でベクトル化を止める(`vectorize.width=1` 相当)必要がある。
- **影響**: spec §1(2)(3)、§5、§6。

### 62. 探索ループの実装は Python で先に作る
- **知見**: 既存の計測・profile・dump 処理はすべて Python / bash スクリプトで揃っている。Rust の CLI を書き直すのは実験には不要な工数。
- **判断**: 実験用の探索ループ(`scripts/jev_search.py`: マーク解決 → dump → Jev に聞く → plan → ビルド → 測る → 結果を返す → 次ラウンド、`--proposer jev|random|oracle`)を Python で作る。Rust の `jev-opt` バイナリは製品化するときに検討。「今作っているものは捨ててもよい」の範囲。
- **影響**: spec §4、§8。

### 63. jaq の site は 149(127 key)。oracle は事前登録の機械的な上限で 16 loop key + 15 関数に絞る
- **知見**: 15 マークは全部解決(plugin のマーク照合に 3 件のバグがあり修正: `#` の行中コメント扱い、generic の全削除で名前が潰れる、`fn_attrs` が単相化に当たらない)。`loop_in_mark` は 149 site / 127 key、分布は極端(`read::parse` 49、`write::write` 22、9 マークは 10 未満)。ホットで解決できるがループを持たないマークが 2 つある。oracle を素直に回すと 1488 ビルド / 112 時間。`results.md` §87〜§94。
- **判断**: 結果を見ない機械的規則を事前登録して絞る: (1) 訓練 profile のカウントが入らない key を落とす → (2) trip count < 2 を落とす → (3) マークごとに hotness 上位 3。残り 16 loop key + 関数属性 15 マーク = 31 site、oracle は 267 ビルド / 約 20 時間。**Jev / random / oracle の 3 提案者はすべてこの同じ site 集合を使う。** site ごとの候補絞り込みはしない(spec §1(2))。
- **影響**: spec §2(oracle の規模)、§8 `[search]`。

### 64. site key は jaq では一意でない。plan のエントリは「key への指示」
- **知見**: 127 key のうち 13 が 2〜9 個のループに解決(最悪は再帰シリアライザ `write::write` の 9 重。owner・inline chain・leaf・fingerprint・depth がすべて同一で、header count だけが桁違い)。plugin は衝突 key の全コピーにヒントを付けた上で `ambiguous` を報告する。
- **判断**: `ambiguous` は失敗ではなく件数として記録する(失敗は `vanished` と `unmatched`)。key に header count を混ぜると PGO の値に依存して不安定になるので、key の定義は変えない。
- **影響**: spec §5、plugin README(訂正済み)。

### 65. 探索ドライバの確定事項
- **知見**: `scripts/jev_search.py` は 1 ラウンド = 2 ビルド(関数属性 → `apply-dump` でループ取り直し → ループヒント → ビルド → 正しさ → 計測)。toy の smoke で、n=3 だと同一コードのビルドが採用規則を通ってしまう(in-sweep null panel の発火そのもの)ので、n=15 が凍結値である理由が実測で出た。ソース抜粋の basename 一致は無関係なテストファイルを state に混ぜていたため廃止。`results.md` 「Search driver (smoke)」。
- **判断**: (a) 採用規則(事前登録): 全ケースで出力一致、plan の全エントリが効いた(`ambiguous` は件数のみ)、集計速度比の 95% 信頼区間下限がこれまでの最良の点推定を上回る。(b) 関数属性の 1 Choice はマーク自身と全単相化に展開し、内部のクロージャには**及ばない**(`--fn-attr-scope all` で plugin 本来の範囲に戻せる)。(c) confidence の閾値は設けない(`min_confidence = 0`)。(d) 履歴は round ごとに変わる key でなく `site_id`(マーク@file:line:col#depth)で持つ。(e) state と語彙は `v1-2026-09-22` で凍結。(f) 実験の順序: Jev 5 ラウンド → ランダム 5 ラウンド → oracle(関数属性 90 ビルド → ループ 177 ビルド)→ 最良 plan を holdout で 1 回。このマシンでは同時に 1 つ。
- **影響**: spec §1(3)、§6、§8。

### 66. Experiment 3(jaq、5 ラウンド): Jev は 107 問すべてに `KEEP_DEFAULT` を返した
- **知見**: 31 site × 5 ラウンドで、返ってきた 107 回答はすべて `KEEP_DEFAULT`(confidence 中央値 0.97、平均 0.95。次点は `inline` 62、`vectorize_width_8` 24)。したがって Jev の plan は 5 ラウンドとも空で、バイナリは基準と同一。ランダムは訓練で最良 +1.9%(採用)だが holdout で −1.9%(符号反転)。MDE 3% に届くものは無し。同一バイナリ 3 本の holdout が 1.000 / 0.979 / 0.991 と 2.1 ポイント開き、jaq の測定ノイズは A/A 半幅で見るより大きい。API は 24 回の試行のうち 17 回が 503 で、3 リクエストは 3 回とも失敗して規定どおり `KEEP_DEFAULT` に落ちた。費用は無料枠で 0、実時間の 0.8%。`results.md` §95〜§102。
- **判断**: この run は「Jev のヒントで速くなるか」を検証できていない(Jev がヒントを出していない)。検証できたのは、ループが回ること、plan が効くこと、聞かれたときに Jev が何と言うか。Jev の「触るな」が正しいかどうかは oracle(全候補の実測)で判定できるので、oracle は事前登録どおり回す(関数属性 90 ビルドを先に)。
- **影響**: §2 の「Jev ÷ oracle」は oracle 待ち。

### 67. 「Jev がいろいろやる」ためには state の設計を変える必要がある(判断待ち)
- **知見**: state は「`KEEP_DEFAULT` は基準の再現」「LLVM が既に付けている属性」「前ラウンドの結果(空 plan なので基準と同じ)」を含む。この情報で聞くと Jev は高い確信で「触らない」を選び、結果のフィードバックも生まれない。決定 19 で見た「state に LLVM の現状を書くと既定維持に寄る」の再現。
- **判断**(未決、ユーザーに提示): 案 (a) 探索ラウンドでは `KEEP_DEFAULT` を候補から外し「どのヒントが最も見込みがあるか」を聞く(何かを試させる)。案 (b) Score で候補ごとの期待利得を聞き、上位を試す。案 (c) 質問文を「変えるべきか」でなく「この関数を速くするならどれか」にする。いずれも Claude が候補を絞るのではなく、聞き方の変更。Jev が「触るな」と言い続けること自体を結果として書く選択肢もある(oracle がそれを正当化するなら)。
- **影響**: spec §1(3)、§6(判断後)。

### 68. Jev に渡していた platform と profile の情報は薄く、15 問同梱で希釈されていた
- **知見**: ユーザーの指摘を受けて実送信の JSONL を確認。1 リクエスト 71 KB・15 問。platform は 1 行(CPU 名、znver3、AVX2、AVX-512 なし、LLVM 23.1.1、フラグ)だけで、キャッシュ容量、ベクトル幅とレジスタ本数、コア構成は無い。profile はマークの share とループの trip count のみで、ワークロード別 share、self / reach の区別、命令数・分岐・call、remark の理由は site ごとに付いていない。
- **判断**: prompt study(Jev API のみ、ビルドなし)に、platform を構造化するブロック、site ごとの profile 表、1 問 1 リクエスト、探索フレーミング、の変種を追加し、選択が site の特徴を追うようになるかを測る。結果で state v2 を決める。Claude が候補を絞ることはしない。
- **影響**: spec §6(state の書式、判断後)。

### 69. 実験の指標を「Jev の答えが Claude の判断にどれだけ近づくか」に定める
- **知見**: ユーザーの言葉(2026-09-22)。「最適化の判断は Claude の方が圧倒的に正しいが、高価で使えない。Jev は速くて安い。Jev の返しが Claude の考える結果に近くなる(またはそれ以上になる)にはどうすればよいか」。
- **判断**: prompt study と以後の Jev ラウンドの主指標は、Claude の参照判断との一致率(完全一致 / 同じ族 / 不一致)、3 回反復の安定性、費用・待ち時間。Jev の価値は「同じ判断を 3 桁安く速く、全 site に一度に下せること」。近づけるための手として、platform と profile の構造化、1 問 1 リクエスト、ヒントの一般的な解説書、判断の 2 段分解、実測に基づく実例、を試す。「Claude の理由付けを見せる」変種は上限の確認用で製品には使わない。推奨する state v2 は「Claude なしで運用できる範囲」で最も一致率が高いもの。
- **影響**: spec §2(指標)、§6(state)。判断後に反映。

### 70. prompt study(Jev API のみ、18 通りの聞き方 × 9 site × 3 回): 聞き方は confidence を動かすが結論はほぼ動かさない
- **知見**: Claude の参照判断は 9 site 中 KEEP_DEFAULT 6、`inline(never)` 2(`TermId::run` 10496 命令 × 62 単相化、`write::write` 5467 命令の再帰)、`vectorize.width=16` 1(`to_ascii_lowercase` のバイトループ、trip 222、call なし)。Jev は凍結版の聞き方で 100% KEEP(confidence 0.92)。18 変種で結論は「触らない」で安定し、confidence(0.35〜0.93)と確率質量は大きく動くが選択はほぼ動かない。Claude が機構ありと見た L3 の幅 16 は**一度も**選ばれず、`inline(never)` は 1 変種で 3 回中 1 回のみ。Jev が `inline` を付けるのは集合中**最大**の body(10496、5467、7660 命令)で Claude と逆方向。唯一 `inline` に機構がある 251 命令のホット葉は既に inlinehint 済みで、Jev もそれを読んで KEEP。legality の remark は唯一明確に読まれている入力で、LLVM が「ベクトル化不能」と言ったループに vectorize を選んだことは 54 セル中 0 回(remark を外すと質量が跳ね上がる)。`docs/experiments/jev-prompt-study/`。
- **判断**: (a) 一致率を上げたのは質問文の変更だけ(V2: 「変えるべきか」→「この workload でこの関数を速くする可能性が最も高いヒントはどれか」、KEEP_DEFAULT を中立に記述)。同族一致 0 → 6。(b) platform の構造化、site ごとの profile 表、1 問 1 request は選択を 1 site も変えなかった(決定 68 の仮説は不支持。ただし記録のため platform / profile ブロックは残す)。(c) ヒント解説書、実測の実例、Claude の理由付けを渡すと Jev は**より保守的**になり全部 KEEP に戻る。(d) KEEP_DEFAULT を候補から外すと定数回答(fn は全部 `inline`、loop は全部 `unroll.disable`)になるので外さない。remark も外さない。
- **影響**: spec §6(state v2)。

### 71. 安い梃子は prompt でなく「読み出し」。全 site が KEEP でも探索が動くようにする
- **知見**: 確率質量は情報を持っているが driver は argmax しか使っておらず、全 site KEEP → 空 plan → フィードバック無し、が構造的に起きていた。
- **判断**: state v2 = V2 の文言 + platform / profile ブロック、request は phase ごと 1 本(従来どおり)。driver の読み出しを変える: site を `1 − P(KEEP_DEFAULT)` で並べ、全 site が KEEP なら最上位 site の最良 non-KEEP 候補を 1 つ試す(探索が必ず動く)。これは「正しい探索」ではなく「動く探索」で、正しいかは oracle が決める。Jev の「触るな」が誤りかどうかも oracle 待ち。oracle が noise floor 上に何も見つけなければ、Claude と Jev の食い違い(`TermId::run` の inline(never)、バイトループの幅 16)で Jev の方が近かったことになる。
- **影響**: spec §1(3)、§6。API: 153 request で取りこぼし 0(503 はバースト、指数バックオフで全回収)、費用 0。

### 72. 順序の変更: 正解が存在する小さな対象で「Claude の判断 → 実測 → Jev」を先に閉じる
- **知見**: ユーザーの指摘(2026-09-22)。実験 3 で適用されたヒントは Jev のもの(全部 KEEP)で、Claude の判断が実際に速くするかは未測定(oracle A に 2 つ含まれ、幅 16 はループ側の oracle 待ち)。toy は plugin の機構検証にしか使っておらず、「このヒントで速くなる」正解が存在する小さな対象は無い。jaq はノイズが 2〜4% で 1 箇所の効果が個別に見えず、Claude の判断を実測なしに参照点にしていた。
- **判断**: 語彙の各ヒントが効くはずの構造を持つ関数 6〜8 個の「ヒントベンチマーク」crate(`targets/hintbench/`)を作る。site ≤ 12 で oracle は約 130 ビルド × 30 秒、ノイズは toy 並み。順序は (1) Claude が各カーネルの期待ヒントと機構を計測前に `EXPECTED.md` に書く → (2) oracle で実測の正解を得る(Claude の精度も測れる)→ (3) Jev を state v2 で当て、**実測の正解**との一致率を測る → (4) jaq に戻る。設計と実装は計測なしで oracle A と並行、計測は oracle A の後。
- **影響**: spec §6(対象の順序)、§9(実装順序)。判断後に反映。

### 73. prompt study 第 2 弾: 「強制」でなく「記述」で Jev は Claude の判断に届く(9 site 中 8、3 回とも同一)
- **知見**: (a) **選択肢の説明に適用条件を書く**(`inline(never)`「数千命令の本体や多数の複製で効く、小さな葉では逆効果」等)だけで、Jev が最大の body に `inline` を付ける挙動は全反復で消え、`TermId::run` と `write::write` に `inline(never)` を選ぶようになった(confidence 0.78)。(b) **機械的な判定行**(「u8 → 1 レジスタ 32 レーン → この一覧で収まる最大は 16」「本体 10496 命令、閾値の桁上」)を質問の横に置くと、バイトループで幅 16 を 3 回とも選ぶ。Jev はこの算術をしないが、してやれば従う。(c) 両者はループで干渉する(適用条件の文がバイトループを unroll 4 に引く)ので、**関数フェーズは適用条件付き説明、ループフェーズは判定行のみ**(W7)。結果 8/9 完全一致、24/27 安定。(d) 同じ説明文でも state のブロックに置くと 100% KEEP、`criteria` の中に置くと選ぶ。配置が本質。(e) legality の判定は完璧化(不能ループの vectorize 質量 0.056 → 0.003)。(f) 強制(KEEP 削除)は形状で選ぶようになったが「触るな」が正解の 6 site を落とすので依然誤った聞き方。2 択総当たりは診断には最良、提案には最悪。(g) 残る不一致は `read::parse`(Jev は `inline(never)`、Claude は触るな。根拠はどの判定行にも載らない inline host の情報)。`docs/experiments/jev-prompt-study/` Round 2。
- **判断**: state v2 = W7(判定ブロックは両フェーズ、適用条件付き説明は関数フェーズのみ)。決定 70(d) の「解説書を state に入れるな」は、一般的な機構説明を `criteria` に置く形に限り撤回(実測例と Claude の理由付けは従来どおり除外)。読み出しは決定 71 のとおり `1 − P(KEEP)` 順。**限界**: 閾値と文言を書いた人間は 9 site を既に見ている。参照判断が正しいかは oracle 待ち。ヒントベンチマークがこの限界を埋める測定になる(ベンチマークの site は閾値を書いた後に作られたものとして扱う)。
- **影響**: spec §6(state v2)、`scripts/jev_vocab.py` v2。

### 74. ヒントベンチマーク: 8 カーネル中 4 つは意図どおり作れなかった。うち 2 つは「ヒントが不活性」という発見
- **知見**: `targets/hintbench/`(8 カーネル、`EXPECTED.md` に計測前の期待と根拠)。(a) K4(u8 → u32 のバイト数え、jaq の `to_ascii_lowercase` と同形)と K5(u32 の乗算 reduction)は基準が既に VF 8 × IC 4 で、幅 16 も IC も余地がない。LLVM は reduction を持つベクトル化ループに常に最大の IC を返す。期待を KEEP_DEFAULT に改訂(K5 は `interleave.count=1` で大幅悪化するはずの校正 site に)。**Claude が study で選んだ幅 16 は、この形では効かない可能性が高い。** (b) `inline`(inlinehint)と `cold` は plugin が付け、LTO パイプラインの入力 IR にも属性が存在するのに、**inliner は無いかのように振る舞う**(remark の threshold が変わらず、インライン判断も変わらない)。`inline(never)`(noinline)と `align=64` は効く。原因は未確定(PGO の profile summary があると callee の inlinehint / cold 属性より profile 由来の hotness が優先される LLVM の設計が有力な仮説)。`results.md` §103〜§109。
- **判断**: (1) 原因を LLVM 23.1.1 のソース(`InlineCost.cpp` の閾値決定)で確認し、PGO 下で不活性なら語彙の `inline` を `inline(always)`(alwaysinline、profile に関係なく強制)に置き換えるか、`inline` / `cold` を「PGO 下では不活性」と明記して語彙から外す。jaq でも apply 1 本で確認する。(2) study で Jev が最も多く選んだのが `inline` だったので、結論の読み方が変わる(選んでも何も起きない候補だった)。
- **影響**: spec §1(2) 語彙、`jev_vocab.py` v2(要改訂)。

### 75. hintbench のビルドには `-Zcross-crate-inline-threshold=never` が必須
- **知見**: 無いと rustc の MIR inliner が 8 カーネル中 6 つを LLVM に届く前に消し、IR に無い関数には属性を付けられない。`-Cprofile-use` は MIR のハッシュで照合するので、計装ビルドにも同じフラグが要る(無いと `main` の profile が丸ごと hash mismatch)。
- **判断**: hintbench の固定フラグに追加。他の対象には影響なし。「マークした関数が LTO 後に存在するか」は dump で必ず確認する(jaq でも 2 マークがループを持たなかった)。
- **影響**: `scripts/target_common.sh`、`target_pgo_baseline.sh`。

### 76. hintbench の oracle は 93 ビルド、約 3 時間。ループ site は 4 に凍結
- **知見**: 12 site(関数 8 × 6 候補 + ループ 4 × 11 候補)。ループ site の凍結規則: ループヒントが検証対象のマークのみ、マーク内で hotness 最大の key 1 本。k3 は driver 側のループが `loop_in_mark` に紛れ込む(決定 61 の曖昧さの再現)ので規則 (2) が要った。
- **判断**: jaq の oracle A 完了後に `scripts/hintbench_oracle.sh run`。K2 の `inline` と K7 の `cold` は基準とコード同一なので in-sweep null パネルとして現れるはず(74 の追認)。
- **影響**: spec §9。

### 77. `inline`(inlinehint)と `cold` は、このレシピ(O3 + PGO + fat LTO)の下で実質不活性。語彙を v3 に改訂
- **知見**: LLVM 23.1.1 `InlineCost.cpp` で確定。inlinehint は読まれる(`:2137`、`max` で閾値を上げる)が、直後の hot / locally-hot callsite 分岐(`:2148〜2154`)が閾値を**代入で上書き**する(FIXME に「本来は超えたときだけ更新すべきだが AutoFDO + ThinLTO が依存」と明記)。`cold` の閾値 45 が適用される唯一のアームは `else if` 鎖の末尾(`:2163〜2179`)で、callsite が hot / locally hot / cold に分類された時点で到達不能。hintbench で観測した閾値 525 と 787 は `LocallyHotCallSiteThreshold`(525、O3 のみ)と単一 BB ボーナス(+50%)から完全に再現される。`hot` 属性は `InlineCost.cpp` に一度も現れない。`alwaysinline` と `noinline` は解析器が作られる前に決着し profile に免疫。さらに instrumentation profile の PSI-hot な callsite ではコスト便益解析が閾値比較を短絡する(remark が `benefit over cost` になる)ので、**jaq の最ホット site では閾値を動かす語彙は原理的に何も効かない**。plugin(PipelineEarlySimplification)の後に `PGOInstrumentationUse` が hot 関数へ inlinehint を付けるので、plugin の `inline` は冗長でもある。`docs/experiments/hintbench/inline-attrs-under-pgo.md`。
- **判断**: 語彙 v3: `inline` → **`inline(always)`**(PGO 下で唯一生きている正方向のインライン梃子。plugin に alwaysinline の分岐を追加、`noinline` を先に外す、`optnone` の callee はスキップ、callee がモジュールから消えるケースに dump / 正規化ハッシュが耐えること)。`cold` と `hot` は語彙から**外す**。`inline(never)` と `align=N` はそのまま。ループヒントは不変。決定 70・73 の一致率は「不活性な候補(`inline`)での一致」を含んでいたので、v3 で取り直す。study の Claude の参照判断 `inline(never)` 2 件はそのまま有効。
- **影響**: spec §1(2)、`jev_vocab.py` v3、plugin、hintbench の `EXPECTED.md`(K2 は `inline(always)` で効きうる)。

### 78. 語彙 v3 を実装。走行中の jaq oracle A は v1(inline / cold の arm を含む)のまま完走させる
- **知見**: plugin に alwaysinline(`noinline` を先に外す、`optnone` はスキップして報告)を追加し、toy で属性が判断を駆動する remark(`always inline attribute at callsite`)と出力一致を確認。v3 の候補は関数 5(`inline(always)` / `inline(never)` / `align 16・32・64`)+ ループ 11。oracle の arm 数は hintbench 84+1、jaq 251+1。fat LTO では依存 crate 側のプロセスからは callee の存否が観測できないため `callee_present` は 3 値(null = 未観測)。走行中の jaq oracle A は起動時の既定 v1 で 90 arm(inline と cold を含む)。掃引途中で `.so` を差し替えたが、新パスは watch 集合が空なら即 return で codegen は変わらない(manifest の sha とは以後不一致。provenance として記録)。
- **判断**: oracle A は止めずに完走させる。決定 77 の予測どおりなら `inline` と `cold` の 30 arm は基準とコード同一の null パネルとして出るはずで、jaq 上での追認になる。`--resume` する場合は `--vocab v1` を明示(resume は件数による位置スキップのため)。完走後の順序: hintbench の oracle(85 arm、約 3 時間)→ Jev v3 を hintbench に当てて実測の正解との一致率 → jaq。`sites.json` の oracle 見積もりと spec §1(2) の語彙表は v3 に合わせて後で更新。
- **影響**: spec §1(2)、§2、`targets/jaq/sites.json`。

### 79. jaq の関数属性 oracle(90 arm、7.4 時間): MDE を超えるものは実質ゼロ。Jev の「触るな」は反証されず、Claude の `inline(never)` 2 件も効かなかった
- **知見**: 91 ビルド全て出力一致、plan 全件 consumed。訓練で +3% を超えたのは `TermId::run cold` 1.032 の 1 本だけで、同じバッチの A/A(同一バイナリ)が 1.026 動いていた。holdout では最良単独アームが 0.991(符号反転)、12 マークの最良を組み合わせた plan も 1.004。MDE 4.1%。下方に MDE 超えは 3 本(`Lex::seq` と `write_until` への `inline(never)` が −5%、−4%。`write::write cold` −3%)。Claude の参照判断 `TermId::run inline(never)` と `write::write inline(never)` はどちらもそのマークの最良ではなく、効かなかった。**90 arm のうち 48 本は基準と命令列が同一の no-op**(`align=16` は 15 本全部、`inline` 10/15、`cold` 9/15、`inline(never)` 6/15): hintbench で見た不活性の実プログラムでの再現。`results.md` §110〜§117、`docs/experiments/jaq-oracle-A/`。
- **判断**: (a) 関数属性の語彙は、jaq の PGO 基準の上では速さを出さない。Jev の 107 件の `KEEP_DEFAULT` は関数属性については**正しかった**。Claude の 2 件は外れ。(b) 「Jev ÷ oracle」は分母がノイズと区別できず計算不能。(c) jaq のループ半分の oracle(176 arm、14 時間)は後回しにし、先に hintbench(正解が存在するはずの対象)で oracle → Jev v3 を閉じる。
- **影響**: spec §2、§6。

### 80. 測定の較正が壊れている: バッチ内 bootstrap の 95% CI は同一バイナリで 90 回中 41 回 1 を除外する
- **知見**: 専用 null パネル(同一バイナリ 4 本)は最大差 0.77 pt だが、掃引内の no-op ビルド 48 本は 4.67 pt に散らばり、20 本の CI が 1 を除外。in-run A/A は 90 回中 41 回で CI が 1 を除外。バッチ内の再スケールでは救えない。事前登録の採用規則 3(CI 下限 > 最良)は、この n ではノイズで通る(実例 3 本)。plugin の apply レポートは関数属性に `skipped_idempotent` 判定が無く全部 consumed を返すので、no-op はバイナリ側(正規化命令列 + シンボル表)でしか判定できない。
- **判断**: (a) 採用は 1 バッチで決めない。MDE を超えた arm は**独立した別バッチで再測定**し、両方で CI 下限 > 1 のときだけ採用(確認バッチ)。ノイズの定義は「同じペアを独立バッチで k 回測ったバッチ間の散らばり」に変える。(b) apply 後に正規化命令列を基準と比べ、no-op のアームは計測せずに「基準と同一」として記録する(掃引の半分が省ける)。(c) 関数属性の 1 Choice がジェネリックマークの全クロージャに波及していた(決定 65(b) の判定はマーク直後の 1 文字しか見ていない)。hintbench の前に直す。
- **影響**: spec §2(採用規則)、§7(ノイズ定義)、driver。

### 81. hintbench への Jev v3 の一発回答: 12 site 中 10 が Claude の予測と完全一致。ただし doc コメントの漏れが交絡
- **知見**: 関数 6/8、ループ 4/4 が完全一致、11/12 が 3 回とも同じ答え。`1 − P(KEEP)` 順の首位は両フェーズで Claude の予測勝者(k6 `align=64`、k3 fill `unroll.disable`)。不一致は k1(Jev は KEEP、Claude は `inline(never)`)と k7(Jev は揺れ、confidence 最低)。**交絡**: カーネルの doc コメントが「the hint under test is …」とヒント名を書いており、それが state の source 窓に入っていた。非 KEEP の 4 件中 3 件がコメントの名指しと一致(ただし k1 は従っておらず、決定的ではない)。state の欠陥も 3 つ: legality の判定行が共有 remark 行の誤帰属で 4 ループ中 3 つを誤って「不能」と書く、k2 の `cost 870 > threshold 787` が呼び出し側の行に帰属して見えず budget 行は逆を言う、`sites.json` の share が全マーク 12.5% 固定で hotness 区分に判別力が無い。API は 503 のバーストで 1 回全滅し、無改変で再送して回収。`docs/experiments/hintbench/jev-oneshot-v3.md`。
- **判断**: (a) source 窓からコメントを除く(driver 側のフィルタ。カーネルのソースは触らない。行番号が動くと key と profile が変わるため)。(b) コメントを除いて一発回答を取り直し、10/12 が維持されるかを見る(これが本当の一致率)。(c) legality の帰属と k2 の cost 帰属は state の既知欠陥として記録し、plugin 側で per-loop の事実を出す改修を検討(後日)。(d) この 10/12 は oracle の実測が出るまで「Claude との一致」であり「正解との一致」ではない。
- **影響**: driver(source 抜粋のフィルタ)、spec §6。

### 82. コメントの漏れを除くと、Jev v3 の一発一致は 10/12 → 7/12。非既定の正答は漏れが作っていた
- **知見**: source 窓から Rust のコメントを除く `--source-comments strip`(既定)を driver に実装(カーネルのソースは不変、行番号も不変)。取り直すと、関数 4/8、ループ 3/4 の一致。pass1 で当たっていた非既定 3 件のうち k6 `align=64` と k3 fill `unroll.disable` は消滅(どちらもコメントが名指ししていたヒント)。残った k2 `inline(always)` も、pass2 では関数 8 site 全部で `inline_always` が最良非既定候補、4 site で argmax、というフェーズ一律の答えがたまたま k2 で正解した形。対照カーネル k8 まで `inline_always` を拾う。関数の confidence は全 site 0.34〜0.48 に崩れ、ループは全 KEEP。`1 − P(KEEP)` 順の首位も Claude の予測勝者から外れた(決定 71 への最初の肯定証拠は消えた)。コメントは送信量の 12% で、`///` の 1 行だけでなく各カーネル上のブロックコメントが機構そのもの(「8 か所にインライン展開されて約 1000 命令」)を書いていた。`docs/experiments/hintbench/jev-oneshot-v3.md` §9〜§15。
- **判断**: (a) 一発の Jev v3 は、漏れの無い state では Claude の予測をほぼ再現しない。関数フェーズには `inline_always` への一律の偏りがある(適用条件の記述が強すぎる可能性。v3 の関数の説明文を見直す)。(b) hintbench の state 欠陥(legality の誤帰属 3/4、k2 の cost 帰属、share 一律)を直してから、「結果のフィードバック付き 5 ラウンド」を回す。「いろいろやる」の本体はフィードバックであり、一発一致は前提ではない。(c) study 第 2 弾の 8/9(jaq)も、閾値と説明文を書いた人間が site を見ていたという別種の漏れを含む。正解との一致は oracle でしか測れない。
- **影響**: `jev_vocab.py` v3 の関数説明文(要見直し)、spec §1(3)、§6。

### 83. state の証拠を機械的に修復: inline の remark は callee 名で集計、legality はループ自身の位置からだけ、一律の share は分類しない
- **知見**: (a) inline の remark は呼び出し側の行に付くので、定義周辺の窓では原理的に拾えない。callee 名で索引すると 8 マーク全部が `EXPECTED.md` の根拠を独立に再現(k2 は「2 call site が cost=870 > threshold=787 で拒否」)。(b) ループの legality を leaf の `file:line:col` 完全一致で取り、同じ行に複数ループの判定行が出ていれば「UNKNOWN(共有行)」と書く。hintbench の 4 ループ中 3 つが共有行(17〜18 ループ分の remark が混在)で、以前の「NOT VECTORIZABLE」は誤りだった。`already_vectorized` は VectorizerStart(LoopVectorize の前)で見ているだけなので `no` が正常。(c) 全マークの share が同一値なら hotness を書かない。jaq は無影響で完走。`docs/experiments/hintbench/jev-oneshot-v4.md`。
- **判断**: v3 の state を v3.1 に(語彙は不変)。dump を一次情報と明記。次に直すべきは prompt でなく**帰属**(共有行のループには「LLVM が何をしたか」を載せられない。plugin にベクトル化後の状態を記録させるか、`remark_attribution.py` を state に繋ぐ)。
- **影響**: driver、spec §6。

### 84. 語彙 v4: 関数ヒントの説明を長さと強さで対称にする。一律の `inline_always` 偏りは記述でなく state の壊れが主因だった
- **知見**: v4 は 6 候補すべて 4 文・「helps where / hurts where」の対・383〜411 字(v3 は 161〜876 字で 5.4 倍差)。壊れた state(pass2)では 8/8 site で `inline_always` が最良非既定、confidence 0.34〜0.48。**state を直しただけ**(v3.1)で 5/8、対照カーネルの偏りも消え、confidence 0.73〜0.97 に回復。v4 は argmax を 1 つも動かさず、残る 2 site(k2、k6。基準がインラインを断っている唯一の 2 マークで、判定行がコスト単位でそれを言う)の質量を半減。EXPECTED との一致は両方 5/12(関数 5/8、ループ 0/4)、12/12 安定。ループでは UNKNOWN にしたことで vectorize の質量が跳ね、k4 は判定行のレーン算術に従って幅 16(P 0.85)、k5 / k8 は基準と同じ幅 8 を要求(null 候補)。k6 は `inline(always)` を選び、Claude はそれを検討していなかった。
- **判断**: v4 を既定にする。一致率の低下(10 → 7 → 5)は劣化ではなく、漏れと誤った前提が剝がれた結果。正解は oracle。k4 の幅 16(Jev)対 KEEP(Claude)、k6 の `inline(always)`(Jev)対 `align=64`(Claude)は、oracle が決着させる具体的な争点。
- **影響**: `jev_vocab.py` v4、spec §1(2)、§6。

### 85. hintbench の oracle(85 arm、4.1 時間): 正解が出た。`inline(always)` が k2 で +67.8%、幅 16 が k8 で +8.8%、unroll 4 が k3 で +4.4%
- **知見**: 85 arm 全部で出力一致。基準と同一のバイナリは 39 本(関数 27/40、ループ 12/44)で計測をスキップ(3.1 時間削減)。null パネルはバッチ内 0.08 pt、バッチ間 0.17 pt(jaq の 0.77 / 4.67 pt よりはるかに静か)。較正 arm(k5 `interleave.count=1`)は予告どおり −70%。**生きているヒント 9/16、うち正方向に効くのは 3 つだけ**: `inline(always)`(k2 +67.8%、`mode` がリテラルになって 60 段の `imul` 鎖が `lea` に。callee はシンボル表から消えた)、`vectorize.width=16`(k8 +8.8%、k5 +2.65%)、`unroll.count=4`(k3 +4.4%)。`align` 3 種は 1 つも動かない(エントリは 64 境界に動くが時計は動かない)。`unroll.disable` と `interleave.count=1` はベクトル化済みループでは同一命令(44 arm 中 8 本が重複測定。jaq の 176 arm にも同じ無駄がある)。組み合わせは訓練 +8.8%、第 3 バッチ +8.5%、カーネル別効果がほぼそのまま残る。`results.md` §118〜§128、`docs/experiments/hintbench/oracle.md`、`EXPECTED.md` §5。
- **判断**: (a) この基準で速さを出せるヒントは、強制インライン(定数特殊化を解く)、ベクトル幅、unroll 回数、の 3 種。関数属性の `align` は語彙から外してよい(次回)。(b) `unroll.disable` はベクトル化済みループでは `interleave.count=1` と同じなので、片方に統合する。(c) jaq の関数属性 oracle は 1 Choice が 60 クロージャに波及していた(決定 80c 修正で 138 → 49 entry)ので、jaq の関数半分は修正後に再実行が要る。
- **影響**: spec §1(2)、§9。

### 86. Claude の予測は 8 問中 1 問正解(MDE ゲートで 3)。`inline(never)` の符号を 3 回外した。効果量の較正は良い
- **知見**: 素点 1 hit(k2)/ 1 same-family(k3: `unroll.disable` は −17%、正解は `unroll.count=4`)/ 6 miss。K1 `inline(never)` は −4.6%(8 箇所が out-of-line になるコストより、インライン済みコピーが得ていたスケジューリングの損が大きい)、K7 は 0、K6 `align=64` は 0。対照カーネル K8 は「余地なし」の予測に反して幅 16 で +8.8%。K4 では「幅 16 は帯域を増やせない」が正しく −42%、K5 では同じ論が逆で +2.65%(遅延律速の reduction では幅を広げると鎖が増える)。効果量のバンドは 8 中 4 が的中。
- **判断**: Claude の「どのつまみか」の判断は信用できない(正解との一致は Jev より低い)。参照点は Claude ではなく oracle。決定 69 の指標「Claude との一致率」は補助に降格し、主指標は「oracle の正解との一致率」。
- **影響**: spec §2。

### 87. Jev v4(state 修正後)の一発回答を正解で採点: 関数 7/8(k2 の +67.8% を含む)、ループ 0/4(k4 で −42% の有害な選択)
- **知見**: 関数フェーズ(MDE ゲート、正解 = 確認済みで MDE 超えの最良、無ければ KEEP): k1 KEEP ○、k2 `inline(always)` ○、k3 KEEP ○、k4 KEEP ○(`inline(never)` +1.5% は MDE 未満)、k5 KEEP ○、k6 `inline(always)` ×(正解 KEEP)、k7 KEEP ○、k8 KEEP ○。**Claude(3/8)より高い。** ループフェーズ: k3 KEEP ×(正解 `unroll.count=4`)、k4 `vectorize.width=16` ×(**−42%**、正解 KEEP)、k5 `vectorize.width=8` ×(null、正解は幅 16 だが MDE 未満なので KEEP 扱い)、k8 `vectorize.width=8` ×(null、正解 `vectorize.width=16` +8.8%)。ループでは state に「LLVM が何をしたか」が載らない(共有行で UNKNOWN)ため、判定行のレーン算術に従って一律に幅を選んでいる。
- **判断**: (a) 関数属性については、state の証拠が揃えば Jev の一発判断は正解に近く、Claude を上回った。k2 の +67.8% を一発で当てたのは本プロジェクトで最初の「Jev のヒントで速くなった」事例。(b) ループでは一発は当たらず、有害な選択(k4)もある。フィードバック付きラウンド(測って結果を返す)が必須で、正しさと速度のゲートが有害な plan を止める。(c) ループの state は帰属の改善(plugin でベクトル化後の VF / IC / 判定を記録)が要る。
- **影響**: spec §1(3)、§2、§6、plugin(次の改修)。
