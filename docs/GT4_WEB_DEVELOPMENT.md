# NFSU2 GT4 Web — development plan

This is an experimental browser-first fork of nfsu2-web. The original project remains on `main`; development takes place on `nfsu2-gt4-web`.

## Goal

Retain the street-racing, free-roam and customization experience while improving visual presentation and eventually supporting an expanded, technically described vehicle catalog inspired by the presentation style of Gran Turismo 4. This is a design direction, not a claim of affiliation with EA, Polyphony Digital or automotive manufacturers.

## Baseline architecture (verified from repository README)

- `tools/`: ahead-of-time translation of a supported PC executable from x86 to C.
- `runtime/` and `runtime/web/`: game platform interfaces and browser-specific implementations.
- `web/src/`: browser UI, WebGPU rendering and Web Audio.
- `web/server-rs/`: Rust server for game assets and multiplayer.
- `web/gen.sh`: generate translated source; `web/build.sh`: compile WASM; `web/start.sh`: launch local server.

The supported game executable is **North American v1.2 SPEED2.EXE**, 4,800,512 bytes, SHA-256 `f9dd86c054878ce6276beb07c1fd61874f7a1e4bf1f241b084c65b73e24168a7`. Never commit the executable, extracted game data, generated `gen/` source, or compiled `out/` artifacts.

## Milestones

1. **Build baseline:** inventory the Codespaces toolchain; check the working tree; build without changing gameplay once legitimate original game data is available. Capture browser launch, console, and performance logs.
2. **Visual baseline:** benchmark one location and one car at identical settings, capture screenshots/FPS, and identify the renderer's relevant modules.
3. **First rendering change:** implement one reversible, user-selectable enhancement. Check compatibility and performance in Chrome/Firefox with WebGPU.
4. **Vehicle data model:** define metadata for makes, models, variants, performance and configuration without importing proprietary car meshes or trademarks into the repo.
5. **Vehicle import prototype:** validate one properly licensed vehicle asset, LOD policy, texture compression and customization hooks.
6. **Expansion:** city lighting, material fidelity, garages, UI, racing systems and scalable performance profiles.

## Acceptance criteria for first milestone

- No changes to the original `main` branch.
- Record the base commit and build commands used.
- Confirm available tools (Python 3, Node.js 20+, Rust, wasi-sdk 34).
- Generate WASM only from a user-provided legitimate game installation; generated material remains untracked.
- Confirm the browser loads through the Codespaces forwarded port and record any missing browser requirements (including secure-context and WebGPU availability).
- Do not claim gameplay or rendering tests passed until they have been performed.

## Codespaces checklist (read-only)

Run from the repository root:

```bash
pwd
git status --short --branch
git rev-parse --short HEAD
python3 --version
node --version
npm --version
rustc --version
cargo --version
git --version
find deps -maxdepth 2 -type f -name clang -print 2>/dev/null || true
```

The code can be edited and committed through GitHub without direct terminal access to Codespaces. However, verifying the Codespaces environment and running the WASM build requires an active Codespaces terminal session or another available execution environment.

## Legal and distribution boundary

This repository's MIT license covers the published open-source code. It does not license Need for Speed Underground 2 game assets, compiled derivatives of the game, soundtracks, branded car models or other third-party intellectual property. Do not publish such assets or generated binaries without appropriate rights. For a publicly distributable standalone racing game, replace proprietary assets and dependencies with original or appropriately licensed alternatives.

## Implemented: opt-in Studio color treatment (first graphics change)

In the browser's **Display > Color treatment**, choose **Original** (default) or **Studio**. Studio is a restrained final WebGPU color pass that changes contrast, saturation, shadow hue and highlight balance during regular driving. Its shader runs after the game's Exposure and White Level adjustment; the game's original rendered picture is the input.

The direct-to-canvas fast path remains unchanged in Original mode. Studio disables that shortcut to use a compositor pass and therefore may reduce performance, especially on phones. Photo Mode uses its own existing filters and does **not** yet apply this Studio treatment. The option takes effect the next time Play is pressed.

This is not improved geometry, a PBR car paint system, new lighting, new cars, ray tracing or a finished GT4 visual remake. No proprietary assets were added.

Verification: branch CI typechecks the browser, bundles its JS/CSS and tests settings plus color-pass wiring. A successful CI is **not** proof of correct WebGPU imagery, unchanged FPS or successful Bayview gameplay. Those tests require the game's original, properly licensed files and a compatible browser.
