//! AgentDroid Native Rust Engine, CLI & Client.
//!
//! Provides ultra-low-latency ADB operations, token-efficient UI element representations,
//! and high-performance HTTP client bindings for AgentDroid.

pub mod adb;
pub mod client;
pub mod ui;

pub use adb::Adb;
pub use client::Client;
pub use ui::{CompactUi, UiElement};
