# AgentDroid Benchmark Suite

Reproducible, competitor-aligned benchmarks measured live on local Redroid (`redroid11_x86_64`, Android 11, `1080x2400`, `Artemis v1.2.0` + kernel `/dev/uinput` `InputDaemon` + native Rust `agentdroid-fast`) via [`benchmark.py`](benchmark.py).

Every AgentDroid metric is measured live with zero dropped failures (`samples.csv`, nearest-rank `p90`). External competitor metrics are loaded from primary sources in [`baselines.json`](baselines.json):
- **Sandbox & Device Infra:** [Mobilebox (`benchmarks/results/summary.csv`, `2026-11-08`)](https://github.com/mobilebox-dev/mobilebox/blob/main/benchmarks/results/summary.csv) covering Mobilebox, Limrun, Phone Harness, and Local Android Emulator (AVD KVM On/Off).
- **Autonomous Mobile Agents:** [AndroidWorld (`arXiv:2405.14573v3`)](https://arxiv.org/abs/2405.14573), [Minitap `mobile-use` (`arXiv:2602.07787`)](https://arxiv.org/abs/2602.07787), [Droidrun / Mobilerun](https://mobilerun.ai), [Google Artemis](https://github.com/google/artemis), and [Vostride](https://vostride.com/benchmark/android-world).

---

## 1. Infrastructure & Device Sandbox Parity (`summary.csv` Metrics)

Same lifecycle and latency metrics reported by Mobilebox / Limrun / AVD benchmarks (`median` / `p90`, nearest rank, `0` failed trials across all AgentDroid measurements):

| Metric | AgentDroid (Local Redroid) | Mobilebox (Nuremberg) | Limrun (Nuremberg) | Phone Harness | Local AVD (KVM On) | Local AVD (KVM Off) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`ready`** *(cold boot / start)* | **14,921 ms** (`p90 15,009`, `n=3`) | 17,833 ms (`p90 18,072`, `n=10`) | 338 ms (`p90 454`, `n=10`) | 20,676 ms (`p90 66,953`, `n=10`) | 49,231 ms (`p90 49,309`, `n=5`) | 782,342 ms (`13.0 min`, `n=1`) |
| **`cold_start_to_screenshot`** | **16,992 ms** (`p90 17,539`, `n=3`) | 19,353 ms (`p90 19,487`, `n=10`) | 977 ms (`p90 1,067`, `n=10`) | 23,028 ms (`p90 69,977`, `n=10`) | 50,009 ms (`p90 50,278`, `n=5`) | 812,681 ms (`13.5 min`, `n=1`) |
| **`park`** *(pause / suspend)* | **68.6 ms** (`p90 92.3`, `n=3`) | 986 ms (`p90 1,019`, `n=10`) | — | — | — | — |
| **`resume_to_screenshot`** | **913.6 ms** (`p90 964.6`, `n=3`) | 11,515 ms (`p90 11,841`, `n=10`) | — | — | — | — |
| **`apk_install`** *(`org.fossify.math`)* | **1,990 ms** fresh (`n=3`) · **1,065 ms** `-r` (`n=5`) | 1,172 ms (`p90 1,544`, `n=10`) | 850 ms (`p90 954`, `n=10`) | 3,572 ms (`p90 29,315`, `n=9`) | 6,091 ms (`p90 7,307`, `n=5`) | 125,911 ms (`n=1`) |
| **`tap`** *(single input)* | **1.53 ms** `InputDaemon` (`n=100`) · **8.91 ms** Rust CLI (`n=20`) | 517 ms (`p90 526`, `n=100`) | 76 ms (`p90 78`, `n=100`) | 252 ms (`p90 258`, `n=93`) | 150 ms (`p90 383`, `n=50`) | 1,880 ms (`p90 5,107`, `n=10`) |
| **`tap_to_screenshot`** *(tap + PNG)* | **366.0 ms** (`p90 391.5`, `n=10`) | 1,448 ms (`p90 1,487`, `n=100`) | 384 ms (`p90 402`, `n=100`) | 1,906 ms (`p90 2,351`, `n=93`) | 1,035 ms (`p90 3,523`, `n=50`) | 18,691 ms (`p90 23,373`, `n=10`) |
| **`tap_to_ui_dump`** *(AgentDroid default)* | **19.78 ms** (`p90 26.60`, `n=100`) | Screenshot-first (`1,448 ms`) | Screenshot-first (`384 ms`) | Screenshot-first (`1,906 ms`) | Screenshot-first (`1,035 ms`) | Screenshot-first (`18,691 ms`) |
| **10-min Session Infra Cost** | **$0.00** *(self-hosted)* | $0.10 (`$0.01/min`) | $0.40 (`$0.04/min` on `$20` plan) | Cloud API | Local | Local |

### Additional Runtime & Footprint Micro-Benchmarks

- **Gesture injection speedup:** `InputDaemon` persistent `/dev/uinput` tap (**`1.53 ms`**, `n=100`) is **424x faster** than raw `adb shell input tap` (**`648.84 ms`**, `n=20`), and Rust CLI `agentdroid ui tap` executes end-to-end in **`8.91 ms`** (`n=20`).
- **Perception turnaround:** `ui_dump` via Artemis + Rust parser runs in **`16.06 ms`** (`n=100`, CLI **`14.15 ms`** `n=20`); full `tap_to_ui_dump` (**`19.78 ms`**) is **47.4x faster** than `adb` tap-to-screencap (**`937.28 ms`**) and **73.2x faster** than Mobilebox's `tap_to_screenshot` (**`1,448 ms`**).
- **3-action burst vs shell chain:** `execute_action_burst` (**`99.00 ms`** median, `n=5`) is **18.7x faster** than chaining 3 `adb shell input` calls (**`1,855.58 ms`**).
- **Container footprint (`docker stats`):** Idles at **`1.08%` CPU** and **`856.1 MiB` (`0.84 GiB`) RAM** (`909` PIDs); drops to **`0.0%` CPU** when parked via `docker pause` (`68.6 ms`) and resumes to first screenshot in **`913.6 ms`**.

---

## 2. Autonomous Agent & Token Efficiency Comparison

Evaluated across **Success Rate (Pass@1)**, **Task Wall-Clock Time**, **Steps & LLM Turns**, **Perception Payload / Tokens**, **Crash-Free Rate**, and **API Cost** (the core metrics tracked by AndroidWorld, Minitap, Droidrun, Artemis, and Vostride):

| Platform / Agent | Task Scope & Source | Success Rate (SR) | Avg Task Duration | LLM Turns / Steps | Perception Payload / Step | Est. Tokens / Task | Cost / Task |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **AgentDroid (1-Turn Compound / MCP)** | `13` verifiable real-app tasks *(live)* | **100.0%** (`13/13` · `100%` crash-free) | **2.88 s** mean · **2.17 s** med (`37.38 s` total · **26.1x** vs Vostride) | **1** host turn · **9.62** steps | **423–676 est. tok** (`1.7–2.7 KB` text) | **338.7 tok** mean (`-97.6%` vs vision loop) | **$0.00** *(existing host coding agent)* |
| **Minitap (`mobile-use`)** | AndroidWorld `116` tasks *(`arXiv:2602.07787`)* | **100.0%** *(published)* | **31.0 s** *(vs `68 s` single-agent)* | Multi-agent (`6` roles) | A11y + screenshots | Multi-agent context | Frontier/mixed OpenRouter |
| **Google Artemis** | AndroidWorld `100+` tasks *(`google/artemis`)* | **99.1%** *(published)* | `~15–40 s/step` *(Pro)* | Planner + Operator + Checker | Screenshot + XML | Multi-turn | Cloud LLM API |
| **Droidrun (Mobilerun)** | AndroidWorld `116` tasks *(`droidrun.ai`)* | **91.4%** *(open-source published)* | Multi-turn loop | Manager-Executor | Portal A11y (+ vision) | `3,225+` tok | `~$0.075` / task |
| **AutoGLM / GLM-4V Mobile** | AndroidWorld `116` tasks *(published)* | **80.2%** *(published)* | Multi-turn VLM | End-to-end GUI model | `~1,200` vision tok/step | Multi-turn | API token pricing |
| **Human Baseline** | AndroidWorld `116` tasks *(`arXiv:2405.14573`)* | **80.0%** *(published)* | — | Human actions | Native display | — | — |
| **Mobile-Agent-v2 / AppAgent** | AndroidWorld `116` tasks *(published)* | **73.3%** *(published)* | Multi-turn VLM | Multi-agent | Screenshot + OCR crops | Multi-turn | Multimodal API |
| **UI-TARS (ByteDance)** | AndroidWorld `116` tasks *(published)* | **46.6%** *(published)* | Multi-turn VLM | Native GUI VLM | Full PNG screenshot | Multi-turn | Dedicated GPU / cloud |
| **Google M3A (A11y / SoM)** | AndroidWorld `116` tasks *(`arXiv:2405.14573`)* | **30.6%** *(A11y)* · **25.4%** *(SoM)* | **~234.0 s** | Two-step loop | XML / SoM PNG | Multi-turn | Frontier VLM API |

---

## 3. Screen Perception & Token Efficiency (`1080x2400`)

| Live App Screen | Compact Elements | Raw XML (`/snapshot`) | Compact JSON | AgentDroid `formatted_text` | Token Savings vs XML | Vision PNG (`1080x2400`) & Vision Tokens | Token Savings vs OpenAI Vision |
| :--- | :---: | :--- | :--- | :--- | :---: | :--- | :---: |
| **Fossify Math** (`org.fossify.math`) | `28` | `13,721 B` (`~3,430` tok) | `2,928 B` | **`1,730 chars`** (**`~433` tok**) | **-87.4%** | `54,656 B` PNG · **1,445** OpenAI (`2x4`) / **1,477** Anthropic tok | **-70.0%** |
| **Android Settings** (`com.android.settings`) | `38` | `18,308 B` (`~4,577` tok) | `3,879 B` | **`2,701 chars`** (**`~676` tok**) | **-85.2%** | `142,833 B` PNG · **1,445** OpenAI (`2x4`) / **1,477** Anthropic tok | **-53.2%** |
| **DeskClock** (`com.android.deskclock`) | `25` | `12,350 B` (`~3,088` tok) | `2,634 B` | **`1,692 chars`** (**`~423` tok**) | **-86.3%** | `64,922 B` PNG · **1,445** OpenAI (`2x4`) / **1,477** Anthropic tok | **-70.7%** |

---

## 4. Per-Task Ground-Truth E2E Results (`13` Real-App Tasks)

Every task resets app state before execution and is verified independently against SQLite databases, `ContentProvider` rows, pulled `/sdcard/` files, or live UI state deltas with crash-check (`logcat`) validation:

| Tier | Task | App | AgentDroid Time | Steps | Turns | Prompt Tokens | Vision Loop Equiv. | Baseline (Vostride) | Speedup | Ground-Truth Verifier | Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :---: |
| **Simple** | `ClockStopWatchRunning` | Clock | **1.20 s** | `5` | `1` | `263` | `7,225` | `38.0 s` | **31.8x** | `pause=True, lap=True` | **PASS** |
| **Simple** | `ClockStopWatchPausedVerify` | Clock | **0.24 s** | `2` | `1` | `314` | `2,890` | `97.0 s` | **397.5x** | `start=True, pause_absent=True` | **PASS** |
| **Simple** | `SettingsNavigateAboutPhone` | Settings | **1.74 s** | `3` | `1` | `677` | `4,335` | — | — | `pkg=com.android.settings, android_version=True` | **PASS** |
| **Medium** | `DeskClockAddAlarm` | Clock | **1.34 s** | `5` | `1` | `377` | `7,225` | — | — | `clocks=2->3, on=0->1` | **PASS** |
| **Medium** | `ClockTimerEntry` | Clock | **0.82 s** | `8` | `1` | `263` | `11,560` | `57.0 s` | **69.8x** | `timer_16m35s=True` | **PASS** |
| **Medium** | `TasksAddTask` | Tasks | **2.17 s** | `7` | `1` | `186` | `10,115` | — | — | `sqlite='Submit benchmark report'` | **PASS** |
| **Medium** | `FossifyMathCompute` | Fossify Math | **0.48 s** | `8` | `1` | `433` | `11,560` | — | — | `result='100'` (`42 + 58`) | **PASS** |
| **Medium** | `AudioRecorderRecordAudio` | Audio Recorder | **4.04 s** | `11` | `1` | `140` | `15,895` | `62.0 s` | **15.3x** | `Record-1.m4a` (`23,851 B`) | **PASS** |
| **Complex** | `ContactsAddContact` | Contacts | **3.54 s** | `12` | `1` | `418` | `17,340` | `81.0 s` | **22.9x** | `matched_ada_5550199=True` | **PASS** |
| **Complex** | `SimpleCalendarAddOneEvent` | Simple Calendar | **3.10 s** | `13` | `1` | `857` | `18,785` | `184.0 s` | **59.4x** | `sqlite='Architecture Sync\|Room 402'` | **PASS** |
| **Complex** | `BroccoliAddSingleRecipe` | Broccoli | **2.84 s** | `11` | `1` | `243` | `15,895` | `138.0 s` | **48.6x** | `sqlite='Pasta Pesto\|15 mins\|Pasta, Basil, Garlic'` | **PASS** |
| **Complex** | `AudioRecorderRecordAudioWithFileName` | Audio Recorder | **6.17 s** | `13` | `1` | `140` | `18,785` | `106.0 s` | **17.2x** | `interview_clip.m4a` (`25,523 B`) | **PASS** |
| **Complex** | `MarkorCreateAndSaveNote` | Markor | **9.70 s** | `27` | `1` | `92` | `39,015` | `64.0 s` *(+onboard)* | **6.6x** | Pulled `bench_log.md` (`19 B`, `match=True`) | **PASS** |

**Tier Summary (`13/13 = 100.0%` SR · `100.0%` Crash-Free):**
- **Simple (`3/3`):** `1.06 s` mean (`1.20 s` med) · `3.33` steps · `93.8x` faster on `2` matched baselines (`1.44 s` vs `135.0 s`)
- **Medium (`5/5`):** `1.77 s` mean (`1.33 s` med) · `7.80` steps · `24.5x` faster on `2` matched baselines (`4.86 s` vs `119.0 s`)
- **Complex (`5/5`):** `5.07 s` mean (`3.54 s` med) · `15.20` steps · `22.6x` faster on `5` matched baselines (`25.35 s` vs `573.0 s`)
- **Overall (`13/13`):** `2.88 s` mean (`2.17 s` med, `6.17 s` p90, `37.38 s` total) · `4,403` prompt tokens vs `180,625` vision-loop equivalent tokens (**`97.6%` token reduction**) · **`26.1x`** faster on `9` matched Vostride tasks (`31.65 s` vs `827.0 s`).

---

## 5. Artifacts & Reproduce

| File | Description |
| :--- | :--- |
| [`benchmark.py`](benchmark.py) | Full live benchmark runner (infra lifecycle, micro-benchmarks, payload tokens, 13-task E2E, optional `--with-jev`). |
| [`baselines.json`](baselines.json) | Primary-source competitor baselines (Mobilebox `summary.csv`, Limrun, Phone Harness, AVD, AndroidWorld, Minitap, Droidrun, Artemis, Vostride). |
| [`results/summary.json`](results/summary.json) | Complete structured JSON report with all raw samples, payloads, footprint, and E2E task summaries. |
| [`results/summary.csv`](results/summary.csv) | Mobilebox-compatible CSV (`provider,region,client,metric,n,failed,median_ms,p90_ms,dates`). |
| [`results/samples.csv`](results/samples.csv) | Raw per-trial latency records across all `413` infrastructure/micro samples. |
| [`results/tasks.csv`](results/tasks.csv) | Per-task E2E CSV (`wall_clock_sec`, `steps_executed`, `llm_turns_required`, `tokens`, `speedup_x`, `verification`). |

```bash
agentdroid doctor -s 127.0.0.1:5555
python3 benchmarks/benchmark.py --serial 127.0.0.1:5555 --cold-starts 3 --park-runs 3 --taps 100 --adb-taps 20
# E2E only (skip container restarts):
python3 benchmarks/benchmark.py --serial 127.0.0.1:5555 --skip-infra
# Include optional TypeSafe AI Jev System One autonomous track:
TYPESAFE_API_KEY="<key>" python3 benchmarks/benchmark.py --serial 127.0.0.1:5555 --skip-infra --with-jev
```
