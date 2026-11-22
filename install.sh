#!/usr/bin/env bash
# ==============================================================================
# movie CLI - One-line Universal Installer
# Works on Linux, macOS, and Android (Termux)
# ==============================================================================

set -e

# Default repository URL (Update with your GitHub username)
GITHUB_REPO="${GITHUB_REPO:-Aashishjawalker/movie}"
BRANCH="${BRANCH:-main}"

# ANSI color codes
BOLD="\033[1m"
GREEN="\033[32m"
CYAN="\033[36m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

echo -e "${CYAN}${BOLD}"
cat << 'EOF'
  __  __  ______      _____ ______ 
 |  \/  |/ __ \ \    / /_ _|  ____|
 | \  / | |  | \ \  / / | || |__   
 | |\/| | |  | |\ \/ /  | ||  __|  
 | |  | | |__| | \  /  _| || |____ 
 |_|  |_|\____/   \/  |___|______| 
EOF
echo -e "${RESET}"
echo -e "${BOLD}Installing movie CLI...${RESET}"
echo

# 1. Check for Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] python3 is not installed.${RESET}"
    if [ -d "/data/data/com.termux" ]; then
        echo -e "On Termux, run: ${YELLOW}pkg install python${RESET}"
    elif command -v apt >/dev/null 2>&1; then
        echo -e "On Debian/Ubuntu, run: ${YELLOW}sudo apt update && sudo apt install python3${RESET}"
    elif command -v brew >/dev/null 2>&1; then
        echo -e "On macOS, run: ${YELLOW}brew install python3${RESET}"
    fi
    exit 1
fi

# 2. Determine target directories
INSTALL_DIR="${HOME}/.local/share/movie"

# Choose bin directory (prefer Termux's $PREFIX/bin if on Termux, otherwise ~/.local/bin)
if [ -n "$PREFIX" ] && [ -d "$PREFIX/bin" ] && [ -w "$PREFIX/bin" ]; then
    BIN_DIR="$PREFIX/bin"
else
    BIN_DIR="${HOME}/.local/bin"
fi

mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"

# 3. Download / update the movie source files
echo -e "${CYAN}==>${RESET} Downloading movie files from ${BOLD}${GITHUB_REPO}${RESET}..."

ARCHIVE_URL="https://github.com/${GITHUB_REPO}/archive/refs/heads/${BRANCH}.tar.gz"

TMP_DIR="$(mktemp -d 2>/dev/null || mktemp -d -t 'movie-install')"
trap 'rm -rf "$TMP_DIR"' EXIT

if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$ARCHIVE_URL" | tar -xz -C "$TMP_DIR"
elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$ARCHIVE_URL" | tar -xz -C "$TMP_DIR"
else
    echo -e "${RED}[ERROR] Neither curl nor wget was found. Please install one to continue.${RESET}"
    exit 1
fi

# Locate extracted contents (GitHub tarballs extract into <repo>-<branch>/)
EXTRACTED_DIR=$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)

if [ -z "$EXTRACTED_DIR" ] || [ ! -f "$EXTRACTED_DIR/movie.py" ]; then
    echo -e "${RED}[ERROR] Failed to extract movie source files.${RESET}"
    exit 1
fi

# Copy files into ~/.local/share/movie
rm -rf "${INSTALL_DIR:?}"/*
cp -R "$EXTRACTED_DIR"/* "$INSTALL_DIR/"

# 4. Create the executable launcher script
LAUNCHER="$BIN_DIR/movie"

cat << EOF > "$LAUNCHER"
#!/usr/bin/env bash
exec python3 "$INSTALL_DIR/movie.py" "\$@"
EOF

chmod +x "$LAUNCHER"

# 5. Check if BIN_DIR is in PATH
PATH_UPDATED=0
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    SHELL_CONFIG=""
    if [ -n "$ZSH_VERSION" ] || [ "$SHELL" = "*/zsh" ]; then
        SHELL_CONFIG="$HOME/.zshrc"
    elif [ -f "$HOME/.bashrc" ]; then
        SHELL_CONFIG="$HOME/.bashrc"
    elif [ -f "$HOME/.profile" ]; then
        SHELL_CONFIG="$HOME/.profile"
    fi

    if [ -n "$SHELL_CONFIG" ] && [ -f "$SHELL_CONFIG" ]; then
        if ! grep -q "export PATH=\"\$PATH:$BIN_DIR\"" "$SHELL_CONFIG"; then
            echo "" >> "$SHELL_CONFIG"
            echo "# movie CLI path" >> "$SHELL_CONFIG"
            echo "export PATH=\"\$PATH:$BIN_DIR\"" >> "$SHELL_CONFIG"
            PATH_UPDATED=1
        fi
    fi
fi

echo
echo -e "${GREEN}${BOLD}✓ movie installed successfully!${RESET}"
echo -e "Installed to: ${CYAN}$INSTALL_DIR${RESET}"
echo -e "Executable:   ${CYAN}$LAUNCHER${RESET}"
echo

if [ "$PATH_UPDATED" -eq 1 ]; then
    echo -e "${YELLOW}Note: Added $BIN_DIR to your PATH in $SHELL_CONFIG.${RESET}"
    echo -e "Run ${BOLD}source $SHELL_CONFIG${RESET} or restart your terminal."
    echo
fi

echo -e "To start, simply type:"
echo -e "  ${GREEN}${BOLD}movie${RESET}"
echo
