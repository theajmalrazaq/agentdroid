//! Minimal zero-dependency JSON parser and serializer for AgentDroid IPC & CLI output.

use std::collections::BTreeMap;
use std::fmt::Write as _;

#[derive(Debug, Clone, PartialEq)]
pub enum Json {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    Arr(Vec<Json>),
    Obj(BTreeMap<String, Json>),
}

impl Json {
    pub fn as_str(&self) -> Option<&str> {
        match self {
            Json::Str(s) => Some(s.as_str()),
            _ => None,
        }
    }

    pub fn as_bool(&self) -> Option<bool> {
        match self {
            Json::Bool(b) => Some(*b),
            _ => None,
        }
    }

    pub fn as_i64(&self) -> Option<i64> {
        match self {
            Json::Int(n) => Some(*n),
            Json::Float(f) => Some(*f as i64),
            _ => None,
        }
    }

    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Json::Float(f) => Some(*f),
            Json::Int(n) => Some(*n as f64),
            _ => None,
        }
    }

    pub fn as_arr(&self) -> Option<&[Json]> {
        match self {
            Json::Arr(a) => Some(a.as_slice()),
            _ => None,
        }
    }

    pub fn get(&self, key: &str) -> Option<&Json> {
        match self {
            Json::Obj(m) => m.get(key),
            _ => None,
        }
    }

    pub fn get_str(&self, key: &str) -> Option<&str> {
        self.get(key).and_then(Json::as_str)
    }

    pub fn get_bool(&self, key: &str) -> Option<bool> {
        self.get(key).and_then(Json::as_bool)
    }

    pub fn get_i64(&self, key: &str) -> Option<i64> {
        self.get(key).and_then(Json::as_i64)
    }

    pub fn get_f64(&self, key: &str) -> Option<f64> {
        self.get(key).and_then(Json::as_f64)
    }

    pub fn to_json_string(&self) -> String {
        let mut out = String::with_capacity(256);
        self.write_to(&mut out);
        out
    }

    fn write_to(&self, out: &mut String) {
        match self {
            Json::Null => out.push_str("null"),
            Json::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            Json::Int(n) => {
                let _ = write!(out, "{n}");
            }
            Json::Float(f) => {
                if f.is_finite() {
                    let _ = write!(out, "{f}");
                } else {
                    out.push_str("null");
                }
            }
            Json::Str(s) => write_escaped_str(s, out),
            Json::Arr(arr) => {
                out.push('[');
                for (i, item) in arr.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    item.write_to(out);
                }
                out.push(']');
            }
            Json::Obj(map) => {
                out.push('{');
                for (i, (k, v)) in map.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    write_escaped_str(k, out);
                    out.push(':');
                    v.write_to(out);
                }
                out.push('}');
            }
        }
    }
}

pub fn write_escaped_str(s: &str, out: &mut String) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

pub fn obj(pairs: Vec<(&str, Json)>) -> Json {
    let mut map = BTreeMap::new();
    for (k, v) in pairs {
        map.insert(k.to_string(), v);
    }
    Json::Obj(map)
}

pub fn parse_json(input: &str) -> Result<Json, String> {
    let mut p = Parser {
        bytes: input.as_bytes(),
        pos: 0,
    };
    p.skip_ws();
    let val = p.parse_val()?;
    p.skip_ws();
    if p.pos != p.bytes.len() {
        return Err(format!("Trailing JSON bytes at offset {}", p.pos));
    }
    Ok(val)
}

struct Parser<'a> {
    bytes: &'a [u8],
    pos: usize,
}

impl<'a> Parser<'a> {
    fn skip_ws(&mut self) {
        while self.pos < self.bytes.len() && self.bytes[self.pos].is_ascii_whitespace() {
            self.pos += 1;
        }
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.pos).copied()
    }

    fn parse_val(&mut self) -> Result<Json, String> {
        self.skip_ws();
        match self.peek() {
            Some(b'n') => {
                if self.bytes[self.pos..].starts_with(b"null") {
                    self.pos += 4;
                    Ok(Json::Null)
                } else {
                    Err("Invalid literal".into())
                }
            }
            Some(b't') => {
                if self.bytes[self.pos..].starts_with(b"true") {
                    self.pos += 4;
                    Ok(Json::Bool(true))
                } else {
                    Err("Invalid literal".into())
                }
            }
            Some(b'f') => {
                if self.bytes[self.pos..].starts_with(b"false") {
                    self.pos += 5;
                    Ok(Json::Bool(false))
                } else {
                    Err("Invalid literal".into())
                }
            }
            Some(b'"') => Ok(Json::Str(self.parse_str()?)),
            Some(b'[') => self.parse_arr(),
            Some(b'{') => self.parse_obj(),
            Some(b'-' | b'0'..=b'9') => self.parse_num(),
            Some(b) => Err(format!("Unexpected byte '{}' at {}", b as char, self.pos)),
            None => Err("Unexpected EOF".into()),
        }
    }

    fn parse_str(&mut self) -> Result<String, String> {
        self.pos += 1; // opening quote
        let mut out = String::new();
        while self.pos < self.bytes.len() {
            let b = self.bytes[self.pos];
            if b == b'"' {
                self.pos += 1;
                return Ok(out);
            }
            if b == b'\\' {
                self.pos += 1;
                if self.pos >= self.bytes.len() {
                    return Err("Unterminated escape".into());
                }
                match self.bytes[self.pos] {
                    b'"' => out.push('"'),
                    b'\\' => out.push('\\'),
                    b'/' => out.push('/'),
                    b'b' => out.push('\u{0008}'),
                    b'f' => out.push('\u{000C}'),
                    b'n' => out.push('\n'),
                    b'r' => out.push('\r'),
                    b't' => out.push('\t'),
                    b'u' => {
                        let code = self.parse_hex4()?;
                        if (0xD800..=0xDBFF).contains(&code) {
                            if self.pos + 2 < self.bytes.len()
                                && self.bytes[self.pos + 1] == b'\\'
                                && self.bytes[self.pos + 2] == b'u'
                            {
                                self.pos += 2;
                                let low = self.parse_hex4()?;
                                let cp = 0x10000
                                    + (((code as u32 - 0xD800) << 10) | (low as u32 - 0xDC00));
                                if let Some(ch) = char::from_u32(cp) {
                                    out.push(ch);
                                }
                            }
                        } else if let Some(ch) = char::from_u32(code as u32) {
                            out.push(ch);
                        }
                    }
                    other => out.push(other as char),
                }
                self.pos += 1;
                continue;
            }
            // UTF-8 multibyte passthrough
            let s = std::str::from_utf8(&self.bytes[self.pos..])
                .map_err(|e| format!("UTF-8 error: {e}"))?;
            let ch = s.chars().next().ok_or("EOF in string")?;
            out.push(ch);
            self.pos += ch.len_utf8();
        }
        Err("Unterminated string".into())
    }

    fn parse_hex4(&mut self) -> Result<u16, String> {
        if self.pos + 4 >= self.bytes.len() {
            return Err("Truncated \\u escape".into());
        }
        let hex = std::str::from_utf8(&self.bytes[self.pos + 1..self.pos + 5])
            .map_err(|_| "Bad \\u hex")?;
        let val = u16::from_str_radix(hex, 16).map_err(|_| "Invalid \\u hex")?;
        self.pos += 4;
        Ok(val)
    }

    fn parse_arr(&mut self) -> Result<Json, String> {
        self.pos += 1;
        let mut items = Vec::new();
        self.skip_ws();
        if self.peek() == Some(b']') {
            self.pos += 1;
            return Ok(Json::Arr(items));
        }
        loop {
            items.push(self.parse_val()?);
            self.skip_ws();
            match self.peek() {
                Some(b',') => self.pos += 1,
                Some(b']') => {
                    self.pos += 1;
                    return Ok(Json::Arr(items));
                }
                _ => return Err("Expected ',' or ']'".into()),
            }
        }
    }

    fn parse_obj(&mut self) -> Result<Json, String> {
        self.pos += 1;
        let mut map = BTreeMap::new();
        self.skip_ws();
        if self.peek() == Some(b'}') {
            self.pos += 1;
            return Ok(Json::Obj(map));
        }
        loop {
            self.skip_ws();
            if self.peek() != Some(b'"') {
                return Err("Expected object key".into());
            }
            let key = self.parse_str()?;
            self.skip_ws();
            if self.peek() != Some(b':') {
                return Err("Expected ':'".into());
            }
            self.pos += 1;
            let val = self.parse_val()?;
            map.insert(key, val);
            self.skip_ws();
            match self.peek() {
                Some(b',') => self.pos += 1,
                Some(b'}') => {
                    self.pos += 1;
                    return Ok(Json::Obj(map));
                }
                _ => return Err("Expected ',' or '}'".into()),
            }
        }
    }

    fn parse_num(&mut self) -> Result<Json, String> {
        let start = self.pos;
        if self.peek() == Some(b'-') {
            self.pos += 1;
        }
        while matches!(self.peek(), Some(b'0'..=b'9')) {
            self.pos += 1;
        }
        let mut is_float = false;
        if self.peek() == Some(b'.') {
            is_float = true;
            self.pos += 1;
            while matches!(self.peek(), Some(b'0'..=b'9')) {
                self.pos += 1;
            }
        }
        if matches!(self.peek(), Some(b'e' | b'E')) {
            is_float = true;
            self.pos += 1;
            if matches!(self.peek(), Some(b'+' | b'-')) {
                self.pos += 1;
            }
            while matches!(self.peek(), Some(b'0'..=b'9')) {
                self.pos += 1;
            }
        }
        let slice = std::str::from_utf8(&self.bytes[start..self.pos]).map_err(|_| "Bad num")?;
        if is_float {
            let f = slice.parse::<f64>().map_err(|e| e.to_string())?;
            Ok(Json::Float(f))
        } else if let Ok(n) = slice.parse::<i64>() {
            Ok(Json::Int(n))
        } else {
            let f = slice.parse::<f64>().map_err(|e| e.to_string())?;
            Ok(Json::Float(f))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_json() {
        let v = parse_json(r#"{"op":"wait","items":[1,2.5,true,null,"a\nb\u0041"]}"#).unwrap();
        assert_eq!(v.get_str("op"), Some("wait"));
        let s = v.to_json_string();
        assert_eq!(parse_json(&s).unwrap(), v);
    }

    #[test]
    fn handles_surrogates_escapes_numbers_and_empty_containers() {
        let v = parse_json(
            r#"{"empty_arr":[],"empty_obj":{},"neg":-42,"sci":1.5e-1,"emoji":"\uD83D\uDE00","ctrl":"x\ty\r\"\\"}"#,
        )
        .unwrap();
        assert_eq!(v.get_i64("neg"), Some(-42));
        assert_eq!(v.get_f64("sci"), Some(0.15));
        assert_eq!(v.get_str("emoji"), Some("😀"));
        assert_eq!(v.get_str("ctrl"), Some("x\ty\r\"\\"));
        assert_eq!(v.get("empty_arr").and_then(Json::as_arr).unwrap().len(), 0);
        let serialized = v.to_json_string();
        assert_eq!(parse_json(&serialized).unwrap(), v);
    }

    #[test]
    fn rejects_invalid_json() {
        assert!(parse_json("").is_err());
        assert!(parse_json("{\"a\":1} trailing").is_err());
        assert!(parse_json("\"unterminated").is_err());
        assert!(parse_json("tru").is_err());
        assert!(parse_json("[1, 2,]").is_err());
    }
}
