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
- rrule: `DTSTART;TZID=Asia/Tokyo:19700101T000000` / `RRULE:FREQ=DAILY;BYHOUR=9,11,13,15,17,19,21,23;BYMINUTE=37`（9 時〜23 時の奇数時、37 分）

```text
Misskey wander: <OWNER> lets <BOT> do whatever it likes on <INSTANCE>. Browse one or two of the timelines (home/local/hybrid/global) with `python3 <MEMORY>/files/misskey-harness/mk.py --raw tl <tl> -n 30` (env MISSKEY_HOST=https://<INSTANCE>, MISSKEY_TOKEN from the secret), then follow the 'TL 巡回と自発投稿' section of files/misskey-social/PLAYBOOK.md: maybe react, maybe reply, maybe post a note of your own, or do nothing. Record it in files/misskey-social/wander.json, update affinity.json if you talked to someone, and sync memory. Message <OWNER> only if something needs them.
```

## 注意

- Automation から起きたセッションには MCP サーバーが付きません。Misskey の操作は `mk.py` だけで完結させています。
- 実行時刻の分（17 分、37 分）は、ほかの定期処理と重ならないようにずらしています。
