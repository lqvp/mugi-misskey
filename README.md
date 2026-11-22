# mugi-misskey

Devin の Bot「むぎ」が自分の Misskey アカウント（misskey.vip の @mugi）を運用している仕組みをまとめたリポジトリです。コード、交流ルール、Devin Automation の設定が入っています。[セットアップ手順](docs/setup-with-devin.md)に沿って進めれば、Devin を使える人なら誰でも同じ仕組みを自分の Bot とアカウントで再現できます。

トークンや Webhook シークレットはこのリポジトリに入れていません。設定ファイルの値はすべてダミー（`misskey.example.com`、`examplebot` など）です。

## 全体像

```
[Misskey]  mention / reply / follow / followed ──Webhook──┐
[Misskey]  reaction ──streaming (main チャンネル)──┐       │
                                                   ▼       ▼
                              Cloudflare Worker（relay/worker.js）
                              ・Webhook: ヘッダー名を付け替えて転送
                              ・Durable Object: 常時接続して reaction を転送
                                                   │
                                                   ▼
                   Devin Automation「Webhook で反応」（LLM チェックで選別）
                                                   │ message_session
                                                   ▼
        Bot の会話（むぎ本体）── harness/mk.py で Misskey API を操作
                               └ social/PLAYBOOK.md と好感度・カーソルの JSON を読み書き
        ▲
        └─ 定期 Automation「通知チェック」（6 時間ごと）「TL 巡回」（1 日 8 回）
```

| 部品 | 場所 | 役割 |
| --- | --- | --- |
| CLI | [harness/](harness/) | Python 標準ライブラリだけで書いた Misskey API クライアント（投稿・リプ・リアクション・TL・通知・フォローなど） |
| 交流ルール | [social/](social/) | 口調・好感度・TL 巡回のルール（`PLAYBOOK.md`）と、状態を保存する JSON のひな形 |
| リレー | [relay/](relay/) | Misskey と Devin の間に入る Cloudflare Worker と Durable Object |
| Automation | [automations/](automations/) | Devin Automation 3 本のトリガー、プロンプト、LLM チェック |

## 中の振り分け（どのイベントが、どこで、何に処理されるか）

1. 入口は 2 本です。 メンション・リプライ・フォローは Misskey の Webhook で届きます。リアクションは Misskey が Webhook を送らないため、Durable Object が streaming API の `main` チャンネルにつなぎっぱなしにして拾います。どちらも同じ Devin Automation の Webhook URL に、同じ形の JSON で送ります。
2. ヘッダーを付け替えます。 Misskey はシークレットを `X-Misskey-Hook-Secret` で送りますが、Devin は `X-Webhook-Secret` しか受け付けません。Worker はヘッダー名を付け替えるだけで、シークレットの値は自分では持ちません。値が違えば Devin が 401 を返します。
3. LLM チェックで選り分けます。 Automation の LLM チェック（Devin 側の判定モデル）が、イベントの種類と「行動した人」を見ます。bot フラグの付いたアカウントと自分自身からのイベントは、ここで落とします。セッションを起こす前に止まるので、無駄な実行が増えません。
4. Bot 本体に届けます。 通ったイベントは `message_session`（`target_bot_id` 指定、`auto_create: false`）で Bot の会話に届きます。毎回新しいセッションを作るのではなく、記憶と人格を持った Bot 本体が受け取ります。応答に使うモデルは Bot に設定したエージェントモードのモデルです。このリポジトリではモデル名を決めていません。
5. Bot が判断して動きます。 Bot は `PLAYBOOK.md` と好感度（`affinity.json`）を見て、返信・リアクション・フォロー返し・無視のどれかを選び、`mk.py` で実行します。最後に通知カーソル（`state.json`）を進め、メモリを同期します。
6. 定期実行で取りこぼしを拾います。 「通知チェック」は 6 時間ごとに通知一覧を読み、Webhook で漏れた分を処理します。「TL 巡回」は 1 日 8 回 TL を眺め、気が向けばリアクション・リプ・独り言の投稿をします。何もしない回もあります。
7. 重い作業は子セッションに任せます。 調査やコード変更のような大きな仕事は、Bot が子セッションに切り出します（このリポジトリ自体もその流れで作りました）。Misskey での日常のやり取りは Bot 本体だけで完結します。

## ディレクトリ

```
harness/mk.py          Misskey CLI
social/PLAYBOOK.md     交流ルール
social/*.example.json  状態ファイルのひな形（本物は Bot のメモリに置く）
relay/worker.js        Cloudflare Worker + Durable Object
relay/wrangler.toml    デプロイ設定（値はダミー）
automations/README.md  Automation 3 本の設定
docs/                  セットアップ手順と設計メモ（ADR）
tests/, relay/test/    テスト
```

## テスト

```sh
python3 -m unittest discover -s tests
cd relay && node --test test/
```

外部への通信はモックしています。本物の Misskey や Devin には接続しません。

## 設計メモ

- [ADR 0001: Webhook と streaming をリレー経由で Devin Automation に流す](docs/adr/0001-relay-and-streaming.md)
