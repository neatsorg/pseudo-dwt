# pseudo-dwt

Sway (wlroots/libinput) 環境で、MacBook Air 2013 内蔵トラックパッド (`bcm5974`) の
DWT (Disable While Typing) をユーザースペースで擬似的に実現するデーモン。

## 背景

COSMICからSwayに乗り換えたところ、COSMICでは効いていたDWTがSwayで効かなくなった。
調査の結果、以下が判明した。

- `bcm5974` カーネルドライバが、libinputのDWT機構が要求するケイパビリティを
  そもそも公開しておらず、`libinput list-devices` で常に `Disable-w-typing: n/a`
  になる。udevルールやlibinput quirksファイルでは修正不可能な、カーネル側の制約。
- COSMICで動いていたのは、おそらくlibinputのネイティブDWTではなく、
  cosmic-comp (Smithayベース) が独自にキーボードのアクティビティを監視して
  タッチパッドを無効化する実装を持っているため。
- Sway/wlrootsはlibinputのネイティブDWTにしか依存していないため、この
  カーネル側の制約をそのまま受けてしまう。

そのため、libinputのDWTには頼らず、ユーザースペースで同等の挙動を実装した。

## 仕組み

このマシンでは `keyd` (キーリマップデーモン) が物理キーボード
(`Apple Inc. Apple Internal Keyboard / Trackpad`, `/dev/input/event6` 相当) を
`EVIOCGRAB` で専有し、リマップ後のキーを仮想デバイス `keyd virtual keyboard`
として再送出している。物理デバイスは他プロセスからは読めなくなるため、
`pseudo-dwt.py` は代わりにこの `keyd virtual keyboard` を直接読み、
キー押下を検知するたびに以下を行う。

1. `swaymsg input <touchpad識別子> events disabled` でタッチパッドを即座に無効化
2. 350ms (`DEBOUNCE_SEC`) 入力が途絶えたら `events enabled` で再度有効化

タッチパッドの識別子 (`swaymsg -t get_inputs` の `identifier` フィールド) は
起動時に動的取得しており、ハードコードしていない。

root権限のsystemdシステムサービスとして動かし、`runuser -u user` で
実際のSwayセッションに対して `swaymsg` を発行する。ユーザーを `input` グループに
入れる方式は、ユーザーの全プロセスに恒久的な生キーイベント読み取り権限
(事実上のキーロガー権限) を与えてしまうため避けた。

## インストール

```bash
./install.sh
```

内容は以下と同じ。

```bash
sudo cp pseudo-dwt.py /usr/local/bin/pseudo-dwt.py
sudo chmod +x /usr/local/bin/pseudo-dwt.py
sudo cp pseudo-dwt.service /etc/systemd/system/pseudo-dwt.service
sudo systemctl daemon-reload
sudo systemctl enable --now pseudo-dwt.service
```

## 動作確認

```bash
sudo systemctl status pseudo-dwt.service
journalctl -u pseudo-dwt.service -f
```

## 前提

- `keyd` が `keyd virtual keyboard` という名前の仮想デバイスを作っていること
  (別環境で使う場合は `pseudo-dwt.py` の `KEYBOARD_NAME` を実機のキーボード名に
  変更する。`keyd` を使っていない環境では物理キーボードのデバイス名をそのまま
  指定すればよい)
- ログインユーザー名・UIDが `user` / `1000` であること
  (異なる場合は `SWAY_UID` / `SWAY_USER` を変更する)
- 64bit Linux (x86_64など、`long` が8byte) であること。`struct input_event` の
  レイアウトが64bit前提のため、32bit環境やABIが異なる環境では動作しない
