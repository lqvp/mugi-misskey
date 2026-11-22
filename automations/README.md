# Devin Automation の設定

むぎが使っている 3 本の Automation です。どれもアクションは `message_session` で、`target_bot_id` に Bot の ID を指定し、`auto_create: false` にしています。こうすると、毎回新しいセッションを作らずに Bot 本体の会話へ届きます。

作るときは、Bot に「automations/README.md の 3 本を作って」と頼むのが簡単です（Devin の `managing-automations` スキルで作れます）。プロンプトの `<MEMORY>` は Bot のメモリフォルダ、`<BOT>` は Bot の名前、`<OWNER>` は運用者の名前、`<INSTANCE>` は Misskey のホスト名に置き換えます。トークンは exec の `env` で `MISSKEY_TOKEN=secret:...:MISSKEY_TOKEN` のように参照し、プロンプトに値を書きません。

## 1. Webhook で反応

- トリガー: `webhook:incoming`（シークレットは `MISSKEY_HOOK_SECRET` と同じ値）
- LLM チェック: 有効

プロンプトは次のとおりです。

```text
Misskey webhook: someone mentioned, replied to, reacted to or followed <BOT> on <INSTANCE>. <OWNER> lets <BOT> use the account freely. Read the event, then follow files/misskey-social/PLAYBOOK.md with the harness (`python3 <MEMORY>/files/misskey-harness/mk.py ...`, env MISSKEY_HOST=https://<INSTANCE>, MISSKEY_TOKEN from the secret): update affinity.json, reply, react or ignore by affinity (replying is optional), follow back when it says so, advance files/misskey-social/state.json past this notification, and sync memory. Message <OWNER> only if something needs them.
```

LLM チェックのプロンプトは次のとおりです。

```text
Admit a Misskey webhook payload whose type is mention, reply, follow, followed or reaction. Judge only the acting user: for mention and reply, body.body.note.user (the top-level note's author); for follow events, body.body.user; for reaction, the user who reacted (body.body.user), not the note's author. Admit when that user's isBot is not true and their username is not <BOT_USERNAME>. Ignore nested notes entirely: a reply's body.body.note.reply, or a reacted note, is usually authored by the bot account, which is bot-flagged, and that must never cause a skip. Skip other event types and anything that is not a Misskey webhook payload.
```

「入れ子のノートは無視する」という一文が大事です。リプライ先のノートは Bot 自身（bot フラグ付き）が書いたものなので、これがないと、判定モデルが正当なリプライまで落とすことがあります。

## 2. 通知チェック

- トリガー: `schedule:recurring`
- rrule: `DTSTART;TZID=Asia/Tokyo:19700101T000000` / `RRULE:FREQ=HOURLY;INTERVAL=6;BYMINUTE=17`（6 時間ごと、17 分）

Webhook の取りこぼしを拾うための保険です。

```text
Misskey check: <OWNER> lets <BOT> use its <INSTANCE> account freely. Run `python3 <MEMORY>/files/misskey-harness/mk.py --raw notifs -n 30` (env MISSKEY_HOST=https://<INSTANCE>, MISSKEY_TOKEN from the secret) and handle only mentions, replies, quotes and follows from accounts without the bot flag that are newer than the cursor in files/misskey-social/state.json. Follow files/misskey-social/PLAYBOOK.md: update affinity.json, reply or react or ignore by affinity (replying is optional), follow back when it says so, then save the new cursor and sync memory. Message <OWNER> only if something needs them.
```

## 3. TL 巡回

- トリガー: `schedule:recurring`
- rrule: `DTSTART;TZID=Asia/Tokyo:19700101T000000` / `RRULE:FREQ=DAILY;BYHOUR=9,10,11,12,13,14,15,16,17,18,19,20,21,22,23;BYMINUTE=0,5,10,15,20,25,30,35,40,45,50,55`（9:00〜23:55 に 5 分ごと）
- Preflight check: スクリプト（python）、[preflight/wander_random.py](preflight/wander_random.py) をそのまま貼ります。シークレットは使いません。

トリガーは 5 分ごとに起きますが、実際に巡回するのは Preflight check が通した回だけです。スクリプトは毎時最初の起動で、その時間に巡回する時刻（スロット）を 0〜3 個くじ引きで決めます。

- 1 時間あたりの回数は、0 回 20%、1 回 40%、2 回 30%、3 回 10% です（平均 1.3 回、1 日あたり約 20 回）。
- スロットは 5 分刻みで、互いに 10 分以上あけます。前の時間の最後の巡回からも 10 分以上あけます。
- スロット以外の起動はセッションを起こさずに skip します。決めたスロットと最後に巡回した時刻は、Preflight の `$STATE_FILE` に保存します。

決まった時刻に毎回動くと機械っぽく見えるので、時刻も回数も毎時ばらつくようにしています。頻度を変えたいときは、スクリプト冒頭の `WEIGHTS`（回数ごとの重み）と `MIN_GAP`（最短間隔、分）を直します。トリガーの `BYMINUTE` の刻みを変えたら、`TICK` も合わせます。

```text
Misskey wander: <OWNER> lets <BOT> do whatever it likes on <INSTANCE>. Browse one or two of the timelines (home/local/hybrid/global) with `python3 <MEMORY>/files/misskey-harness/mk.py --raw tl <tl> -n 30` (env MISSKEY_HOST=https://<INSTANCE>, MISSKEY_TOKEN from the secret), then follow the 'TL 巡回と自発投稿' section of files/misskey-social/PLAYBOOK.md: maybe react, maybe reply, maybe post a note of your own, or do nothing. Record it in files/misskey-social/wander.json, update affinity.json if you talked to someone, and sync memory. Message <OWNER> only if something needs them.
```

## 注意

- Automation から起きたセッションには MCP サーバーが付きません。Misskey の操作は `mk.py` だけで完結させています。
- 通知チェックの実行時刻（17 分）は、ほかの定期処理と重ならないようにずらしています。TL 巡回は時刻がランダムなので、ずらす必要はありません。
- Preflight check の状態は Automation ごとに保存されます。Bot のメモリ（`wander.json` など）とは別です。
