# AgentDroid Native Rust Engine, CLI & Client (`agentdroid-rs`)

High-performance native Rust core engine, command-line tool, and client library for **AgentDroid**.

---

## Features

- **Zero External Dependencies**: Pure Rust standard library implementation (`std::process`, `std::net`).
- **Sub-Millisecond ADB Execution**: Direct transport to Android `adb` shell and input events.
- **Token-Efficient Compact UI**: Compact ~150-token UI representation for AI agents (`CompactUi`, `UiElement`).
- **Native CLI Binary (`agentdroid-rs`)**:
  - `agentdroid-rs health`
  - `agentdroid-rs tap 500 800`
  - `agentdroid-rs type "Hello Android"`
  - `agentdroid-rs key HOME`
  - `agentdroid-rs open "https://news.ycombinator.com"`
  - `agentdroid-rs do "click:Login"`
  - `agentdroid-rs run ./pipeline.json`

---

## Building & Running

```bash
cd api/rust
cargo build --release
./target/release/agentdroid-rs --help
```

---

## Using as a Rust Library

```rust
use agentdroid_rs::{Adb, Client};

fn main() {
    let adb = Adb::new(Some("127.0.0.1:5555"));
    if adb.is_connected() {
        println!("Connected to Android!");
        adb.open_url("https://example.com").unwrap();
        adb.key("HOME").unwrap();
    }
}
```
