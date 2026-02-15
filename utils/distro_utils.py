import os
import shutil
import platform

def get_distro_info():
    """Parse /etc/os-release to get distribution information."""
    info = {}
    if os.path.exists("/etc/os-release"):
        with open("/etc/os-release") as f:
            for line in f:
                if "=" in line:
                    key, value = line.rstrip().split("=", 1)
                    info[key] = value.strip('"')
    return info

def get_ss_install_command():
    """Suggest a package manager command for shadowsocks-rust based on the distro."""
    info = get_distro_info()
    distro_id = info.get("ID", "").lower()
    distro_like = info.get("ID_LIKE", "").lower().split()

    if distro_id == "fedora" or "fedora" in distro_like:
        return "sudo dnf install shadowsocks-rust"
    elif distro_id in ["ubuntu", "debian"] or "debian" in distro_like:
        # Note: shadowsocks-rust might not be in all debian/ubuntu repos by default,
        # but this is the general expectation for modern distros.
        return "sudo apt update && sudo apt install shadowsocks-rust"
    elif distro_id == "arch" or "arch" in distro_like:
        return "sudo pacman -S shadowsocks-rust"
    elif distro_id == "opensuse" or "suse" in distro_like:
        return "sudo zypper install shadowsocks-rust"
    else:
        return "Please install shadowsocks-rust using your package manager or cargo."

def check_ss_local():
    """Check if sslocal is available in PATH using shutil.which."""
    return shutil.which("sslocal") is not None
