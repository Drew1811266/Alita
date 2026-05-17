use std::{
    fs,
    path::{Path, PathBuf},
};

use base64::{engine::general_purpose, Engine as _};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub const MAX_ASR_AUDIO_BYTES: usize = 4 * 1024 * 1024;
const MAX_ASR_AUDIO_BASE64_BYTES: usize = ((MAX_ASR_AUDIO_BYTES + 2) / 3) * 4;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct TranscribeVoiceAudioPayload {
    pub wav_base64: String,
}

pub fn decode_wav_base64(payload: &str) -> Result<Vec<u8>, String> {
    if payload.len() > MAX_ASR_AUDIO_BASE64_BYTES {
        return Err(format!(
            "voice audio payload is too large; maximum is {} bytes",
            MAX_ASR_AUDIO_BYTES
        ));
    }

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
    let temp_dir = temp_dir.as_ref();
    fs::create_dir_all(temp_dir)
        .map_err(|error| format!("failed to create temporary audio directory: {error}"))?;
    let path = temp_dir.join(format!("alita-asr-{}.wav", Uuid::new_v4()));
    fs::write(&path, bytes)
        .map_err(|error| format!("failed to write temporary audio file: {error}"))?;
    Ok(path)
}

pub fn remove_temp_audio_file(path: impl AsRef<Path>) {
    let _ = fs::remove_file(path);
}
