# Misskey CLI（mk.py）

Bot が自分の Misskey アカウントを操作するための CLI です。Python 標準ライブラリだけで動くので、インストールは要りません。

## 使い方

トークンはファイルに書かず、exec の `env` でシークレットを渡します。

```
exec(command="python3 <MEMORY>/files/misskey-harness/mk.py me",
     env={"MISSKEY_HOST": "https://misskey.example.com",
          "MISSKEY_TOKEN": "secret:<scope>:MISSKEY_TOKEN"})
```

| 環境変数 | 内容 |
| --- | --- |
| `MISSKEY_HOST` | インスタンスの URL（既定値はダミーの `https://misskey.example.com`） |
| `MISSKEY_TOKEN` | アクセストークン（`MISSKEY_MUGI_TOKEN` があればそちらを優先） |

| コマンド | 内容 |
| --- | --- |
| `me` | 自分のプロフィール |
| `note "本文" [--cw 注意書き] [--visibility home] [--reply ID] [--renote ID] [--file 画像パス]` | 投稿（本文を `-` にすると標準入力から読む。`--reply` は、相手が自分以外なら先頭に `@user` か `@user@host` を自動で付ける） |
| `delete ID` / `react ID 👍` | 削除・リアクション |
| `tl [home\|local\|hybrid\|global] [-n 20]` | タイムライン |
| `notifs [-n 20]` | 通知 |
| `user @alice [-n 10]` | ユーザー情報と最近の投稿 |
| `follow @alice` / `unfollow @alice` | フォロー |
| `upload パス` | ドライブにアップロード |
| `profile [--name] [--bio] [--avatar パス] [--banner パス] [--field 名前=値] [--bot true] [--pin ID]` | プロフィール更新 |
| `api エンドポイント '{"json":1}'` | 任意の API を呼ぶ（`@file.json` も可） |

`--raw` を付けると生の JSON を出します。API の一覧は各インスタンスの `/api-doc` にあります。

## 注意

- Cloudflare を前段に置いたインスタンス（misskey.vip など）は、Python 既定の User-Agent（`Python-urllib`）を 403 で弾くことがあります。`mk.py` は独自の User-Agent を付けて回避しています。
- HTTP 429 が返ったら、2 秒、4 秒と間をあけて再試行します。
- Bot として動かすアカウントには、`profile --bot true` で bot フラグを付けておきます。
