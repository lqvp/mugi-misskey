# ADR 0001: Webhook と streaming をリレー経由で Devin Automation に流す

- 状態: 採用

## 背景

Bot が Misskey のメンションやリプライに数秒で反応できるようにしたい。ただし、次の 2 つの制約がある。

1. Devin の `webhook:incoming` は `X-Webhook-Secret` ヘッダーでしかシークレットを受け取らない。Misskey は `X-Misskey-Hook-Secret` で送るので、直接つなぐと 401 になる。
2. Misskey 本体は `reaction` の Webhook を送らない。

## 決定

- Cloudflare Worker を間に置き、ヘッダー名だけを付け替える。シークレットは Worker に置かず、照合は Devin に任せる。
- 同じ Worker の Durable Object で streaming API に常時接続し、リアクションを Webhook と同じ形で送る。取りこぼしは `i/notifications` で取り直す。
- どちらも 1 本の Automation に集め、LLM チェックで bot と自分自身を落としてから、`message_session` で Bot 本体に届ける。
- 取りこぼしに備えて、6 時間ごとの通知チェックを別の Automation で回す。

## 検討した案

| 案 | 長所 | 短所 |
| --- | --- | --- |
| A. 定期ポーリングだけ | 部品が少ない | 反応が最大数時間遅れる。毎回セッションを起こすので無駄が多い |
| B. Worker で中継し、Durable Object でリアクションを補う（採用） | 数秒で反応する。リアクションも拾える | Worker と Durable Object の運用が増える |
| C. Misskey 本体を改修して、ヘッダーとリアクションに対応させる | 部品が減る | 自分のインスタンスでしか使えない。アップストリームに入らない |

## 影響

- `worker.js` を変えたら `CODE_VERSION` を上げる必要がある（接続中の Durable Object が古いコードで動き続けるため）。
- Misskey のトークンは Durable Object のストレージに保存される。トークンを作り直したら `/stream/setup` を呼び直す。
