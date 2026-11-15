use std::process::Command;

/// Client for communicating with the AgentDroid Cloud REST API.
#[derive(Debug, Clone)]
pub struct Client {
    pub base_url: String,
    pub api_key: Option<String>,
}

impl Client {
    pub fn new(base_url: &str, api_key: Option<&str>) -> Self {
        Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            api_key: api_key.map(|s| s.to_string()),
        }
    }

    /// Execute a compound single-call Android pipeline via curl or HTTP.
    pub fn run_pipeline(&self, payload_json: &str) -> Result<String, String> {
        let url = format!("{}/api/v1/run", self.base_url);
        let mut cmd = Command::new("curl");
        cmd.args(["-s", "-X", "POST", &url, "-H", "Content-Type: application/json"]);

        if let Some(ref key) = self.api_key {
            cmd.args(["-H", &format!("X-API-Key: {}", key)]);
        }

        cmd.args(["-d", payload_json]);

        let output = cmd.output().map_err(|e| format!("curl execution failed: {}", e))?;
        if !output.status.success() {
            return Err("HTTP request failed".to_string());
        }

        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    }

    /// Perform a semantic action (--do) on the device.
    pub fn perform_do(&self, action: &str) -> Result<String, String> {
        let url = format!("{}/api/v1/do", self.base_url);
        let payload = format!("{{\"action\": \"{}\"}}", action.replace('\"', "\\\""));

        let mut cmd = Command::new("curl");
        cmd.args(["-s", "-X", "POST", &url, "-H", "Content-Type: application/json"]);

        if let Some(ref key) = self.api_key {
            cmd.args(["-H", &format!("X-API-Key: {}", key)]);
        }

        cmd.args(["-d", &payload]);

        let output = cmd.output().map_err(|e| format!("curl execution failed: {}", e))?;
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    }

    /// Dump compact UI hierarchy (~150 tokens).
    pub fn dump_ui(&self) -> Result<String, String> {
        let url = format!("{}/api/v1/ui/dump", self.base_url);
        let mut cmd = Command::new("curl");
        cmd.args(["-s", "-X", "GET", &url]);

        if let Some(ref key) = self.api_key {
            cmd.args(["-H", &format!("X-API-Key: {}", key)]);
        }

        let output = cmd.output().map_err(|e| format!("curl execution failed: {}", e))?;
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    }
}
