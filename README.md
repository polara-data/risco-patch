# risco_patch

A tiny Home Assistant custom component that **monkey-patches pyrisco at runtime** to fix three known bugs in the official **Risco Local** integration.
The official integration ships pyrisco `0.6.8`, where these bugs are unresolved as of HA `2026.4.x`.

> **Audience.** You only need this if your Risco panel keeps reconnecting / your panel beeps every ~30 minutes / your config entry ends up in `FAILED_UNLOAD` after a few hours. It's most common on **Italian / EU LightSYS / Agility / ProSYS** panels.

---

## What it fixes

### 1. `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xa7`
`pyrisco` hardcodes UTF-8 when decoding panel responses. Italian (and other latin-1 / cp1252) panels routinely send bytes in `0x80–0xFF`. Each invalid byte raises `UnicodeDecodeError`, which kills the listener task. The integration reconnects, the panel sees back-to-back disconnect/connects and **emits a "supervision lost" beep**.

**Patch:** default `encoding="latin-1"` on `RiscoSocket.__init__` (latin-1 maps every byte 0x00-0xFF, never raises). Plus `errors="replace"` on the actual decode call as a belt-and-braces safety net.

### 2. `FAILED_UNLOAD` after `ConnectionResetError`
`async_unload_entry` calls `local_data.system.disconnect()` without a try/except. When the panel has already RST'd the TCP connection, `_writer.wait_closed()` raises `ConnectionResetError`. HA marks the entry as `FAILED_UNLOAD` and refuses any reload — only a full HA restart unblocks it.

**Patch:** wrap `RiscoSocket.disconnect` in `try/except (ConnectionResetError, OSError, BrokenPipeError)` and call `_close()` for cleanup. Same intent as upstream PR [`home-assistant/core#165924`](https://github.com/home-assistant/core/pull/165924) (open, approved by @OnFreund, awaiting merge as of 2026-05).

### 3. `ValueError: too many values to unpack (expected 2, got 3)` in `RiscoCrypt.decode`
`decode()` does `command, crc = decrypted.split('\x17')` assuming exactly one `0x17` (ETB) byte in the message. If the payload happens to contain another `0x17` (e.g. extended character set output, or certain firmware status messages), the split returns 3 parts and crashes the listener.

**Patch:** use `rfind('\x17')` so the **last** `0x17` is treated as the separator; tolerate empty / malformed messages by returning a "bad CRC" tuple instead of raising.

---

## Install

### Option A — Manual

1. Copy the `custom_components/risco_patch/` directory of this repo into `<config>/custom_components/`. Final layout:

   ```
   <config>/
   ├── configuration.yaml
   └── custom_components/
       └── risco_patch/
           ├── __init__.py
           └── manifest.json
   ```

2. Add **one line** to `configuration.yaml`:

   ```yaml
   risco_patch:
   ```

3. **Settings → System → Restart** Home Assistant.

4. Verify in **Settings → System → Logs** (or `home-assistant.log`):

   ```
   [risco_patch] RiscoSocket encoding default -> latin-1
   [risco_patch] RiscoSocket.disconnect hardened
   [risco_patch] RiscoCrypt.decode patched (rsplit + errors=replace)
   ```

### Option B — HACS custom repository

If you use HACS:

1. HACS → ⋮ → **Custom repositories** → add this repo URL, category **Integration**.
2. Search "Risco Patch", install.
3. Add `risco_patch:` to `configuration.yaml`.
4. Restart HA.

---

## How to verify it actually worked

Within ~5 minutes of the restart you should see:

| Before | After |
|---|---|
| Repeated `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xa7…` in the log | Gone |
| Risco config entry occasionally lands in `failed_unload`, requires HA restart | Stable `loaded` state |
| Panel beeping every ~30 min | Silent |

Quick check from the Developer Tools → Template tab:

```yaml
{{ states('alarm_control_panel.<your_partition>') }}
```

Should return `disarmed` / `armed_*` and update in real time when you arm from the keypad.

---

## How to remove

When upstream PR [#165924](https://github.com/home-assistant/core/pull/165924) lands and (hopefully) when pyrisco exposes an `encoding` option:

1. Remove `risco_patch:` from `configuration.yaml`.
2. Delete `<config>/custom_components/risco_patch/`.
3. Restart HA.

The patch leaves no persistent state. Risco will go back to using stock pyrisco.

---

## Compatibility & caveats

- Tested on: HA Core `2026.4.4` (Home Assistant Green), pyrisco `0.6.8`, panel Risco LightSYS Plus (Italy).
- Patches are written defensively and idempotent — they check a marker attribute before reapplying.
- The `latin-1` default is **only applied if il caller doesn't specify `encoding`**. If a future HA version starts passing `encoding="utf-8"` explicitly, this patch becomes a no-op (and you should uninstall it anyway).
- If your panel firmware speaks pure ASCII (most US installations), this patch is harmless but unnecessary.
- If your panel actually **needs** UTF-8 (e.g. zone labels with emoji), you can change `_DEFAULT_ENCODING` at the top of `__init__.py` to `"utf-8"` and only Patch 2 + 3 will apply.

---

## Why a custom_component instead of a fork of pyrisco?

A custom_component:

- Survives `pyrisco` package updates (you don't need to keep a vendored copy).
- Is opt-in (set via `configuration.yaml` line).
- Disappears cleanly when the upstream fix lands.
- Doesn't require touching the HA core image (which is read-only on HA OS).

---

## Links

- Upstream resilience PR: <https://github.com/home-assistant/core/pull/165924>
- pyrisco repo: <https://github.com/OnFreund/pyrisco>
- HA Risco integration docs: <https://www.home-assistant.io/integrations/risco>

---

## License

MIT. Use at your own risk.
