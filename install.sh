#!/bin/bash
# Mnemosyne Installation Script
# Usage: curl -fsSL https://github.com/tipsy-kereru/mnemosyne/releases/latest/download/install.sh | sh
# With options: curl -fsSL ... | sh -s -- --force --version 0.7.0

set -e

# Defaults
FORCE=false
VERSION="${MNE_VERSION:-latest}"
PYTHON="${PYTHON:-python3}"
VENV="${MNE_VENV:-true}"

# Parse arguments
while [ "$#" -gt 0 ]; do
    case "$1" in
        --force)
            FORCE=true
            shift
            ;;
        --version)
            VERSION="$2"
            shift 2
            ;;
        --no-venv)
            VENV=false
            shift
            ;;
        --python)
            PYTHON="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

echo "🔧 Mnemosyne Installation"
echo "   Version: $VERSION"
echo "   Python: $PYTHON"
echo "   Force: $FORCE"
echo "   VEnv: $VENV"

# Detect platform
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux)  PLATFORM="linux" ;;
    Darwin) PLATFORM="macos" ;;
    *)      PLATFORM="unknown" ;;
esac

# Check Python
if ! command -v "$PYTHON" &> /dev/null; then
    echo "❌ Python not found: $PYTHON" >&2
    echo "   Please install Python 3.8+ or specify with: curl ... | sh -s -- --python python3.11" >&2
    exit 1
fi

PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "   Python version: $PY_VERSION"

# Create virtual env if requested
if [ "$VENV" = "true" ]; then
    VENV_DIR="${MNE_VENV_DIR:-$HOME/.mnemosyne/venv}"

    if [ "$FORCE" = "true" ] && [ -d "$VENV_DIR" ]; then
        echo "🗑️  Removing existing venv: $VENV_DIR"
        rm -rf "$VENV_DIR"
    fi

    if [ ! -d "$VENV_DIR" ]; then
        echo "📦 Creating virtual environment: $VENV_DIR"
        $PYTHON -m venv "$VENV_DIR"
    fi

    PIP="$VENV_DIR/bin/pip"
    PYTHON="$VENV_DIR/bin/python"
else
    PIP="$PYTHON -m pip"
fi

# Install uv if available for faster installs
if command -v uv &> /dev/null && [ "$VENV" = "true" ]; then
    INSTALLER="uv pip"
    INSTALL_CMD="uv pip install"
else
    INSTALLER="pip"
    INSTALL_CMD="$PIP install"
fi

echo "📥 Using installer: $INSTALLER"

# Install from PyPI or GitHub
if [ "$VERSION" = "latest" ]; then
    echo "📦 Installing latest from PyPI..."
    if [ "$FORCE" = "true" ]; then
        if $INSTALL_CMD --force-reinstall mnemosyne-kg; then
            echo "✅ Installed from PyPI"
        else
            echo "⚠️  PyPI install failed, trying GitHub..."
            VERSION="main"
        fi
    else
        if $INSTALL_CMD mnemosyne-kg; then
            echo "✅ Installed from PyPI"
        else
            echo "⚠️  PyPI install failed, trying GitHub..."
            VERSION="main"
        fi
    fi
fi

# Install from GitHub if needed
if [ "$VERSION" != "latest" ]; then
    GIT_URL="https://github.com/tipsy-kereru/mnemosyne.git@$VERSION"
    echo "📦 Installing from GitHub: $GIT_URL"

    if [ "$INSTALLER" = "uv pip" ]; then
        $INSTALL_CMD --force-reinstall "git+$GIT_URL"
    else
        $INSTALL_CMD --force-reinstall "git+$GIT_URL"
    fi
fi

# Verify installation
echo "✅ Verifying installation..."
$PYTHON -c "import mnemosyne; print(f'   Mnemosyne {mnemosyne.__version__} installed successfully')"

# Add to PATH if using venv
if [ "$VENV" = "true" ] && [ "$PLATFORM" = "macos" ]; then
    SHELL_RC="$HOME/.zshrc"
    [ ! -f "$SHELL_RC" ] && SHELL_RC="$HOME/.bash_profile"

    VENV_LINE="export PATH=\"$VENV_DIR/bin:\$PATH\""

    if ! grep -q "$VENV_DIR" "$SHELL_RC" 2>/dev/null; then
        echo ""
        echo "📝 Adding to PATH in $SHELL_RC"
        echo "" >> "$SHELL_RC"
        echo "# Mnemosyne" >> "$SHELL_RC"
        echo "$VENV_LINE" >> "$SHELL_RC"
        echo "   Please run: source $SHELL_RC"
    fi
fi

echo ""
echo "✨ Installation complete!"
echo "   Run: mnemosyne --help"
