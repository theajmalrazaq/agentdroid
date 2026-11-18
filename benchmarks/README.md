# AgentDroid Unified Benchmark

One reproducible benchmark ([`benchmark.py`](benchmark.py) → [`results/summary.json`](results/summary.json)) measured live on `redroid11_x86_64` (`Android 11`, `1080x2400`) against primary baselines from [AndroidWorld (`arXiv:2405.14573v3`)](https://arxiv.org/html/2405.14573v3), [Vostride](https://vostride.com/benchmark/android-world), [Google Artemis](https://github.com/google/artemis), and [Mobilebox (`summary.csv`)](https://github.com/mobilebox-dev/mobilebox/blob/main/benchmarks/results/summary.csv).

---

## 1. Platform Comparison

| Platform / Agent | Task Success Rate | Avg Task Time | Action + Observe Latency | Payload / Step | Boot / Install |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AgentDroid (1-Turn Compound / MCP)** | **100.0%** (`13/13` verified) | **2.35 s** (`30.6 s` total · **32.4x** vs Vostride) | **0.83 ms** tap · **16.4 ms** UI loop (`82.9 ms` burst) | **430–674 tok** (`1.7–2.7 KB` text) | **11.9 s** boot · **910 ms** APK |
| **AgentDroid + Jev (`jev-latest` AI)** | **92.3%** (`12/13` verified) | **10.33 s** (`323–558 ms`/turn · **10.6x** vs Vostride) | **0.83 ms** tap · **16.4 ms** UI loop | **430–674 tok** (`1.7–2.7 KB` text) | **11.9 s** boot · **910 ms** APK |
| **Vostride** *(matched `9` tasks)* | Baseline (`9` matched) | **91.9 s** (`827.0 s` total) | **517 ms** tap · **8–15 s** VLM | **1,445 tok** (`125 KB` PNG) | Cloud VM |
| **Google Artemis** *(AndroidWorld)* | **99.1%** *(published)* | **180–300 s** | **150–400 ms** A11y · **3–40 s** LLM | Screenshot + XML | Standalone stack |
| **AutoGLM / GLM-4V Mobile** | **80.2%** *(published)* | **60–120 s** | **500 ms** `adb` · **6–10 s** VLM | ~1,200 tok PNG | Host + Device |
| **Mobile-Agent-v2 / AppAgent** | **73.3%** *(published)* | **90–180 s** | **520 ms** `adb` · **7–14 s** VLM | PNG + OCR crops | Host + Python |
| **UI-TARS (ByteDance)** | **46.6%** *(published)* | **45–90 s** | **500 ms** `adb` · **4–8 s** VLM | Full PNG | Dedicated GPU |
| **Google M3A** *(`arXiv:2405.14573v3`)* | **30.6%** *(A11y)* · **25.4%** *(SoM)* | **~234.0 s** | **550 ms** `adb` · **12–25 s** VLM | XML / SoM PNG | AVD QEMU (`49.2 s` boot) |
| **Mobilebox** *(Nuremberg, `summary.csv`)* | Infra baseline | **24.6–37.9 s** *(demo)* | **517 ms** tap · **1,448 ms** cap | `50+ KB` PNG | **17.8 s** boot · **1,172 ms** APK |
| **Android Studio AVD (KVM On/Off)** | Static scripts (`0%` adapt) | Script dependent | **150–1,880 ms** · **1–18 s** cap | Static selectors | **49.2 s / 13.0 min** boot |

- **Speedups vs. host baselines:** Persistent `/dev/uinput` `InputDaemon` tap (`0.83 ms` median vs `607.8 ms` `adb shell input`) is **732x faster**; `tap_to_ui_dump` (`16.44 ms` vs `1,065.7 ms` `tap_to_screenshot`) is **65x faster**; 3-action burst (`82.85 ms` vs `1,770.4 ms` shell chain) is **21.4x faster**.
- **Token reduction:** Pruned text (`1,719–2,694 chars` / `~430–674` est. tok) vs raw XML (`13.7–18.3 KB`) & Vision PNG (`1,445` OpenAI / `1,477` Anthropic tok).

---

## 2. Per-Task Ground-Truth Results (`13` Real-App Tasks)

Every task starts from cleared/clean state, executes dynamically until completion or limit, and is checked against SQLite, `ContentProvider`, `/sdcard/` disk files, or live accessibility UI deltas:

| Complexity | Task | App | Baseline | AgentDroid Compound (`1` turn) | AgentDroid + Jev (`jev-latest`) | Ground-Truth Verifier |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Simple** | `ClockStopWatchRunning` | Clock | `38.0 s` *(Vostride)* | **PASS** · **`0.56 s`** (`5` steps) | **PASS** · **`3.19 s`** (`3` steps) | UI has `'Pause'` & `'LAP'` |
| **Simple** | `ClockStopWatchPausedVerify` | Clock | `97.0 s` *(Vostride)* | **PASS** · **`0.22 s`** (`2` steps) | **FAIL** · `11.15 s` (`8` steps, toggle loop) | UI has `'Start'`, `'Pause'` absent |
| **Simple** | `SettingsNavigateAboutPhone` | Settings | Real UI scroll | **PASS** · **`1.24 s`** (`3` steps) | **PASS** · `43.53 s` (`6` steps) | `'Android version'` & `'Device name'` |
| **Medium** | `DeskClockAddAlarm` | Clock | State delta | **PASS** · **`0.80 s`** (`5` steps) | **PASS** · **`2.36 s`** (`3` steps) | Alarm clocks `+1`, `'ON'` switches `+1` |
| **Medium** | `ClockTimerEntry` | Clock | `57.0 s` *(Vostride)* | **PASS** · **`0.69 s`** (`9` steps) | **PASS** · `16.40 s` (`6` steps) | Timer readout shows `'16m 35s'` |
| **Medium** | `TasksAddTask` | Tasks | AndroidWorld App | **PASS** · **`2.53 s`** (`7` steps) | **PASS** · **`3.94 s`** (`4` steps) | SQLite `tasks` has `'Submit benchmark report'` |
| **Medium** | `FossifyMathCompute` | Fossify Math | Mobilebox APK | **PASS** · **`0.47 s`** (`8` steps) | **PASS** · **`6.10 s`** (`7` steps) | `result` label == `'100'` (`42 + 58`) |
| **Medium** | `AudioRecorderRecordAudio` | Audio Recorder | `62.0 s` *(Vostride)* | **PASS** · **`3.97 s`** (`11` steps) | **PASS** · **`7.07 s`** (`7` steps) | `/sdcard/.../Record-1.m4a` (`24–41 KB`) |
| **Complex** | `ContactsAddContact` | Contacts | `81.0 s` *(Vostride)* | **PASS** · **`2.58 s`** (`12` steps) | **PASS** · **`8.58 s`** (`8` steps) | `contacts/data` has `'Ada'` & `'555-0199'` |
| **Complex** | `SimpleCalendarAddOneEvent` | Simple Calendar | `184.0 s` *(Vostride)* | **PASS** · **`2.62 s`** (`13` steps) | **PASS** · **`6.41 s`** (`7` steps) | SQLite `events.db` `'Architecture Sync\|Room 402'` |
| **Complex** | `BroccoliAddSingleRecipe` | Broccoli | `138.0 s` *(Vostride)* | **PASS** · **`2.40 s`** (`11` steps) | **PASS** · **`5.71 s`** (`6` steps) | SQLite `recipes` `'Pasta Pesto\|15 mins\|...'` |
| **Complex** | `AudioRecorderRecordAudioWithFileName` | Audio Recorder | `106.0 s` *(Vostride)* | **PASS** · **`4.43 s`** (`13` steps) | **PASS** · **`7.75 s`** (`8` steps) | `/sdcard/.../interview_clip.m4a` (`25–38 KB`) |
| **Complex** | `MarkorCreateAndSaveNote` | Markor | `64.0 s` *(post-onboard)* | **PASS** · **`8.08 s`** (`27` steps) | **PASS** · **`12.04 s`** (`12` steps) | Pulled `bench_log.md` == `'Verified on Redroid'` |

**Tier Totals:**
- **Compound (`13/13 = 100.0%` SR):** Simple **`0.67 s`** (`3.3` steps) → Medium **`1.69 s`** (`8.0` steps) → Complex **`4.02 s`** (`15.2` steps) · **`2.35 s`** avg overall (**32.4x** faster on 9 matched AndroidWorld tasks).
- **Jev Autonomous (`12/13 = 92.3%` SR):** `ClockStopWatchPausedVerify` oscillated on the swapped `Pause`/`Start` widget node; all `Medium` (`5/5`) and `Complex` (`5/5`) tasks completed cleanly (**10.6x** faster on matched tasks).

---

## 3. Reproduce

```bash
agentdroid doctor -s 127.0.0.1:5555
python3 benchmarks/benchmark.py --serial 127.0.0.1:5555 --cold-starts 3
# Include live TypeSafe AI (Jev) track:
TYPESAFE_API_KEY="<key>" python3 benchmarks/benchmark.py --serial 127.0.0.1:5555 --cold-starts 0 --with-jev
```
