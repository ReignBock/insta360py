{
  description = "insta360py development environment";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };

        # PySide6 wheels expect these on the loader path, which NixOS does not
        # provide. The last group is for the window itself: wayland for the
        # Wayland platform plugin (WSLg), the xcb libraries for the X11 fallback.
        qtLibs = with pkgs; [
          stdenv.cc.cc.lib
          zlib
          glib
          libGL
          libxkbcommon
          fontconfig
          freetype
          dbus
          zstd
          libx11

          wayland
          libxcb
          libxcb-cursor
          libxcb-util
          libxcb-image
          libxcb-keysyms
          libxcb-render-util
          libxcb-wm
        ];
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            uv
            git
            ffmpeg
            nodejs
            python313
          ];

          shellHook = ''
            export UV_PYTHON="${pkgs.python313}/bin/python3.13"

            ${pkgs.lib.optionalString pkgs.stdenv.isLinux ''export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath qtLibs}:$LD_LIBRARY_PATH"''}

            uv -q sync --extra dev
            source .venv/bin/activate
          '';
        };
      }
    );
}
