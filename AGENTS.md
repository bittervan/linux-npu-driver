# Repository Guidelines

## Project Structure & Module Organization
- `umd/`: user-mode driver implementation and shared utilities.
- `compiler/`: compiler-in-driver build integration (`npu_compiler.cmake`).
- `firmware/`: firmware packaging and headers.
- `validation/`: test applications and configs, e.g. `validation/umd-test/configs/`.
- `cmake/`: shared CMake modules and build helpers.
- `docs/`: build/troubleshooting documentation (`docs/overview.md`).
- `third_party/`: vendored dependencies; avoid editing unless required.
- `build/`: out-of-tree build output (generated).

## Build, Test, and Development Commands
- `git submodule update --init --recursive`: fetch third-party dependencies.
- `cmake -B build -S .`: configure the driver build.
- `cmake --build build --parallel $(nproc)`: compile all targets.
- `sudo cmake --install build`: install binaries/firmware to the system.
- `cmake -B build -S . -DENABLE_NPU_COMPILER_BUILD=ON`: build with compiler-in-driver support.
- `build/bin/npu-umd-test` or `npu-umd-test`: run user-mode driver functional tests after build/install.

## Coding Style & Naming Conventions
- C/C++ formatting is governed by `.clang-format` (4-space indent, 100-column limit, no tabs).
- Keep changes localized to the relevant module (`umd/`, `firmware/`, `compiler/`) and mirror existing naming patterns in that area.
- For new files, prefer descriptive, lower_snake_case filenames in the existing directory conventions.

## Testing Guidelines
- Functional tests live in `validation/umd-test`; configs are in `validation/umd-test/configs/`.
- Example: `npu-umd-test --config=validation/umd-test/configs/basic.yaml`.
- Kernel module functional tests produce `npu-kmd-test` in `build/bin/` when built.

## Commit & Pull Request Guidelines
- Recent history shows short, free-form subject lines; there is no strict convention enforced.
- Use a concise, imperative subject (e.g., “add cache eviction guard”) and include scope if helpful.
- PRs should describe the change, list build/test commands run, and note relevant hardware/firmware versions when applicable.

## Security & Configuration Tips
- Review `security.md` before reporting vulnerabilities or sensitive issues.
- Driver logging is controlled via `ZE_INTEL_NPU_LOGLEVEL` and `ZE_INTEL_NPU_LOGMASK` (see `docs/overview.md`).
