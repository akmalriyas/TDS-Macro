# 16. Open Computer Use (`ocu`) MCP Setup & Integration Guide

**Date:** October 2026  
**Package:** `open-computer-use@1.1.2` (`ocu`)

---

## 1. Overview

`open-computer-use` (`ocu`) is a native Windows desktop automation CLI and MCP server installed globally on this machine. It provides 31 MCP tools (`desktop_observe`, `screen_capture`, `mouse_click`, `keyboard_type`, `window_focus`, `wait_for_text`, `doctor`, etc.) backed by a compiled Go/Win32 binary (`open-computer-use.exe`).

---

## 2. Installed Binary & Capabilities

- **Global NPM Package Path**: `C:\Users\akmal\AppData\Roaming\npm\node_modules\open-computer-use`
- **Native Windows x64 Binary**: `C:\Users\akmal\AppData\Roaming\npm\node_modules\open-computer-use\dist\windows\amd64\open-computer-use.exe`
- **Verified Capabilities (`ocu capabilities --json`)**:
  - `screen`: native Win32 capture (`2560x1440` primary monitor)
  - `mouse`: native cursor move, click, drag, scroll
  - `keyboard`: native key tap, type, hotkey, key down/up
  - `window`: native window list, focus, move, resize, minimize, maximize
  - `clipboard`: native clipboard read/write
  - `accessibility`: Windows UI Automation tree inspection

---

## 3. Antigravity MCP Configuration (`mcp_config.json`)

Both [`C:\Users\akmal\.gemini\antigravity\mcp_config.json`](file:///C:/Users/akmal/.gemini/antigravity/mcp_config.json) and [`C:\Users\akmal\.gemini\config\mcp_config.json`](file:///C:/Users/akmal/.gemini/config/mcp_config.json) have been configured with the `open-computer-use` MCP server:

```json
{
  "mcpServers": {
    "Roblox_Studio": {
      "command": "C:\\Users\\akmal\\AppData\\Local\\Roblox\\mcp.bat"
    },
    "open-computer-use": {
      "command": "C:\\Users\\akmal\\AppData\\Roaming\\npm\\node_modules\\open-computer-use\\dist\\windows\\amd64\\open-computer-use.exe",
      "args": [
        "mcp"
      ]
    }
  }
}
```

> [!NOTE]
> Calling `open-computer-use.exe` directly (rather than the `ocu.cmd` wrapper) avoids `cmd.exe` stdio buffering overhead when running over MCP JSON-RPC.

---

## 4. Using `ocu` Alongside `tds_macro`

1. **Via MCP Server**: Once the Antigravity session reloads MCP servers, `open-computer-use` tools (`desktop_observe`, `screen_capture`, `window_list`, `mouse_click`, etc.) are available directly as MCP tools.
2. **Via CLI (`ocu`)**: Can also be invoked from PowerShell at any time:
   - `ocu doctor --json` — Verify desktop automation readiness.
   - `ocu window list --json` — List open windows including `Roblox`.
   - `ocu screenshot --output %TEMP%\tds_macro\ocu_snap.png` — Capture a full-screen PNG.
