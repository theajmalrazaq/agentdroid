# AgentDroid Empirical Benchmark Suite

Reproducible, code-executed benchmarks evaluating **AgentDroid** (`redroid11_x86_64`, Android 11, `1080x2400`, Artemis Accessibility Helper `v1.2.0` + kernel `/dev/uinput` `InputDaemon` on `127.0.0.1:18889`) across the three standard evaluation axes used in mobile GUI-agent and systems research.

**Methodological Principles:**
1. **Zero synthetic estimates:** Every AgentDroid figure is measured on live hardware via `time.perf_counter()` and archived under [`benchmarks/results/`](results/).
2. **Independent ground-truth verification:** End-to-end tasks are never graded by self-reported LLM claims or truncated fixed-step loops. Every task runs dynamically to completion or failure (`max_steps` scaled by task complexity) and is verified directly against SQLite databases, Android `ContentProvider` queries, pulled `/sdcard/` files, or live accessibility state deltas.
3. **Strict separation of local telemetry vs. published baselines:** External comparison metrics are cited directly from their primary papers and repositories:
   - **Google Research AndroidWorld** ([`google-research/android_world`](https://github.com/google-research/android_world), Rawles et al., [`arXiv:2405.14573v3`](https://arxiv.org/html/2405.14573v3))
   - **Vostride AndroidWorld Leaderboard** ([`vostride.com/benchmark/android-world`](https://vostride.com/benchmark/android-world))
   - **Mobilebox & Cloud AVD Parity** ([`mobilebox-dev/mobilebox`](https://github.com/mobilebox-dev/mobilebox), [`benchmarks/results/summary.csv`](https://github.com/mobilebox-dev/mobilebox/blob/main/benchmarks/results/summary.csv))
   - **Google Artemis** ([`google/artemis`](https://github.com/google/artemis))

---

## 1. Industry Architecture & Literature Comparison

| Agent / Platform | Execution Stack | Decision Intelligence | Turn Decision Latency | Gesture Injection Latency | Perception Payload | Mean E2E Task Duration | Empirical Pass / Success Rate | Host Idle Footprint |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **AgentDroid (Compound / MCP)** | **Local Redroid container + `InputDaemon`** | **Host Coding Agent (`1`-turn action burst)** | **Single turn** (Host LLM plans once) | **1.82 ms** (`/dev/uinput` median) | **1.7–2.8 KB** pruned hierarchy (`~433–694 tok`) | **3.77 s** (`49.1 s` total / `13` tasks) | **100.0%** (`13/13` ground-truth E2E) | **0.32% CPU** · `1.16 GB` RAM |
| **AgentDroid + TypeSafe AI (Jev)** | **Local Redroid container + `InputDaemon`** | **TypeSafe AI `jev-latest` (System One Logits)** | **323–558 ms** (typical keep-alive) | **1.82 ms** (`/dev/uinput` median) | **1.7–2.8 KB** (`~167–585 tok`/turn) | **10.33 s** (`134.3 s` total / `13` tasks) | **92.3%** (`12/13` autonomous closed-loop) | **0.32% CPU** · `1.16 GB` RAM |
| **Vostride AndroidWorld Agent** | Cloud VM / Emulated Android | Multimodal VLM (GPT-4o / Claude) | 8,000–15,000 ms | 517 ms (`adb shell input`) | 125 KB PNG tiles (`1,445 tok`) | **91.9 s** (`827.0 s` on matched `9` tasks) | Standard full-suite leaderboard | Cloud VM |
| **Google Artemis** | Multi-Agent Graph (Planner + Operator) | Gemini 2.5 Pro / Flash Graph | 3,000–5,000 ms (Flash) · 15–40s (Pro) | 150–400 ms (A11y HTTP) | Screenshot + raw XML | 180–300 s (published suite) | **99.1%** (published full AndroidWorld) | ~2.2 GB RAM |
| **Mobilebox (Limrun Cloud)** | Cloud Android 14 (Nuremberg DC) | External SDK / LangGraph / VLM | LLM dependent | **76 ms** (Cloud WebSocket) | Full screenshot PNG | 24.6–37.9 s (demo tasks) | Cloud infra baseline | Cloud serverless |
| **Google Research M3A (`arXiv:2405.14573v3`)** | Android Studio AVD (QEMU + KVM) | GPT-4 Turbo / Gemini 1.5 Pro (A11y / SoM) | 12,000–25,000 ms | ~550 ms (`adb shell input`) | A11y tree / SoM annotated PNG | ~234.0 s | **30.6%** (A11y) · **25.4%** (SoM) | `3.5 GB` RAM · High QEMU CPU |
| **AutoGLM / GLM-4V Mobile** | Host Python + Virtual/Real Device | Fine-tuned GLM-4V | 6,000–10,000 ms | ~500 ms (`adb input`) | Vision tokens (~1,200 tok) | 60–120 s | **80.2%** (published AndroidWorld) | Standard host |
| **Mobile-Agent-v2 / AppAgent** | Local Python + Vision Memory | Qwen-VL / GPT-4o Vision | 7,000–14,000 ms | ~520 ms (`adb input`) | Screenshot + OCR + icon crops | 90–180 s | **73.3%** (published AndroidWorld) | Python runtime |
| **UI-TARS (ByteDance)** | Dedicated GPU VLM | UI-TARS 7B / 72B | 4,000–8,000 ms | ~500 ms (`adb input`) | Full resolution screenshot | 45–90 s | **46.6%** (published AndroidWorld) | Dedicated GPU (A100/4090) |

---

## 2. Pillar 1: Systems & Gesture Latency Parity (`benchmark_agentdroid.py`)

Measured directly against Mobilebox's published [`summary.csv`](https://github.com/mobilebox-dev/mobilebox/blob/main/benchmarks/results/summary.csv) dataset using [`benchmark_agentdroid.py`](benchmark_agentdroid.py) (raw data: [`results/benchmark_agentdroid_results.json`](results/benchmark_agentdroid_results.json)):

| Operation | AgentDroid (Local Redroid `127.0.0.1:5555`) | Mobilebox EU (`summary.csv`) | Limrun Cloud (`summary.csv`) | Local AVD KVM On (`summary.csv`) | Local AVD KVM Off (`summary.csv`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Cold-Start `ready` (median)** | **9,767 ms** (`n=3`, p90 `9,886`) | **17,833 ms** (`n=10`, p90 `18,072`) | **338 ms** (`n=10`, p90 `454`) | **49,231 ms** (+`75,307 ms` setup) | **782,342 ms** (`13.0 min`) |
| **`cold_start_to_screenshot` (median)** | **10,963 ms** (`n=3`, p90 `11,096`) | **19,353 ms** (`n=10`, p90 `19,487`) | **977 ms** (`n=10`, p90 `1,067`) | **50,009 ms** (`n=5`, p90 `50,278`) | **812,681 ms** (`13.5 min`) |
| **APK Install (`org.fossify.math`)** | **675 ms** fresh (`n=3`) · **648 ms** `-r` (`n=5`) | **1,172 ms** (`n=10`, p90 `1,544`) | **850 ms** (`n=10`, p90 `954`) | **6,091 ms** (`n=5`, p90 `7,307`) | **125,911 ms** (`n=1`) |
| **Single Tap Injection (median)** | **1.82 ms** `InputDaemon` (`n=10`) · **3.06 ms** IPC (`n=20`) | **517 ms** (`n=100`, p90 `526`) | **76 ms** (`n=100`, p90 `78`) | **150 ms** (`n=50`, p90 `383`) | **1,880 ms** (`n=10`, p90 `5,107`) |
| **3-Action Sequence (`burst` vs `adb`)** | **310.6 ms** Compound Burst vs **1,652.2 ms** `adb` shell chain (`5.3x` faster) | — | — | — | — |
| **Environment Turnaround (Action -> Obs)** | **6.46 ms** `tap_to_ui_dump` (`n=10`) · **758 ms** `adb screencap` | **1,448 ms** `tap_to_screenshot` | **384 ms** `tap_to_screenshot` | **1,035 ms** `tap_to_screenshot` | **18,691 ms** `tap_to_screenshot` |

**Why this matters:** Bypassing `/system/bin/input` VM startup via a persistent `/dev/uinput` daemon cuts single touch injection from `552.4 ms` (`adb shell input`) to `1.82 ms` (**303x faster**), while structural UI dumps cut tap-to-observation turnaround from `758 ms` to `6.46 ms` (**117x faster**).

---

## 3. Pillar 2: Perception Payload & Token Efficiency (`1080x2400`)

Standard vision-based mobile agents encode full screenshots into vision transformer patches on every step. AgentDroid prunes non-interactive layout wrappers into compact indexed element trees:

| Live App Screen | Raw Hierarchy XML | `dump_compact_ui` JSON | AgentDroid `formatted_text` | Size Reduction vs XML | Vision Screenshot (`1080x2400`) & Token Cost |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Fossify Math** (`34` XML nodes) | `13,721 B` (`~3,430` est. tok) | `2,864 B` (`28` elements) | **`1,730 chars`** (**`~433` est. tok**) | **87.4% smaller (`7.9x`)** | `54,662 B` PNG · **1,445 tok** (OpenAI `2x4` tiles) / **1,477 tok** (Anthropic) |
| **Android Settings** (`47` XML nodes) | `18,959 B` (`~4,740` est. tok) | `3,932 B` (`40` elements) | **`2,774 chars`** (**`~694` est. tok**) | **85.4% smaller (`6.8x`)** | `125,747 B` PNG · **1,445 tok** (OpenAI `2x4` tiles) / **1,477 tok** (Anthropic) |

---

## 4. Pillar 3: Complexity-Stratified End-to-End Task Suite (`run_e2e_benchmark.py`)

Executed end-to-end across **13 verifiable tasks** spanning **8 real open-source Android apps** (`Clock`, `Settings`, `Tasks`, `Fossify Math`, `Audio Recorder`, `Contacts`, `Simple Calendar`, `Broccoli`, `Markor`) and **3 complexity tiers** (`Simple`, `Medium`, `Complex`). Full raw step traces and artifacts: [`results/benchmark_e2e_results.json`](results/benchmark_e2e_results.json).

### 4.1 Complexity-Tier Summary

| Complexity Tier | Tasks (`n`) | Track 1: AgentDroid Compound (`1`-Turn Burst) | Track 2: AgentDroid + Jev (`jev-latest` Closed Loop) |
| :--- | :---: | :--- | :--- |
| **Simple** (`2–6` steps) | `3` | **100.0% SR** (`3/3`) · `3.33` steps · **`2.31 s`** avg | **66.7% SR** (`2/3`) · `5.67` steps · **`19.29 s`** avg *(note 1)* |
| **Medium** (`3–11` steps) | `5` | **100.0% SR** (`5/5`) · `8.00` steps · **`4.42 s`** avg | **100.0% SR** (`5/5`) · `5.40` steps · **`7.18 s`** avg |
| **Complex** (`6–27` steps) | `5` | **100.0% SR** (`5/5`) · `15.20` steps · **`4.01 s`** avg | **100.0% SR** (`5/5`) · `8.20` steps · **`8.10 s`** avg |
| **Overall Suite** | **`13`** | **100.0% SR (`13/13`) · `9.69` steps · `3.77 s` avg (`49.07 s` total)** | **92.3% SR (`12/13`) · `6.54` steps · `10.33 s` avg (`134.25 s` total)** |

*(1) Simple tier average in Track 2 reflects `SettingsNavigateAboutPhone` hitting a transient network/UI stall (`43.53 s`, `6` steps) and `ClockStopWatchPausedVerify` failing `max_steps=8` (`11.15 s`) due to stateless Pause/Start label oscillation.*

### 4.2 Complete Per-Task Telemetry & Ground-Truth Verification

| Tier | Task ID | App | Published Baseline | AgentDroid Compound (`1` turn) | AgentDroid + Jev (`jev-latest`) | Ground-Truth Post-Condition Verifier |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Simple** | `ClockStopWatchRunning` | Clock | `38.0 s` (`2` acts, Vostride) | **PASS** · **`2.35 s`** (`5` steps) | **PASS** · **`3.19 s`** (`3` steps, `343 ms`/AI) | Live UI contains `'Pause'` & `'LAP'` |
| **Simple** | `ClockStopWatchPausedVerify` | Clock | `97.0 s` (`4` acts, Vostride) | **PASS** · **`0.46 s`** (`2` steps) | **FAIL** · `11.15 s` (`8` steps, toggle loop) | Live UI shows `'Start'`, `'Pause'` absent |
| **Simple** | `SettingsNavigateAboutPhone` | Settings | Real UI scroll baseline | **PASS** · **`4.12 s`** (`3` steps) | **PASS** · `43.53 s` (`6` steps, `468 ms`/AI) | Foreground `com.android.settings`, `'Android version'` & `'Device name'` present |
| **Medium** | `DeskClockAddAlarm` | Clock | Real-App delta baseline | **PASS** · **`3.58 s`** (`5` steps) | **PASS** · **`2.36 s`** (`3` steps, `457 ms`/AI) | `digital_clock` count `2 -> 3`, `'ON'` switch `0 -> 1` |
| **Medium** | `ClockTimerEntry` | Clock | `57.0 s` (`6` acts, Vostride) | **PASS** · **`2.65 s`** (`9` steps) | **PASS** · **`16.40 s`** (`6` steps, Step 1 cold spike) | Live UI timer readout displays `'16m 35s'` |
| **Medium** | `TasksAddTask` | Tasks | AndroidWorld Tasks app | **PASS** · **`7.93 s`** (`7` steps) | **PASS** · **`3.94 s`** (`4` steps, `383 ms`/AI) | SQLite `tasks` table contains `'Submit benchmark report'` |
| **Medium** | `FossifyMathCompute` | Fossify Math | Mobilebox parity APK | **PASS** · **`1.34 s`** (`8` steps) | **PASS** · **`6.10 s`** (`7` steps, `466 ms`/AI) | Display `result` element equals `'100'` (`42 + 58`) |
| **Medium** | `AudioRecorderRecordAudio` | Audio Recorder | `62.0 s` (`6` acts, Vostride) | **PASS** · **`6.61 s`** (`11` steps) | **PASS** · **`7.07 s`** (`7` steps, `378 ms`/AI) | `/sdcard/.../Record-1.m4a` on disk (`20–40 KB`) |
| **Complex** | `ContactsAddContact` | Contacts | `81.0 s` (`7` acts, Vostride) | **PASS** · **`2.66 s`** (`12` steps) | **PASS** · **`8.58 s`** (`8` steps, `558 ms`/AI) | `content://com.android.contacts/data` has `'Ada'` + `'555-0199'` |
| **Complex** | `SimpleCalendarAddOneEvent` | Simple Calendar | `184.0 s` (`18` acts, Vostride) | **PASS** · **`2.54 s`** (`13` steps) | **PASS** · **`6.41 s`** (`7` steps, `376 ms`/AI) | SQLite `events.db` contains `'Architecture Sync\|Room 402'` |
| **Complex** | `BroccoliAddSingleRecipe` | Broccoli | `138.0 s` (`13` acts, Vostride) | **PASS** · **`2.44 s`** (`11` steps) | **PASS** · **`5.71 s`** (`6` steps, `350 ms`/AI) | SQLite `broccoli` DB has `'Pasta Pesto\|15 mins\|Pasta, Basil, Garlic'` |
| **Complex** | `AudioRecorderRecordAudioWithFileName` | Audio Recorder | `106.0 s` (`10` acts, Vostride) | **PASS** · **`4.57 s`** (`13` steps) | **PASS** · **`7.75 s`** (`8` steps, `324 ms`/AI) | `/sdcard/.../interview_clip.m4a` on disk (`25–38 KB`) |
| **Complex** | `MarkorCreateAndSaveNote` | Markor | `64.0 s` (post-onboard, Vostride) | **PASS** · **`7.82 s`** (`27` steps) | **PASS** · **`12.04 s`** (`12` steps, `384 ms`/AI) | Pulled `/sdcard/Documents/markor/bench_log.md` (`19 B`: `'Verified on Redroid'`) |

### 4.3 Key Experimental Takeaways

1. **Intra-App Complexity Scaling Holds Empirically:** In Track 2 (`jev`), `AudioRecorderRecordAudioWithFileName` took more autonomous steps (`8` vs `7`) and longer wall time (`7.75 s` vs `7.07 s`) than `AudioRecorderRecordAudio` due to filename `EditText` entry and IME dismissal; full onboarding + disk save in `MarkorCreateAndSaveNote` scaled smoothly to `12` steps (`12.04 s`).
2. **Matched AndroidWorld Speedup (`10.6x` Autonomous / `25.8x` Compound):** Across the 9 tasks with direct published Vostride AndroidWorld baselines (`827.0 s` baseline total), **AgentDroid + Jev** completed the subset in **`78.31 s`** (**10.6x faster**, `88.9%` SR) and **AgentDroid Compound** completed all 9 in **`32.09 s`** (**25.8x faster**, `100.0%` SR).
3. **Failure Mode Transparency (`ClockStopWatchPausedVerify`):** When Jev tapped `Pause`, Android swapped the button text at the exact same widget node to `Start` without showing a `'Paused'` state string, causing the stateless System One classifier to bounce between `Pause` and `Start`. Track 1 (`Compound`) avoids toggle oscillation because host agents plan state-aware bursts.

---

## 5. How to Reproduce

```bash
# 1. Verify silent container, root ADB, Accessibility Helper, and InputDaemon
agentdroid doctor -s 127.0.0.1:5555

# 2. Download/install real open-source AndroidWorld benchmark APKs if needed
python3 scripts/download_android_world_apks.py 127.0.0.1:5555

# 3. Run Pillar 1 & 2 (Infrastructure latency & perception token benchmarks)
python3 benchmarks/benchmark_agentdroid.py --serial 127.0.0.1:5555 --cold-starts 3

# 4. Run Pillar 3 (Verifiable 13-task E2E suite — local Compound mode)
python3 benchmarks/run_e2e_benchmark.py --serial 127.0.0.1:5555 --mode compound

# 5. Run Pillar 3 (Both local Compound + autonomous TypeSafe AI Jev tracks)
export TYPESAFE_API_KEY="<your-typesafe-key>"
python3 benchmarks/run_e2e_benchmark.py --serial 127.0.0.1:5555 --mode both
```
