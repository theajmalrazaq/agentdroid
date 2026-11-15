use std::process::Command;

/// Lightweight ADB wrapper providing fast execution of Android commands.
#[derive(Debug, Clone)]
pub struct Adb {
    pub serial: String,
}

impl Adb {
    /// Construct ADB instance for a target device serial.
    pub fn new(serial: Option<&str>) -> Self {
        let s = serial
            .map(|s| s.to_string())
            .or_else(|| std::env::var("REDROID_ADDR").ok())
            .unwrap_or_else(|| "127.0.0.1:5555".to_string());
        Self { serial: s }
    }

    /// Check if target ADB device is connected and ready.
    pub fn is_connected(&self) -> bool {
        let output = Command::new("adb")
            .args(["-s", &self.serial, "get-state"])
            .output();

        match output {
            Ok(out) => {
                let state = String::from_utf8_lossy(&out.stdout);
                state.trim() == "device"
            }
            Err(_) => false,
        }
    }

    /// Execute a root shell command and return stdout.
    pub fn shell(&self, cmd: &str) -> Result<String, String> {
        let output = Command::new("adb")
            .args(["-s", &self.serial, "shell", cmd])
            .output()
            .map_err(|e| format!("adb shell execution failed: {}", e))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(format!("adb command returned error: {}", stderr));
        }

        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    }

    /// Tap screen at coordinates (x, y).
    pub fn tap(&self, x: f32, y: f32) -> Result<(), String> {
        self.shell(&format!("input tap {:.0} {:.0}", x, y)).map(|_| ())
    }

    /// Input text into focused field.
    pub fn type_text(&self, text: &str) -> Result<(), String> {
        let escaped = text.replace(' ', "%s").replace('\'', "");
        self.shell(&format!("input text '{}'", escaped)).map(|_| ())
    }

    /// Send a keycode or global action (HOME, BACK, RECENTS, ENTER).
    pub fn key(&self, key: &str) -> Result<(), String> {
        let upper = key.to_uppercase();
        let code = match upper.as_str() {
            "HOME" => "KEYCODE_HOME",
            "BACK" => "KEYCODE_BACK",
            "RECENTS" => "KEYCODE_APP_SWITCH",
            "ENTER" => "KEYCODE_ENTER",
            other => other,
        };
        self.shell(&format!("input keyevent {}", code)).map(|_| ())
    }

    /// Open a URL or deep link.
    pub fn open_url(&self, url: &str) -> Result<(), String> {
        self.shell(&format!(
            "am start -a android.intent.action.VIEW -d '{}'",
            url
        ))
        .map(|_| ())
    }

    /// Read Android clipboard text.
    pub fn get_clipboard(&self) -> Result<String, String> {
        let out = self.shell("service call clipboard 2 s16 text")?;
        Ok(out.trim().to_string())
    }
}
