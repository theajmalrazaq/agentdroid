/// Represents a single interactive or labelled Android UI element.
#[derive(Debug, Clone)]
pub struct UiElement {
    pub id: u32,
    pub label: String,
    pub class_name: String,
    pub center: (i32, i32),
    pub bounds: [i32; 4],
}

impl UiElement {
    /// Format element into a concise ~8-12 token representation.
    pub fn to_compact_string(&self) -> String {
        format!(
            "[#{}] \"{}\" ({}) @{},{}",
            self.id, self.label, self.class_name, self.center.0, self.center.1
        )
    }
}

/// Token-efficient summary of visible screen elements (~150 tokens total).
#[derive(Debug, Clone, Default)]
pub struct CompactUi {
    pub foreground_package: String,
    pub foreground_activity: String,
    pub elements: Vec<UiElement>,
}

impl CompactUi {
    /// Format the entire screen representation for an AI agent in ~150 tokens.
    pub fn to_token_efficient_prompt(&self) -> String {
        let mut out = String::new();
        out.push_str(&format!(
            "Screen (App: {}/{} | Elements: {})\n",
            self.foreground_package,
            self.foreground_activity,
            self.elements.len()
        ));
        for el in &self.elements {
            out.push_str("  ");
            out.push_str(&el.to_compact_string());
            out.push('\n');
        }
        out
    }

    /// Find an element by #index or case-insensitive text match.
    pub fn find_element(&self, selector: &str) -> Option<&UiElement> {
        let trimmed = selector.trim();

        // 1. Match by #index
        if let Some(idx_str) = trimmed.strip_prefix('#') {
            if let Ok(target_id) = idx_str.parse::<u32>() {
                return self.elements.iter().find(|e| e.id == target_id);
            }
        }
        if let Ok(target_id) = trimmed.parse::<u32>() {
            return self.elements.iter().find(|e| e.id == target_id);
        }

        let sel_lower = trimmed.to_lowercase();
        // 2. Exact match
        if let Some(el) = self
            .elements
            .iter()
            .find(|e| e.label.to_lowercase() == sel_lower)
        {
            return Some(el);
        }

        // 3. Substring match
        self.elements
            .iter()
            .find(|e| e.label.to_lowercase().contains(&sel_lower))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_element_compact_formatting_and_lookup() {
        let ui = CompactUi {
            foreground_package: "com.android.settings".to_string(),
            foreground_activity: ".SettingsActivity".to_string(),
            elements: vec![
                UiElement {
                    id: 1,
                    label: "Network & internet".to_string(),
                    class_name: "android.widget.TextView".to_string(),
                    center: (540, 300),
                    bounds: [0, 200, 1080, 400],
                },
                UiElement {
                    id: 2,
                    label: "Connected devices".to_string(),
                    class_name: "android.widget.TextView".to_string(),
                    center: (540, 500),
                    bounds: [0, 400, 1080, 600],
                },
            ],
        };

        // Lookup by #index
        assert_eq!(ui.find_element("#1").unwrap().label, "Network & internet");
        assert_eq!(ui.find_element("2").unwrap().label, "Connected devices");

        // Lookup by exact and substring match
        assert_eq!(ui.find_element("Network & internet").unwrap().id, 1);
        assert_eq!(ui.find_element("connected").unwrap().id, 2);

        // Compact prompt representation
        let prompt = ui.to_token_efficient_prompt();
        assert!(prompt.contains("[#1] \"Network & internet\""));
    }
}
