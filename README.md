# Meta-Finger Viewer

[![License](https://img.shields.io/badge/license-MIT-black?style=flat-square)](LICENSE) [![Python](https://img.shields.io/badge/python-≥3.10-3776AB?style=flat-square&logo=python)](https://www.python.org) [![Rerun](https://img.shields.io/badge/rerun-0.20.0-blue?style=flat-square)](https://rerun.io)

This is a viewer example for the [Meta-Finger](https://github.com/han-xudong/meta-finger). The viewer visualizes streams of multimodal data, including 3D scene of mesh, captured image, detected pose of marker, and estimated force.

![Viewer](assets/viewer.jpg)

## Quick Start

Clone the latest repository and install the dependencies:

```bash
git clone https://github.com/han-xudong/meta-finger-viewer.git
cd meta-finger-viewer
pip install -r requirements.txt
```

Run the viewer:

```bash
python server.py
```

## License

This project is licensed under the MIT License (see [LICENSE](LICENSE) for details).

## Acknowledgments

- [rerun](https://rerun.io): Visualize streams of multimodal data.
- [ZeroMQ](https://zeromq.org): Communication between the viewer and the Meta-Finger.
- [ProtoBuf](https://developers.google.com/protocol-buffers): Define the message format for the communication.
