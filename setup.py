import subprocess
import sys
from setuptools import setup

def has_cargo():
    try:
        # Check if cargo is installed on the system
        subprocess.run(["cargo", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False

extra_args = {}

if has_cargo():
    try:
        from setuptools_rust import Binding, RustExtension
        extra_args["rust_extensions"] = [
            RustExtension(
                target="mnemosyne.mnemosyne_core",
                path="mnemosyne-core/Cargo.toml",
                binding=Binding.PyO3,
            )
        ]
    except ImportError:
        # If setuptools-rust is not installed but rust compiler exists,
        # we can dynamically install setuptools-rust via build dependencies
        pass

setup(**extra_args)
