use std::{
    fs,
    path::{Path, PathBuf},
};

use base64::{engine::general_purpose, Engine as _};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub const MAX_ASR_AUDIO_BYTES: usize = 10 * 1024 * 1024;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct TranscribeVoiceAudioPayload {
    pub audio_base64: String,
}

pub fn decode_wav_base64(payload: &str) -> Result<Vec<u8>, String> {
    let bytes = general_purpose::STANDARD
        .decode(payload)
        .map_err(|error| format!("invalid voice audio payload: {error}"))?;
    if bytes.len() > MAX_ASR_AUDIO_BYTES {
        return Err(format!(
            "voice audio payload is too large; maximum is {} bytes",
            MAX_ASR_AUDIO_BYTES
        ));
    }

    Ok(bytes)
}

pub fn write_temp_audio_file(temp_dir: impl AsRef<Path>, bytes: &[u8]) -> Result<PathBuf, String> {
    let path = temp_dir
        .as_ref()
        .join(format!("alita-asr-{}.wav", Uuid::new_v4()));
    fs::write(&path, bytes)
        .map_err(|error| format!("failed to write temporary audio file: {error}"))?;
    Ok(path)
}

pub fn remove_temp_audio_file(path: impl AsRef<Path>) {
    let _ = fs::remove_file(path);
}
