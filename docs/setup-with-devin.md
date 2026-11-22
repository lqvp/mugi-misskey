# Devin で再現する手順

自分の Devin Bot に、自分の Misskey アカウントを運用させるまでの手順です。`<...>` は自分の値に置き換えてください。手順の多くは、このリポジトリを Bot に渡して「docs/setup-with-devin.md の通りにセットアップして」と頼めば Devin が進めます。人がやる必要があるのは、印の付いた手順だけです。

## 用意するもの

- Devin の Bot（会話を持つ Devin）。以下 `<BOT_ID>` は `bot-...` 形式の ID です。
- Misskey のアカウント。Bot 用なので、プロフィール設定で「Bot」フラグを付けておきます。
- Cloudflare アカウント（Workers の無料プランで動きます）。

## 1. Misskey のトークンを作る（人）

Misskey の「設定 → API」でアクセストークンを作ります。必要な権限はアカウント情報、ノートの作成・削除、リアクション、フォロー、通知、ドライブ、Webhook の読み取りです。

トークンは Devin の Secrets に `MISSKEY_TOKEN` として保存します（Bot だけが使うなら Bot スコープ）。ファイルやチャットには書きません。

## 2. ファイルを Bot のメモリに置く

状態ファイルはセッションをまたいで残す必要があるので、Bot のメモリフォルダ（以下 `<MEMORY>`。例: `~/memory/<bot-memory>`）に置きます。

```sh
mkdir -p <MEMORY>/files/misskey-harness <MEMORY>/files/misskey-social
cp harness/mk.py <MEMORY>/files/misskey-harness/
cp social/PLAYBOOK.md <MEMORY>/files/misskey-social/
for f in affinity state wander; do cp social/$f.example.json <MEMORY>/files/misskey-social/$f.json; done
```

`PLAYBOOK.md` の `@owner` は運用者の acct に、口調の節は Bot の人格に合わせて書き換えます。配置したら `memory_sync` で保存します。

次のコマンドで動作を確かめます。

```sh
MISSKEY_HOST=https://<instance> python3 <MEMORY>/files/misskey-harness/mk.py me
```

`MISSKEY_TOKEN` は exec の `env` でシークレットとして渡します。

## 3. Webhook シークレットを決める

ランダムな文字列を 1 つ作り、Devin の Secrets に `MISSKEY_HOOK_SECRET` として保存します。同じ値を、Misskey の Webhook と Devin の Automation の両方に設定します。

## 4. Webhook 用の Automation を作る

[automations/README.md](../automations/README.md) の「1. Webhook で反応」を作ります。トリガーは `webhook:incoming`、シークレットは手順 3 の値です。作ると Webhook URL（`https://app.devin.ai/api/webhooks/automations/<ORG_ID>/<AUTOMATION_ID>`）が発行されます。

## 5. リレーをデプロイする

`relay/wrangler.toml` の `[vars]` を自分の値に書き換えます。

| 変数 | 値 |
| --- | --- |
| `DEVIN_WEBHOOK_URL` | 手順 4 の Webhook URL |
| `MISSKEY_ORIGIN` | `https://<instance>`（末尾のスラッシュなし） |
| `BOT_USERNAME` | Bot アカウントのユーザー名（`@` なし） |
| `MISSKEY_WEBHOOK_ID` | 空のままでよい（手順 6 の後に入れれば、セットアップ時にシークレットを Misskey から読みます） |

```sh
cd relay && npx wrangler deploy
```

## 6. Misskey の Webhook を作る

Misskey の「設定 → Webhook」で作成します。

- URL: リレーの URL（`https://<worker>.<subdomain>.workers.dev`）
- シークレット: 手順 3 の値
- イベント: メンション、返信、フォローした、フォローされた

## 7. リアクションの監視を始める

Durable Object にトークンとシークレットを一度だけ渡します。値はファイルに書かず、環境変数で渡します。

```sh
curl -sS -X POST https://<worker>/stream/setup \
  -H 'Content-Type: application/json' \
  -d "{\"token\":\"$MISSKEY_TOKEN\",\"hookSecret\":\"$MISSKEY_HOOK_SECRET\"}"
curl -sS https://<worker>/stream/status
```

`connected: true` になれば完了です。値は Durable Object のストレージにだけ保存されます。

## 8. 定期 Automation を作る

[automations/README.md](../automations/README.md) の「2. 通知チェック」と「3. TL 巡回」を作ります。

TL 巡回には、Preflight check（スクリプト）として [automations/preflight/wander_random.py](../automations/preflight/wander_random.py) を付けます。これがないと、5 分ごとに毎回巡回してしまいます。Automation を作る前に、Devin の Preflight テスト（`script_check_test`）で、スロットの時刻は run、それ以外は skip になることを確かめます。

## 9. 確認する

- 別のアカウントから Bot にメンションして、数秒〜数十秒で返事が来るか。
- Bot のノートにリアクションを付けて、`/stream/status` の `lastForward.devinStatus` が 200 か。
- Misskey の Webhook 画面で、最後の送信結果が 200 か。

## つまずきどころ

- Python の標準 User-Agent は、Cloudflare の前段で 403 になるインスタンスがあります。`mk.py` は独自の User-Agent を付けています。
- Automation の preflight スクリプトからは Bot スコープのシークレットを使えません。トークンは Bot のセッション内で exec の `env` から渡します。
- リアクションの Webhook は、Misskey 本体が送ってきません。そのため Durable Object で補っています。
- `worker.js` を変えたら、`CODE_VERSION` を必ず上げてからデプロイします。上げないと、接続中の Durable Object が古いコードのまま動き続けます。
- Durable Object のクラス名を変えるときは、migration を 2 段（新クラス追加 → 旧クラス削除）に分けます。
