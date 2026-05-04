# risco_patch

A tiny Home Assistant custom component that **monkey-patches pyrisco at runtime** to fix three known bugs in the official **Risco Local** integration.

The official integration ships pyrisco `0.6.8`, where these bugs are unresolved as of HA `2026.4.x`.

> **Status (2026-05-04).** The 3 patches eliminate the integration-side crashes (UTF-8, FAILED_UNLOAD, 0x17 ValueError). They do NOT eliminate the panel "supervision lost" beep that some users (incl. me) are experiencing every ~20 minutes since a recent regression — see the [open question](#open-question--recent-regression-please-help) section.

---

## What the patch fixes (3 code patches)

### 1. `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xa7`
`pyrisco` hardcodes UTF-8 when decoding panel responses. Italian (and other latin-1 / cp1252) panels routinely send bytes in `0x80–0xFF`. Each invalid byte raises `UnicodeDecodeError`, killing the listener task.

**Patch:** default `encoding="latin-1"` on `RiscoSocket.__init__` (latin-1 maps every byte 0x00-0xFF, never raises). Plus `errors="replace"` on the actual decode call as a belt-and-braces safety net.

### 2. `FAILED_UNLOAD` after `ConnectionResetError`
`async_unload_entry` calls `local_data.system.disconnect()` without a try/except. When the panel has already RST'd the TCP connection, `_writer.wait_closed()` raises `ConnectionResetError`. HA marks the entry as `FAILED_UNLOAD` and refuses any reload — only a full HA restart unblocks it.

**Patch:** wrap `RiscoSocket.disconnect` in `try/except (ConnectionResetError, OSError, BrokenPipeError)` and call `_close()` for cleanup. Same intent as upstream PR [`home-assistant/core#165924`](https://github.com/home-assistant/core/pull/165924) (open, approved by @OnFreund, awaiting merge as of 2026-05).

### 3. `ValueError: too many values to unpack (expected 2, got 3)` in `RiscoCrypt.decode`
`decode()` does `command, crc = decrypted.split('\x17')` assuming exactly one `0x17` (ETB) byte in the message. If the payload contains another `0x17`, the split returns 3 parts and crashes the listener.

**Patch:** use `rfind('\x17')` so the **last** `0x17` is treated as the separator; tolerate empty / malformed messages by returning a "bad CRC" tuple instead of raising.

---

## Open question — recent regression, please help

In my own setup (HA OS `2026.4.4`, pyrisco `0.6.8`, Risco LightSYS Plus IT firmware), with the 3 patches above applied **and the integration otherwise stable**, the panel still emits a "supervision lost" beep every **~20 minutes**, triggered by an unsolicited TCP RST from the panel.

**Crucially**: this **was NOT happening a few weeks ago** with the same panel and the same network. The integration was rock-solid for months. Something changed recently — and it's not pyrisco itself (`0.6.7` → `0.6.8` only changed cloud `User-Agent`, the local socket code is byte-identical).

If you have **any** of the following info, please open an issue / reply on the [HA forum thread](https://community.home-assistant.io/t/risco-local-custom-component-to-fix-utf-8-failed-unload-0x17-split-bugs-and-an-open-question-on-a-recent-regression/1009293) — it would help nail the root cause:

- Same panel model + same firmware: are you also seeing the ~20-min RST/beep cycle now, even though it was fine weeks ago?
- Did your panel receive a firmware OTA update recently?
- Any HA core release in the last few weeks that changed the Risco integration's poll interval / keep-alive / connection lifecycle?
- pyrisco DEBUG logs showing the last few RX/TX commands before the panel sends the RST.

Things I've already ruled out: `scan_interval` (tried 30s, 60s, 600s), `keepalive` interval (5s vs 60s) — the RST timing is identical regardless. So it's **not poll-induced**; the panel itself is closing the connection.

**Workarounds that mask but don't fix this** (and that I'm explicitly NOT shipping in this repo):

- A 15-min "preemptive reconnect" automation that reloads the config entry before the panel times out. Hides the beep but causes 1-3 min of `setup_in_progress` per cycle and assumes the timeout is fixed (it might not be).
- Bumping `scan_interval` to a high value. Doesn't actually change the RST timing.

If/when the real cause is found, I'll update this repo and the forum post.

---

## Install

### Option A — Manual

1. Copy `custom_components/risco_patch/` into `<config>/custom_components/`. Final layout:

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

1. HACS → ⋮ → **Custom repositories** → add this repo URL, category **Integration**.
2. Search "Risco Patch", install.
3. Add `risco_patch:` to `configuration.yaml`.
4. Restart HA.

---

## How to verify it actually worked

| Before | After (with this patch) |
|---|---|
| Repeated `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xa7…` in the log | Gone |
| Risco config entry occasionally lands in `failed_unload`, requires HA restart | Stable `loaded` state |
| `ValueError: too many values to unpack` in `RiscoCrypt.decode` | Gone |
| Panel beep every ~20 min from supervision lost | **Still present — root cause not yet identified, see [open question](#open-question--recent-regression-please-help)** |

---

## How to remove

1. Remove `risco_patch:` from `configuration.yaml`.
2. Delete `<config>/custom_components/risco_patch/`.
3. Restart HA.

The patch leaves no persistent state.

---

## Compatibility & caveats

- Tested on: HA Core `2026.4.4` (Home Assistant Green), pyrisco `0.6.8`, panel Risco LightSYS Plus (Italy).
- Patches are written defensively and idempotent — they check a marker attribute before reapplying.
- The `latin-1` default is **only applied if the caller doesn't specify `encoding`**. If a future HA version starts passing `encoding="utf-8"` explicitly, this patch becomes a no-op for Patch 1.
- If your panel firmware speaks pure ASCII (most US installations), the encoding patch is harmless but unnecessary.

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
- HA forum discussion: <https://community.home-assistant.io/t/risco-local-custom-component-to-fix-utf-8-failed-unload-0x17-split-bugs-and-an-open-question-on-a-recent-regression/1009293>

---

## License

MIT. Use at your own risk.
