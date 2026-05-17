#[path = "../src/asr.rs"]
#[allow(dead_code)]
mod asr;

use std::fs;

use asr::{decode_wav_base64, remove_temp_audio_file, write_temp_audio_file, MAX_ASR_AUDIO_BYTES};

#[test]
fn decodes_base64_audio_payload() {
    let bytes = decode_wav_base64("UklGRg==").expect("payload should decode");

    assert_eq!(bytes, b"RIFF");
}

#[test]
fn rejects_payloads_over_max_size() {
    let oversized = vec![0_u8; MAX_ASR_AUDIO_BYTES + 1];
    let encoded = base64::Engine::encode(&base64::engine::general_purpose::STANDARD, oversized);

    let error = decode_wav_base64(&encoded).unwrap_err();

    assert!(error.contains("voice audio payload is too large"));
}

#[test]
fn writes_temp_audio_file_under_temp_directory() {
    let temp_dir = tempfile::tempdir().unwrap();

    let path = write_temp_audio_file(temp_dir.path(), b"RIFF....WAVE").unwrap();

    assert!(path.starts_with(temp_dir.path()));
    assert!(path
        .file_name()
        .unwrap()
        .to_string_lossy()
        .starts_with("alita-asr-"));
    assert_eq!(fs::read(path).unwrap(), b"RIFF....WAVE");
}

#[test]
fn removes_temp_audio_file_without_failing_on_missing_file() {
    let temp_dir = tempfile::tempdir().unwrap();
    let path = write_temp_audio_file(temp_dir.path(), b"RIFF....WAVE").unwrap();

    remove_temp_audio_file(&path);
    remove_temp_audio_file(&path);

    assert!(!path.exists());
}
