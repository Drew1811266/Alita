# llama.cpp Runtime Design

## Goal

Integrate `llama.cpp` as Alita's local-first model runtime framework without choosing or bundling a specific AI model yet.

## Selected Approach

Use the official `llama-server.exe` Windows NVIDIA CUDA x64 release as an application resource managed by Tauri, with the CPU package available as an explicit fallback. Rust starts and stops the server, Python LangGraph talks to it through an OpenAI-compatible HTTP client, and the model path remains configurable.

## Runtime Boundary

- Runtime executable: `src-tauri/resources/llama-cpp/llama-server.exe`
- Runtime dependencies: `src-tauri/resources/llama-cpp/*.dll`
- Default host: `127.0.0.1`
- Default port: `8766`
- Default context size: `16384`
- Default GPU layers: `all`, configurable through `ALITA_LLAMA_GPU_LAYERS`
- Model path: not bundled; configured later through `ALITA_LLAMA_MODEL_PATH` or a future UI settings file
- If no model path is configured, Tauri skips starting llama.cpp and the Agent sidecar continues to run.
- The first production-oriented default keeps one model service resident in memory with `--ctx-size 16384`, instead of dynamically restarting llama.cpp for chat and document tasks.

## Rust Responsibilities

Rust owns local runtime lifecycle:

- detect whether a model path is configured
- build `llama-server.exe` arguments
- start the server from Tauri's resource directory
- check the local server port before starting
- kill the process on app exit

## Python Responsibilities

Python sidecar owns model calls:

- expose one `ModelClient` boundary
- support llama.cpp through OpenAI-compatible `/v1/chat/completions`
- keep the existing deterministic MVP graph path when no model call is needed

## Packaging

The build uses `scripts/install-llama-cpp.ps1` to download the official latest GitHub release assets matching the selected backend. By default it detects the NVIDIA driver CUDA capability and installs the matching `llama-*-bin-win-cuda-*-x64.zip` plus `cudart-llama-bin-win-cuda-*-x64.zip`, then copies `llama-server.exe` and required DLL files into `src-tauri/resources/llama-cpp`. Tauri bundles this directory as application resources.

## Verification

- Rust tests cover config defaults, argument generation, health URL, and disabled behavior without a model path.
- Python tests cover model client request/response behavior without requiring a real model.
- Manual verification confirms `llama-server.exe` and CUDA DLLs are present after installation, the CUDA backend loads on an NVIDIA GPU, and the app still opens when no model is configured.


