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
