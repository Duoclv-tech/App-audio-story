"""
Stable per-machine hardware fingerprint (``device_id``).

Formula is FROZEN by contract (license-verify-lifecycle.md §4) — never change
the inputs or the hashing once shipped, or every existing customer's machine
would compute a new id and burn their 2-device quota.

    raw = machine_guid + "|" + bios_serial + "|" + system_disk_serial
    device_id = sha256( lowercase(trim(raw)) )   # 64 hex chars

Design notes:
- MachineGuid (registry) is the primary, most stable anchor; survives reinstall
  of the tool, changes only on OS reinstall / hardware swap.
- MAC address is deliberately NOT used (changes with Wi-Fi/USB/VPN adapters).
- A component that can't be read is replaced by the literal "na" so the
  ``a|b|c`` structure stays constant instead of collapsing.
- The result is cached for the process lifetime because the WMI/PowerShell
  probe is slow (spawns a subprocess) and the value never changes at runtime.
"""
import functools
import hashlib
import subprocess
import sys


def _machine_guid() -> str:
    """HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid, or 'na'."""
    if sys.platform != "win32":
        return "na"
    try:
        import winreg
        # KEY_WOW64_64KEY: always read the 64-bit view, never the WOW6432 redirect.
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value).strip() or "na"
    except Exception:
        return "na"


def _powershell(command: str) -> str:
    """Run a PowerShell one-liner, return stdout (empty string on any failure).

    subprocess.Popen is globally patched (app.paths.hide_subprocess_windows) to
    add CREATE_NO_WINDOW, so this never flashes a console in the windowed build.
    """
    if sys.platform != "win32":
        return ""
    try:
        proc = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-Command", command,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return (proc.stdout or "").strip()
    except Exception:
        return ""


def _bios_and_disk_serials() -> tuple[str, str]:
    """Read BIOS serial + OS-disk serial in a SINGLE PowerShell call.

    Emits two lines: ``<bios>`` then ``<disk>``. Either may be blank; callers
    substitute 'na'. Uses the physical disk backing the C: volume so the value
    is the OS disk, not an arbitrary drive.
    """
    command = (
        "$b = (Get-CimInstance Win32_BIOS -ErrorAction SilentlyContinue).SerialNumber; "
        "$d = try { (Get-Partition -DriveLetter C -ErrorAction Stop | "
        "Get-Disk -ErrorAction Stop).SerialNumber } catch { '' }; "
        "Write-Output $b; Write-Output $d"
    )
    out = _powershell(command)
    lines = [ln.strip() for ln in out.splitlines()]
    bios = lines[0] if len(lines) >= 1 and lines[0] else "na"
    disk = lines[1] if len(lines) >= 2 and lines[1] else "na"
    return bios, disk


@functools.lru_cache(maxsize=1)
def _probe() -> tuple[str, str, str]:
    """(machine_guid, bios_serial, disk_serial) — each 'na' when unreadable.

    Cached per process: the WMI/PowerShell probe is slow (spawns a subprocess)
    and the values never change at runtime. compute_device_id() and
    has_hardware_anchor() share this single probe so they never disagree.
    """
    if sys.platform == "win32":
        guid = _machine_guid()
        bios, disk = _bios_and_disk_serials()
    else:
        # Non-Windows dev fallback: keep the a|b|c shape, stable per host.
        import platform
        guid = (platform.node() or "na").strip()
        bios, disk = "na", "na"
    return guid, bios, disk


@functools.lru_cache(maxsize=1)
def compute_device_id() -> str:
    """Return the 64-char hex fingerprint for this machine (cached per process)."""
    guid, bios, disk = _probe()
    raw = f"{guid}|{bios}|{disk}"
    return hashlib.sha256(raw.strip().lower().encode("utf-8")).hexdigest()


def has_hardware_anchor() -> bool:
    """True when at least one tamper-resistant hardware serial (BIOS or system
    disk) was read successfully.

    When BOTH are 'na' (typical of a VM whose hypervisor hides serials), the
    device_id collapses to sha256(MachineGuid|na|na) — and MachineGuid is a mere
    registry value an admin can overwrite. Any machine with the same forged
    MachineGuid then reproduces the same device_id, so a copied license.json
    verifies offline everywhere and node-locking is defeated. Activation refuses
    this state (see app.license.service.activate) so no portable token is minted.
    """
    _guid, bios, disk = _probe()
    return bios != "na" or disk != "na"
