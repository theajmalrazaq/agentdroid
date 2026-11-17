//! Fast streaming Android accessibility XML parser, IME filter, and interactivity-scored selector.

use crate::json::{obj, Json};

#[derive(Debug, Clone)]
pub struct UiElement {
    pub id: usize,
    pub label: String,
    pub full_text: Option<String>,
    pub class_short: String,
    pub center: [i32; 2],
    pub desc: Option<String>,
    pub resource_id: Option<String>,
    pub clickable: bool,
    pub editable: bool,
    pub systemui: bool,
}

impl UiElement {
    pub fn to_json(&self) -> Json {
        let mut pairs = vec![
            ("id", Json::Int(self.id as i64)),
            ("label", Json::Str(self.label.clone())),
            ("class", Json::Str(self.class_short.clone())),
            (
                "center",
                Json::Arr(vec![
                    Json::Int(self.center[0] as i64),
                    Json::Int(self.center[1] as i64),
                ]),
            ),
        ];
        if let Some(ref ft) = self.full_text {
            pairs.push(("full_text", Json::Str(ft.clone())));
        }
        if let Some(ref d) = self.desc {
            pairs.push(("desc", Json::Str(d.clone())));
        }
        if let Some(ref r) = self.resource_id {
            pairs.push(("resource_id", Json::Str(r.clone())));
        }
        if self.clickable {
            pairs.push(("clickable", Json::Bool(true)));
        }
        if self.editable {
            pairs.push(("editable", Json::Bool(true)));
        }
        if self.systemui {
            pairs.push(("systemui", Json::Bool(true)));
        }
        obj(pairs)
    }

    pub fn format_line(&self) -> String {
        let mut parts = vec![
            format!("[#{}]", self.id),
            if self.label.is_empty() {
                self.class_short.clone()
            } else {
                format!("{}: '{}'", self.class_short, self.label)
            },
        ];
        if let Some(ref d) = self.desc {
            parts.push(format!("Desc: '{d}'"));
        }
        if let Some(ref r) = self.resource_id {
            parts.push(format!("ID: {r}"));
        }
        parts.push(format!("Center: ({}, {})", self.center[0], self.center[1]));
        parts.join(" | ")
    }
}

#[derive(Debug, Clone)]
pub struct ParsedHierarchy {
    pub elements: Vec<UiElement>,
    pub non_sysui_count: usize,
    pub has_systemui: bool,
    pub display_size: [i32; 2],
    pub formatted_text: String,
}

fn unescape_xml(raw: &str) -> String {
    if !raw.contains('&') {
        return raw.to_string();
    }
    let mut out = String::with_capacity(raw.len());
    let mut rest = raw;
    while let Some(amp) = rest.find('&') {
        out.push_str(&rest[..amp]);
        let after = &rest[amp..];
        if let Some(semi) = after.find(';') {
            let ent = &after[1..semi];
            match ent {
                "amp" => out.push('&'),
                "lt" => out.push('<'),
                "gt" => out.push('>'),
                "quot" => out.push('"'),
                "apos" => out.push('\''),
                _ if ent.starts_with("#x") || ent.starts_with("#X") => {
                    if let Ok(cp) = u32::from_str_radix(&ent[2..], 16) {
                        if let Some(ch) = char::from_u32(cp) {
                            out.push(ch);
                        }
                    }
                }
                _ if ent.starts_with('#') => {
                    if let Ok(cp) = ent[1..].parse::<u32>() {
                        if let Some(ch) = char::from_u32(cp) {
                            out.push(ch);
                        }
                    }
                }
                _ => out.push_str(&after[..=semi]),
            }
            rest = &after[semi + 1..];
        } else {
            out.push('&');
            rest = &rest[amp + 1..];
        }
    }
    out.push_str(rest);
    out
}

fn parse_bounds(s: &str) -> Option<[i32; 4]> {
    let s = s.trim();
    if !s.starts_with('[') {
        return None;
    }
    let mid = s.find("][")?;
    let first = &s[1..mid];
    let second = s[mid + 2..].strip_suffix(']')?;
    let (x1s, y1s) = first.split_once(',')?;
    let (x2s, y2s) = second.split_once(',')?;
    let x1 = x1s.trim().parse::<i32>().ok()?;
    let y1 = y1s.trim().parse::<i32>().ok()?;
    let x2 = x2s.trim().parse::<i32>().ok()?;
    let y2 = y2s.trim().parse::<i32>().ok()?;
    Some([x1, y1, x2, y2])
}

fn is_ime_node(pkg: &str, class_short: &str) -> bool {
    if class_short == "Key" {
        return true;
    }
    let lower = pkg.to_ascii_lowercase();
    lower.contains("inputmethod") || lower.contains("latinime") || lower.contains("gboard")
}

fn extract_node_attrs(tag: &str) -> Vec<(&str, String)> {
    let mut attrs = Vec::with_capacity(8);
    let b = tag.as_bytes();
    let mut i = 0;
    while i < b.len() {
        while i < b.len() && b[i].is_ascii_whitespace() {
            i += 1;
        }
        if i >= b.len() || b[i] == b'/' || b[i] == b'>' || b[i] == b'?' {
            break;
        }
        let name_start = i;
        while i < b.len() && b[i] != b'=' && !b[i].is_ascii_whitespace() {
            i += 1;
        }
        let name = &tag[name_start..i];
        while i < b.len() && (b[i].is_ascii_whitespace() || b[i] == b'=') {
            i += 1;
        }
        if i >= b.len() {
            break;
        }
        let quote = b[i];
        if quote != b'"' && quote != b'\'' {
            continue;
        }
        i += 1;
        let val_start = i;
        while i < b.len() && b[i] != quote {
            i += 1;
        }
        let raw_val = &tag[val_start..i];
        if i < b.len() {
            i += 1;
        }
        match name {
            "package" | "text" | "content-desc" | "resource-id" | "clickable" | "class"
            | "bounds" => attrs.push((name, unescape_xml(raw_val))),
            _ => {}
        }
    }
    attrs
}

fn truncate_chars(s: &str, max_chars: usize) -> String {
    let mut end = s.len();
    for (idx, (byte_i, _)) in s.char_indices().enumerate() {
        if idx == max_chars {
            end = byte_i;
            break;
        }
    }
    s[..end].to_string()
}

pub fn parse_hierarchy_xml(
    xml: &str,
    max_elements: usize,
    include_ime: bool,
) -> Result<ParsedHierarchy, String> {
    let start = xml.find('<').ok_or_else(|| "Empty XML".to_string())?;
    let s = &xml[start..];
    if !s.contains("<hierarchy") && !s.contains("<displays") {
        return Err("Missing <hierarchy or <displays root tag".to_string());
    }

    let mut elements = Vec::with_capacity(max_elements.min(64));
    let mut non_sysui_count = 0usize;
    let mut has_systemui = false;
    let mut max_w = 0i32;
    let mut max_h = 0i32;
    let mut idx = 1usize;

    let mut pos = 0usize;
    let bytes = s.as_bytes();
    while pos < bytes.len() {
        let Some(lt_rel) = s[pos..].find('<') else {
            break;
        };
        let lt = pos + lt_rel;
        if s[lt..].starts_with("<!--") {
            if let Some(end_c) = s[lt..].find("-->") {
                pos = lt + end_c + 3;
                continue;
            }
            break;
        }
        let mut gt = lt + 1;
        let mut quote: Option<u8> = None;
        while gt < bytes.len() {
            let c = bytes[gt];
            if let Some(q) = quote {
                if c == q {
                    quote = None;
                }
            } else if c == b'"' || c == b'\'' {
                quote = Some(c);
            } else if c == b'>' {
                break;
            }
            gt += 1;
        }
        if gt >= bytes.len() {
            break;
        }
        let inner = &s[lt + 1..gt];
        pos = gt + 1;

        if inner.starts_with("window")
            && inner
                .as_bytes()
                .get(6)
                .map(|b| b.is_ascii_whitespace())
                .unwrap_or(false)
        {
            for (k, v) in extract_node_attrs(&inner[6..]) {
                if k == "bounds" {
                    if let Some([_, _, x2, y2]) = parse_bounds(&v) {
                        max_w = max_w.max(x2);
                        max_h = max_h.max(y2);
                    }
                }
            }
            continue;
        }

        if !inner.starts_with("node")
            || inner
                .as_bytes()
                .get(4)
                .map(|b| !b.is_ascii_whitespace())
                .unwrap_or(true)
        {
            continue;
        }

        let attrs = extract_node_attrs(&inner[4..]);
        let mut node_pkg = String::new();
        let mut text = String::new();
        let mut desc = String::new();
        let mut res_id = String::new();
        let mut class_raw = String::new();
        let mut bounds_str = String::new();
        let mut clickable = false;

        for (k, v) in attrs {
            match k {
                "package" => node_pkg = v.trim().to_string(),
                "text" => text = v.trim().to_string(),
                "content-desc" => desc = v.trim().to_string(),
                "resource-id" => res_id = v.trim().to_string(),
                "class" => class_raw = v,
                "bounds" => bounds_str = v,
                "clickable" => clickable = v == "true",
                _ => {}
            }
        }

        if node_pkg == "com.android.systemui" {
            has_systemui = true;
        }
        let Some(b) = parse_bounds(&bounds_str) else {
            continue;
        };
        if b[2] > max_w {
            max_w = b[2];
        }
        if b[3] > max_h {
            max_h = b[3];
        }
        if b[2] <= b[0] || b[3] <= b[1] {
            continue;
        }

        let short_cls = class_raw.rsplit('.').next().unwrap_or("").to_string();
        if !include_ime && is_ime_node(&node_pkg, &short_cls) {
            continue;
        }

        let editable = class_raw.contains("EditText");
        if text.is_empty() && desc.is_empty() && !clickable && !editable {
            continue;
        }
        if elements.len() >= max_elements {
            continue;
        }

        let short_id = res_id
            .rsplit('/')
            .next()
            .unwrap_or(&res_id)
            .to_string();
        let raw_label = if !text.is_empty() {
            text.clone()
        } else if !desc.is_empty() {
            desc.clone()
        } else if !short_id.is_empty() {
            short_id.clone()
        } else {
            short_cls.clone()
        };

        let label = truncate_chars(&raw_label, 180);
        let full_text = if (editable || raw_label.chars().count() > 180) && raw_label != label {
            Some(raw_label.clone())
        } else {
            None
        };
        let desc_opt = if !text.is_empty() && !desc.is_empty() && text != desc {
            Some(truncate_chars(&desc, 120))
        } else {
            None
        };
        let rid_opt = if !short_id.is_empty() && short_id != label {
            Some(short_id)
        } else {
            None
        };

        let cx = (b[0] + b[2]) / 2;
        let cy = (b[1] + b[3]) / 2;
        if node_pkg != "com.android.systemui" {
            non_sysui_count += 1;
        }

        elements.push(UiElement {
            id: idx,
            label,
            full_text,
            class_short: short_cls,
            center: [cx, cy],
            desc: desc_opt,
            resource_id: rid_opt,
            clickable,
            editable,
            systemui: node_pkg == "com.android.systemui",
        });
        idx += 1;
    }

    let formatted_lines: Vec<String> = elements.iter().map(UiElement::format_line).collect();
    let formatted_text = formatted_lines.join("\n");

    let display_size = if max_w > 0 && max_h > 0 {
        [max_w, max_h]
    } else {
        [1080, 2400]
    };

    Ok(ParsedHierarchy {
        elements,
        non_sysui_count,
        has_systemui,
        display_size,
        formatted_text,
    })
}

/// Interactivity-aware selector supporting `#idx`, `btn:`, `edit:`, `exact:`, `id:`, `text:`.
pub fn select_element<'a>(elements: &'a [UiElement], selector: &str) -> Option<&'a UiElement> {
    let sel = selector.trim();
    if sel.is_empty() {
        return None;
    }

    if let Some(idx_str) = sel.strip_prefix('#') {
        if !idx_str.is_empty() && idx_str.bytes().all(|b| b.is_ascii_digit()) {
            if let Ok(target_id) = idx_str.parse::<usize>() {
                if let Some(el) = elements.iter().find(|e| e.id == target_id) {
                    return Some(el);
                }
            }
        }
    }

    let (mode, needle_raw) = if let Some(rest) = sel.strip_prefix("btn:") {
        ("btn", rest.trim())
    } else if let Some(rest) = sel.strip_prefix("edit:") {
        ("edit", rest.trim())
    } else if let Some(rest) = sel.strip_prefix("exact:") {
        ("exact", rest.trim())
    } else if let Some(rest) = sel.strip_prefix("id:") {
        ("id", rest.trim())
    } else if let Some(rest) = sel.strip_prefix("text:") {
        ("text", rest.trim())
    } else {
        ("any", sel)
    };

    let needle = needle_raw.to_lowercase();
    if needle.is_empty() {
        return None;
    }

    if let Some(sub_idx_str) = needle_raw.strip_prefix('#') {
        if !sub_idx_str.is_empty() && sub_idx_str.bytes().all(|b| b.is_ascii_digit()) {
            if let Ok(nth) = sub_idx_str.parse::<usize>() {
                if nth >= 1 {
                    let mut count = 0usize;
                    for el in elements {
                        let matched_kind = match mode {
                            "btn" => el.clickable || el.class_short.contains("Button"),
                            "edit" => el.editable,
                            _ => false,
                        };
                        if matched_kind {
                            count += 1;
                            if count == nth {
                                return Some(el);
                            }
                        }
                    }
                    return None;
                }
            }
        }
    }

    let mut best: Option<(i32, usize, &'a UiElement)> = None;
    for (pos, el) in elements.iter().enumerate() {
        if mode == "btn" && !el.clickable && !el.class_short.contains("Button") {
            continue;
        }
        if mode == "edit" && !el.editable {
            continue;
        }

        let interactive_bonus = if el.clickable || el.editable { 20 } else { 0 };
        let non_webview_bonus = if el.class_short == "WebView" { 0 } else { 5 };
        let sysui_penalty = if el.systemui { -60 } else { 0 };

        let candidate_fields: Vec<(&str, i32)> = match mode {
            "id" => el.resource_id.as_deref().map(|s| vec![(s, 3)]).unwrap_or_default(),
            "text" => {
                let mut v = vec![(el.label.as_str(), 4)];
                if let Some(ref ft) = el.full_text {
                    v.push((ft.as_str(), 4));
                }
                v
            }
            _ => {
                let mut v = vec![(el.label.as_str(), 4)];
                if let Some(ref ft) = el.full_text {
                    v.push((ft.as_str(), 4));
                }
                if let Some(ref d) = el.desc {
                    v.push((d.as_str(), 3));
                }
                if let Some(ref r) = el.resource_id {
                    v.push((r.as_str(), 5));
                }
                v
            }
        };

        let mut field_score = 0i32;
        for (val, weight) in candidate_fields {
            let v_low = val.trim().to_lowercase();
            if v_low.is_empty() {
                continue;
            }
            if v_low == needle {
                field_score = field_score.max(100 + weight);
            } else if mode != "exact" && v_low.contains(&needle) {
                field_score = field_score.max(40 + weight);
            }
        }

        if field_score == 0 {
            continue;
        }

        let total_score = field_score + interactive_bonus + non_webview_bonus + sysui_penalty;
        match best {
            None => best = Some((total_score, pos, el)),
            Some((b_score, b_pos, _)) => {
                if total_score > b_score || (total_score == b_score && pos < b_pos) {
                    best = Some((total_score, pos, el));
                }
            }
        }
    }

    if let Some((_, _, el)) = best {
        return Some(el);
    }
    if sel.bytes().all(|b| b.is_ascii_digit()) {
        if let Ok(target_id) = sel.parse::<usize>() {
            return elements.iter().find(|e| e.id == target_id);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn filters_ime_and_prefers_clickable_element() {
        let xml = r#"<hierarchy rotation="0">
            <node package="com.android.inputmethod.latin" class="android.inputmethodservice.Keyboard$Key" text="a" bounds="[0,1500][100,1650]" />
            <node package="org.demo" class="android.webkit.WebView" text="Search settings and more" bounds="[0,0][1440,3120]" />
            <node package="org.demo" class="android.widget.Button" text="Search" clickable="true" bounds="[900,100][1040,200]" />
        </hierarchy>"#;
        let parsed = parse_hierarchy_xml(xml, 80, false).unwrap();
        assert_eq!(parsed.display_size, [1440, 3120]);
        assert_eq!(parsed.elements.len(), 2); // Keyboard$Key excluded!
        let picked = select_element(&parsed.elements, "Search").unwrap();
        assert_eq!(picked.class_short, "Button");
        assert!(picked.clickable);
    }
}
