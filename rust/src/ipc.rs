//! Persistent localhost IPC clients for Artemis Helper HTTP (`18888`),
//! InputDaemon TCP (`18889`), and fast non-blocking UI wait conditions.

use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::{Duration, Instant};

use crate::adb_wire::{adb_forward_create, adb_list_forwards, adb_shell};
use crate::json::{obj, parse_json, Json};
use crate::xml_ui::{parse_hierarchy_xml, ParsedHierarchy};

pub const HELPER_PORT: u16 = 18888;
pub const INPUT_DAEMON_PORT: u16 = 18889;
pub const FAST_DUMP_PORT: u16 = 18890;

pub fn b64_encode(input: &[u8]) -> String {
    const TBL: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(input.len().div_ceil(3) * 4);
    for chunk in input.chunks(3) {
        let b0 = chunk[0] as u32;
        let b1 = if chunk.len() > 1 { chunk[1] as u32 } else { 0 };
        let b2 = if chunk.len() > 2 { chunk[2] as u32 } else { 0 };
        let triple = (b0 << 16) | (b1 << 8) | b2;
        out.push(TBL[((triple >> 18) & 0x3F) as usize] as char);
        out.push(TBL[((triple >> 12) & 0x3F) as usize] as char);
        out.push(if chunk.len() > 1 {
            TBL[((triple >> 6) & 0x3F) as usize] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            TBL[(triple & 0x3F) as usize] as char
        } else {
            '='
        });
    }
    out
}

pub fn load_or_create_token(explicit: Option<&str>) -> String {
    if let Some(t) = explicit {
        let trimmed = t.trim();
        if !trimmed.is_empty() {
            return trimmed.to_string();
        }
    }
    if let Ok(t) = std::env::var("AGENTDROID_HELPER_TOKEN") {
        let trimmed = t.trim();
        if trimmed.len() >= 32 {
            return trimmed.to_string();
        }
    }
    let home = std::env::var("HOME").unwrap_or_default();
    let tmp = std::env::temp_dir();
    let candidates = [
        tmp.join("agentdroid/helper-token/session.token"),
        std::path::PathBuf::from(&home).join(".cache/agentdroid/helper-token/session.token"),
        tmp.join("artemis/helper-token/session.token"),
        std::path::PathBuf::from(&home).join(".cache/artemis/helper-token/session.token"),
    ];
    for p in &candidates {
        if let Ok(content) = std::fs::read_to_string(p) {
            let trimmed = content.trim();
            if trimmed.len() >= 32 {
                return trimmed.to_string();
            }
        }
    }
    String::new()
}

fn decode_chunked(raw: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    let mut pos = 0usize;
    while pos < raw.len() {
        let Some(rel_end) = raw[pos..].windows(2).position(|w| w == b"\r\n") else {
            break;
        };
        let len_str = String::from_utf8_lossy(&raw[pos..pos + rel_end]);
        let hex = len_str.split(';').next().unwrap_or("").trim();
        let Ok(sz) = usize::from_str_radix(hex, 16) else {
            break;
        };
        pos += rel_end + 2;
        if sz == 0 || pos + sz > raw.len() {
            break;
        }
        out.extend_from_slice(&raw[pos..pos + sz]);
        pos += sz + 2;
    }
    out
}

pub fn http_request(
    port: u16,
    method: &str,
    path: &str,
    token: &str,
    body_json: Option<&str>,
    timeout_ms: u64,
) -> Result<(u16, String), String> {
    let addr: SocketAddr = format!("127.0.0.1:{port}")
        .parse()
        .map_err(|e| format!("{e}"))?;
    let timeout = Duration::from_millis(timeout_ms.max(200));
    let mut stream =
        TcpStream::connect_timeout(&addr, timeout).map_err(|e| format!("connect {addr}: {e}"))?;
    let _ = stream.set_read_timeout(Some(timeout));
    let _ = stream.set_write_timeout(Some(timeout));
    let _ = stream.set_nodelay(true);

    let mut req = format!(
        "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-Artemis-Token: {token}\r\nAccept: application/json\r\nConnection: close\r\n"
    );
    if let Some(body) = body_json {
        req.push_str(&format!(
            "Content-Type: application/json\r\nContent-Length: {}\r\n\r\n{}",
            body.len(),
            body
        ));
    } else {
        req.push_str("\r\n");
    }
    stream
        .write_all(req.as_bytes())
        .map_err(|e| format!("http write: {e}"))?;

    let mut raw = Vec::with_capacity(8192);
    stream
        .read_to_end(&mut raw)
        .map_err(|e| format!("http read: {e}"))?;

    let Some(hdr_end) = raw.windows(4).position(|w| w == b"\r\n\r\n") else {
        return Err("Invalid HTTP response".into());
    };
    let hdr_str = String::from_utf8_lossy(&raw[..hdr_end]);
    let status = hdr_str
        .lines()
        .next()
        .and_then(|l| l.split_whitespace().nth(1))
        .and_then(|s| s.parse::<u16>().ok())
        .unwrap_or(0);
    let body_raw = &raw[hdr_end + 4..];
    let body = if hdr_str
        .to_ascii_lowercase()
        .contains("transfer-encoding: chunked")
    {
        String::from_utf8_lossy(&decode_chunked(body_raw)).into_owned()
    } else {
        String::from_utf8_lossy(body_raw).into_owned()
    };
    Ok((status, body))
}

#[derive(Default)]
pub struct SessionState {
    pub forwards: BTreeMap<(String, u16), u16>,
    pub input_socks: BTreeMap<String, BufReader<TcpStream>>,
    pub last_sparse_fallback: BTreeMap<String, Instant>,
    pub last_ui_sig: BTreeMap<String, String>,
}

impl SessionState {
    pub fn resolve_forward(&mut self, serial: &str, remote_port: u16) -> Result<u16, String> {
        let key = (serial.to_string(), remote_port);
        if let Some(&p) = self.forwards.get(&key) {
            return Ok(p);
        }
        if let Ok(list) = adb_list_forwards(serial, 2500) {
            for (loc, rem) in list {
                self.forwards.insert((serial.to_string(), rem), loc);
            }
            if let Some(&p) = self.forwards.get(&key) {
                return Ok(p);
            }
        }
        let loc = adb_forward_create(serial, remote_port, 5000)?;
        self.forwards.insert(key, loc);
        Ok(loc)
    }

    pub fn invalidate_forward(&mut self, serial: &str, remote_port: u16) {
        self.forwards.remove(&(serial.to_string(), remote_port));
        if remote_port == INPUT_DAEMON_PORT {
            self.input_socks.remove(serial);
        }
    }

    pub fn ping_helper(&mut self, serial: &str, token: &str, timeout_ms: u64) -> Option<Json> {
        let port = self.resolve_forward(serial, HELPER_PORT).ok()?;
        match http_request(port, "GET", "/ping", token, None, timeout_ms) {
            Ok((200, body)) => match parse_json(&body) {
                Ok(v) if v.get_bool("success") == Some(true) => Some(v),
                _ => None,
            },
            _ => {
                self.invalidate_forward(serial, HELPER_PORT);
                None
            }
        }
    }

    pub fn helper_action(
        &mut self,
        serial: &str,
        token: &str,
        body_json: &str,
        timeout_ms: u64,
    ) -> Result<Json, String> {
        let port = self.resolve_forward(serial, HELPER_PORT)?;
        let (status, resp) =
            http_request(port, "POST", "/action", token, Some(body_json), timeout_ms)?;
        if status >= 400 {
            return Err(format!("HTTP {status}: {resp}"));
        }
        parse_json(&resp)
    }

    pub fn input_daemon_exec(
        &mut self,
        serial: &str,
        token: &str,
        cmd_line: &str,
        timeout_ms: u64,
    ) -> Result<String, String> {
        let port = self.resolve_forward(serial, INPUT_DAEMON_PORT)?;
        if !self.input_socks.contains_key(serial) {
            let addr: SocketAddr = format!("127.0.0.1:{port}")
                .parse()
                .map_err(|e| format!("{e}"))?;
            let sock = TcpStream::connect_timeout(&addr, Duration::from_millis(1500))
                .map_err(|e| format!("input connect: {e}"))?;
            let _ = sock.set_nodelay(true);
            self.input_socks
                .insert(serial.to_string(), BufReader::new(sock));
        }

        let Some(reader) = self.input_socks.get_mut(serial) else {
            return Err("missing socket".into());
        };
        let dur = Duration::from_millis(timeout_ms.max(500));
        let _ = reader.get_ref().set_read_timeout(Some(dur));
        let _ = reader.get_ref().set_write_timeout(Some(dur));
        let payload = format!("{token}\t{cmd_line}\n");
        if let Err(e) = reader.get_mut().write_all(payload.as_bytes()) {
            self.input_socks.remove(serial);
            return Err(format!("input write: {e}"));
        }
        let mut resp = String::new();
        match reader.read_line(&mut resp) {
            Ok(0) => {
                self.input_socks.remove(serial);
                Err("input daemon EOF".into())
            }
            Ok(_) => {
                let trimmed = resp.trim().to_string();
                if trimmed.starts_with("OK") {
                    Ok(trimmed)
                } else {
                    Err(trimmed)
                }
            }
            Err(e) => {
                self.input_socks.remove(serial);
                Err(format!("input read: {e}"))
            }
        }
    }

    pub fn dump_ui(
        &mut self,
        serial: &str,
        token: &str,
        max_elements: usize,
        include_ime: bool,
        allow_sparse_fallback: bool,
    ) -> Result<Json, String> {
        let mut fg: Option<Json> = None;
        let mut xml_str = String::new();
        let mut backend = "helper";

        if let Some(ping) = self.ping_helper(serial, token, 1500) {
            let pkg = ping.get_str("package").unwrap_or("").to_string();
            let act_raw = ping.get_str("activity").unwrap_or("").to_string();
            if !pkg.is_empty() && !pkg.eq_ignore_ascii_case("null") {
                let act_opt = if act_raw.is_empty() || act_raw.eq_ignore_ascii_case("null") {
                    None
                } else {
                    Some(act_raw)
                };
                let is_overlay = pkg.to_ascii_lowercase().contains("inputmethod")
                    || pkg == "com.android.systemui"
                    || matches!(
                        act_opt.as_deref(),
                        Some("android.view.View" | "android.inputmethodservice.SoftInputWindow")
                    );
                if !is_overlay {
                    let comp = act_opt
                        .as_ref()
                        .map(|a| Json::Str(format!("{pkg}/{a}")))
                        .unwrap_or(Json::Null);
                    fg = Some(obj(vec![
                        ("package", Json::Str(pkg)),
                        ("activity", act_opt.map(Json::Str).unwrap_or(Json::Null)),
                        ("component", comp),
                    ]));
                }
            }
            if let Ok(port) = self.resolve_forward(serial, HELPER_PORT) {
                if let Ok((200, body)) =
                    http_request(port, "GET", "/hierarchy.xml", token, None, 2000)
                {
                    xml_str = body;
                }
            }
        }

        if fg.is_none() {
            fg = Some(resolve_fg_via_adb(serial));
        }

        if xml_str.is_empty() || (!xml_str.contains("<hierarchy") && !xml_str.contains("<displays"))
        {
            if !allow_sparse_fallback {
                return Ok(obj(vec![
                    ("backend", Json::Str("helper".into())),
                    ("foreground", fg.unwrap_or(Json::Null)),
                    (
                        "display_size",
                        Json::Arr(vec![Json::Int(1080), Json::Int(2400)]),
                    ),
                    ("element_count", Json::Int(0)),
                    ("elements", Json::Arr(vec![])),
                    ("formatted_text", Json::Str(String::new())),
                ]));
            }
            if let Some(fast_xml) = self.fast_dump_xml(serial, token) {
                backend = "fast_dump";
                xml_str = fast_xml;
            } else {
                backend = "uiautomator";
                xml_str = bounded_uiautomator_dump(serial);
            }
        }

        let mut parsed = match parse_hierarchy_xml(&xml_str, max_elements, include_ime) {
            Ok(p) => p,
            Err(e) => {
                return Ok(obj(vec![
                    ("backend", Json::Str(backend.into())),
                    ("foreground", fg.unwrap_or(Json::Null)),
                    ("element_count", Json::Int(0)),
                    ("elements", Json::Arr(vec![])),
                    ("parse_error", Json::Str(e)),
                ]));
            }
        };

        // Bounded multi-window recovery when persistent helper dump shows systemui + <=2 app stubs
        // OR when a WebView is present on screen and helper may lack descendant child text.
        let has_webview = parsed.elements.iter().any(|e| e.class_short == "WebView");
        let need_rich_dump = (parsed.has_systemui && parsed.non_sysui_count <= 2) || has_webview;
        let now = Instant::now();
        let cooled = self
            .last_sparse_fallback
            .get(serial)
            .map(|t| {
                now.duration_since(*t)
                    >= Duration::from_millis(if has_webview { 100 } else { 1500 })
            })
            .unwrap_or(true);
        if (allow_sparse_fallback || has_webview) && backend == "helper" && need_rich_dump {
            if let Some(fast_xml) = self.fast_dump_xml(serial, token) {
                if let Ok(fast_parsed) = parse_hierarchy_xml(&fast_xml, max_elements, include_ime) {
                    if fast_parsed.non_sysui_count > parsed.non_sysui_count
                        || (has_webview && fast_parsed.elements.len() >= parsed.elements.len())
                    {
                        backend = "fast_dump";
                        parsed = fast_parsed;
                    }
                }
            } else if allow_sparse_fallback && cooled && parsed.non_sysui_count <= 2 {
                self.last_sparse_fallback.insert(serial.to_string(), now);
                let uia_xml = bounded_uiautomator_dump(serial);
                if let Ok(uia_parsed) = parse_hierarchy_xml(&uia_xml, max_elements, include_ime) {
                    if uia_parsed.non_sysui_count > parsed.non_sysui_count {
                        backend = "uiautomator";
                        parsed = uia_parsed;
                    }
                }
            }
        }

        let mut sig = String::new();
        for el in &parsed.elements {
            sig.push_str(&el.label);
            sig.push('\n');
            if let Some(ref ft) = el.full_text {
                sig.push_str(ft);
                sig.push('\n');
            }
            if let Some(ref d) = el.desc {
                sig.push_str(d);
                sig.push('\n');
            }
            if let Some(ref r) = el.resource_id {
                sig.push_str(r);
                sig.push('\n');
            }
        }
        self.last_ui_sig
            .insert(serial.to_string(), sig.to_ascii_lowercase());

        Ok(parsed_to_json(backend, fg.unwrap_or(Json::Null), &parsed))
    }

    pub fn fast_dump_xml(&mut self, serial: &str, token: &str) -> Option<String> {
        let port = self.resolve_forward(serial, FAST_DUMP_PORT).ok()?;
        let addr: SocketAddr = format!("127.0.0.1:{port}").parse().ok()?;
        let stream = TcpStream::connect_timeout(&addr, Duration::from_millis(800)).ok()?;
        let _ = stream.set_read_timeout(Some(Duration::from_millis(2500)));
        let _ = stream.set_write_timeout(Some(Duration::from_millis(1000)));
        let _ = stream.set_nodelay(true);
        let mut reader = BufReader::new(stream);
        let payload = format!("{token}\tdump\n");
        if reader.get_mut().write_all(payload.as_bytes()).is_err() {
            self.invalidate_forward(serial, FAST_DUMP_PORT);
            return None;
        }
        let mut hdr = String::new();
        if reader.read_line(&mut hdr).ok()? == 0 {
            self.invalidate_forward(serial, FAST_DUMP_PORT);
            return None;
        }
        let trimmed = hdr.trim();
        let len_str = trimmed.strip_prefix("OK ")?;
        let byte_len: usize = len_str.trim().parse().ok()?;
        if byte_len == 0 || byte_len > 8 * 1024 * 1024 {
            return None;
        }
        let mut buf = vec![0u8; byte_len];
        reader.read_exact(&mut buf).ok()?;
        let xml = String::from_utf8_lossy(&buf).into_owned();
        if xml.contains("<hierarchy") || xml.contains("<displays") {
            Some(xml)
        } else {
            None
        }
    }

    pub fn wait_condition(
        &mut self,
        serial: &str,
        token: &str,
        mode: &str,
        patterns: &[String],
        timeout_sec: f64,
        include_ime: bool,
    ) -> Result<Json, String> {
        let started = Instant::now();
        let deadline = started + Duration::from_secs_f64(timeout_sec.max(0.2));
        let needles: Vec<String> = patterns
            .iter()
            .map(|s| s.trim().to_ascii_lowercase())
            .filter(|s| !s.is_empty())
            .collect();
        let mut prev_sig: Option<String> = None;
        let mut initial_sig: Option<String> = if mode == "change" {
            self.last_ui_sig.get(serial).cloned()
        } else {
            None
        };
        let mut poll_ms = 50u64;

        loop {
            let elapsed = started.elapsed().as_secs_f64();
            let ui_json = self.dump_ui(serial, token, 100, include_ime, elapsed >= 1.5)?;
            let elements = ui_json
                .get("elements")
                .and_then(Json::as_arr)
                .unwrap_or(&[]);
            let mut blob = String::new();
            for el in elements {
                if let Some(l) = el.get_str("label") {
                    blob.push_str(l);
                    blob.push('\n');
                }
                if let Some(ft) = el.get_str("full_text") {
                    blob.push_str(ft);
                    blob.push('\n');
                }
                if let Some(d) = el.get_str("desc") {
                    blob.push_str(d);
                    blob.push('\n');
                }
                if let Some(r) = el.get_str("resource_id") {
                    blob.push_str(r);
                    blob.push('\n');
                }
            }
            let blob_low = blob.to_ascii_lowercase();

            match mode {
                "change" => {
                    let sig = blob_low.clone();
                    if let Some(ref init) = initial_sig {
                        if &sig != init {
                            return Ok(obj(vec![
                                ("success", Json::Bool(true)),
                                (
                                    "elapsed_sec",
                                    Json::Float(
                                        (started.elapsed().as_secs_f64() * 100.0).round() / 100.0,
                                    ),
                                ),
                                ("ui", ui_json),
                            ]));
                        }
                    } else if !elements.is_empty() {
                        initial_sig = Some(sig);
                    }
                }
                "gone" => {
                    let any_present = needles.iter().any(|n| blob_low.contains(n));
                    if !any_present && !elements.is_empty() {
                        return Ok(obj(vec![
                            ("success", Json::Bool(true)),
                            (
                                "elapsed_sec",
                                Json::Float(
                                    (started.elapsed().as_secs_f64() * 100.0).round() / 100.0,
                                ),
                            ),
                            ("ui", ui_json),
                        ]));
                    }
                }
                "stable" => {
                    if !elements.is_empty() {
                        let sig = blob.clone();
                        if prev_sig.as_deref() == Some(sig.as_str()) {
                            return Ok(obj(vec![
                                ("success", Json::Bool(true)),
                                (
                                    "elapsed_sec",
                                    Json::Float(
                                        (started.elapsed().as_secs_f64() * 100.0).round() / 100.0,
                                    ),
                                ),
                                ("ui", ui_json),
                            ]));
                        }
                        prev_sig = Some(sig);
                    }
                }
                "all" => {
                    if needles.iter().all(|n| blob_low.contains(n)) {
                        return Ok(obj(vec![
                            ("success", Json::Bool(true)),
                            (
                                "elapsed_sec",
                                Json::Float(
                                    (started.elapsed().as_secs_f64() * 100.0).round() / 100.0,
                                ),
                            ),
                            ("ui", ui_json),
                        ]));
                    }
                }
                _ => {
                    // "any" (also default for single pattern)
                    for (idx, n) in needles.iter().enumerate() {
                        if blob_low.contains(n) {
                            return Ok(obj(vec![
                                ("success", Json::Bool(true)),
                                ("matched", Json::Str(patterns[idx].clone())),
                                (
                                    "elapsed_sec",
                                    Json::Float(
                                        (started.elapsed().as_secs_f64() * 100.0).round() / 100.0,
                                    ),
                                ),
                                ("ui", ui_json),
                            ]));
                        }
                    }
                }
            }

            if Instant::now() >= deadline {
                return Ok(obj(vec![
                    ("success", Json::Bool(false)),
                    (
                        "elapsed_sec",
                        Json::Float((started.elapsed().as_secs_f64() * 100.0).round() / 100.0),
                    ),
                    ("ui", ui_json),
                ]));
            }
            std::thread::sleep(Duration::from_millis(poll_ms));
            poll_ms = (poll_ms + 25).min(150);
        }
    }
}

fn parsed_to_json(backend: &str, fg: Json, parsed: &ParsedHierarchy) -> Json {
    let els: Vec<Json> = parsed.elements.iter().map(|e| e.to_json()).collect();
    obj(vec![
        ("backend", Json::Str(backend.into())),
        ("foreground", fg),
        (
            "display_size",
            Json::Arr(vec![
                Json::Int(parsed.display_size[0] as i64),
                Json::Int(parsed.display_size[1] as i64),
            ]),
        ),
        ("element_count", Json::Int(els.len() as i64)),
        ("elements", Json::Arr(els)),
        ("formatted_text", Json::Str(parsed.formatted_text.clone())),
        ("non_sysui_count", Json::Int(parsed.non_sysui_count as i64)),
        ("has_systemui", Json::Bool(parsed.has_systemui)),
    ])
}

fn resolve_fg_via_adb(serial: &str) -> Json {
    let out = adb_shell(
        serial,
        "dumpsys window displays | grep -E 'mCurrentFocus|mFocusedApp'",
        2500,
    )
    .unwrap_or_default();
    for tok in out.split_whitespace() {
        let clean = tok.trim_matches(|c| c == '}' || c == '{' || c == ',');
        if let Some((pkg, act)) = clean.split_once('/') {
            if !pkg.is_empty() && !act.is_empty() && pkg.contains('.') && !pkg.contains(':') {
                return obj(vec![
                    ("package", Json::Str(pkg.to_string())),
                    ("activity", Json::Str(act.to_string())),
                    ("component", Json::Str(format!("{pkg}/{act}"))),
                ]);
            }
        }
    }
    obj(vec![
        ("package", Json::Null),
        ("activity", Json::Null),
        ("component", Json::Null),
    ])
}

fn bounded_uiautomator_dump(serial: &str) -> String {
    adb_shell(
        serial,
        "rm -f /sdcard/agentdroid_ui.xml; timeout 4 uiautomator dump /sdcard/agentdroid_ui.xml >/dev/null 2>&1 || true; cat /sdcard/agentdroid_ui.xml 2>/dev/null || true",
        5500,
    )
    .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base64_works() {
        assert_eq!(b64_encode(b""), "");
        assert_eq!(b64_encode(b"f"), "Zg==");
        assert_eq!(b64_encode(b"fo"), "Zm8=");
        assert_eq!(b64_encode(b"foo"), "Zm9v");
        assert_eq!(b64_encode(b"hello world"), "aGVsbG8gd29ybGQ=");
        assert_eq!(b64_encode(b"a\nb"), "YQpi");
    }

    #[test]
    fn decode_chunked_handles_multiple_chunks_and_extensions() {
        let body = b"5;ext=1\r\nhello\r\n6\r\n world\r\n0\r\n\r\n";
        assert_eq!(decode_chunked(body), b"hello world");
    }

    #[test]
    fn load_or_create_token_prefers_explicit() {
        assert_eq!(
            load_or_create_token(Some("  abcdef012345  ")),
            "abcdef012345"
        );
    }
}
