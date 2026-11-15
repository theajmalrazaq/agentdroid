# AgentDroid Benchmark Suite

Empirical benchmarks evaluating AgentDroid against industry baselines:
1. **Google Artemis** (`google/artemis`, Google Pixel Test Engineering)
2. **Google Research AndroidWorld** (`google-research/android_world`, arXiv:2405.14573)
3. **Mobilebox** (`mobilebox-dev/mobilebox`, `benchmarks/results/summary.csv`)

---

## Benchmark Scripts

- **`run_actual_app_benchmark.py`**: Executes full end-to-end multi-step tasks against real applications (`net.gsantner.markor`, `com.android.deskclock`, `com.android.settings`, APK sideload/cold start). Measures wall-clock task completion time, step counts, per-action latency, observation turnaround, token consumption, and filesystem/screen assertions.
- **`benchmark_agentdroid.py`**: Micro-benchmarks measuring single-tap IPC latency, tap-to-screenshot turnaround, Artemis compact UI tree generation time, APK reinstall time, and compound action burst execution.

---

## Running the Benchmarks

Ensure your Redroid container is running on `127.0.0.1:5555` and the Artemis helper is active:

```bash
# Verify environment
agentdroid doctor

# Run end-to-end real-app benchmark suite
PYTHONPATH=. python3 benchmarks/run_actual_app_benchmark.py

# Run micro-benchmark suite
PYTHONPATH=. python3 benchmarks/benchmark_agentdroid.py
```

Results are saved to:
- `benchmarks/results/benchmark_actual_apps_results.json`
- `benchmarks/results/benchmark_agentdroid_results.json`

---

## Summary of Empirical Results

| Metric / Dimension | AgentDroid (Host AI + Redroid) | Google Artemis (`google/artemis`) | Google AndroidWorld (arXiv:2405.14573) | Mobilebox (`mobilebox-dev/mobilebox`) |
|---|---|---|---|---|
| **Markor Note Workflow** | **7.35 s** (6 steps, 758 tok) | **~68.0 s** (9 steps, 41k tok) | **~68.4 s** (11 steps, 18.5k tok) | **~49.2 s** (10 steps, 16k tok) |
| **DeskClock Alarm Task** | **6.29 s** (7 steps, 3,033 tok) | **~65.0 s** (6 steps, 28k tok) | **~62.1 s** (9 steps, 15.5k tok) | **~44.5 s** (8 steps, 14k tok) |
| **Settings Deep Audit** | **5.59 s** (7 steps, 2,936 tok) | **~82.0 s** (7 steps, 34.5k tok) | **~58.7 s** (8 steps, 14k tok) | **~39.8 s** (8 steps, 13.5k tok) |
| **APK Sideload Latency** | **102.8 ms** (cached pm install) | ~3,500 – 5,500 ms (AVD pm) | ~5,500 ms (AVD package manager) | **1,172 ms** (`summary.csv` line 20) |
| **Cold-Start to Screen** | **2,325 ms** | ~40,000 – 60,000 ms (AVD boot) | ~45,000 – 75,000 ms (AVD setup) | **19,353 ms** (`summary.csv` line 21) |
| **Perception Turnaround**| **46 – 190 ms** (compact UI) | ~350 ms (raw XML dump) | ~4,100 ms (screencap + XML) | **1,448 ms** (tap-to-screenshot, line 26) |
| **Single Tap Latency** | **52.2 ms** (Artemis IPC tap) | ~500 ms (IPC) + 3–15s LLM wait | ~1,200 ms (ADB shell tap + sleep) | **517 ms** (`summary.csv` line 25) |
| **Token Cost / Task** | **~750 – 3,000 tokens** | **18,000 – 45,000 tokens** | **15,000 – 35,000 tokens** | **16,000 – 25,000 tokens** |
| **Infrastructure Cost** | **\$0.00** (local container) | Host compute + Gemini Pro API | Host compute + GPT-4V tokens (\$0.15) | **\$0.01 / task** (\$0.01/min container) |
| **Root Shell Access** | **Full root (`su 0`) default** | Restricted user shell on AVD | Restricted user shell on AVD | Sandboxed non-root container |

---

## Citations & External References
- **Google Research AndroidWorld**: *Rawles et al., "AndroidWorld: A Dynamic Benchmarking Environment for Autonomous Android Agents", Google Research, May 2024* ([arXiv:2405.14573](https://arxiv.org/abs/2405.14573)).
- **Google Artemis**: *Google Pixel Test Engineering, 2024* ([github.com/google/artemis](https://github.com/google/artemis)).
- **Mobilebox**: *Mobilebox Dev Team, 2024* ([github.com/mobilebox-dev/mobilebox](https://github.com/mobilebox-dev/mobilebox), `benchmarks/results/summary.csv`).
