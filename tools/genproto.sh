#!/usr/bin/env bash
# Regenerate the protobuf bindings for the INFO frame (frame type 1).
#
# Both outputs are committed:
#   extra_metadata_pb2.py   the runtime bindings
#   extra_metadata_pb2.pyi  type stubs
#
# The stub is not cosmetic. protobuf 7.x builds message classes at runtime via
# _builder, so ExtraMetadata does not appear in the .py at all; the stub is the
# only reason pyright (and Pylance) can resolve it and its fields. Re-run this
# whenever extra_metadata.proto changes, and commit both files together.
#
# Uses grpcio-tools, so no Docker and no protoc on PATH. Install it with
#   pip install -e '.[proto]'
# It is kept out of the dev extra: the bindings are committed, so a normal
# change never needs this large a download.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG="$REPO_ROOT/src/insvtools"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"

"$PYTHON" -m grpc_tools.protoc \
    --proto_path="$PKG" \
    --python_out="$PKG" \
    --pyi_out="$PKG" \
    "$PKG/extra_metadata.proto"

echo "regenerated: extra_metadata_pb2.py extra_metadata_pb2.pyi"
