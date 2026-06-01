#!/usr/bin/env python3

"""
Utility functions for processing in the Metafinger Viewer.
"""

import os
import time
import trimesh
import numpy as np
import matplotlib.pyplot as plt
import rerun as rr
from multiprocessing import Queue, Value
from metafinger_viewer.modules.zmq import MetafingerSubscriber
from metafinger_viewer.utils.log_utils import log_camera, log_metafinger, log_state_dict, log_asset
from metafinger_viewer.utils.data_utils import parse_data


class MetafingerVis:
    """
    MetafingerVis class.
    
    This class is responsible for visualizing the Metafinger in live or replay mode.
    It initializes the Metafinger mesh and logs the data received from the ZMQ subscriber.
    
    Attributes:
        log_time (float): Time tracking for logging.
        metafinger_mesh (trimesh.Trimesh): The 3D mesh of the metafinger.
        metafinger_node_num (int): Number of nodes in the metafinger mesh.
        metafinger_def_node (numpy.ndarray): The deformable nodes of the metafinger.
        metafinger_colormap (list[tuple[float, float, float, float]]): Colormap for the metafinger.
        metafinger_cmin (float): Minimum value for colormap normalization.
        metafinger_cmax (float): Maximum value for colormap normalization.
    """
    
    def __init__(self) -> None:
        """
        Initialize the MetafingerVis class.
        """

        # Initialize time tracking for logging
        self.log_time = 0.0

        # Define templates directory
        templates_dir = os.path.join("templates")

        # Load the metafinger mesh from files
        metafinger_mesh_dir = os.path.join(templates_dir, "metafinger")
        if not os.path.exists(metafinger_mesh_dir):
            raise FileNotFoundError(
                f"Assets directory {metafinger_mesh_dir} does not exist."
            )
        surf_coor_path = os.path.join(metafinger_mesh_dir, "surface_coordinate.txt")
        metafinger_vertices = np.loadtxt(surf_coor_path, delimiter=",")
        surf_tri_path = os.path.join(metafinger_mesh_dir, "surface_triangle.txt")
        metafinger_faces = np.loadtxt(surf_tri_path, delimiter=",").astype(int) - 1
        self.metafinger_mesh = trimesh.Trimesh(
            vertices=metafinger_vertices, faces=metafinger_faces
        )
        self.metafinger_node_num = len(self.metafinger_mesh.vertices)
        self.metafinger_def_node = np.loadtxt(
            os.path.join(metafinger_mesh_dir, "deform_node.txt"), dtype=int
        )
        self.metafinger_colormap = [plt.get_cmap("viridis")(i / 255) for i in range(256)]
        self.metafinger_cmin = 0.0
        self.metafinger_cmax = 10.0

        # Log the metafinger base
        metafinger_base_dir = os.path.join(templates_dir, "metafinger_base")
        if not os.path.exists(metafinger_base_dir):
            raise FileNotFoundError(
                f"Assets directory {metafinger_base_dir} does not exist."
            )
        log_asset(
            log_path="metafinger_base",
            file_path=os.path.join(metafinger_base_dir, "metafinger_base.obj"),
            translation=np.array([0, 0, -30]),
            mat3x3=np.array(
                [
                    [-1, 0, 0],
                    [0, 0, 1],
                    [0, 1, 0],
                ]
            ),
            scale=10.0,
        )

        # Log the metafinger mesh
        log_metafinger(
            "metafinger",
            np.zeros([len(self.metafinger_def_node), 3]),
            self.metafinger_mesh,
            self.metafinger_node_num,
            self.metafinger_def_node,
            self.metafinger_colormap,
            self.metafinger_cmin,
            self.metafinger_cmax,
        )

    def run(
        self,
        zmq_queue: Queue,
        recording_queue: Queue,
        is_recording,
        start_time,
    ) -> None:
        """
        Run the viewer in live mode.

        Args:
            zmq_queue (multiprocessing.Queue): The queue for receiving the data.
            recording_queue (multiprocessing.Queue): The queue for recording the data.
            is_recording (multiprocessing.Value): A multiprocessing Value indicating whether recording is active.
            start_time (multiprocessing.Value): A multiprocessing Value to store the start time of the recording.

        Raises:
            KeyboardInterrupt: If Ctrl+C is pressed, the viewer will terminate.
            Exception: If any other error occurs, it will be printed and the viewer will terminate.
        """

        # Run the viewer
        try:
            while True:
                if not zmq_queue.empty():
                    # Receive the data from the queue
                    metafinger_data = zmq_queue.get()

                    # Log the metafinger mesh
                    metafinger_node = metafinger_data["node"]
                    log_metafinger(
                        "metafinger",
                        metafinger_node,
                        self.metafinger_mesh,
                        self.metafinger_node_num,
                        self.metafinger_def_node,
                        self.metafinger_colormap,
                        self.metafinger_cmin,
                        self.metafinger_cmax,
                    )

                    # Log the camera images
                    log_camera(
                        imgs={
                            "metafinger": np.frombuffer(
                                metafinger_data["img"], dtype=np.uint8
                            )
                        }
                    )

                    # Log the state dictionary
                    log_state_dict(
                        state_dict={
                            "metafinger/pose": metafinger_data["pose"],
                            "metafinger/force": metafinger_data["force"],
                        }
                    )

                    # Put the data into the recording queue
                    if is_recording.value == 1:
                        recording_queue.put(
                            {
                                "time": time.time() - start_time.value,
                                **metafinger_data,
                            }
                        )
        except KeyboardInterrupt:
            print("\nCtrl+C detected. Terminating viewer...")
            return
        except Exception as e:
            print(f"An error occurred: {e}")
            return

    def log(
        self,
        data: dict,
        start_time,
    ) -> None:
        """
        Log the data for the replay mode.

        Args:
            data (dict): The data to be logged.
            start_time (multiprocessing.Value): A multiprocessing Value to store the start time of the recording.
        """

        # Log the data from the replay mode
        frame = 0
        while True:
            if (time.time() - start_time.value) > data["time"][frame]:
                # Log the state dictionary
                log_state_dict(
                    state_dict={
                        "metafinger/pose": data["pose"][frame],
                        "metafinger/force": data["force"][frame],
                    }
                )

                # Log the metafinger mesh
                metafinger_node = data["node"][frame]
                log_metafinger(
                    "metafinger",
                    metafinger_node,
                    self.metafinger_mesh,
                    self.metafinger_node_num,
                    self.metafinger_def_node,
                    self.metafinger_colormap,
                    self.metafinger_cmin,
                    self.metafinger_cmax,
                )

                # Log the camera images
                log_camera(
                    imgs={
                        "metafinger": data["img"][frame],
                    }
                )

                # Increment the frame
                frame += 1

                # Check if the frame is the last one
                if frame == len(data["time"]):
                    return


@rr.shutdown_at_exit
def rerun_server(
    blueprint,
    zmq_queue: Queue,
    recording_queue: Queue,
    is_recording,
    start_time,
) -> None:
    """
    Run the rerun server.

    Args:
        blueprint (rerun.blueprint.Blueprint): The blueprint for the rerun server.
        zmq_queue (multiprocessing.Queue): The queue for receiving the data.
        recording_queue (multiprocessing.Queue): The queue for recording the data.
        is_recording (multiprocessing.Value): A multiprocessing Value indicating whether recording is active.
        start_time (multiprocessing.Value): A multiprocessing Value to store the start time of the recording.
    """

    # Initialize the rerun server
    rr.init("Metafinger Viewer")
    rr.connect_tcp()
    rr.send_blueprint(blueprint)

    # Initialize the MetafingerVis
    metafinger_vis = MetafingerVis()

    # Run the MetafingerVis
    metafinger_vis.run(zmq_queue, recording_queue, is_recording, start_time)


@rr.shutdown_at_exit
def rerun_log(
    blueprint,
    data: dict,
    init_ready,
) -> None:
    """
    Run the rerun log.

    Args:
        blueprint (rerun.blueprint.Blueprint): The blueprint for the rerun log.
        data (dict): The data to be logged.
        init_ready (multiprocessing.Array): A multiprocessing Array to indicate that the rerun server is ready.
    """

    # Initialize the rerun server
    rr.init("Metafinger Viewer")
    rr.connect_tcp()
    rr.send_blueprint(blueprint)

    metafinger_vis = MetafingerVis()

    # Wait for the initialization
    for i in range(len(init_ready)):
        if init_ready[i] == 0:
            init_ready[i] = 1
            break
    while sum(init_ready) != len(init_ready):
        time.sleep(0.01)

    # Set start time
    start_time = Value("d", time.time())

    # Log the data
    metafinger_vis.log(data, start_time)


def zmq_subscriber(host: str, port: int, queue: Queue) -> None:
    """
    Start the ZMQ process.

    Args:
        host (str): The host address for the ZMQ subscriber.
        port (int): The port number for the ZMQ subscriber.
        queue (multiprocessing.Queue): The queue to put the received data into.
    """

    # Initialize the MetafingerSubscriber
    subscriber = MetafingerSubscriber(host, port)

    # Start the ZMQ subscriber
    start = time.time()
    count = 0
    try:
        while True:
            # Subscribe to the message
            metafinger_msg = subscriber.subscribeMessage()

            # Put the data into the queue
            queue.put(parse_data(metafinger_msg))

            count += 1
            if count == 60:
                print(f"FPS: {60 / (time.time() - start):.2f}, Press Ctrl+C to exit.")
                start = time.time()
                count = 0
    except KeyboardInterrupt:
        print("\nCtrl+C detected. Terminating ZMQ subscriber...")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        subscriber.close()
        return
