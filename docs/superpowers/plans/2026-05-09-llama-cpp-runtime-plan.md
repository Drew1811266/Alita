# llama.cpp Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `llama.cpp` as Alita's local model runtime framework without bundling a model yet.

**Architecture:** Tauri bundles the official Windows NVIDIA CUDA `llama-server.exe` and DLLs as resources, with CPU available as an explicit fallback. Rust manages runtime startup/shutdown only when a model path is configured, while Python calls the local OpenAI-compatible API through a small model client.

**Tech Stack:** Tauri 2, Rust, PowerShell, llama.cpp server, Python, FastAPI, LangGraph, pytest.

---

## Files

- Create: `scripts/install-llama-cpp.ps1`
- Create: `src-tauri/src/llama_runtime.rs`
- Create: `src-tauri/tests/llama_runtime_tests.rs`
- Create: `python/agent_service/model_client.py`
- Create: `python/tests/test_model_client.py`
- Modify: `src-tauri/src/lib.rs`
- Modify: `src-tauri/tauri.conf.json`
- Modify: `scripts/build-windows-app.ps1`
- Modify: `docs/windows-desktop-runbook.md`
- Modify: `docs/mvp-verification.md`

## Task 1: Install Runtime Resource

- [x] Write `scripts/install-llama-cpp.ps1`.
- [x] Download the latest official Windows CUDA x64 `llama.cpp` release assets from `ggml-org/llama.cpp`.
- [x] Copy `llama-server.exe` and `*.dll` into `src-tauri/resources/llama-cpp`.
- [x] Record the downloaded release in `src-tauri/resources/llama-cpp/VERSION.txt`.
- [x] Support `-Backend cpu` as an explicit fallback installer mode.

## Task 2: Rust Runtime Boundary

- [x] Write failing tests for default config, server args, health URL, and disabled startup.
- [x] Implement `LlamaRuntimeConfig`, `LlamaRuntimeState`, and lifecycle helpers.
- [x] Register runtime management in Tauri setup and shutdown.

## Task 3: Python Model Client

- [x] Write failing tests for llama.cpp chat request and disabled config behavior.
- [x] Implement `ModelClient` with OpenAI-compatible `/v1/chat/completions`.
- [x] Keep LangGraph deterministic MVP flow unchanged until a model is configured.

## Task 4: Packaging and Documentation

- [x] Include `src-tauri/resources/llama-cpp` in Tauri bundle resources.
- [x] Run `scripts/install-llama-cpp.ps1` from the Windows build script.
- [x] Document how to configure `ALITA_LLAMA_MODEL_PATH`.
- [x] Document how to configure `ALITA_LLAMA_GPU_LAYERS`.

## Task 5: Verification

- [x] Run Rust tests.
- [x] Run Python tests.
- [x] Run MVP verification.
- [x] Build the desktop package.
- [x] Confirm release app still starts with no model configured.
- [x] Confirm CUDA backend loads and detects the local NVIDIA GPU.


