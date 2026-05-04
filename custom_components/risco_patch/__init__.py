"""Risco Patch — workaround for pyrisco 0.6.x bugs on (mostly Italian) Risco panels.

Three issues addressed (none fixed in pyrisco 0.6.8 nor in HA 2026.4.x):

  1. UnicodeDecodeError on byte 0xa7 / 0x80-0xff: pyrisco hardcodes UTF-8
     but Italian/EU panels send latin-1 encoded text. Fixes the constant
     reconnect loop that triggers panel supervision beeps every ~30 min.

  2. RiscoSocket.disconnect raising ConnectionResetError leaves the config
     entry in non-recoverable FAILED_UNLOAD state (HA core requires manual
     restart). Same fix as PR home-assistant/core#165924 (still open).

  3. RiscoCrypt.decode crashes with ValueError when the panel embeds a
     literal 0x17 byte inside the payload (legitimate with extended
     character set or some firmware variants).

The patches are applied at MODULE LOAD time (not in async_setup) so they are
in effect before risco.async_setup_entry runs.

Enable by adding a single line to configuration.yaml:

    risco_patch:

Remove this directory + that line when the upstream fixes ship.
"""
from __future__ import annotations

import logging
from typing import Any

DOMAIN = "risco_patch"
_LOGGER = logging.getLogger(__name__)

_DEFAULT_ENCODING = "latin-1"  # tolerates every byte; safe for Italian panels


def _apply_patches() -> None:
    """Monkey-patch pyrisco at import time."""
    try:
        from pyrisco.local.risco_socket import RiscoSocket
        from pyrisco.local.risco_crypt import RiscoCrypt, _is_encrypted
    except Exception:
        _LOGGER.exception("[risco_patch] cannot import pyrisco; abort")
        return

    # ----- Patch 1: RiscoSocket.__init__ default encoding -----
    if not getattr(RiscoSocket, "_dani_patched_init", False):
        _orig_socket_init = RiscoSocket.__init__

        def _patched_socket_init(self, host, port, code, **kwargs):
            kwargs.setdefault("encoding", _DEFAULT_ENCODING)
            _orig_socket_init(self, host, port, code, **kwargs)

        RiscoSocket.__init__ = _patched_socket_init
        RiscoSocket._dani_patched_init = True
        _LOGGER.warning("[risco_patch] RiscoSocket encoding default -> %s", _DEFAULT_ENCODING)

    # ----- Patch 2: RiscoSocket.disconnect hardened -----
    if not getattr(RiscoSocket, "_dani_patched_disconnect", False):
        _orig_disconnect = RiscoSocket.disconnect

        async def _patched_disconnect(self):
            try:
                return await _orig_disconnect(self)
            except (ConnectionResetError, OSError, BrokenPipeError) as exc:
                _LOGGER.warning(
                    "[risco_patch] disconnect raised %s — suppressing to avoid FAILED_UNLOAD",
                    type(exc).__name__,
                )
                try:
                    await self._close()
                except Exception:  # noqa: BLE001
                    pass

        RiscoSocket.disconnect = _patched_disconnect
        RiscoSocket._dani_patched_disconnect = True
        _LOGGER.warning("[risco_patch] RiscoSocket.disconnect hardened")

    # ----- Patch 3: RiscoCrypt.decode (rsplit on 0x17 + errors=replace) -----
    if not getattr(RiscoCrypt, "_dani_patched_decode", False):

        def _patched_decode(self, chars):
            self.encrypted_panel = _is_encrypted(chars)
            decrypted_chars = self._decrypt_chars(chars)
            decrypted = decrypted_chars.decode(self._encoding, errors="replace")
            sep_idx = decrypted.rfind("\x17")
            if sep_idx < 0:
                return [None, decrypted, False]
            raw_command = decrypted[: sep_idx + 1]
            command = decrypted[:sep_idx]
            crc = decrypted[sep_idx + 1 :]
            if command and command[0] in ("N", "B"):
                cmd_id = None
                command_string = command
            else:
                try:
                    cmd_id = int(command[:2])
                    command_string = command[2:]
                except (ValueError, IndexError):
                    return [None, command, False]
            return [cmd_id, command_string, self._valid_crc(raw_command, crc)]

        RiscoCrypt.decode = _patched_decode
        RiscoCrypt._dani_patched_decode = True
        _LOGGER.warning("[risco_patch] RiscoCrypt.decode patched (rsplit + errors=replace)")


# Apply at module import time so the patches are in place before
# risco.async_setup_entry runs (which happens later in HA bootstrap).
_apply_patches()


async def async_setup(hass: Any, config: dict) -> bool:
    """Re-apply patches if needed (idempotent)."""
    _apply_patches()
    return True
