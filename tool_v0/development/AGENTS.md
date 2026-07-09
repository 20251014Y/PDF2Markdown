# PDF2Markdown v0 maintenance notes

The user-facing project keeps input, output, and tool_v0 at the root.

Runtime code lives in tool_v0/converter_core. The name identifies the Python
conversion engine and avoids duplicating the product name.

Development-only files live in tool_v0/development:

- installer: online installer source;
- tests: unit tests;
- pyproject.toml: package metadata;
- .gitignore: source-control rules.

The local development runtime is tool_v0/.python-dev. The installed user
runtime is tool_v0/.python so the delivered project can be moved as a unit.

User entry point:

    .\tool_v0\run_local.cmd

API 模式入口：

    .\tool_v0\run_api.cmd

Development test command:

    .\tool_v0\.python-dev\Scripts\python.exe -m unittest discover -s .\tool_v0\development\tests -v

Build the installer:

    powershell -ExecutionPolicy Bypass -File .\tool_v0\development\installer\build-installer.ps1

Do not place temporary logs, PID files, CAB files, or installer build files in
the project root. Runtime diagnostics belong under tool_v0/.runtime-home.
