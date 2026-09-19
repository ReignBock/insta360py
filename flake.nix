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

            uv -q sync --extra dev
            source .venv/bin/activate
          '';
        };
      }
    );
}
