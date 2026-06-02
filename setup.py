from setuptools import setup
from setuptools.command.build_py import build_py
from pathlib import Path
import subprocess
import sys

class BuildPyWithProtobuf(build_py):
    def run(self):
        proto_dir = Path(__file__).parent / "metafinger_viewer" / "modules" / "protobuf"
        proto_files = list(proto_dir.glob("*.proto"))

        if proto_files:
            print("Compiling protobuf files...")
            for proto in proto_files:
                subprocess.check_call([
                    sys.executable,
                    "-m",
                    "grpc_tools.protoc",
                    f"-I{proto_dir}",
                    f"--python_out={proto_dir}",
                    str(proto),
                ])
        else:
            assert False, "No .proto files found to compile."

        super().run()

setup(
    cmdclass={
        "build_py": BuildPyWithProtobuf,
    }
)