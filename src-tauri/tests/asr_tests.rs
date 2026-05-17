#[path = "../src/asr.rs"]
#[allow(dead_code)]
mod asr;

use std::fs;

use asr::{
    decode_wav_base64, remove_temp_audio_file, write_temp_audio_file, TranscribeVoiceAudioPayload,
    MAX_ASR_AUDIO_BYTES,
};

#[test]
fn asr_max_audio_bytes_matches_spec() {
    assert_eq!(MAX_ASR_AUDIO_BYTES, 4 * 1024 * 1024);
}

#[test]
fn asr_payload_uses_wav_base64_json_field() {
    let payload: TranscribeVoiceAudioPayload =
        serde_json::from_value(serde_json::json!({ "wavBase64": "UklGRg==" }))
            .expect("payload should deserialize");

    assert_eq!(payload.wav_base64, "UklGRg==");

    let json = serde_json::to_value(payload).expect("payload should serialize");

    assert_eq!(json["wavBase64"], "UklGRg==");
    assert!(json.get("audioBase64").is_none());
}

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
fn asr_rejects_oversized_encoded_payload_before_decoding() {
    let encoded_max = ((MAX_ASR_AUDIO_BYTES + 2) / 3) * 4;
    let encoded = format!("!{}", "A".repeat(encoded_max));

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
fn asr_temp_audio_write_creates_missing_directory() {
    let temp_dir = tempfile::tempdir().unwrap();
    let nested_temp_dir = temp_dir.path().join("missing").join("audio");

    let path = write_temp_audio_file(&nested_temp_dir, b"RIFF....WAVE").unwrap();

    assert!(path.starts_with(&nested_temp_dir));
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
