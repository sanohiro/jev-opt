# jev-opt 実装仕様(v0.5、日本語正本)— マークした関数を Jev がヒントで速くする

実験の問いは **「人または Claude がマークした関数を、Jev がヒントで最大限速くできるか」** の一点である。v0.3(ループヒントのグローバル掃引)と v0.4(PGO 訓練データ選定・FP 再結合)は git 履歴(`git show c58545d:SPEC.ja.md` が v0.4、その中の参照 `3a41f49` が v0.3)と `docs/decisions.ja.md` に残っており、否定結果と経緯はそちらを参照する。v0.5 は決定 58 の 4 項目にそのまま戻したもので、それ以外は仕様から落とす。本文は決定 66〜109 を反映済み(語彙 v5、state v5.0/v5.1、読み出し規則、採用規則、探索と再訪、ベクトル化後事実、503 方針、k5 の計測モード、反復による機能別評価、hintbench の実測、対象の順序、argv[0] 長の固定、語彙 v6、zopfli の訓練分割、zopfli の実測、no-op 指標、小さく検証、protocol v2、MDE v2 とその確定、マーク選定の規則。決定 107・108 は API のみの study で、仕様には 108 の結論(Jev は機械規則と同点)と 109 の規則だけを入れる)。決定 60・62・75〜78 は実装状況として参照する。決定事項の一覧表はこの仕様には置かず `docs/decisions.ja.md` を正本とする。方針は 4 つ: **速さは追求する / 作りはシンプルにする / 判断は Jev に任せる / わかりやすくする。** 最適化は対象のソースを書き換えずに行う。本文中の主張は **実測 / 仮説(ソース確認のみ)/ 未測定** を明示する。

## 1. 一枚で分かる

### (1) マーク: 速くしたい関数を指定する(既定は規則の種 + 灰色帯 Jev、人や Claude が指定してもよい)

- **既定の手順(決定 109)**: `scripts/target_marks.py` が perf の表から機械的に選ぶ。**種** = 訓練 reach の上位 N ∪ 訓練 self の上位 N(C・サンク・コンパイラ生成を除いた中で。問わずにマーク)。**灰色帯** = reach か self が 1% 以上の残りの関数で、Jev に mark / skip の Choice を 3 回聞き中央値 P ≥ 0.5 でマーク。除外 = IR 無し / C、サンク(≤ 8 命令)、1% 未満。N は凍結マークの本数(jaq 15、zopfli 6、hintbench 8。`--marks-n`)で、最終集合は N を超えてよい。出力は `jev-marks.jev.txt` と根拠 `jev-marks.jev.rationale.md`。driver は `--marks` が無ければ最新の生成済みファイルを使い、無ければ 1 回だけ生成する(perf の表が無ければ準備として取る)。凍結済みの `jev-marks.txt` は既存の比較のために残し、置き換えは対象ごとにオーナーが決める。API での検証は `results.md` §179(jaq は 34 行で正解 2/2、zopfli は 14 行)。
- 人または Claude が直接指定してもよい: perf の上位を見て、速くしたい関数を選ぶ。**方法は問わない**(人が読んで決めてもよい)。**ビルドの工程には組み込まない。** Claude は人間の代理人であってシステムの部品ではない。Jev だけにマークを選ばせる形は決定 108 で「機械規則と同点、上回らない」と分かっており、既定にはしない。
- 形は 2 つ、どちらでも受ける。(a) `jev-marks.txt` — 1 行 1 関数、Rust のパス名(`jaq_core::interpret::run`)。(b) 対象ソース中の `#[jev_opt::optimize]` 属性 — CLI がソースを走査してマークに変換する。
- **解決は CLI 側で行う**(plugin は Rust のパス名を知らない)。`dump` は**全関数**の表と**全ループ**を出し、CLI が `rustc-demangle` で demangle してマークに一致するものだけを site に残す。generic は全単相化にマッチさせる。解決件数 0 の行はエラーで止める。

### (2) ヒントの一覧は固定・全マーク共通

| 種別 | ヒント | 値域 | 適用先 |
|---|---|---|---|
| 関数属性 | `inline(always)` / `inline(never)` / `align=N` | N ∈ {16, 32, 64} | マークされた関数(LLVM 属性 `alwaysinline` / `noinline` / `align`) |
| ループ | `unroll.count=N` / `unroll.disable` | N ∈ {2, 4, 8} | マーク内の各ループ(`llvm.loop.*` metadata) |
| ループ | `vectorize.width=N` / `interleave.count=N` | width ∈ {2, 4, 8, 16}、interleave ∈ {1, 2, 4} | 同上 |
| コンパイラ設定 | `-Cllvm-args` の少数のノブ | `llvm-knobs.json` から事前選定(決定 31 で動いた SLP 閾値・アラインメント系) | ビルド全体に 1 つ。マーク単位ではない |

**v5 で `align` 3 種と `unroll.disable` を外した(決定 85・93)。**

- **`KEEP_DEFAULT`(=「何もしない」)を常に候補に含める。** 候補から外すと Jev は定数回答(関数は一律に同じインライン候補、ループは全部 `unroll.disable`)になる(決定 70(d)、v2 語彙での実測)。語彙はラウンド 1 の前に凍結し、途中で足さない。足した場合は再測定する。
- **語彙 v3(決定 77)。`inline`(inlinehint)と `cold` は語彙から外した。** このレシピ(`-Copt-level=3` + PGO + fat LTO)では、inliner は callee の属性を読んだ直後に **callsite の hotness クラスで閾値を代入上書きする**ので inlinehint は実質不活性(`InlineCost.cpp:2137` で読み `:2154` で破棄)。`cold` の閾値 45 を使う `else if`(`:2163〜2179`)は callsite が hot / locally hot / cold のいずれかに分類された時点で到達不能。`hot` は `InlineCost.cpp` に一度も現れず、そもそも inliner の入力ではない。`alwaysinline`(`:3209`)と `noinline`(`:3242`)は cost model が作られる前に決着するので profile に免疫(以上 **ソース確認**、LLVM 23.1.1、`docs/experiments/hintbench/inline-attrs-under-pgo.md` §7)。**実測**でも、hintbench では `inline` / `cold` を付けても remark の閾値が動かず(`results.md` §103〜§109)、jaq の関数属性 oracle では **90 arm 中 48 本が基準と命令列同一**だった(`inline` 10/15、`cold` 9/15、`align=16` 15/15。決定 79)。plugin の後段で `PGOInstrumentationUse` が hot 関数へ inlinehint を付けるので plugin の `inline` は冗長でもある。`inline(always)` が速くすることは **実測で確認済み**(hintbench K2 で **+67.8%**。決定 85)。**ループのヒントは v2 から不変。**
- **語彙 v4(決定 84)。候補の説明文を長さと強さで対称にしただけ**(6 候補すべて 4 文・「効く形 / 逆効果の形」の対・383〜411 字。v3 は 161〜876 字で 5.4 倍差)で、**argmax は 1 site も動かなかった**(実測)。v3 で見えた `inline_always` への一律の偏りは記述ではなく state の壊れが主因で、state を直しただけで消えた(決定 83・84)。
- **実測で生きているヒントは 3 種だけ(決定 85、hintbench oracle 85 arm)**: **強制インライン**(`inline(always)`、定数特殊化を解く)、**ベクトル幅**(`vectorize.width=16`)、**unroll 回数**(`unroll.count=4`)。16 候補中 9 つは MDE を超えて動かせるが、正方向に動かせるのはこの 3 つだけで、残る 6 つは遅くする梃子である。
- **`align` 3 種は 1 つも動かなかったので語彙から外す予定**(実測根拠: `align=16` は 8/8 が基準と命令列同一、`align=32` / `align=64` は 6/8 が同一で、残る 2 本も最大 0.7%・未確認。oracle §9)。**`unroll.disable` はベクトル化済みループでは `interleave.count=1` と同一命令**なので片方に統合する(k5 / k4 / k8 で比が 0.2941 / 0.2957 など一致し、44 arm 中 8 本が重複測定だった)。ただし**ベクトル化されないループでは別物**(k3 では `unroll.disable` が unroller に届いて −29.4%、`interleave.count=1` は不活性)で、`sites.json` の `already_vectorized` は `VectorizerStartEP` で読むので**どちらのループかを事前に言えない**(決定 85(b)、oracle §9(b))。
- **語彙 v6(決定 98)。** v5 は凍結のまま、v6 = v5 + ループ `unroll.disable` を戻した版で、zopfli にのみ使う(語彙一覧そのものは全マーク共通のまま、対象単位でどの版を使うかを選ぶ)。決定 85(b) の統合(直前の 2 箇条)はベクトル化済みループでの観測が前提だったが、zopfli の Stage 0 で唯一効いた `-unroll-max-count=1`(+1.6%、`cache.rs:108`)は LLVM がベクトル化しないループの「アンロールしない」で、そこでは `interleave.count=1` が no-op のまま `unroll.disable` だけがアンローラを止める(実測、`results.md` §31.1・§31.3、remark「unable to calculate the loop count」)。v5 のままでは zopfli の既知の正解を語彙が表現できないため、版を分けて足した。
- 一覧は全マークで同じ。site ごとに候補を絞る作業(それは最適化そのもの)は**しない**。

### (3) Jev がいろいろやる

1. マークされた関数と、その中のループを site として列挙する(`dump`)。
2. **site ごとに Jev が Choice を 1 回**、(2) の一覧から 1 つ選ぶ。関数フェーズとループフェーズでそれぞれ 1 request(**1 request / phase**)。
3. plugin が plan を適用してビルドする(ソースは触らない)。
4. 測る(§7 の手順)。
5. 結果(site ごとの選択、集計速度比と 95% 信頼区間、採用 / 不採用)を state に入れて次の Choice へ。
6. 決めた回数(初期 **5 ラウンド**)繰り返し、**最良の plan を残す**。

- **読み出し規則(決定 71)**: driver は argmax だけを使わない。site を `1 − P(KEEP_DEFAULT)` の降順に並べ、**全 site が `KEEP_DEFAULT` でも首位 site の最良の非既定候補を 1 件だけ試す**(空 plan では結果のフィードバックが生まれず、探索が止まる)。**これでは足りないことが実測で分かった**: hintbench の Jev 5 ラウンドで `forced_top1` は**一度も発火しなかった**(k2 が毎回非 KEEP なのでフェーズ全体が KEEP にならない)ため、取りこぼした 2 件はどちらも**一度も試していない候補**だった(決定 88(b))。
- **探索機構を足す(決定 89(b))。実装済み(決定 90)。explore は既定 ON なので、ラウンド 1 は一発回答の対照にならない(90)。再訪予算(決定 92・93)の適格条件は『argmax を上書きしない』と衝突し、非 KEEP に固定された site には届かない(93)。** 各ラウンドで、**非既定を一度も試していない site のうち hotness 上位 K(1〜2)**に対して「**未試行の候補から選ぶ**」Choice を追加する。候補集合は機械的に未試行のものだけで作り、Claude は絞らない。あわせて (a) **採用は plan が変わった場合のみ比較する**(決定 89(a))、(c) 履歴に**そのヒントが他ケースで出したコスト**を載せる(`inline(always)` は k6 で不活性だが k3 で −2.8%)、(d) **複数 site が 1 ケースを共有する場合は履歴に明記する**(k4 の関数 site とループ site は per-case の読み出しで分離できない)。ループの state には「LLVM が何をしたか」が載らない(共有行で UNKNOWN)ので、**plugin にベクトル化後の VF / IC / 判定を記録させる**(決定 87(c))。実装済み(決定 90)。判定行(`--pv-untried`)は Jev に届くが、k8 の幅 16 は浮かせなかった(93)。
- **フィードバックはフィルタとして機能し、探索としては機能しない(実測、決定 88)。** hintbench の 5 ラウンドで、R1 の有害な選択(k4 の `vectorize.width=16`、単体 −42%)は 1 ラウンドで捨てられ(確率 0.88 → 0.28 → 0.07)、効いた選択は強化された。しかし試していない候補については何も語れない。上の探索機構はこの穴を埋めるためのものである。
- **state / 語彙 v4**(`state-v4.1-2026-09-22` / `v4`。v3.1 の証拠修復に per-case の読み出しを足したもの)の要点: (a) 質問文は V2(「変えるべきか」ではなく「この workload でこの関数を速くする可能性が最も高いヒントはどれか」)、(b) `KEEP_DEFAULT` は中立に記述する(基準の再現であって消極的選択ではない)、(c) **関数フェーズの選択肢の説明にだけ適用条件を書く**(効く形・逆効果の形・no-op の形。ループフェーズに同じ文を置くと唯一機構のあるループの選択が壊れる)、(d) **両フェーズに機械的な判定行**(size / copy / trip / hotness / lanes / legality / inline budget を、state が数値で持っているものを読み上げた形で置く)、(e) **platform ブロック**(`lscpu`、キャッシュ、`-march=native` の解決先、レジスタ幅)、(f) **1 request / phase**、(g) **per-case の読み出し**(ラウンド履歴に全ケースの比と 95% CI、site の履歴にはその site 自身のケースの比・CI・採用可否を書く。集約比だけだと k4 の −42% が「−6%」としか届かない。exp4 §1.4)。**ループの候補と説明文は v2 から不変**(v3 / v4 が触ったのは関数側だけ)なので、ループ site に差が出たら語彙以外 — state の証拠(決定 83)かフィードバック — が原因。
- **state の証拠は機械的に直してある(決定 83、実測)**: inline の remark は呼び出し側の行に付くので**callee 名で索引**する(8 マーク全部が `EXPECTED.md` の根拠を独立に再現)。ループの legality は**そのループ自身の `file:line:col` 完全一致でだけ**取り、同じ行に複数ループの判定が混じるなら「UNKNOWN(共有行)」と書く(hintbench の 4 ループ中 3 つが共有行で、以前の「ベクトル化不能」は誤りだった)。全マークの share が同一値なら hotness を書かない。**書き方より帰属が効く**: 語彙を v4 にしても argmax は動かなかったが、state を直しただけで関数フェーズの一律の偏りが消え、confidence が 0.34〜0.48 → 0.73〜0.97 に回復した(決定 84)。
- 聞き方の探索は打ち切ってよい(決定 70・73、実測): 18 通り × 9 site × 3 回で、**聞き方は confidence を大きく動かすが結論はほとんど動かさない**。効いたのは適用条件つき**記述**と**判定行**だけで、同じ文でも state のブロックに置くと 100% KEEP、`criteria` の中に置くと選ぶ — **置き場所が本質**。`KEEP_DEFAULT` を外す「強制」は定数回答を招くので誤った聞き方。**remark は外さない**。platform / profile の構造化と 1 問 1 request は選択を 1 site も変えなかった(記録のためブロックは残す)。この study の 8/9 は Claude との一致であり、**正解との一致ではない**(決定 82(c)、86)。

### (4) 測る

基準と Jev の最終 plan を比べる。補助として **oracle**(全候補を機械的に回した上限)と**ランダム探索**(同ラウンド数)を同じ手順で回し、Jev が賢く探せているかを見る。

## 2. 問いと結論の出し方

| 指標 | 定義 | 値 |
|---|---|---|
| **主指標** | Jev の最終 plan − 基準(集計速度比、95% 信頼区間つき) | hintbench **Exp5/Exp6 で +7.4〜7.8%**(決定 92・93)。jaq `Val::hash` の inline(always) +4.5% が 1 本、見出しはフラット(決定 91)。zopfli は oracle の天井自体が +1.8%(v1 の MDE 3% 未満。確定した MDE v2(集計 A/A × 2、下限 1%。zopfli は 1.00%)の事後読みでは、組み合わせ +1.81 / +2.06 / holdout +1.77% と `squeeze.rs:325` の `unroll.count=8` +1.26 / +1.29 / holdout +1.33% が 3 脚とも超える再現性のある +α。事後の読みと明記する。決定 105・106)で、Jev vs ランダム(各 n=3)は採用 plan 6 走行とも 0、代表値は両アームとも基準の 1.0000 で n=3 では未解像(決定 100・101) |
| **主指標(判断の質)** | **oracle の実測の正解との一致率**(site ごとに 完全一致 / 同族 / 不一致 / **有害**。正解 = 2 バッチで確認済みかつ MDE 超えの最良、無ければ `KEEP_DEFAULT`) | hintbench 一発 **7/12**(関数 7/8、ループ 0/4。決定 87)、最終 plan **9 完全一致 / 1 同族 / 2 不一致 / 0 有害**(決定 88) |
| **主指標(探索の質)** | **oracle の組み合わせの何 % に届いたか** = `(plan − 1) ÷ (combination − 1)` を同種のバッチ同士で | hintbench **71〜77%**(訓練)、**79.4%**(第 3 バッチ)。ランダムは **0%** |
| 補助 | **Claude の参照判断との一致率**(決定 69。**決定 86 で補助に降格**) | hintbench で Claude は 8 問中 **1 問**(MDE ゲートで 3)、Jev は関数 7/8 |
| 補助 | Jev vs ランダム探索(同ラウンド数、同 site 集合、同じ n) | hintbench: 採用ラウンド 2 対 **0**、有害選択 2(いずれも 1 ラウンドで撤回)対 **5**(撤回なし) |
| 参考 | 待ち時間・費用(Jev 呼出しの合計) | hintbench の Jev 5 ラウンド(29 分)で 12 リクエスト(10 本 + 503 の再送 2 本)、**費用 0**、実時間の **1.1%** |

- **基準**: PGO + LTO + `-Ctarget-cpu=native` で固定。**PGO の訓練は合成ワークロードで行い、準備扱いとする**(全アーム・全ラウンドで同一の `merged.profdata` を共有し、その sha256 を記録する)。訓練集合の選び方は主題から外した(決定 55、§10)。
- **oracle**: 候補の直積は指数なので回さない。定義は **(a) site ごとの 1 因子掃引**(各 site で候補 1 つだけを既定から変え、他は `KEEP_DEFAULT`)+ **(b) 各 site の最良を組み合わせた 1 本**。(b) が (a) の最良を下回ることは起こりうるので、oracle = (a) と (b) を含む全アームの最良とし、そのことを結果に明記する。ビルド数は Σ(site 数 × 候補数) + 1 なので、**マークは数〜十数関数に抑え**(決定 57)、`[search] max_sites` を凍結して oracle のビルド数を事前に記録する。
- **参照判断そのものを実測で検証した結果、Claude は参照点として使えない(決定 86)。** hintbench の oracle で採点すると Claude の「どのつまみか」は **8 問中 1 問**(MDE ゲートで 3)で、`inline(never)` の符号を 3 回外した。予測どおりに付ければ K2 で +67.8% を取る一方、K1 に −4.6%、K3 のループに有害な `unroll.disable`(0.71、正解は `unroll.count=4` +4.4%)、K6 に無効な `align=64` を入れることになる(**集計として測った arm は存在しない**。site 別 arm の実測から言える範囲)。対照のはずの K8 でも「余地なし」の予測に反して幅 16 が **+8.8%**。**効果量の較正だけは良い**(8 中 4 がバンド内)。jaq でも **Claude の `inline(never)` 2 件はどちらも効かず、Jev の 107 件の `KEEP_DEFAULT` は関数属性については正しかった**(決定 79)。よって**参照点は Claude ではなく oracle**とし、一致率は oracle の正解を分母にする。
- **hintbench の実測(決定 85〜88)。** oracle は 85 arm・4.1 時間で全 arm 出力一致、39 本は基準と同一バイナリなので計測をスキップした(3.1 時間削減)。組み合わせは訓練 **+8.8%**、確認バッチ +8.6%、第 3 バッチ(hintbench は訓練/holdout を分けないので同じ 8 ワークロードの独立バッチ)+8.5% で、カーネル別効果がほぼそのまま残る(claim の積が +22.4% で実測 +2.15% だった jaq とは逆)。Jev(v4、フィードバック付き 5 ラウンド)は **+6.3〜+6.8%**(9 バッチが 1.0628〜1.0679)= **oracle の組み合わせの 71〜77%**、ランダムは 5 ラウンドで 1 つも採用されず **0%**(58 回答中、速くできる 3 つのヒントを 1 つも引かなかった)。**有害な選択は速度ゲートが全部止め、出力不一致は 10 ラウンドでゼロ。** 取りこぼした 21% の主因は k3 ループの `unroll.count=4`(+4.4%)と k8 ループの幅 16(+8.8%)で、どちらも**一度も試していない候補**である(§1 (3) の探索機構)。残りは組み合わせ側が拾っている MDE 未満の 2 件(k5 ループの幅 16 +2.65%、k4 関数の `inline(never)` +1.5%)で、この protocol の 3% 床では取りに行かない(確定した MDE v2(決定 106)では hintbench の集計 MDE は 1.00%、カーネル別の主張は §162 の A/A から 1.00〜3.18%。Exp4〜6 の見出しは v1 で読んだまま再採点しない)。
- **ノイズと最小効果量**: holdout の前に同一バイナリを 2 ラベルにした **A/A** を同一手順で回す。**jaq の A/A はおよそ 4%(実測)。** ただし**バッチ内 bootstrap CI の較正は破れている**(同一バイナリで 90 回中 41 回 1 を除外する。決定 80、§7)ので、**ノイズは「同じペアを独立したバッチで k 回測ったときのバッチ間の散らばり」で定義する**。**MDE v2(決定 105、確定は決定 106)**: MDE = `max(2 × h, 0.01)`。`h` は対象の登録 A/A パネル(同一バイナリの脚だけ)の**集計(幾何平均)95% 半幅**で、計測前に対象ごとに凍結し、バッチごとには再計算しない。見出しは集計比なので、その MDE も集計の A/A から取る。**ケース別の主張**(hintbench のカーネル別読み出しなど)は、そのケースの A/A 半幅の 2 倍(下限 1%)を使う。効果 = ラウンドバッチと確認バッチの両方が同じ側で MDE を超えること。記事では holdout の一致も添える。これを超えない限り「速い」と書かない(「ノイズでなければ入れる」。3% の方針下限(決定 27)は撤回)。1〜2% の主張は Jev vs ランダムでは n≥3(決定 96)が要る。確定値(`results.md` §172): zopfli 訓練 1.00%(集計半幅 0.414%)/ holdout 1.00%、hintbench 集計 1.00%(§162、カーネル別 1.00〜3.18%、k8 が最大)、jaq 1.13%(§140 holdout の aa、ただし jaq のバッチ内半幅は過信気味で、これはノイズの下限にすぎない)。決定 105 より前の結果は v1(`max(2 × 最悪 per-case 半幅, 0.03)` をバッチごと)で読んだまま残し、v2 での読み直しは事後の脚注(§171・§172)に留める。driver は `[evaluation] mde_floor`(既定 0.01)と `mde_from`(既定 `"aggregate"`)を持ち、各走行の `rounds.jsonl` と manifest に `mde_rule` / `mde_floor` / `mde_from` を記録する(`mde_from = "worst_case"` + `mde_floor = 0.03` で旧規則を再現)。集計は約 1%、単一ケースは約 3% までしか信用できない(実測、`results.md` §58)。
- **採用規則(決定 80 a)**: **1 バッチで決めない。** MDE を超えた arm は**独立した別バッチ**(同じ 2 本のバイナリ、同じ条件、新しいシャッフル seed)で再測定し、**両方のバッチで CI が 1 を同じ符号で除外したときだけ採用する**。1 バッチの「CI 下限 > 最良」だけでは、この n ではノイズが通る(jaq で 3 本が通り、holdout で 3 本とも符号反転。実測)。**追加(決定 89(a)、未実装)**: 規則が「plan が変わったか」を問わないため、hintbench では同一バイナリが 2 回昇格した(R2〜R5 は同一 plan で、R5 が R2 を「新 best」で上書き)。**採用の比較は plan が変わった場合のみ行う。**
- **機能ごとの効果(決定 39・94・96)。** (a) 各 arm(対照・各機能・ランダム)は**独立に n 回**走らせる。既定 **n=3**(最低)。1 走行 = `--rounds` 分の探索 1 回、代表値 = その走行の最良採用 plan の訓練比。反復 r は shuffle seed に記録済みのオフセットを足す(同じ seed では提案側の揺れしか測れない)。費用は hintbench が 1 走行約 30 分(実測)なので、4 arm + ランダムの 15 走行で約 7.5 h。(b) arm の代表値は**中央値**とし、**範囲(最小〜最大)を併記**する。機能の効果は**中央値の差**で報告する。「効果」と呼ぶのは、**事前登録した向きで 2 arm の範囲が重ならず**、かつ中央値の差が対象の計測 MDE を超える場合だけ。交換可能性の下で範囲が重ならない確率は 2/C(2n,n) で、n=3 なら両側 10%・片側 5%、n=4 なら両側 2.9%(算術)。向きを事前登録しない(両側の)主張をしたいときは n=4 以上にする。対のあるブートストラップは採らない。arm 間に自然な対は無く(Jev に seed が無い)、n=3 では区間が範囲とほぼ同じになるからである。n≥5 のときだけ補助として付ける。逆向きに範囲が重ならない場合は「逆向きの兆候」と記録し、効果とは呼ばない。(c) **機構チェック**(「k8 で幅 16 が選ばれたか」のような二値の判定)は n=1 でも成り立つので、arm ごとに全走行を集計して **k/n** で報告する。(d) 計測の規則(決定 80・95)は変えない。走行内の採否は確認バッチ規則、パネルの A/A は ±0.5%。**バッチごとに基準の k5 の `mean_s` のモードを記録する**(遅い ≈358〜362 ms / 速い ≈326〜333 ms、実測。境界の 345 ms は仮置きで、決定 95(b) の調査までは暫定)。**比較は同じモードの中でだけ行い**、代表値はラウンドバッチ(Exp6 では 20/20 が遅いモードで、oracle の 1.0881 と同じ)から取る。モードが混ざったらモード別に報告する。同じ `bin_sha256` が arm 間でずれる量(0.51/1.48 pt、実測)は計測だけの成分として併記する。(e) **Jev の非決定性を報告する。** 各 arm のラウンド 1 の要求は反復間でバイト一致するはずである(履歴が空のため。`request_sha256` で確認)。一致する対ごとに、確率ベクトルの最大 |ΔP| と argmax の反転数をフェーズ別に記録する。(f) **事前登録に、1 実験の走行数(arm × n)、壁時計の見込み、API 要求数の上限を書く**(Exp6 実測で 1 走行 ≈ 本フェーズ 10 + 探索 6〜7 本、再送は 200 回 / 600 s の上限)。n は開始前に固定する。結果を見てから反復を足すこと(optional stopping)は禁止で、足した場合は新しい実験として登録する。(g) **ランダム対照も同じ n** で回し、反復ごとに別の seed を使う。(h) 遡及はしない。Exp6 は n=1 の記録として残す(`results.md` §159)。**oracle の天井が MDE 未満の対象では、no-op の正しさは採用 plan の有無ではなく、oracle がフラットと測った site での `KEEP_DEFAULT` 率で報告する**(`forced_top1` + `--explore 2` はどのラウンドでも基準そのものを組めない構造なので、採用 plan 0 を「Jev が正しく no-op を選んだ」とは読まない。決定 102)。
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
- **state の書式(凍結する)= v4.1**(§1 (3)、`docs/search-driver.md`): (1) 関数のソース(ループ site は本体 ±20 行と外側関数のシグネチャ。**コメントは除く** — `--source-comments strip` が既定。カーネルの doc コメントが検証対象のヒント名を書いており、一発一致 10/12 の 3 件はそれが作っていた。決定 81・82)、(2) profile 上の share(その site が全実行時間の何 % か。全マークが同一値なら書かない)、(3) remark の要約(その site について LLVM が何を見送ったか。**外さない**。inline は callee 名で索引し、legality はそのループ自身の位置からだけ取る。決定 83)、(4) **前ラウンドまでの結果表**(ラウンド番号、その site に選んだヒント、そのビルド全体の速度比と信頼区間、**その site 自身のケースの比と CI**、採用 / 不採用、`post_vectorize` の事実行(決定 90))、(5) **platform ブロック**、(6) 各 question に付く**判定行**、(7) 関数フェーズの選択肢に付く**適用条件**。**state の書き方で答えが変わる**(実測、`docs/jev-samples/01-*`、決定 19・70・73)ので、書式と語彙は測定条件と同じ扱いで同時に凍結し(`--vocab` が両方を選ぶ)、変更したら再測定する。
- `criteria` は §1 (2) の一覧そのまま。**`KEEP_DEFAULT` を必ず含める。** 応答なし・timeout・不正応答・confidence が閾値未満のときは安全側の既定として `KEEP_DEFAULT` を採り、理由を記録する。オフライン問い合わせなので、要求 timeout 20 s、試行上限 200 回・壁時計 600 s、固定 2 s ±20% のバックオフで無改変再送、フェーズの再送は最大 2 回、半分の plan は組まない(決定 92・93)。
- **全 request / response を JSONL に記録する。** `artifacts/jev-log/<run-id>.jsonl` に 1 行 1 問い合わせで `{ts, round, request, response, http_status, latency_ms}`。送受信した JSON をそのまま入れる。**`Authorization` ヘッダは記録しない。** `jev-plan.json` の各 entry は `<run-id>.jsonl#<行番号>` を `answer_ref` に持つ。
- **人が読むテキストログも出す。** `.log` に 1 問い合わせ 1 行(`ts round question数 http_status latency_ms input_tokens output_tokens cost`)、末尾に集計(HTTP 本数、Choice 総数、待ち時間の合計・平均・最大、トークン合計、費用合計、実験全体に対する Jev 待ちの割合)。同じ集計を `results.md` に転記する。
- `doctor` は `GET /typesafe/v1/models` で `typesafe-ai/jev` が使えることを確認する。Jev は Hobby の無料枠で動く(応答約 150 ms、定価でも 1 回 1 万分の 2 セント前後。実測)。キーは `.env`(git 管理外)。

## 7. 評価手順

- **主指標**: end-to-end wall time。ケースごとの速度比を事前固定重みの幾何平均で集計し、交互実行の pair を単位に bootstrap で 95% 信頼区間を出す。arm 間の比較は §2 の反復規則に従う。
- **ノイズフロアと MDE**: §2(MDE v2 = `max(2 × 登録 A/A の集計半幅, 1%)`、ケース別の主張はケース別 A/A、対象ごとに計測前に凍結。決定 105・106)。A/A は holdout の前に同一手順で回す。
- **バッチ内 bootstrap CI の較正は破れている(実測、決定 80)。** jaq の 90 arm の掃引で、同一バイナリに対する in-run A/A の CI が **90 回中 41 回 1 を除外した**(覆ったのは 49 回)。専用 null パネル(同一バイナリ 4 本)の最大差は 0.77 pt にとどまるのに、掃引内の no-op ビルド 48 本は 4.67 pt に散らばり、うち 20 本の CI が 1 を除外した。バッチ内の再スケールでは救えない。したがって **CI は 1 バッチでは採否に使わず、§2 の確認バッチ規則に従う**。事前登録の「CI 下限 > 最良」だけでは足りず、jaq では 3 本が通って holdout で 3 本とも符号反転した。
- **ラベル順はローテートでなくシャッフルする**(ローテートだと隣接ラベルの A/A がラウンド内のドリフトを過小評価する)。
- **ノイズは対象ごとに桁が違う(実測)。** hintbench の null パネルは**バッチ内 0.08 pt、バッチ間 0.17 pt(k5 のクラス差を除く。決定 97)**で、jaq の **0.77 / 4.67 pt** よりはるかに静か。ただし k5 は同じバイナリでも 2 つのモードを持ち、A/A では捕まえられない(決定 95)。この差は測定手順ではなく**対象の性質**と読む(hintbench の 1 因子 arm はコードを測っており、jaq のそれは機械を測っていた。oracle §7。**仮説**)ので、jaq の較正不良を hintbench の結果に持ち込まない(逆も同じ)。対象ごとに null パネルを回してから採否の規則を当てる。
- **計測するバイナリの argv[0](絶対パス)の長さで hintbench の k5 が約 9% 動く(実測、決定 97)。** glibc のチャンククラス `c = max(32, (len+23) & ~15)` で例外なく分かれる: c96 が遅い、c80・c112 が速い、周期は 32 バイト。機構は未解明(`results.md` §160〜161)。`scripts/bench.py` は全ラベルを 80 バイト(クラス 96 = oracle と全ラウンドバッチのクラス)の別名パスにハードリンクして実行し、長さ・クラスが揃わなければ計測前に失敗する。`stats.json` / `rounds.jsonl` / manifest に `len` と `class` を記録する。クラスをまたぐ比較(Exp4〜6 の confirm と panel は c112)には脚注を付ける。`--argv0-raw` は調査用。
- **確認バッチは hintbench では採否を 1 件も変えなかった(実測)。** oracle の組み合わせに入る 6 site は「2 バッチで確認」でも「1 バッチで CI 下限 > 1」でも同一だった(38 本の確認バッチは実際に回っている)。**つまり 2 バッチ規則の要否はまだ検証されていない**ので、jaq のように騒がしい対象では規則を外さない。
- **in-sweep null パネルを必須にする。** 正規化コードハッシュが基準と一致したラベルを、その run の中の追加の null 対照として使う。専用のノイズプローブは信用しない(jaq では「ノイズプローブ」のつもりだったアラインメントのフラグが集計 +1.32%、単一ケース +3.42% 動いた。実測)。
- **測定条件**: `taskset` で物理コア 1 つに固定し SMT 兄弟を空ける。`lscpu -e` を記録に残す(WSL2 からはホストの CCD が見えないので「単一 CCD 内」は主張しない)。ASLR は有効のまま。n(既定 15〜50)、warmup(3〜5)、trimming 規則を凍結し、事後変更した run は無効。
- **jaq 型の対象**: 大きな入力 1 本ではなく**小さい入力を複数回**並べ、`--gap-ms 250` の整定ギャップを入れる(72 MiB の配列 1 本では RSS 1.2 GiB で同一バイナリ・同一入力が二峰になり、A/A 半幅が 13% まで悪化した。実測)。
- **同時に 1 対象しか測らない**(別対象のビルドを並走させると A/A 半幅が 0.3% → 1.7% に悪化した。実測)。**実行中の共有スクリプトを in-place で編集しない**(bash が途中から読み直して落ちる。実測)。
- **探索ラウンドと最終 holdout を分ける。** ラウンド中の測定は探索用のケース集合で行い、**holdout は最良 plan が確定してから 1 回だけ**回す。holdout のケースと重みはラウンド開始前に凍結する。見てから条件を変えた場合は新 seed で再生成し、全実行履歴を `results.md` に列挙する。**zopfli は探索用訓練セット(`search-{text,binary,json}.dat`、896 KiB × 3、seed 20260923201〜203)を PGO 訓練(合成ワークロード、`merged.profdata` は不変)と holdout(`hold-*.dat`、1400 KiB × 3)の両方から分離して持つ**(決定 98)。ラウンド中は探索用訓練セット、転移の一度きりの測定には holdout を使う。
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
mde_floor       = 0.01         # 決定 106(旧 0.03)
mde_from        = "aggregate"  # max(2 × 集計 A/A 半幅, mde_floor)。"worst_case" で旧規則
cpu_pin         = "4"
seed            = 20260921

[search]
rounds    = 5               # 初期値
max_sites = 40              # 超えたらエラー。oracle のビルド数を有限に保つ(§2)
hints     = "…"             # §1 (2) の一覧。ラウンド 1 前に凍結
knobs     = ["…"]           # llvm-knobs.json から選んだノブ。同上
stage     = "separate"      # 関数属性ラウンドとループラウンドを分ける(§5)
vocab     = "v4"            # 語彙と state 書式は 1 つの測定条件(§1 (3))

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
| `jev-opt mark` | 既定は決定 109 の規則(`scripts/target_marks.py`: 種 = reach 上位 ∪ self 上位、灰色帯だけ Jev)で `jev-marks.jev.txt` を書く。人や Claude が選ぶ場合は perf(または代替)の上位を関数単位で表示して助け、同じ形式の `jev-marks.txt` を書く。**ビルドの工程ではない** |
| `jev-opt search` | ラウンドを回す。`dump` → 提案 → plan → ビルド → 測定 → 結果を state へ、を `rounds` 回。`--proposer jev\|random\|oracle` でアームを切り替える。最良 plan と全ラウンドのログを残す |
| `jev-opt bench` | 最良 plan / 基準 / oracle / random を holdout で交互実行、シャッフル、bootstrap、in-sweep null パネル、帰属 diff、`results.md` 生成 |

cargo への組み込みは「CLI が環境変数を組んで `cargo build --release --target …` を exec する」だけ。`.cargo/config.toml` は使わない(RUSTFLAGS と上書き競合し、variant 切替で状態が残る)。

## 9. 対象の順序と実装順序

**対象の順序(決定 72)**: **正解が存在するはずの小さな対象を jaq の前に置く。** `targets/hintbench/` — 8 カーネルの crate で、語彙の各ヒントが効くはずの構造を意図して作ってある(`EXPECTED.md` に計測前の Claude の期待ヒントと機構が書いてある)。site は 12(関数 8 × 5 候補 + ループ 4 × 11 候補 = 85 arm、**実測 4.1 時間**)。ループ site の凍結規則は「ループヒントが検証対象のマークのみ、マーク内で hotness 最大の key 1 本」(決定 76)。**`-Zcross-crate-inline-threshold=never` は hintbench の固定フラグ**(無いと rustc の MIR inliner が 8 カーネル中 6 つを LLVM に届く前に消す。`-Cprofile-use` は MIR のハッシュで照合するので計装ビルドにも同じフラグが要る。決定 75、実測)。ただし **8 カーネル中 4 つは意図どおりに作れていない**(K4 / K5 は基準が既に VF 8 × IC 4、K2 の `inline` と K7 の `cold`(いずれも v3 で語彙から外した)は不活性。決定 74、実測)。**「正解が存在する」ことは oracle で確認済み**(決定 85、実測): 16 候補中 9 つが MDE を超え、正方向は 3 つ。ただし設計の意図どおりではなく、対照のはずの K8 で幅 16 が **+8.8%**、余地なしのはずの K5 で幅 16 が +2.65%(遅延律速の reduction では幅を広げると独立鎖が増える)だった。

1. **plugin**(C++)— **済**。EP を toy の実測で確定し、off 等価性(未ロード / off / 空 plan で `.text` と出力がビット一致)と手書き plan の消費を確認(決定 60)。`alwaysinline` 分岐も追加し、toy で `always inline attribute at callsite` の remark と出力一致を確認済み(決定 78)。
2. **探索ドライバ** — **済**(Python 実装、決定 62・65、`docs/search-driver.md`)。マーク解決、plan 生成、ビルド、測定、state 組み立て、Jev 接続、`--proposer` 3 種。語彙 v4、state v4.1(per-case の読み出し)、`--source-comments strip` 実装済み。
3. **hintbench の oracle** — **済**(85 arm、4.1 時間。決定 85)。実測の正解と、`EXPECTED.md` の Claude 予測の採点(8 問中 1 問。決定 86)。
4. **Jev を hintbench に当てる** — **済**。一発(決定 87、関数 7/8・ループ 0/4)と**フィードバック付き 5 ラウンド + ランダム対照**(決定 88、Experiment 4)。

以降の順序:

5. **探索機構の実装** — **済**(決定 90)。決定 89(a)〜(d) と 87(c)(§1 (3))。未試行候補の Choice、plan 変更時のみの採用、履歴の他ケースコストと共有ケース明記、plugin のベクトル化後事実。
6. **hintbench 再走** — **済**(Exp5/Exp6、決定 92・93)。同じ凍結条件で、探索機構が **oracle の組み合わせにどこまで届くか**(現状 71〜77%)を測る。取りこぼし 2 件(k3 ループ `unroll.count=4`、k8 ループ 幅 16)が拾えるかが判定。
7. **jaq の関数属性 oracle を再実行** — **済**(決定 91)。v1 で走らせた 90 arm はフラットだった(決定 79)が、1 Choice が 60 クロージャに波及していた(決定 80(c) の修正で 138 → 49 entry)。**v4 + クロージャ修正で再実行済み(決定 91)。**
8. **jaq のループ oracle** — 176 arm、約 14 時間。ただし**ベクトル化済みループでは `unroll.disable` と `interleave.count=1` が重複**する(決定 85(b))。どのループがそれに当たるかは dump では判別できない(§1 (2))ので、重複除去は **5 の plugin 改修(ベクトル化後の VF / IC の記録)後**に行うか、arm 同士の正規化命令列比較で行う(no-op skip は各 arm を基準としか比べないのでこの対は拾えない)。
9. **jaq の Jev ラウンド** — `search --proposer oracle|random|jev` → `bench`。§2 の表の jaq 列を埋める。
10. **zopfli を転移先として通す** — **済**(決定 98〜102)。hintbench / jaq で凍結した手順をそのまま当てた。per-case の読み出しが無い対象(`own_workload_of` が `None`)なので、site の履歴は集約比だけになる。語彙 v6(決定 98)・探索用訓練セット(決定 98)で oracle(68 arm、6 マーク × 関数属性 + 5 site × ループ候補 + 組み合わせ 1)を実測: 良い arm **0/67**、有害 2(`squeeze.rs:275` の unroll 4/8)、命令列が基準と同一(no-op)38、残りは平坦か確認済みの負方向で、組み合わせも **+1.8〜2.1%(MDE 3% 未満)**(決定 100。確定した MDE v2 の zopfli 1.00% では、組み合わせと `squeeze.rs:325` の `unroll.count=8` が 3 脚とも超える。事後の読み。決定 106)。Jev vs ランダム(各 n=3、6 走行)は採用 plan が両アームとも 0、代表値はすべて基準の 1.0000 で **n=3 では未解像**(決定 101)。oracle の天井が MDE 未満のため、driver の構造(`forced_top1` + `--explore 2`)はどのラウンドでも基準そのものを組めず、no-op の正しさは採用 plan ではなく oracle がフラットと測った site での `KEEP_DEFAULT` 率(80%)で読む(決定 102)。
11. **記事**(zenn)。

**済(基盤)**: toolchain pin、gate 0、`llvm-knobs.json`(2689 ノブ)、remark 機構の選定、`.text` の debuginfo 依存、測定手順一式(A/A、MDE、交互実行、bootstrap、正規化コードハッシュ、整定ギャップ、`scripts/ipsample.c`)。いずれも `results.md` Day 0 と §8〜§10・§46・§55 に記録済み。

**失敗時の分岐**: dlopen で abort → LLVM を静的リンクしている(リンク指定を全部外す)。LTO 段でどの EP も発火しない → pre-link 段で適用する(冪等性設計がそのまま使える)。off 等価性が崩れる → plugin が off でもパイプラインを変えている(差分関数を特定するまで進まない)。ヒントを付けても remark が変わらない → 付与先の同定が間違っている(`--emit=llvm-ir` で目視する)。

## 10. スコープ外

以下は本実験の主題ではない。別テーマとして扱い、成功と混同しない。**PGO の訓練ワークロードを選ぶこと**(経緯と数値は `docs/decisions.ja.md` 38・43〜55、`results.md` §62〜§69。v0.5 では合成ワークロードでの PGO を準備として固定する)、**浮動小数点の再結合を許す判断**(`decisions.ja.md` 40〜42・56。v0.5 は全アームで再結合を封鎖する側に固定)、**効果の出る対象を探して回ること**(`decisions.ja.md` 57・58。対象は hintbench → jaq に固定する。決定 72)、**v0.3 のヒント 5 ファミリーのグローバル掃引**(4 対象すべてフラットだった。`decisions.ja.md` 12〜14・21〜24・29〜31・37、`results.md` §12〜§61)、**語彙から外したヒント** — `inline`(inlinehint)と `cold` はこのレシピの下で inliner に対して不活性、`hot` はそもそも inliner の入力ではなく Rust の表層構文も無い(決定 77、`docs/experiments/hintbench/inline-attrs-under-pgo.md` §7。plugin は v1 / v2 の再現用に受理を残すだけ)。**callsite 文字列属性 `function-inline-threshold` / `function-inline-cost`**(クラス B・C・D で閾値を外から動かせる唯一の経路だが、plugin は関数を marking する設計なので、将来の site 種別の話であって語彙の話ではない)、意味変換(HashMap を線形探索に変える等)、パス挿入(unswitch / fusion / interchange)、AVX-512 幅選択(この機に無い)、PGO を使わない静的 Jev(全ループに問い合わせる方式は費用と待ち時間が成立しない)、他言語への展開、**Claude を参照点にする評価**(決定 69 の「Claude の判断との一致率」を主指標にする設計。hintbench の oracle で Claude が 8 問中 1 問だったので**決定 86 で補助に降格**した。Claude は準備工程(マーク、期待の事前登録)には残すが、正解の代理にはしない。マークの既定は決定 109 の規則で、Claude の手は要らない)。

## 言語方針

- **英語**: ソースコメント、コミットメッセージ、PR 本文、README、CLI のヘルプとログ。
- **日本語**: `SPEC.ja.md`、`docs/decisions.ja.md`、zenn 記事、開発ノート。開発中はこちらが正本。
- 実装が落ち着いた時点で `SPEC.md`(英語)を生成物として追随させる。

理由: コミット履歴は後から英語化できないので最初から英語で書く。設計判断の理解と議論は日本語の方が速く正確なので、仕様と記事は日本語で持つ。
