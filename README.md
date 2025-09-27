# 主要機能

- /start : 初期化、ヘルプ
- /log : 記録をする
- /today : 今日の記録を時系列で表示
- /week : 直近 7 日を表示（日別）
- /undo : 最近の 1 件を削除
- /export : CSV を書き出して送信する

## BotFather でボット作成

1. Telegram で @BotFather を開く
2. `/start` -> `/newbot` と入力
3. ボット名 を決める
4. 返ってきた Bot Token を控える

### 仮想環境を作る

```
python3 -m venv venv
source venv/bin/activate
```

### フォーマッターを実行する

```
pip install black
black skeddybot.py
```

## 起動方法

必要なパッケージをインストールする

```
pip install python-telegram-bot==20.7
```

環境変数にトークンを入れる

```
export TELEGRAM_TOKEN="自分のボットのトークン"
```

起動

```
python skeddybot.py
```
