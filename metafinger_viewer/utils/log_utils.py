#!/usr/bin/env python3

"""
Utility functions for logging in the Metafinger Viewer.
"""

import trimesh
import numpy as np
import rerun as rr
from rerun.blueprint import (
    Blueprint,
    Horizontal,
    Vertical,
    Spatial3DView,
    TimeSeriesView,
    SelectionPanel,
    TimePanel,
    Spatial2DView,
)


def log_asset(
    log_path: str,
    file_path: str,
    translation: np.ndarray = np.zeros(3),
    mat3x3: np.ndarray = np.eye(3),
    scale: float = 0.001,
) -> None:
    """
    Log the asset, including .gltf, .glb, .obj, .stl, etc.

    Args:
        log_path (str): Path to the log directory.
        file_path (str): Path to the asset file.
        translation (numpy.ndarray, optional): Translation vector for the asset. Default is a zero vector.
        mat3x3 (numpy.ndarray, optional): 3x3 rotation matrix for the asset. Default is an identity matrix.
        scale (float, optional): Scale factor for the asset. Default is 0.001.
    """

    if file_path.endswith((".gltf", ".glb", ".obj", ".stl")):
        rr.log(log_path, rr.Asset3D(path=file_path))
        rr.log(
            log_path,
            rr.Transform3D(
                translation=translation,
                mat3x3=mat3x3,
                scale=scale,
            ),
        )
    else:
        raise ValueError(f"Unsupported asset file type: {file_path}")


def log_camera(imgs: dict) -> None:
    """
    Log the camera images.

    Args:
        imgs (dict): Dictionary of camera images.
    """

    for cam in imgs.keys():
        img = imgs[cam]
        if img is not None:
            rr.log(
                f"{cam}/camera/color",
                rr.EncodedImage(contents=img, media_type="image/jpeg"),
            )


def log_metafinger(
    name: str,
    def_node: np.ndarray,
    metafinger_mesh: trimesh.Trimesh,
    metafinger_node_num: int,
    metafinger_def_node: np.ndarray,
    metafinger_colormap: list[tuple[float, float, float, float]],
    cmin: float = 0.0,
    cmax: float = 12.0,
) -> None:
    """
    Log the metafinger mesh.

    Args:
        name (str): Name of the metafinger.
        def_node (numpy.ndarray): Deform node positions.
        metafinger_mesh (trimesh.Trimesh): Metafinger mesh.
        metafinger_node_num (int): Number of nodes in the metafinger.
        metafinger_def_node (numpy.ndarray): Indices of the deform nodes.
        metafinger_colormap (list[tuple[float, float, float, float]]): Colormap for the metafinger.
        cmin (float, optional): Minimum value for colormap normalization. Default is 0.0.
        cmax (float, optional): Maximum value for colormap normalization. Default is 12.0.
    """

    node = np.zeros([metafinger_node_num, 3])
    def_node = def_node.reshape(-1, 3)
    if def_node.shape[0] == len(metafinger_def_node):
        node[metafinger_def_node - 1] += def_node

    rr.log(
        f"{name}/mesh",
        rr.Mesh3D(
            vertex_positions=(metafinger_mesh.vertices + node),
            triangle_indices=metafinger_mesh.faces,
            vertex_colors=[
                metafinger_colormap[i]
                for i in (
                    (np.clip(np.linalg.norm(node, axis=1), cmin, cmax) - cmin)
                    / (cmax - cmin)
                    * (len(metafinger_colormap) - 1)
                )
                .astype(int)
                .tolist()
            ],
        ),
    )


def log_state_dict(state_dict: dict[str, np.ndarray]) -> None:
    """
    Log the state dictionary.

    Args:
        state_dict (dict[str, numpy.ndarray]): Dictionary of states.
    """

    # Log the state dictionary
    for key, val in state_dict.items():
        if type(val) is np.ndarray:
            # Check if the array has a shape attribute and it's not empty
            if hasattr(val, "shape") and len(val.shape) > 0:
                # Log the vector
                for i in range(val.shape[0]):
                    rr.log(f"/{key}/{i}", rr.Scalar(val[i]))
            else:
                # Handle scalar numpy arrays
                rr.log(f"/{key}", rr.Scalar(float(val)))
        else:
            # Log the scalar
            rr.log(f"/{key}", rr.Scalar(float(val)))


def gen_blueprint() -> Blueprint:
    """
    Generate the blueprint for the viewer.

    Returns:
        blueprint (rerun.blueprint.Blueprint): The generated blueprint for the viewer.
    """

    return Blueprint(
        Horizontal(
            Vertical(
                Spatial3DView(name="3D Scene", origin="/", contents=["/**"]),
                Spatial2DView(
                    name="Metafinger Camera",
                    origin="/metafinger/camera/color",
                ),
                row_shares=[2, 1],
            ),
            Horizontal(
                Vertical(
                    *(TimeSeriesView(origin=f"/metafinger/pose/{i}") for i in range(6)),
                    name="pose",
                ),
                Vertical(
                    *(TimeSeriesView(origin=f"/metafinger/force/{i}") for i in range(6)),
                    name="force",
                ),
                column_shares=[1, 1],
            ),
            column_shares=[1, 1],
        ),
        SelectionPanel(state="hidden"),
        TimePanel(state="collapsed"),
    )
