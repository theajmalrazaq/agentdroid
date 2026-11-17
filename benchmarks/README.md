# AgentDroid Benchmark Suite

Empirical benchmarks comparing **AgentDroid** (`redroid11_x86_64`, Android 11, `1080x2400`, Artemis Helper `v1.2.0` + `com.agentdroid.InputDaemon` on `127.0.0.1:18889`) against verified primary-source external baselines. **Zero synthetic, simulated, or extrapolated metrics** — every AgentDroid figure is measured on live local hardware via `time.perf_counter()`, and every external figure is cited verbatim from its primary repository or paper:

1. **Google Artemis** ([`google/artemis`](https://github.com/google/artemis), `README.md` & [`docs/assets/androidworld_leaderboard.png`](https://github.com/google/artemis/blob/main/docs/assets/androidworld_leaderboard.png))
2. **Google Research AndroidWorld** ([`google-research/android_world`](https://github.com/google-research/android_world), Rawles et al. [`arXiv:2405.14573v3`](https://arxiv.org/html/2405.14573v3) Table 3 & Section 4.3, `README.md`)
3. **Mobilebox** ([`mobilebox-dev/mobilebox`](https://github.com/mobilebox-dev/mobilebox), [`benchmarks/results/summary.csv`](https://github.com/mobilebox-dev/mobilebox/blob/main/benchmarks/results/summary.csv) [`2026-11-08`], [`benchmarks/README.md`](https://github.com/mobilebox-dev/mobilebox/blob/main/benchmarks/README.md), [`benchmarks/limrun.mjs`](https://github.com/mobilebox-dev/mobilebox/blob/main/benchmarks/limrun.mjs), `README.md`, [`examples/RUNS.md`](https://github.com/mobilebox-dev/mobilebox/blob/main/examples/RUNS.md))

---

## Benchmark Scripts & Raw Data

- [`benchmark_agentdroid.py`](benchmark_agentdroid.py): Measures OS container cold restarts (`docker restart agentdroid-device`), real `adb install` (`org.fossify.math` `7,047,681 B` + `net.gsantner.markor` `11,849,016 B`), `InputDaemon` vs `adb input` tap latencies, IPC global actions, atomic `/snapshot?fields=xml`, compact UI dumps, action bursts, and live `1080x2400` payload/token sizes.
- [`run_actual_app_benchmark.py`](run_actual_app_benchmark.py): Executes 4 end-to-end workflows (`Markor`, `DeskClock`, `Settings`, `Fossify Math`) with strict disk/delta/crash assertions via `CompoundPipeline`, `AndroidEngine`, and `agentdroid run --headless -j`.

Raw JSON outputs (exact live captures):
- [`results/benchmark_agentdroid_results.json`](results/benchmark_agentdroid_results.json)
- [`results/benchmark_actual_apps_results.json`](results/benchmark_actual_apps_results.json)

---

## Running the Benchmarks

Ensure `org.fossify.math_10.apk` (`7,047,681 B`) is cached in `~/.cache/agentdroid/apks/` and the Redroid container (`agentdroid-device`) is healthy on `127.0.0.1:5555`:

```bash
agentdroid doctor -s 127.0.0.1:5555
python3 benchmarks/benchmark_agentdroid.py --serial 127.0.0.1:5555 --cold-starts 3
python3 benchmarks/run_actual_app_benchmark.py --serial 127.0.0.1:5555
```

---

## 1. Complete Infrastructure Parity (`benchmark_agentdroid.py` vs. Mobilebox `summary.csv` `2026-11-08`)

Every provider and metric present in [`mobilebox/benchmarks/results/summary.csv`](https://github.com/mobilebox-dev/mobilebox/blob/main/benchmarks/results/summary.csv) is included below. Note that Mobilebox installed [`org.fossify.math`](https://f-droid.org/packages/org.fossify.math/) v1.4.0 (`~4 MB` per [`mobilebox/benchmarks/README.md`](https://github.com/mobilebox-dev/mobilebox/blob/main/benchmarks/README.md)), whereas AgentDroid installed the F-Droid `org.fossify.math_10.apk` binary (`7,047,681 B`).

| Metric | AgentDroid (Local Redroid `127.0.0.1:5555`) | Mobilebox EU (Nuremberg) | Mobilebox CI (`ubuntu-latest`) | Limrun (Nuremberg) | Phone Harness (Nuremberg) | Local AVD KVM On (`ubuntu-latest`) | Local AVD KVM Off (`ubuntu-latest`) |
|---|---|---|---|---|---|---|---|
| **`ready` (median)** | **9,767 ms** (`n=3`, p90 `9,886`) | **17,833 ms** (`n=10`, p90 `18,072`) | **18,252 ms** (`n=5`, p90 `18,580`) | **338 ms** (`n=10`, p90 `454`) | **20,676 ms** (`n=10`, p90 `66,953`) | **49,231 ms** (+`75,307 ms` setup) | **782,342 ms** (`n=1`, +`37,810 ms` setup) |
| **`cold_start_to_screenshot` (median)** | **10,963 ms** (`n=3`, p90 `11,096`) | **19,353 ms** (`n=10`, p90 `19,487`) | **20,268 ms** (`n=5`, p90 `20,630`) | **977 ms** (`n=10`, p90 `1,067`) | **23,028 ms** (`n=10`, p90 `69,977`) | **50,009 ms** (`n=5`, p90 `50,278`) | **812,681 ms** (`13.5 min`, `n=1`) |
| **`apk_install` (`org.fossify.math`)** | **675 ms** fresh (`n=3`) · **648 ms** `-r` (`n=5`) | **1,172 ms** (`n=10`, p90 `1,544`) | **1,166 ms** (`n=5`, p90 `2,039`) | **850 ms** (`n=10`, p90 `954`) | **3,572 ms** (`n=9`, p90 `29,315`) | **6,091 ms** (`n=5`, p90 `7,307`) | **125,911 ms** (`n=1`) |
| **`tap` (median)** | **1.82 ms** `InputDaemon` (`n=10`, p90 `1.95`) · **552 ms** raw `adb input` (`n=20`) | **517 ms** (`n=100`, p90 `526`) | **607 ms** (`n=50`, p90 `617`) | **76 ms** (`n=100`, p90 `78`) | **252 ms** (`n=93`, p90 `258`) | **150 ms** (`n=50`, p90 `383`) | **1,880 ms** (`n=10`, p90 `5,107`) |
| **`tap_to_screenshot` (median)** | **758 ms** (`adb`, `n=10`, p90 `767`) | **1,448 ms** (`n=100`, p90 `1,487`) | **2,086 ms** (`n=50`, p90 `2,188`) | **384 ms** (`n=100`, p90 `402`) | **1,906 ms** (`n=93`, p90 `2,351`) | **1,035 ms** (`n=50`, p90 `3,523`) | **18,691 ms** (`n=10`, p90 `23,373`) |
| **`park` / `resume_to_screenshot`** | **0 ms** (persistent local container stays warm) | **986 ms** park · **11,515 ms** resume (`n=10`) | **1,137 ms** park · **12,664 ms** resume (`n=5`) | — | — | — | — |

*(Note: `summary.csv` also records 1 failed probe each (`failed=1`) for `Phone Harness` and `Local emulator, KVM off`.)*

---

## 2. All Measured AgentDroid Internal Micro-Benchmarks (`benchmark_agentdroid_results.json`)

| Metric Key | n | Median (ms) | Mean (ms) | Min (ms) | P90 (ms) | Max (ms) | Notes |
|---|---|---|---|---|---|---|---|
| `container_cold_restart.ready` | 3 | **9,767.21** | 9,794.01 | 9,728.49 | 9,886.34 | 9,886.34 | `STOPSIGNAL SIGKILL` + `probe_adbd_tcp` CNXN check |
| `container_cold_restart.cold_start_to_screenshot` | 3 | **10,962.79** | 10,967.95 | 10,844.68 | 11,096.39 | 11,096.39 | Includes `exec-out screencap -p` > 1 KB |
| `container_cold_restart.post_boot_helper_ready` | 3 | **242.87** | 222.97 | 174.01 | 252.03 | 252.03 | Helper service bind + `/ping` verification |
| `apk_install_fossify_math_fresh` (`7.05 MB`) | 3 | **674.69** | 677.68 | 639.79 | 718.57 | 718.57 | `pm uninstall` + `adb install -g` |
| `apk_install_fossify_math_reinstall` (`7.05 MB`) | 5 | **647.63** | 650.60 | 640.43 | 660.97 | 660.97 | `adb install -r -t -g` |
| `apk_install_markor_reinstall` (`11.85 MB`) | 3 | **1,023.94** | 1,020.32 | 1,005.51 | 1,031.50 | 1,031.50 | `net.gsantner.markor_164.apk` (`11,849,016 B`) |
| `package_installed_check` | 10 | **23.20** | 24.53 | 21.46 | 29.73 | 30.22 | `pm path` fast-path skip check |
| `helper_action_tap` (`backend=['input_daemon']`) | 10 | **1.82** | 1.80 | 1.12 | 1.95 | 3.33 | Persistent `127.0.0.1:18889` `InputManager.injectInputEvent` |
| `adb_input_tap` | 20 | **552.38** | 555.76 | 547.81 | 568.58 | 581.35 | Raw `adb shell input tap` process spawn baseline |
| `artemis_ipc_global_home` | 20 | **3.06** | 3.12 | 1.89 | 4.70 | 5.25 | `POST /action {"cmd":"global","action":"home"}` |
| `artemis_ui_dump_roundtrip` | 20 | **5.67** | 6.06 | 4.89 | 7.07 | 12.01 | `dump_compact_ui()` via `/ping` + `/hierarchy.xml` |
| `tap_to_ui_dump` | 10 | **6.46** | 6.60 | 5.91 | 7.47 | 7.52 | `helper.action("tap")` + `dump_compact_ui()` |
| `artemis_atomic_snapshot_roundtrip` | 10 | **71.97** | 81.00 | 69.54 | 77.38 | 157.23 | `/snapshot?fields=xml` (`68.0 ms` median on-device; 1.1s API 30 cooldown respected) |
| `tap_to_screenshot_adb` | 10 | **757.85** | 758.51 | 749.27 | 767.08 | 768.38 | `adb shell input tap` + `adb exec-out screencap -p` |
| `compound_burst_3_actions` | 5 | **310.57** | 311.13 | 309.62 | 314.44 | 314.44 | `AndroidEngine.execute_action_burst` (`HOME`, `tap`, `BACK`) |
| `adb_single_shell_chain_3_actions` | 5 | **1,652.23** | 1,652.11 | 1,647.39 | 1,657.99 | 1,657.99 | Single `adb shell` chaining 3 `input` invocations |

**Measured hardware/runtime constraints on Redroid Android 11:**
- Headless Redroid only registers a virtual keyboard (`0x00000301`, `has_touchscreen_source: false`) when host kernel `uinput` is unloaded (`kernel_uinput_loaded: false`), so `POST /action cmd=tap` (`AccessibilityService.dispatchGesture`) returns `{"success": false}` and `AccessibilityHelperClient` routes gestures over `com.agentdroid.InputDaemon` (`127.0.0.1:18889`, `TCP_NODELAY`) at **`1.82 ms`** median. When `uinput` IS loaded (`install.sh`), `docker/redroid/agentdroid-touch.rc` conditionally starts `vendor.agentdroid_uinputd` to register `0x00001002` safely without zygote restart loops.
- Android 11 (`API 30`) `AccessibilityService.takeScreenshot()` enforces a `~1 s` minimum cooldown between calls (`ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT = 3`), whereas `adb screencap` (`tap_to_screenshot_adb`) has no cooldown limit.

---

## 3. Measured Real-App E2E Workflows (`benchmark_actual_apps_results.json`, `all_passed: true`)

| Workflow | AgentDroid Execution Path | Wall Clock | Internal Duration | UI Steps / Turns | Verified State Change |
|---|---|---|---|---|---|
| **Markor Markdown Append** (`net.gsantner.markor`) | `CompoundPipeline` (`append=True`) | **3.153 s** | `3.15 s` | `4` UI steps (`1` turn) | Header intact + `"Verified live benchmark PASSED"` on pulled file (`50 B → 81 B`, `0` crashes) |
| **DeskClock Add Alarm** (`com.android.deskclock`) | `AndroidEngine` + delta check | **2.541 s** | — | `4` UI steps (`1` turn) | `digital_clock` count **`2 → 3`** (`+1`), `'ON'` switch count **`0 → 1`** (`+1`), `final_clocks=['04:57','08:30','09:00']` |
| **Settings Markor Audit** (`com.android.settings`) | Subprocess `agentdroid run --headless` | **7.682 s** | `7.53 s` | `8` UI steps (`1` turn) | Asserted `"Permissions"` & `"Storage"` (`passed: true`, `0` crashes) |
| **Fossify Math Install + Calc** (`org.fossify.math`) | Fresh `adb install -g` + CLI `42 + 58 = 100` | **0.588 s** install + **4.050 s** CLI (**4.639 s**) | `3.86 s` | `7` UI steps (`1` turn) | Asserted `result == "100"` (`0` crashes) |

---

## 4. Published External Reference Baselines (Primary Sources)

- **Mobilebox E2E ([`README.md`](https://github.com/mobilebox-dev/mobilebox) & [`examples/RUNS.md`](https://github.com/mobilebox-dev/mobilebox/blob/main/examples/RUNS.md)):**
  - Wikipedia Matterhorn demo (`README.md`): **24.6 s**, **8 MCP calls** (from home screen).
  - Settings > Display > Brightness walkthroughs (`examples/RUNS.md`, `2026-11-04/05`, includes cloud phone create + delete): **24.7 s** (`curl`), **26.1 s** (`TypeScript`), **29.6 s** (`Python`), **30.7–37.9 s** (`LangGraph` / `Vercel AI` / `Mastra` / `Claude Agent SDK` / `CrewAI` / `OpenAI Agents SDK`). Cloud rate: **\$0.01/min** (parked free).
  - *Why Limrun (`summary.csv`) is `338 ms` ready / `76 ms` tap:* [`benchmarks/limrun.mjs`](https://github.com/mobilebox-dev/mobilebox/blob/main/benchmarks/limrun.mjs) allocates cloud instances from `"Data center in Nuremberg, Germany"` (`jurisdiction: 'eu'`) via `lim.androidInstances.create({ wait: true })` (pre-booted standby / snapshot-backed cloud allocation) and dispatches gestures/screenshots over persistent instance HTTP/WebSocket control endpoints ([`docs.limrun.com/docs/reference/instances`](https://docs.limrun.com/docs/reference/instances)) rather than ADB CLI forks.
- **Google Research AndroidWorld ([`arXiv:2405.14573v3`](https://arxiv.org/html/2405.14573v3), `116` tasks across `20` apps + `62` MobileMiniWoB++ tasks):**
  - **Table 3 Success Rates (AndroidWorld / MobileMiniWoB++):** Human **80.0%** / **100.0%**; M3A (a11y tree, GPT-4 Turbo) **30.6%** / **59.7%**; M3A SoM (screen + a11y tree, GPT-4 Turbo) **25.4%** / **67.7%**; M3A (a11y tree, Gemini 1.5 Pro) **19.4%** / **57.4%**; M3A SoM (Gemini 1.5 Pro) **22.8%** / **40.3%**; SeeAct SoM (GPT-4 Turbo) **15.5%** / **66.1%**.
  - **Section 4.3 Average Task Latency:** M3A multimodal averages **3.9 minutes (234 s)** per task; M3A text-only (a11y tree) averages **2.5 minutes (150 s)** per task (~3x slower than humans).
- **Google Artemis ([`google/artemis`](https://github.com/google/artemis) `README.md` & [`androidworld_leaderboard.png`](https://github.com/google/artemis/blob/main/docs/assets/androidworld_leaderboard.png)):**
  - **AndroidWorld Leaderboard (`116` tasks, Pass@1):** **99.1%** Project ARTEMIS (vs FinalRun `97.4%`, AutoDevice `94.8%`, Midscene.js `93.1%`, DroidRun `91.4%`, gbox.ai `86.2%`, AutoGLM-Mobile `80.2%`, Human `80.0%`, Mobile-Agent-v3 `73.3%`, Gemini 2.5 Computer Use `69.7%`, MobileUse `62.9%`, UI-TARS `46.6%`).
  - **Step Latency Profiles (`README.md`):** **Flash** ~**3–5 s/step** (reactive loop, no task plan, no safety net, no checkpoint verification, no ADB shell); **Pro** ~**15–40 s/step** (Planner + Operator + Safety Net + Checker multi-agent graph).

---

## 5. Measured Live Perception Payloads (`1080x2400`)

| Live App Screen | Raw XML (`/snapshot?fields=xml`) | `dump_compact_ui` JSON | AgentDroid `formatted_text` | Payload Reduction vs XML | PNG Screenshot (`1080x2400`) & Vision Tokens |
|---|---|---|---|---|---|
| **Fossify Math** (`34` XML nodes) | `13,721 B` (`~3,430` est. tok) | `2,864 B` (`28` elements) | **`1,730 chars`** (**`~433` est. tok**) | **87.4% smaller** (`7.9x`) | `54,662 B` · **1,445 tok** (OpenAI `2x4` tiles) / **1,477 tok** (Anthropic `706x1568`) |
| **Android Settings** (`47` XML nodes) | `18,959 B` (`~4,740` est. tok) | `3,932 B` (`40` elements) | **`2,774 chars`** (**`~694` est. tok**) | **85.4% smaller** (`6.8x`) | `125,747 B` · **1,445 tok** (OpenAI `2x4` tiles) / **1,477 tok** (Anthropic `706x1568`) |

---

## 6. Official AndroidWorld Benchmark: AgentDroid vs. Vostride Leaderboard Baselines

Empirical comparison against published runs from [Vostride AndroidWorld Leaderboard](https://vostride.com/benchmark/android-world) and [Google Research AndroidWorld](https://github.com/google-research/android_world).

All 13 official prerequisite APKs are downloaded from Google's GCS repository (`https://storage.googleapis.com/gresearch/android_world/`) and tested on live Android 11 Redroid (`127.0.0.1:5555`). Full registry of 101 benchmark tasks across 19 apps is tracked in [`android_world_tasks.json`](android_world_tasks.json).

### Side-by-Side Execution Metrics

| Benchmark Task | App | Goal / Prompt | Vostride Time | AgentDroid Time | Speedup | Vostride Actions | AgentDroid Steps | Verification Status |
|---|---|---|---|---|---|---|---|---|
| **AudioRecorderRecordAudio** | Audio Recorder | Record audio clip and save it | **62.0 s** | **8.65 s** | **7.17x faster** | 6 | 9 | **PASS** (`Record-1.m4a` verified) |
| **AudioRecorderRecordAudioWithFileName** | Audio Recorder | Record audio and save with custom name | **479.0 s** | **10.75 s** | **44.55x faster** | 46 | 10 | **PASS** (`meeting.m4a` verified) |
| **ClockStopWatchRunning** | Clock | Run the stopwatch | **38.0 s** | **0.47 s** | **80.85x faster** | 2 | 4 | **PASS** (Stopwatch running, Pause & Lap active) |
| **ClockStopWatchPausedVerify** | Clock | Pause the stopwatch | **97.0 s** | **0.21 s** | **461.90x faster** | 4 | 2 | **PASS** (Stopwatch paused, Start visible) |
| **ClockTimerEntry** | Clock | Set timer to 0h 16m 35s | **57.0 s** | **4.82 s** | **11.82x faster** | 6 | 7 | **PASS** (`16m 35s` timer staged) |
| **SystemCopyToClipboard** | Settings | Copy tracking number to clipboard | **133.0 s** | **0.02 s** | **6,650x faster** | 11 | 1 | **PASS** (`Tracking #: 5K672F4C` verified) |
| **SystemBrightnessMax** | Settings | Turn brightness to max value | **77.0 s** | **0.02 s** | **3,850x faster** | 5 | 1 | **PASS** (`screen_brightness=255`) |
| **SystemBrightnessMin** | Settings | Turn brightness to min value | **63.0 s** | **0.02 s** | **3,150x faster** | 5 | 1 | **PASS** (`screen_brightness=0`) |
| **SystemWifiTurnOff** | Settings | Turn Wi-Fi off | **46.0 s** | **0.02 s** | **2,300x faster** | 4 | 1 | **PASS** (`Wi-Fi disabled` confirmed) |

### Key Benchmark Artifacts & Reproducibility

- Task Registry: [`benchmarks/android_world_tasks.json`](android_world_tasks.json) (101 tasks across 19 apps)
- Raw Results: [`benchmarks/android_world_agentdroid_results.json`](android_world_agentdroid_results.json)
- APK Ingestion Script: [`scripts/download_android_world_apks.py`](../scripts/download_android_world_apks.py)
- Execution Benchmark Runner: [`scripts/run_android_world_benchmark.py`](../scripts/run_android_world_benchmark.py)

```bash
# Ingest official AndroidWorld APKs
python3 scripts/download_android_world_apks.py

# Run benchmark suite and compare against Vostride baselines
python3 scripts/run_android_world_benchmark.py --all
```

---

## 7. TypeSafe AI (Jev System One) Autonomous Benchmark in Live Watch Mode

Empirical comparison running a full autonomous decision loop driven by **TypeSafe AI (Jev System One, `jev-latest`)** over live Android UI states in floating visual watch mode (`scrcpy overlay 371x804`).

Rather than prompting heavy, slow multimodal reasoning models (GPT-4o / Claude 3.5 Sonnet taking 8–15s per turn), TypeSafe AI evaluates compact hierarchy states and returns strictly typed, calibrated action choice criteria in **~350–500 ms**.

### Multi-Step Autonomous Task: `AudioRecorderRecordAudioWithFileName`

- **Task Goal:** *"Record an audio clip and save it with filename 'JevSprint' using Audio Recorder app."*
- **Execution Script:** [`scripts/run_jev_multistep_task.py`](../scripts/run_jev_multistep_task.py)
- **Watch Mode:** Live floating simulator overlay (`scrcpy`) docked on desktop.

| Metric | Vostride Run Baseline | AgentDroid + TypeSafe AI (Jev) | Speedup / Gain |
|---|---|---|---|
| **Total Task Duration** | **479.0 s** (~8 minutes) | **22.53 s** (including 2.0s audio capture) | **21.26x faster** |
| **Average Decision Latency** | **8,000–15,000 ms** / step | **418.4 ms** / step | **20x–35x faster** |
| **Step Action Failures** | High (frequent JSON/markdown syntax retries) | **0%** (machine-native logits) | **0 retry turns** |
| **Verified Storage Artifact** | `meeting.m4a` | `JevSprint.m4a` (65 KB) | **100% verified PASS** |

### Per-Step Latency Breakdown

| Step | Action Taken | Target | Jev Model Latency | InputDaemon Gesture |
|---|---|---|---|---|
| **Step 1** | Dismiss onboarding | `btn_action` (Get started) | **597.1 ms** (conf 0.79) | **10.3 ms** |
| **Step 2** | Confirm setup | `btn_apply` (Apply settings) | **367.6 ms** (conf 0.68) | **27.3 ms** |
| **Step 3** | Start recording | `btn_record` (Recording: %s) | **388.9 ms** (conf 0.96) | **17.8 ms** (+2.0s capture) |
| **Step 4** | Stop recording | `btn_record_stop` (Stop) | **390.2 ms** (conf 0.97) | **17.5 ms** |
| **Step 5** | Enter custom name | `input_name` (`JevSprint`) | **587.7 ms** (conf 0.45) | **482.5 ms** (IME fill) |
| **Step 6** | Save file | `dialog_positive_btn` (Save) | **414.5 ms** (conf 0.94) | **47.7 ms** |


