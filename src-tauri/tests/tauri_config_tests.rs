use std::fs;

use serde_json::Value;

#[test]
fn tauri_csp_is_set_and_scoped_to_local_services() {
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    let config_path = format!("{manifest_dir}/tauri.conf.json");
    let raw_config = fs::read_to_string(config_path).unwrap();
    let config: Value = serde_json::from_str(&raw_config).unwrap();

    let csp = config["app"]["security"]["csp"]
        .as_str()
        .expect("tauri csp must be a non-null string");

    assert!(csp.contains("default-src 'self'"));
    assert!(csp.contains("connect-src 'self' http://127.0.0.1:8765 http://localhost:8765 http://127.0.0.1:8766 http://localhost:8766 ws://127.0.0.1:1420 ws://localhost:1420"));
    assert!(csp.contains("img-src 'self' asset: http://asset.localhost data: blob:"));
    assert!(csp.contains("media-src 'self' asset: http://asset.localhost data: blob:"));
    assert!(!csp.contains("default-src *"));
    assert!(!csp.contains("connect-src *"));
}
