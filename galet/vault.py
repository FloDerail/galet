"""Encrypted vault for server cards (host, port, user name, folder, recent addresses).

The vault is one file, ``~/.config/galet/vault.gpg``, encrypted with GnuPG
(AES-256, symmetric). Its key is either:

* a random key kept in the GNOME keyring (default — nothing to type), or
* a master password chosen by the user (like Termius): the server list stays
  locked until it is typed once per session. The master password is never stored.

Server passwords stay in the GNOME keyring (see servers.py). Before 0.9, server
cards lived in clear in settings.json: they are moved here on first start.
"""

import json
import logging
import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

from gi.repository import GLib

log = logging.getLogger("galet")

KEYRING_S2K = "1024"  # the keyring key is random: no need to stretch it
MASTER_S2K = "65011712"  # maximum stretching for a human password
KEYRING_ID = "servers"  # keyring attribute of the vault key (tests use another one)


class VaultError(Exception):
    pass


# --------------------------------------------------------------------- gpg

def _gpg():
    return shutil.which("gpg") or shutil.which("gpg2")


def available():
    return _gpg() is not None


def _run_gpg(args, passphrase, data):
    """Run gpg with a throwaway home folder (no agent cache, nothing left behind)."""
    gpg = _gpg()
    if gpg is None:
        raise VaultError("GnuPG (gpg) is not installed")
    with tempfile.TemporaryDirectory(prefix="galet-gpg-") as home:
        os.chmod(home, 0o700)
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, passphrase.encode("utf-8") + b"\n")
        finally:
            os.close(write_fd)
        try:
            result = subprocess.run(
                [gpg, "--homedir", home, "--batch", "--yes", "--quiet", "--no-tty", "--no-symkey-cache",
                 "--pinentry-mode", "loopback", "--passphrase-fd", str(read_fd), *args],
                input=data, capture_output=True, pass_fds=(read_fd,), timeout=60, check=False)
        finally:
            os.close(read_fd)
            if shutil.which("gpgconf"):  # stop the agent and remove its socket folder in /run/user
                subprocess.run(["gpgconf", "--homedir", home, "--kill", "all"], capture_output=True, check=False)
                subprocess.run(["gpgconf", "--homedir", home, "--remove-socketdir"], capture_output=True,
                               check=False)
    if result.returncode != 0:
        raise VaultError(result.stderr.decode("utf-8", "replace").strip() or "gpg failed")
    return result.stdout


def encrypt(data, passphrase, strong=True):
    return _run_gpg(["--symmetric", "--cipher-algo", "AES256", "--s2k-digest-algo", "SHA512",
                     "--s2k-mode", "3", "--s2k-count", MASTER_S2K if strong else KEYRING_S2K,
                     "--compress-algo", "none", "--output", "-"], passphrase, data)


def decrypt(data, passphrase):
    return _run_gpg(["--decrypt", "--output", "-"], passphrase, data)


def is_encrypted(data):
    """Binary OpenPGP symmetric message (what encrypt() writes)."""
    return bool(data) and (data[0] & 0x80) != 0 and not data.lstrip().startswith(b"{")


# ----------------------------------------------------------------- keyring

def _schema():
    import gi
    gi.require_version("Secret", "1")
    from gi.repository import Secret
    return Secret, Secret.Schema.new("io.github.FloDerail.Galet.Vault", Secret.SchemaFlags.NONE,
                                     {"vault": Secret.SchemaAttributeType.STRING})


def _keyring_key(create):
    try:
        secret, schema = _schema()
        key = secret.password_lookup_sync(schema, {"vault": KEYRING_ID}, None)
        if not key and create:
            key = secrets.token_urlsafe(32)
            secret.password_store_sync(schema, {"vault": KEYRING_ID}, secret.COLLECTION_DEFAULT,
                                       "Galet: servers vault key", key, None)
        return key or None
    except Exception as err:  # noqa: BLE001  no Secret Service
        log.warning("Keyring unavailable for the vault: %s", err)
        return None


def _clear_keyring_key():
    try:
        secret, schema = _schema()
        secret.password_clear_sync(schema, {"vault": KEYRING_ID}, None)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------- vault

class Vault:
    def __init__(self, settings):
        self.settings = settings
        folder = Path(GLib.get_user_config_dir()) / "galet"
        self.path = folder / "vault.gpg"
        self.meta_path = folder / "vault.json"
        self.data = {"servers": [], "recent": []}
        self.master = None  # master password while unlocked (memory only)
        self.locked = False
        self.error = None
        self.plain = False  # no keyring and no gpg: cards stay in settings.json, as before 0.9
        self._load()

    # ------------------------------------------------------------ state

    @property
    def uses_master(self):
        return bool(self._meta().get("master"))

    def _meta(self):
        try:
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_meta(self, meta):
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(json.dumps(meta), encoding="utf-8")

    def _load(self):
        legacy = {"servers": self.settings.data.get("servers") or [],
                  "recent": self.settings.data.get("recent_servers") or []}
        if not self.path.exists():
            self.data = legacy
            if legacy["servers"] or legacy["recent"]:
                try:
                    self._save()
                    self._forget_legacy()
                except (VaultError, OSError) as err:
                    log.warning("Servers stay unencrypted (%s)", err)
                    self.plain = True
            return
        if self.uses_master:
            self.locked = True
            return
        key = _keyring_key(create=False)
        if key is None:
            self.locked = True
            self.error = "keyring"
            return
        try:
            self.data = self._parse(decrypt(self.path.read_bytes(), key))
        except (VaultError, OSError, ValueError) as err:
            log.warning("Cannot open the servers vault: %s", err)
            self.locked = True
            self.error = "decrypt"

    @staticmethod
    def _parse(raw):
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("bad vault")
        data.setdefault("servers", [])
        data.setdefault("recent", [])
        return data

    def _forget_legacy(self):
        for key in ("servers", "recent_servers"):
            if key in self.settings.data:
                self.settings.data.pop(key)
        self.settings.set("vault", True)  # writes settings.json without the clear-text cards

    def _save(self):
        raw = json.dumps(self.data, ensure_ascii=False).encode("utf-8")
        if self.master:
            blob = encrypt(raw, self.master, strong=True)
        else:
            key = _keyring_key(create=True)
            if key is None:
                raise VaultError("keyring")
            blob = encrypt(raw, key, strong=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob)
        os.replace(tmp, self.path)
        self._write_meta({"version": 1, "master": bool(self.master)})

    def _changed(self):
        self.settings.emit("changed", "servers")

    # ------------------------------------------------------------- API

    def servers(self):
        return [] if self.locked else list(self.data.get("servers", []))

    def recent(self):
        return [] if self.locked else list(self.data.get("recent", []))

    def set_servers(self, servers):
        if self.locked:
            return
        self.data["servers"] = servers
        self._save_and_notify()

    def set_recent(self, recent):
        if self.locked:
            return
        self.data["recent"] = recent
        self._save_and_notify()

    def _save_and_notify(self):
        if not self.plain:
            try:
                self._save()
            except (VaultError, OSError) as err:
                log.warning("Cannot save the servers vault, keeping servers unencrypted: %s", err)
                self.plain = True
        if self.plain:
            self.settings.data["servers"] = self.data.get("servers", [])
            self.settings.set("recent_servers", list(self.data.get("recent", [])))
        self._changed()

    def unlock(self, password):
        """Open a vault protected by a master password. Returns True on success."""
        try:
            self.data = self._parse(decrypt(self.path.read_bytes(), password))
        except (VaultError, OSError, ValueError):
            return False
        self.master = password
        self.locked = False
        self.error = None
        self._changed()
        return True

    def lock(self):
        if self.uses_master:
            self.master = None
            self.data = {"servers": [], "recent": []}
            self.locked = True
            self._changed()

    def set_master_password(self, password):
        """Protect the vault with a master password (or remove it with None)."""
        if self.locked:
            raise VaultError("locked")
        self.master = password or None
        self._save()
        if self.master:
            _clear_keyring_key()  # the random key would let anyone open the vault
        self._changed()

    def get_list(self, key):
        """Other encrypted lists (e.g. "deploys": project ↔ server pairs)."""
        return [] if self.locked else list(self.data.get(key, []))

    def set_list(self, key, value):
        if self.locked:
            return
        self.data[key] = list(value)
        if not self.plain:
            try:
                self._save()
            except (VaultError, OSError) as err:
                log.warning("Cannot save the vault: %s", err)

    def export(self):
        return {"servers": self.servers(), "recent": self.recent()}

    def merge(self, servers):
        """Add backed-up server cards (by id); returns how many were added or updated."""
        if self.locked:
            return 0
        current = {s.get("id"): s for s in self.data.get("servers", []) if isinstance(s, dict)}
        count = 0
        for server in servers:
            if isinstance(server, dict) and server.get("uri"):
                current[server.get("id") or server["uri"]] = server
                count += 1
        self.data["servers"] = list(current.values())
        self._save_and_notify()
        return count


_VAULTS = {}


def get(settings):
    vault = _VAULTS.get(id(settings))
    if vault is None:
        vault = _VAULTS[id(settings)] = Vault(settings)
    return vault
