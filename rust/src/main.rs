//! `agentdroid-fast`: Native Rust accelerator (`serve` stdio JSON worker + zero-overhead CLI).

mod adb_wire;
mod ipc;
mod json;
mod xml_ui;

use std::io::{BufRead, BufReader, Write};

use adb_wire::{
    adb_devices, adb_first_device, adb_forward_create, adb_get_state, adb_list_forwards, adb_shell,
    probe_adbd_tcp,
};
use ipc::{b64_encode, load_or_create_token, SessionState};
use json::{obj, parse_json, write_escaped_str, Json};
use xml_ui::{parse_hierarchy_xml, select_element, UiElement};

fn resolve_serial(explicit: Option<&str>) -> String {
    if let Some(s) = explicit {
        if !s.trim().is_empty() {
            return s.trim().to_string();
        }
    }
    for var in ["ADB_DEVICE_SERIAL", "REDROID_ADDR"] {
        if let Ok(v) = std::env::var(var) {
            if !v.trim().is_empty() {
                return v.trim().to_string();
            }
        }
    }
    adb_first_device(1500).unwrap_or_else(|| "127.0.0.1:5555".to_string())
}

fn json_elements_to_vec(arr: &[Json]) -> Vec<UiElement> {
    let mut out = Vec::with_capacity(arr.len());
    for item in arr {
        let id = item.get_i64("id").unwrap_or(0) as usize;
        let label = item.get_str("label").unwrap_or("").to_string();
        let full_text = item.get_str("full_text").map(|s| s.to_string());
        let class_short = item.get_str("class").unwrap_or("").to_string();
        let center_arr = item.get("center").and_then(Json::as_arr);
        let cx = center_arr
            .and_then(|a| a.first())
            .and_then(Json::as_i64)
            .unwrap_or(0) as i32;
        let cy = center_arr
            .and_then(|a| a.get(1))
            .and_then(Json::as_i64)
            .unwrap_or(0) as i32;
        let desc = item.get_str("desc").map(|s| s.to_string());
        let resource_id = item.get_str("resource_id").map(|s| s.to_string());
        let clickable = item.get_bool("clickable").unwrap_or(false);
        let editable = item.get_bool("editable").unwrap_or(false);
        let systemui = item.get_bool("systemui").unwrap_or(false);
        out.push(UiElement {
            id,
            label,
            full_text,
            class_short,
            center: [cx, cy],
            desc,
            resource_id,
            clickable,
            editable,
            systemui,
        });
    }
    out
}

fn handle_rpc(state: &mut SessionState, req: &Json) -> Json {
    let op = req.get_str("op").unwrap_or("");
    let serial = req.get_str("serial").unwrap_or("127.0.0.1:5555");
    let token = load_or_create_token(req.get_str("token"));

    match op {
        "probe_adbd" => {
            let host = req.get_str("host").unwrap_or("127.0.0.1");
            let port = req.get_i64("port").unwrap_or(5555) as u16;
            let timeout_ms = req.get_i64("timeout_ms").unwrap_or(350) as u64;
            obj(vec![
                ("ok", Json::Bool(true)),
                ("ready", Json::Bool(probe_adbd_tcp(host, port, timeout_ms))),
            ])
        }
        "adb_state" => match adb_get_state(serial, 3000) {
            Ok(s) => obj(vec![("ok", Json::Bool(true)), ("state", Json::Str(s))]),
            Err(e) => obj(vec![("ok", Json::Bool(false)), ("error", Json::Str(e))]),
        },
        "adb_devices" => match adb_devices(3000) {
            Ok(d) => obj(vec![("ok", Json::Bool(true)), ("output", Json::Str(d))]),
            Err(e) => obj(vec![("ok", Json::Bool(false)), ("error", Json::Str(e))]),
        },
        "adb_shell" => {
            let cmd = req.get_str("cmd").unwrap_or("");
            let timeout_ms = req.get_i64("timeout_ms").unwrap_or(30000) as u64;
            match adb_shell(serial, cmd, timeout_ms) {
                Ok(out) => obj(vec![("ok", Json::Bool(true)), ("output", Json::Str(out))]),
                Err(e) => obj(vec![("ok", Json::Bool(false)), ("error", Json::Str(e))]),
            }
        }
        "adb_forward_list" => match adb_list_forwards(serial, 3000) {
            Ok(list) => {
                let items = list
                    .into_iter()
                    .map(|(l, r)| obj(vec![("local", Json::Int(l as i64)), ("remote", Json::Int(r as i64))]))
                    .collect();
                obj(vec![("ok", Json::Bool(true)), ("forwards", Json::Arr(items))])
            }
            Err(e) => obj(vec![("ok", Json::Bool(false)), ("error", Json::Str(e))]),
        },
        "adb_forward_create" => {
            let remote = req.get_i64("remote").unwrap_or(18888) as u16;
            match adb_forward_create(serial, remote, 5000) {
                Ok(port) => {
                    state.forwards.insert((serial.to_string(), remote), port);
                    obj(vec![("ok", Json::Bool(true)), ("port", Json::Int(port as i64))])
                }
                Err(e) => obj(vec![("ok", Json::Bool(false)), ("error", Json::Str(e))]),
            }
        }
        "parse_xml" => {
            let xml = req.get_str("xml").unwrap_or("");
            let max_el = req.get_i64("max_elements").unwrap_or(80) as usize;
            let include_ime = req.get_bool("include_ime").unwrap_or(false);
            match parse_hierarchy_xml(xml, max_el, include_ime) {
                Ok(p) => {
                    let els: Vec<Json> = p.elements.iter().map(|e| e.to_json()).collect();
                    obj(vec![
                        ("ok", Json::Bool(true)),
                        ("element_count", Json::Int(els.len() as i64)),
                        ("elements", Json::Arr(els)),
                        ("formatted_text", Json::Str(p.formatted_text)),
                        (
                            "display_size",
                            Json::Arr(vec![
                                Json::Int(p.display_size[0] as i64),
                                Json::Int(p.display_size[1] as i64),
                            ]),
                        ),
                        ("non_sysui_count", Json::Int(p.non_sysui_count as i64)),
                        ("has_systemui", Json::Bool(p.has_systemui)),
                    ])
                }
                Err(e) => obj(vec![("ok", Json::Bool(false)), ("error", Json::Str(e))]),
            }
        }
        "select" => {
            let selector = req.get_str("selector").unwrap_or("");
            let arr = req.get("elements").and_then(Json::as_arr).unwrap_or(&[]);
            let els = json_elements_to_vec(arr);
            match select_element(&els, selector) {
                Some(el) => obj(vec![("ok", Json::Bool(true)), ("element", el.to_json())]),
                None => obj(vec![("ok", Json::Bool(true)), ("element", Json::Null)]),
            }
        }
        "ping_helper" => {
            let timeout_ms = req.get_i64("timeout_ms").unwrap_or(1500) as u64;
            match state.ping_helper(serial, &token, timeout_ms) {
                Some(res) => obj(vec![("ok", Json::Bool(true)), ("ping", res)]),
                None => obj(vec![("ok", Json::Bool(false))]),
            }
        }
        "dump_ui" => {
            let max_el = req.get_i64("max_elements").unwrap_or(80) as usize;
            let include_ime = req.get_bool("include_ime").unwrap_or(false);
            let allow_fb = req.get_bool("allow_sparse_fallback").unwrap_or(true);
            match state.dump_ui(serial, &token, max_el, include_ime, allow_fb) {
                Ok(ui) => obj(vec![("ok", Json::Bool(true)), ("ui", ui)]),
                Err(e) => obj(vec![("ok", Json::Bool(false)), ("error", Json::Str(e))]),
            }
        }
        "wait" => {
            let mode = req.get_str("mode").unwrap_or("any");
            let timeout_sec = req.get_f64("timeout_sec").unwrap_or(25.0);
            let include_ime = req.get_bool("include_ime").unwrap_or(false);
            let patterns: Vec<String> = req
                .get("patterns")
                .and_then(Json::as_arr)
                .map(|a| {
                    a.iter()
                        .filter_map(Json::as_str)
                        .map(|s| s.to_string())
                        .collect()
                })
                .unwrap_or_default();
            match state.wait_condition(serial, &token, mode, &patterns, timeout_sec, include_ime) {
                Ok(res) => obj(vec![("ok", Json::Bool(true)), ("result", res)]),
                Err(e) => obj(vec![("ok", Json::Bool(false)), ("error", Json::Str(e))]),
            }
        }
        "input_cmd" => {
            let cmd_line = req.get_str("cmd_line").unwrap_or("");
            let timeout_ms = req.get_i64("timeout_ms").unwrap_or(3000) as u64;
            match state.input_daemon_exec(serial, &token, cmd_line, timeout_ms) {
                Ok(resp) => obj(vec![("ok", Json::Bool(true)), ("resp", Json::Str(resp))]),
                Err(e) => obj(vec![("ok", Json::Bool(false)), ("error", Json::Str(e))]),
            }
        }
        "helper_action" => {
            let body_json = req
                .get("body")
                .map(Json::to_json_string)
                .unwrap_or_else(|| "{}".to_string());
            let timeout_ms = req.get_i64("timeout_ms").unwrap_or(5000) as u64;
            match state.helper_action(serial, &token, &body_json, timeout_ms) {
                Ok(res) => obj(vec![("ok", Json::Bool(true)), ("result", res)]),
                Err(e) => obj(vec![("ok", Json::Bool(false)), ("error", Json::Str(e))]),
            }
        }
        _ => obj(vec![
            ("ok", Json::Bool(false)),
            ("error", Json::Str(format!("Unknown op: {op}"))),
        ]),
    }
}

fn run_serve() -> i32 {
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut out = stdout.lock();
    let mut state = SessionState::default();
    let reader = BufReader::new(stdin.lock());

    for line in reader.lines() {
        let Ok(raw) = line else {
            break;
        };
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            continue;
        }
        let resp = match parse_json(trimmed) {
            Ok(req) => handle_rpc(&mut state, &req),
            Err(e) => obj(vec![("ok", Json::Bool(false)), ("error", Json::Str(e))]),
        };
        if writeln!(out, "{}", resp.to_json_string()).is_err() || out.flush().is_err() {
            break;
        }
    }
    0
}

fn keycode_normalize(raw: &str) -> String {
    let up: String = raw
        .chars()
        .filter(|c| !c.is_whitespace())
        .collect::<String>()
        .to_ascii_uppercase();
    match up.as_str() {
        "BACK" => "KEYCODE_BACK".into(),
        "HOME" => "KEYCODE_HOME".into(),
        "RECENTS" => "KEYCODE_APP_SWITCH".into(),
        "ENTER" => "KEYCODE_ENTER".into(),
        "SEARCH" => "KEYCODE_SEARCH".into(),
        "DELETE" => "KEYCODE_DEL".into(),
        "TAB" => "KEYCODE_TAB".into(),
        "MOVE_END" => "KEYCODE_MOVE_END".into(),
        "PASTE" => "KEYCODE_PASTE".into(),
        "ESCAPE" => "KEYCODE_ESCAPE".into(),
        _ if up.starts_with("KEYCODE_") => up,
        _ => format!("KEYCODE_{up}"),
    }
}

fn run_cli() -> i32 {
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).map(|s| s.as_str()) == Some("serve") {
        return run_serve();
    }

    let mut serial_opt: Option<String> = None;
    let mut as_json = false;
    let mut include_ime = false;
    let mut append = false;
    let mut gone = false;
    let mut timeout_sec = 25.0f64;
    let mut max_elements = 80usize;
    let mut pos: Vec<String> = Vec::new();

    let mut i = 1usize;
    while i < args.len() {
        match args[i].as_str() {
            "-s" | "--serial" => {
                if i + 1 < args.len() {
                    serial_opt = Some(args[i + 1].clone());
                    i += 2;
                    continue;
                }
            }
            "-j" | "--json" => {
                as_json = true;
                i += 1;
                continue;
            }
            "--include-ime" => {
                include_ime = true;
                i += 1;
                continue;
            }
            "--append" => {
                append = true;
                i += 1;
                continue;
            }
            "--gone" => {
                gone = true;
                i += 1;
                continue;
            }
            "--max-elements" => {
                if i + 1 < args.len() {
                    max_elements = args[i + 1].parse().unwrap_or(80);
                    i += 2;
                    continue;
                }
            }
            "--timeout" => {
                if i + 1 < args.len() {
                    timeout_sec = args[i + 1].parse().unwrap_or(25.0);
                    i += 2;
                    continue;
                }
            }
            _ => {}
        }
        pos.push(args[i].clone());
        i += 1;
    }

    let cmd = pos.first().map(|s| s.as_str()).unwrap_or("help");
    let serial = resolve_serial(serial_opt.as_deref());
    let token = load_or_create_token(None);
    let mut state = SessionState::default();

    match cmd {
        "dump" => match state.dump_ui(&serial, &token, max_elements, include_ime, true) {
            Ok(ui) => {
                if as_json {
                    println!("{}", ui.to_json_string());
                } else {
                    let fg = ui
                        .get("foreground")
                        .and_then(|f| f.get_str("component"))
                        .unwrap_or("unknown");
                    let cnt = ui.get_i64("element_count").unwrap_or(0);
                    println!("Foreground: {fg} | Elements: {cnt}");
                    println!("{}", ui.get_str("formatted_text").unwrap_or(""));
                }
                0
            }
            Err(e) => {
                eprintln!("{e}");
                1
            }
        },
        "tap" if pos.len() >= 3 => {
            let x: f64 = pos[1].parse().unwrap_or(0.0);
            let y: f64 = pos[2].parse().unwrap_or(0.0);
            let ok = state
                .input_daemon_exec(&serial, &token, &format!("tap\t{x:.2}\t{y:.2}"), 3000)
                .is_ok();
            if as_json {
                println!(
                    "{{\"action\":\"tap\",\"center\":[{},{}],\"success\":{}}}",
                    x.round() as i64,
                    y.round() as i64,
                    ok
                );
            }
            if ok { 0 } else { 1 }
        }
        "swipe" if pos.len() >= 5 => {
            let x1: f64 = pos[1].parse().unwrap_or(0.0);
            let y1: f64 = pos[2].parse().unwrap_or(0.0);
            let x2: f64 = pos[3].parse().unwrap_or(0.0);
            let y2: f64 = pos[4].parse().unwrap_or(0.0);
            let dur: i64 = pos.get(5).and_then(|s| s.parse().ok()).unwrap_or(300);
            let ok = state
                .input_daemon_exec(
                    &serial,
                    &token,
                    &format!("swipe\t{x1:.2}\t{y1:.2}\t{x2:.2}\t{y2:.2}\t{dur}"),
                    5000,
                )
                .is_ok();
            if as_json {
                println!("{{\"action\":\"swipe\",\"success\":{ok}}}");
            }
            if ok { 0 } else { 1 }
        }
        "key" if pos.len() >= 2 => {
            let kc = keycode_normalize(&pos[1]);
            let ok = state
                .input_daemon_exec(&serial, &token, &format!("key\t{kc}"), 3000)
                .is_ok();
            if as_json {
                println!("{{\"action\":\"global\",\"keycode\":\"{kc}\",\"success\":{ok}}}");
            }
            if ok { 0 } else { 1 }
        }
        "type" if pos.len() >= 2 => {
            let text = &pos[1];
            let mut body = String::from("{\"action\":\"type\",\"text\":");
            write_escaped_str(text, &mut body);
            body.push_str(&format!(",\"append\":{}}}", append));
            let ok = state
                .helper_action(&serial, &token, &body, 5000)
                .map(|r| r.get_bool("success") != Some(false))
                .unwrap_or_else(|_| {
                    if append {
                        let _ = state.input_daemon_exec(&serial, &token, "key\tKEYCODE_MOVE_END", 2000);
                    }
                    text.is_ascii()
                        && state
                            .input_daemon_exec(
                                &serial,
                                &token,
                                &format!("text_b64\t{}", b64_encode(text.as_bytes())),
                                5000,
                            )
                            .is_ok()
                });
            if as_json {
                println!("{{\"action\":\"type\",\"success\":{ok}}}");
            }
            if ok { 0 } else { 1 }
        }
        "click" if pos.len() >= 2 => {
            let sel = &pos[1];
            let res = state.dump_ui(&serial, &token, 120, include_ime, true);
            match res {
                Ok(ui) => {
                    let arr = ui.get("elements").and_then(Json::as_arr).unwrap_or(&[]);
                    let els = json_elements_to_vec(arr);
                    if let Some(el) = select_element(&els, sel) {
                        let ok = state
                            .input_daemon_exec(
                                &serial,
                                &token,
                                &format!("tap\t{:.2}\t{:.2}", el.center[0] as f64, el.center[1] as f64),
                                3000,
                            )
                            .is_ok();
                        if as_json {
                            let out = obj(vec![
                                ("success", Json::Bool(ok)),
                                ("selector", Json::Str(sel.clone())),
                                ("matched_element", el.to_json()),
                            ]);
                            println!("{}", out.to_json_string());
                        }
                        if ok { 0 } else { 1 }
                    } else {
                        if as_json {
                            println!(
                                "{{\"success\":false,\"error\":\"Element not found\"}}"
                            );
                        }
                        1
                    }
                }
                Err(e) => {
                    eprintln!("{e}");
                    1
                }
            }
        }
        "wait" if pos.len() >= 2 => {
            let raw = &pos[1];
            let pats: Vec<String> = raw.split('|').map(|s| s.to_string()).collect();
            let mode = if gone { "gone" } else { "any" };
            match state.wait_condition(&serial, &token, mode, &pats, timeout_sec, include_ime) {
                Ok(r) => {
                    let ok = r.get_bool("success").unwrap_or(false);
                    if as_json {
                        println!("{}", r.to_json_string());
                    }
                    if ok { 0 } else { 1 }
                }
                Err(e) => {
                    eprintln!("{e}");
                    1
                }
            }
        }
        "shell" if pos.len() >= 2 => {
            let shell_cmd = pos[1..].join(" ");
            match adb_shell(&serial, &shell_cmd, (timeout_sec * 1000.0) as u64) {
                Ok(out) => {
                    if !out.is_empty() {
                        println!("{out}");
                    }
                    0
                }
                Err(e) => {
                    eprintln!("{e}");
                    1
                }
            }
        }
        "ping" => {
            let helper_ok = state.ping_helper(&serial, &token, 1500).is_some();
            let input_ok = state
                .input_daemon_exec(&serial, &token, "ping", 1500)
                .is_ok();
            println!(
                "{{\"helper_ok\":{helper_ok},\"input_daemon_ok\":{input_ok},\"serial\":\"{serial}\"}}"
            );
            if helper_ok { 0 } else { 1 }
        }
        _ => {
            println!("agentdroid-fast [-s SERIAL] [--json] <serve|dump|tap|click|swipe|key|type|wait|shell|ping>");
            0
        }
    }
}

fn main() {
    std::process::exit(run_cli());
}
