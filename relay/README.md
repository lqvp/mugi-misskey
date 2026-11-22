# Misskey → Devin リレー（Cloudflare Worker）

Misskey のイベントを、数秒で Devin の Automation に届けるための Worker です。役割は 2 つあります。

## 1. Webhook の中継（`POST /`）

Misskey はシークレットを `X-Misskey-Hook-Secret` ヘッダーで送り、Devin の `webhook:incoming` は `X-Webhook-Secret` ヘッダーでしか受け付けません。Worker はヘッダー名を付け替えて、本文はそのまま `DEVIN_WEBHOOK_URL` に送ります。

- Worker 自身はシークレットを持ちません。Misskey と Devin に同じ値を設定しておき、値の照合は Devin が行います。
- POST 以外、シークレットなし、JSON でない本文、`server` が `MISSKEY_ORIGIN` と違うものは拒否します。
- Workers Logs には `type`、`hookId`、Devin の応答コードだけを残します。

## 2. リアクションの監視（Durable Object `MisskeyStream`）

Misskey 本体は `reaction` を Webhook イベントの一覧に載せていますが、実際には送りません。そこで Durable Object が Bot アカウントの streaming `main` チャンネルに常時つなぎ、`notification` のうち `reaction` を Webhook と同じ形の JSON にして送ります。

- 送る形: `{server, hookId:"stream", userId, eventId, createdAt, type:"reaction", body:{user:{id,username,host,name,isBot}, reaction, note:{id,text,cw,userId,createdAt}}}`。ノートの作者情報はあえて入れていません。作者は bot フラグ付きの Bot 自身なので、入れると LLM チェックが誤って落とすためです。
- 切断中に逃した分は再接続のときと 30 秒ごとのアラームで `i/notifications`（`sinceId` は保存済みの `lastId`）から取り直します。`lastId` は、Devin が 2xx を返したときだけ進めます。
- 毎分の Cron が `/stream/tick` を呼び、接続を保ちます。

| エンドポイント | 内容 |
| --- | --- |
| `POST /stream/setup` | `{"token", "hookSecret"?, "sinceId"?}` を保存して接続する。トークンが `BOT_USERNAME` のものか確かめる。`hookSecret` を省くと `MISSKEY_WEBHOOK_ID` の Webhook から読む。`sinceId` を渡すと、その通知以降を送り直す |
| `GET /stream/status` | `connected`、`lastForward`、`lastCatchUp`、`version` など（秘密は出さない） |

## デプロイ

1. `wrangler.toml` の `[vars]` を自分の値にする（[セットアップ手順](../docs/setup-with-devin.md)の手順 5）。
2. `npx wrangler deploy`
3. 初回だけ `/stream/setup` を呼ぶ（手順 7）。

## つまずきどころ

- 外向きの WebSocket を持つ Durable Object は、再デプロイしても古いコードのまま動き続けます。そのため Worker は `X-Code-Version` を付けて Durable Object を呼び、Durable Object は自分の `CODE_VERSION` と違えば `state.abort()` で作り直されます。コードを変えたら `CODE_VERSION` を必ず上げてください。切り替えの瞬間に 1 回だけ 1101 エラーが出ます。
- `storage.get([...])` は Map を返します。分割代入すると undefined になり、Devin が `Invalid webhook secret` を返します。
- クラス名を変えるときは、migration を 2 段（新クラス追加 → 旧クラス削除）に分けます。

## テスト

```sh
node --test test/
```

`fetch` をモックして、ヘッダーの付け替え、拒否条件、カーソルの進め方を確かめます。
