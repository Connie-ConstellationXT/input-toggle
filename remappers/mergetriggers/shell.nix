{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  buildInputs = with pkgs; [
    python3
    python3Packages.pip
    python3Packages.virtualenv
    linuxHeaders
    libevdev
    pkg-config
    gcc
  ];

  shellHook = ''
    echo "Setting up Python development environment with evdev support..."
    
    # Set up environment variables for compilation
    export PKG_CONFIG_PATH="${pkgs.libevdev}/lib/pkgconfig:$PKG_CONFIG_PATH"
    export C_INCLUDE_PATH="${pkgs.linuxHeaders}/include:${pkgs.libevdev}/include:$C_INCLUDE_PATH"
    export LIBRARY_PATH="${pkgs.libevdev}/lib:$LIBRARY_PATH"
    
    # Create and activate venv if it doesn't exist
    if [ ! -d "venv" ]; then
      echo "Creating virtual environment..."
      python3 -m venv venv
    fi
    
    echo "Activating virtual environment..."
    source venv/bin/activate
    
    echo "Installing evdev..."
    pip install evdev
    
    echo "Development environment ready!"
    echo "You can now run: sudo ./gamepad_daemon.py"
  '';
}