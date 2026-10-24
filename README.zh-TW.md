# landline-hub

[English](README.md) | **繁體中文**

**把家裡或公司的市話，變成會響到手機上的小型電話總機。**

https://github.com/user-attachments/assets/812fc9dc-bb64-444c-bcd6-c42b66932d2e

- **來電轉到手機**：市話一響，你的手機跟著響，人在哪裡都能接。
- **總機與分機**：系統先接起來、請對方按分機，再讓那支分機背後的手機響。公司分機可以就是員工的手機，在不在辦公室都接得到。
- **用手機透過市話撥出**：對方看到的是你的市話號碼。
- **讓程式也能用這條線**：幫你打電話的 AI（[landline-agent](https://github.com/luna61ouo/landline-agent)）對 hub 來說只是另一個用戶端。不用 AI 也能單獨使用 hub。

已用 Grandstream HT813 閘道器與台灣號碼實測。

## 架構

```
 市話 ── FXO 閘道器 ──SIP── landline-hub ──HTTPS / WebSocket── Android App（你的手機）
(牆上插孔) (HT813)             │                               landline-agent（選用）
                               └─ 通話紀錄、配對、             你自己的程式
                                  號碼規則與權限
```

閘道器把類比市話轉成 SIP，整個系統只有 hub 跟 SIP 打交道。手機和程式跟 hub 配對之後，都用同一套小小的 HTTP API：收事件（有電話在響、接起來了、掛斷了）、要求撥出，並透過 WebSocket 收送聲音（8 kHz、16 位元 PCM、每格 20 毫秒）。

## 需要準備

- 一條市話和一台 **FXO 閘道器**（實測 Grandstream HT813；來電會直接轉成一般 SIP 的閘道器，設定 `kind = "sip"` 應該也能用）。
- 同一個網路裡的一台 Linux 電腦，Python 3.11 以上。
- 裝 App 的 Android 手機（Android 10 以上）。自己編譯 App 需要 Android SDK 的 platform 35 與 build-tools 35.0.0。要從外面連回 hub，請在前面架 VPN 或有 TLS 的反向代理；hub 預設只聽本機。

## 安裝

```bash
git clone https://github.com/luna61ouo/landline-hub && cd landline-hub
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
cp config.example.toml config.toml        # 接著改 [gateway]
```

閘道器怎麼接線、哪些設定要改、來電顯示：見 [docs/ht813-setup.md](docs/ht813-setup.md)（英文）。

### 沒有硬體也能試

`tools/fakegw` 是跑在 Docker 裡的假閘道器（baresip），會接電話並播一段聲音。

```bash
tools/fakegw/run.sh start                  # config.toml 的 [gateway].host 設成你的區網 IP
landline-hub serve -c config.toml
landline-hub pair -c config.toml --name my-phone          # 印出一次性配對碼（10 分鐘有效）
python tools/try_client.py http://127.0.0.1:8910 - pair <配對碼>
python tools/try_client.py http://127.0.0.1:8910 <token> dial 0212345678 5
```

### 當成常駐服務

用什麼行程管理都可以。systemd（使用者服務）範例：

```ini
[Service]
WorkingDirectory=/path/to/landline-hub
ExecStart=/path/to/landline-hub/.venv/bin/landline-hub serve -c config.toml
Restart=on-failure
```

## 設定

`config.example.toml` 裡有註解，主要的選擇：

| 區段 | 決定什麼 |
|---|---|
| `[gateway]` | `kind = "ht813"`（從 HT813 的 syslog 偵測響鈴，有人按接聽才真的接起來）或 `"sip"`（閘道器一有來電就用 SIP 送過來）。只接受閘道器那個位址送來的 SIP。 |
| `[forward] mode` | `direct`：所有配對的手機一起響，誰先接誰講。`pbx`：系統先接起來，依分機轉接。 |
| `[pbx]` | 分機號碼與每個分機背後的手機、總機分機、逾時，以及語音提示檔（`greeting.wav`、`invalid.wav`…，8 kHz 單聲道）。分機號碼不能互為開頭（例如 1 和 12），不然按到一半分不出來。 |
| `[numbers] policy` | 號碼規則。目前只有 `tw`（台灣）。 |

## 手機與程式（用戶端）

每個用戶端配對一次，拿到自己專屬的憑證（hub 只存雜湊值）。

```bash
landline-hub pair    -c config.toml --name alex-phone              # 人拿的手機（角色：handset）
landline-hub pair    -c config.toml --name my-agent --role agent   # 程式
landline-hub clients -c config.toml
landline-hub revoke  -c config.toml alex-phone
landline-hub grant   -c config.toml 名稱 --kind emergency          # 見下表
```

各角色能撥什麼：

| | 一般號碼 | 緊急電話（110、119…） | 付費號碼 |
|---|---|---|---|
| **handset**（人） | ✅ | ✅（它就是一支電話） | ❌ |
| **agent**（程式） | ✅ | ❌（除非另外授權） | ❌ |

同一時間只有一個用戶端能使用這條線；線路忙碌時再撥會收到 `409`。

## API

| | |
|---|---|
| `POST /v1/pair` `{code}` | → `{client_id, token}`；不需驗證，一次性配對碼本身就是憑證 |
| `GET /v1/events` | Server-sent events：`incoming`、`answered`、`ended`…。斷線重連時，會立刻補送還在響的電話。 |
| `POST /v1/outbound` `{number, answer_detection?}` | → `{call_id}`；`403` 沒有權限、`409` 線路忙碌 |
| `POST /v1/calls/{id}/answer`、`/hangup` | |
| `WS /v1/calls/{id}/media` | 二進位：雙向 20 毫秒 8 kHz PCM16。送入文字：`{"type":"hangup"}`、`{"type":"clear"}`、`{"type":"dtmf","digits":"1"}`。送出文字：這通電話的事件。 |
| `GET /v1/status`、`GET /v1/history` | 線路狀態；最近 50 通 |

除了配對，其他都要帶 `Authorization: Bearer <token>`。

**判斷對方接起來了沒。** 類比市話不會告訴你「對方接了」：閘道器一撥完號就算接通。設 `answer_detection: true` 時，hub 會聽回鈴音的節奏，在真人（或語音信箱）接起來之前先把聲音扣住，接起來才送出 `callee_answered {how, talking}`。如果只是推測接通（下一聲鈴沒來），hub 會再聽幾秒；鈴聲又響起就關回去，送出 `callee_not_answered`。想在自己的線路上驗證閘門，設 `[answer_detection] keep_audio = true`：hub 會存每通外撥到閘門下判斷為止的原始聲音（`keep_days` 天後刪除），`tools/gate_replay.py --exam` 會把標好答案的錄音重播給閘門考試。這組參數是照台灣的回鈴音（響 1 秒、停 3 秒；有些交換機是響 1.1 秒、停 1.9 秒，兩種都認得）調的。

**真人講話不排隊。** 對人拿的手機，hub 不會讓聲音排隊：接通前的聲音直接丟掉，積壓最多 200 毫秒，所以網路慢時頂多漏一個字，不會整段晚 10 秒。

## Android App

在 `android/`。不用 Gradle，`build.sh` 直接用 SDK 的命令列工具。

```bash
cd android
ANDROID_HOME=/path/to/android-sdk KEYSTORE=/path/to/your.jks KS_PASS_FILE=/path/to/pass bash build.sh
adb install -r build/landline-hub.apk
```

- 用一次性配對碼配對，之後在背景保持連線，來電會像一般電話一樣響。
- 撥號鍵盤、最近通話、通話中按鍵（DTMF）、擴音／聽筒（有接近感應）。
- 英文與繁體中文介面。
- 套件名稱 `org.landlinehub.app`。**簽章鑰匙要保管好**：Android 只接受同一把鑰匙簽的更新。

第一次從電腦安裝時，有些手機品牌會要你在手機上按確認。

## 安全

- **不會被盜打。** 打進來的人按鍵只能選分機或「繼續等／轉總機」。程式裡沒有任何一條路能從來電接到外線，測試裡用 500 輪亂按來驗證。
- **程式不能撥緊急電話或付費號碼**，除非你指名授權。號碼會先統一格式，所以 `110#`、`(110)`、`+886 110` 都會被認成 110。
- **配對好的手機就是一支電話。** 一般電話能撥的它都能撥，包括緊急電話，這是刻意的。如果同一台電腦上的 AI 能操作你的手機（例如透過 adb），那條路不會經過任何核准，請在 AI 那一端擋住。
- hub 預設只聽本機。不要沒有 TLS、沒有 VPN 或代理就直接開到網際網路上。

## 已知限制

- **目前只支援台灣**：號碼規則（`[numbers] policy = "tw"`）和判斷接聽用的回鈴音節奏。其他國家需要各自的規則與參數，歡迎貢獻。
- 一套 hub 接一條線。
- 只在一款閘道器（HT813）上測過。

## 開發

```bash
python3 -m unittest discover -s tests -t .     # 只用標準函式庫
```

## 作者

Luke Liu & Luna Liu

## 授權

MIT — Copyright (c) 2026 Luke Liu。見 [LICENSE](LICENSE)。
