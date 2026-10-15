# 配置手順(Linux 機 hro-calc-prod1)

★**録り逃した日のオッズは永久に埋まらない。** 手で起動する運用にしないこと。
結果と払戻は後から埋められるが、時系列オッズだけは取り返しがつかない。

```bash
cd ~/hro && git clone https://github.com/hro-kt/hro-nar-synchronizer.git
cd hro-nar-synchronizer && poetry install
cp ../hro-synchronizer/.env .          # DB 接続情報を流用
mkdir -p ~/hro/logs
poetry run hro-nar-synchronizer init-db

sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hro-nar-collect.timer hro-nar-results.timer
systemctl list-timers 'hro-nar-*'
```

## 動いているかの確認

```bash
# 今日の被覆。0 が並ぶなら収集が止まっているか、ページの構造が変わっている
poetry run hro-nar-synchronizer coverage

# 直近7日
poetry run hro-nar-synchronizer coverage --date ''
tail -f ~/hro/logs/nar-collect.log
```

`coverage` は締切前の断面が少ないレースがあると終了コード 1 を返す。

## 中央との関係

地方は netkeiba の HTTP だけを使う。JV-Link も IPAT も触らないので、
**中央の収集と同時に動いて構わない**(1台1プロセス制約は中央側だけの話)。
DB は同じだがテーブルは `nar_*` で分かれており、混ざることはない。
