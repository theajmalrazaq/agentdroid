use std::env;
use std::process;

use agentdroid_rs::{Adb, Client};

fn print_usage() {
    println!(
        "AgentDroid Native Rust CLI (agentdroid-rs)\n\n\
        USAGE:\n\
          agentdroid-rs <command> [args...]\n\n\
        COMMANDS:\n\
          health                   Check ADB device connection\n\
          tap <x> <y>              Tap screen coordinates\n\
          type <text>              Input text into focused field\n\
          key <HOME|BACK|ENTER>    Send hardware / navigation key\n\
          open <url>               Open web URL or deep link\n\
          clip                     Read clipboard\n\
          do <action>              Execute semantic action via API\n\
          run <payload.json>       Execute compound pipeline JSON via API\n"
    );
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        print_usage();
        process::exit(0);
    }

    let adb = Adb::new(None);
    let api_url = env::var("AGENTDROID_URL").unwrap_or_else(|_| "http://127.0.0.1:8080".to_string());
    let api_key = env::var("AGENTDROID_API_KEY").ok();
    let client = Client::new(&api_url, api_key.as_deref());

    match args[1].as_str() {
        "health" => {
            let conn = adb.is_connected();
            println!(
                "{{\"ok\": {}, \"device\": \"{}\", \"connected\": {}}}",
                conn, adb.serial, conn
            );
        }
        "tap" => {
            if args.len() < 4 {
                eprintln!("Usage: agentdroid-rs tap <x> <y>");
                process::exit(1);
            }
            let x: f32 = args[2].parse().unwrap_or(0.0);
            let y: f32 = args[3].parse().unwrap_or(0.0);
            if let Err(e) = adb.tap(x, y) {
                eprintln!("Error: {}", e);
                process::exit(1);
            }
            println!("{{\"ok\": true, \"action\": \"tap\", \"x\": {}, \"y\": {}}}", x, y);
        }
        "type" => {
            if args.len() < 3 {
                eprintln!("Usage: agentdroid-rs type <text>");
                process::exit(1);
            }
            if let Err(e) = adb.type_text(&args[2]) {
                eprintln!("Error: {}", e);
                process::exit(1);
            }
            println!("{{\"ok\": true, \"action\": \"type\", \"text\": \"{}\"}}", args[2]);
        }
        "key" => {
            let key = if args.len() >= 3 { &args[2] } else { "BACK" };
            if let Err(e) = adb.key(key) {
                eprintln!("Error: {}", e);
                process::exit(1);
            }
            println!("{{\"ok\": true, \"action\": \"key\", \"key\": \"{}\"}}", key);
        }
        "open" => {
            if args.len() < 3 {
                eprintln!("Usage: agentdroid-rs open <url>");
                process::exit(1);
            }
            if let Err(e) = adb.open_url(&args[2]) {
                eprintln!("Error: {}", e);
                process::exit(1);
            }
            println!("{{\"ok\": true, \"action\": \"open\", \"url\": \"{}\"}}", args[2]);
        }
        "clip" => match adb.get_clipboard() {
            Ok(c) => println!("{{\"ok\": true, \"clipboard\": \"{}\"}}", c),
            Err(e) => {
                eprintln!("Error: {}", e);
                process::exit(1);
            }
        },
        "do" => {
            if args.len() < 3 {
                eprintln!("Usage: agentdroid-rs do <action>");
                process::exit(1);
            }
            match client.perform_do(&args[2]) {
                Ok(out) => println!("{}", out),
                Err(e) => {
                    eprintln!("Error: {}", e);
                    process::exit(1);
                }
            }
        }
        "run" => {
            if args.len() < 3 {
                eprintln!("Usage: agentdroid-rs run <payload.json>");
                process::exit(1);
            }
            let content = match std::fs::read_to_string(&args[2]) {
                Ok(c) => c,
                Err(e) => {
                    eprintln!("Error reading file {}: {}", args[2], e);
                    process::exit(1);
                }
            };
            match client.run_pipeline(&content) {
                Ok(out) => println!("{}", out),
                Err(e) => {
                    eprintln!("Error: {}", e);
                    process::exit(1);
                }
            }
        }
        "-h" | "--help" | "help" => print_usage(),
        other => {
            eprintln!("Unknown command: {}", other);
            print_usage();
            process::exit(1);
        }
    }
}
