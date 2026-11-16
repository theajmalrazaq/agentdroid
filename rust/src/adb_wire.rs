//! Direct TCP SmartSocket client for the ADB server (`127.0.0.1:5037`) and adbd CNXN pre-probe.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream, ToSocketAddrs};
use std::time::Duration;

fn adb_server_addr() -> String {
    let port = std::env::var("ANDROID_ADB_SERVER_PORT")
        .or_else(|_| std::env::var("ADB_SERVER_PORT"))
        .ok()
        .and_then(|s| s.trim().parse::<u16>().ok())
        .unwrap_or(5037);
    format!("127.0.0.1:{port}")
}

fn connect_with_timeout(addr_str: &str, timeout: Duration) -> Result<TcpStream, String> {
    let addrs: Vec<SocketAddr> = addr_str
        .to_socket_addrs()
        .map_err(|e| format!("resolve {addr_str}: {e}"))?
        .collect();
    let mut last_err = String::from("no addresses");
    for addr in addrs {
        match TcpStream::connect_timeout(&addr, timeout) {
            Ok(stream) => {
                let _ = stream.set_read_timeout(Some(timeout));
                let _ = stream.set_write_timeout(Some(timeout));
                let _ = stream.set_nodelay(true);
                return Ok(stream);
            }
            Err(e) => last_err = e.to_string(),
        }
    }
    Err(last_err)
}

fn send_adb_packet(stream: &mut TcpStream, cmd: &str) -> Result<(), String> {
    let pkt = format!("{:04x}{}", cmd.len(), cmd);
    stream
        .write_all(pkt.as_bytes())
        .map_err(|e| format!("adb write: {e}"))
}

fn read_exact_str(stream: &mut TcpStream, len: usize) -> Result<String, String> {
    let mut buf = vec![0u8; len];
    stream
        .read_exact(&mut buf)
        .map_err(|e| format!("adb read: {e}"))?;
    Ok(String::from_utf8_lossy(&buf).into_owned())
}

fn read_status(stream: &mut TcpStream) -> Result<(), String> {
    let status = read_exact_str(stream, 4)?;
    if status == "OKAY" {
        return Ok(());
    }
    if status == "FAIL" {
        let len_hex = read_exact_str(stream, 4)?;
        let len = usize::from_str_radix(&len_hex, 16).unwrap_or(0);
        let msg = if len > 0 {
            read_exact_str(stream, len)?
        } else {
            String::new()
        };
        return Err(format!("ADB FAIL: {msg}"));
    }
    Err(format!("Unexpected ADB status: {status}"))
}

fn read_len_payload(stream: &mut TcpStream) -> Result<String, String> {
    let len_hex = read_exact_str(stream, 4)?;
    let len = usize::from_str_radix(&len_hex, 16)
        .map_err(|e| format!("Invalid ADB length '{len_hex}': {e}"))?;
    if len == 0 {
        return Ok(String::new());
    }
    read_exact_str(stream, len)
}

fn server_query(cmd: &str, timeout: Duration) -> Result<String, String> {
    let mut s = connect_with_timeout(&adb_server_addr(), timeout)?;
    send_adb_packet(&mut s, cmd)?;
    read_status(&mut s)?;
    read_len_payload(&mut s)
}

/// Fast non-blocking TCP pre-probe speaking ADB's 24-byte `CNXN` handshake.
pub fn probe_adbd_tcp(host: &str, port: u16, timeout_ms: u64) -> bool {
    let timeout = Duration::from_millis(timeout_ms.max(50));
    let clean_host = host.trim_matches(|c| c == '[' || c == ']');
    let addr = format!("{clean_host}:{port}");
    let Ok(mut sock) = connect_with_timeout(&addr, timeout) else {
        return false;
    };
    let payload = b"host::\0";
    let checksum: u32 = payload.iter().map(|&b| b as u32).sum();
    let mut pkt = Vec::with_capacity(24 + payload.len());
    for word in [
        0x4E58_4E43u32, // "CNXN"
        0x0100_0001u32,
        256 * 1024u32,
        payload.len() as u32,
        checksum,
        0x4E58_4E43u32 ^ 0xFFFF_FFFFu32,
    ] {
        pkt.extend_from_slice(&word.to_le_bytes());
    }
    pkt.extend_from_slice(payload);
    if sock.write_all(&pkt).is_err() {
        return false;
    }
    let mut resp = [0u8; 24];
    match sock.read(&mut resp) {
        Ok(n) if n >= 4 => &resp[..4] == b"CNXN" || &resp[..4] == b"AUTH",
        _ => false,
    }
}

pub fn adb_devices(timeout_ms: u64) -> Result<String, String> {
    server_query("host:devices", Duration::from_millis(timeout_ms.max(500)))
}

pub fn adb_first_device(timeout_ms: u64) -> Option<String> {
    let out = adb_devices(timeout_ms).ok()?;
    for line in out.lines() {
        let mut parts = line.split_whitespace();
        if let (Some(serial), Some(state)) = (parts.next(), parts.next()) {
            if state == "device" {
                return Some(serial.to_string());
            }
        }
    }
    None
}

pub fn adb_get_state(serial: &str, timeout_ms: u64) -> Result<String, String> {
    server_query(
        &format!("host-serial:{serial}:get-state"),
        Duration::from_millis(timeout_ms.max(500)),
    )
}

pub fn adb_shell(serial: &str, command: &str, timeout_ms: u64) -> Result<String, String> {
    let timeout = Duration::from_millis(timeout_ms.max(500));
    let mut s = connect_with_timeout(&adb_server_addr(), timeout)?;
    send_adb_packet(&mut s, &format!("host:transport:{serial}"))?;
    read_status(&mut s)?;
    send_adb_packet(&mut s, &format!("shell:{command}"))?;
    read_status(&mut s)?;
    let mut buf = Vec::with_capacity(4096);
    s.read_to_end(&mut buf)
        .map_err(|e| format!("adb shell read_to_end: {e}"))?;
    Ok(String::from_utf8_lossy(&buf).trim().to_string())
}

pub fn adb_list_forwards(serial: &str, timeout_ms: u64) -> Result<Vec<(u16, u16)>, String> {
    let raw = server_query(
        &format!("host-serial:{serial}:list-forward"),
        Duration::from_millis(timeout_ms.max(500)),
    )?;
    let mut pairs = Vec::new();
    for line in raw.lines() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() == 3 && parts[0] == serial {
            if let (Some(loc), Some(rem)) = (
                parts[1].strip_prefix("tcp:").and_then(|s| s.parse::<u16>().ok()),
                parts[2].strip_prefix("tcp:").and_then(|s| s.parse::<u16>().ok()),
            ) {
                pairs.push((loc, rem));
            }
        }
    }
    Ok(pairs)
}

pub fn adb_forward_create(serial: &str, remote_port: u16, timeout_ms: u64) -> Result<u16, String> {
    let timeout = Duration::from_millis(timeout_ms.max(500));
    let mut s = connect_with_timeout(&adb_server_addr(), timeout)?;
    send_adb_packet(
        &mut s,
        &format!("host-serial:{serial}:forward:tcp:0;tcp:{remote_port}"),
    )?;
    read_status(&mut s)?;
    read_status(&mut s)?;
    let port_str = read_len_payload(&mut s)?;
    port_str
        .trim()
        .parse::<u16>()
        .map_err(|e| format!("Invalid forwarded port '{port_str}': {e}"))
}
