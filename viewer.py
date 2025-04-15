#!/usr/bin/env python3

import sys
import os
import argparse
import time
import yaml
import trimesh
import cv2
import numpy as np
import matplotlib as mpl
from pynput import keyboard
from multiprocessing import Process
import rerun as rr
from rerun.blueprint import (
    Blueprint,
    Horizontal,
    Vertical,
    Spatial3DView,
    Spatial2DView,
    TimeSeriesView,
    SelectionPanel,
    TimePanel,
)
from modules.zmq.finger import FingerSubscriber

global stop_flag
stop_flag = False


def on_press(key):
    global stop_flag
    if key == keyboard.Key.esc:
        stop_flag = True
        return False


class FingerVis:
    def __init__(self, camera_params: dict, finger_params: dict) -> None:
        """Initialize the FingerVis class.
        
        Args:
            camera_params (dict): Camera parameters.
            finger_params (dict): Finger parameters.
        """
        
        # Set the camera parameters
        self.camera_params = camera_params
        
        # Set the finger parameters
        self.finger_params = finger_params

        # Initialize the finger mesh
        finger_vertices = np.loadtxt("./modules/finger/surf_coor.txt", delimiter=",")
        finger_faces = (
            np.loadtxt("./modules/finger/surf_tri.txt", delimiter=",").astype(int) - 1
        )
        self.finger_mesh = trimesh.Trimesh(vertices=finger_vertices, faces=finger_faces)
        self.finger_node_num = len(self.finger_mesh.vertices)
        self.finger_def_node = np.loadtxt("./modules/finger/def_node.txt", dtype=int)
        self.finger_colormap = mpl.colormaps["viridis"].colors
        
        # Log the finger mesh
        self.log_finger(name="finger", def_node=np.zeros([len(self.finger_def_node), 3]))

    def log_camera(self, imgs: dict) -> None:
        """Log the camera images.
        
        Args:
            imgs (dict): Dictionary of camera images.
        """
        
        cam_list = imgs.keys()
        for cam in cam_list:
            img = imgs[cam]
            if img is not None:
                rr.log(f"{cam}/camera/color", rr.EncodedImage(contents=img, media_type="image/jpeg"))

    def log_finger(
        self,
        name: str,
        def_node: np.ndarray,
        cmin: float = 0.0,
        cmax: float = 10.0,
    ) -> None:
        """Log the finger mesh.
        
        Args:
            node (np.ndarray): Node positions.
            name (str): Name of the mesh.
            cmin (float): Minimum color value.
            cmax (float): Maximum color value.
        """
        
        node = np.zeros([self.finger_node_num, 3])
        node[self.finger_def_node - 1] += def_node.reshape(-1, 3)
        
        rr.log(
            f"{name}/mesh",
            rr.Mesh3D(
                vertex_positions=self.finger_mesh.vertices + node,
                triangle_indices=self.finger_mesh.faces,
                vertex_colors=[
                    self.finger_colormap[i]
                    for i in (
                        (np.clip(np.linalg.norm(node, axis=1), cmin, cmax) - cmin)
                        / (cmax - cmin)
                        * (len(self.finger_colormap) - 1)
                    )
                    .astype(int)
                    .tolist()
                ],
            ),
        )

    def log_state_dict(self, state_dict: dict[str, np.ndarray]) -> None:
        """Log the state dictionary.
        
        Args:
            state_dict (dict): Dictionary of states.
        """
        
        for key, val in state_dict.items():
            for i in range(val.shape[0]):
                rr.log(f"/{key}/{i}", rr.Scalar(val[i]))

    def run(self) -> None:
        """Run the viewer in real-time mode."""
        
        # Create a FingerSubscriber
        finger_subscriber = FingerSubscriber(ip=self.finger_params["ip"], port=self.finger_params["port"])
        
        # Initialize variables
        count = 0
        start_time = time.time()
        
        # Run the viewer
        try:
            global stop_flag
            while True:
                # Receive the message
                img_bytes, pose, force, node = finger_subscriber.sub_msg()
                # Log the finger mesh
                self.log_finger(name="finger", def_node=node)
                # Log the camera images
                self.log_camera(
                    imgs={"finger": np.frombuffer(img_bytes, dtype=np.uint8)}
                )
                # Log the state dictionary
                self.log_state_dict(
                    state_dict={"finger/pose": pose, "finger/force": force}
                )
                
                count += 1
                
                # Print the FPS
                if count == 60:
                    print(f"FPS: {count / (time.time() - start_time):.2f}, Press Ctrl+C to exit.")
                    count = 0
                    start_time = time.time()
                    
                if stop_flag == 1:
                    break
                
        except KeyboardInterrupt:
            print("Stopping the viewer...")
            stop_flag = 1
        finally:
            # Close the subscriber
            finger_subscriber.close()
            sys.exit(0)

    def log(
        self,
        time_list: np.ndarray,
        pose_list: np.ndarray,
        img_list: list[np.ndarray],
    ) -> None:
        """Log the data.
        
        Args:
            time_list (np.ndarray): List of time values.
            pose_list (np.ndarray): List of pose values.
            img_list (list[np.ndarray]): List of images.
        """
        
        # Initialize variables
        start_time = time.time()
        frame = 0
        
        # Run the logging
        while True:
            # Check if the frame is within the time list
            if (time.time() - start_time) > time_list[frame]:
                # Log the finger mesh

                # Log the camera images
                self.log_camera(
                    imgs={cam: img_list[frame] for cam in self.camera_params},
                )
                # Log the state dictionary
                self.log_state_dict(
                    pose=pose_list[frame],
                )

                # Increment the frame
                frame += 1
                # Check if the end of the time list is reached
                if frame == len(time_list):
                    break

    def blueprint(self):
        """Create the blueprint for the viewer."""
        
        return Blueprint(
            Horizontal(
                Vertical(
                    Spatial3DView(name="3D Scene", origin="/", contents=["/**"]),
                    Spatial2DView(
                        name="Finger Camera",
                        origin="/finger/camera/color",
                    ),
                    row_shares=[2, 1],
                ),
                Horizontal(
                    Vertical(
                        *(
                            TimeSeriesView(origin=f"/finger/pose/{i}")
                            for i in range(6)
                        ),
                        name="pose",
                    ),
                    Vertical(
                        *(
                            TimeSeriesView(origin=f"/finger/force/{i}")
                            for i in range(6)
                        ),
                        name="force",
                    ),
                    column_shares=[1, 1],
                ),
                column_shares=[1, 1],
            ),
            SelectionPanel(state="hidden"),
            TimePanel(state="collapsed"),
        )

def rerun_server(
    camera_params: dict,
    finger_params: dict,
):
    """Run the rerun server.
    
    Args:
        camera_params (dict): Camera parameters.
        finger_params (dict): Finger parameters.
    """
    
    # Initialize the rerun server
    rr.init("Finger Viewer", spawn=True)
    
    # Initialize the FingerVis
    finger_vis = FingerVis(camera_params, finger_params)
    
    # Send the blueprint
    rr.send_blueprint(finger_vis.blueprint())
    
    # Run the FingerVis
    finger_vis.run()


def rerun_log(
    camera_params: dict,
    data_path: str,
):
    print("Logging Data...")
    time_list = np.loadtxt(os.path.join(data_path, "time.csv"), delimiter=",")
    pose_list = np.loadtxt(os.path.join(data_path, "pose.csv"), delimiter=",")
    img_path = os.path.join(data_path, "img")
    img_list = [
        cv2.cvtColor(
            cv2.imread(os.path.join(img_path, f"{i}.jpg")),
            cv2.COLOR_BGR2RGB,
        )
        for i in len(time_list.shape)
    ]

    rr.init("Finger Interface", spawn=True)

    finger_vis = FingerVis(camera_params=camera_params)

    rr.send_blueprint(finger_vis.blueprint())


    finger_vis.log(
        time_list=time_list,
        pose_list=pose_list,
        img_list=img_list,
    )

def main(
    mode: str = "real-time",
    data_path: str = "",
) -> None:
    
    with open("./config/camera.yaml", "r") as f:
        camera_params = yaml.load(f.read(), Loader=yaml.Loader)
        
    with open("./config/finger.yaml", "r") as f:
        finger_params = yaml.load(f.read(), Loader=yaml.FullLoader)

    if mode == "real-time":

        rerun_process = Process(
            target=rerun_server,
            args=(
                camera_params,
                finger_params
            ),
        )
        rerun_process.daemon = True
        rerun_process.start()

        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()

        global stop_flag
        try:
            while True:
                if stop_flag == 1:
                    break
        except KeyboardInterrupt:
            print("Stopping the viewer...")
            stop_flag = 1
            listener.stop()
            rerun_process.terminate()
            sys.exit(0)
        finally:
            listener.stop()
            rerun_process.terminate()
            sys.exit(0)

    elif mode == "log-data":
        data_path = os.path.join("./data/", data_path)
        rerun_log(
            camera_params=camera_params,
            data_path=data_path,
        )
    else:
        raise ValueError("\033[91mINVALID MODE\033[0m")


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-m", "--mode", default="real-time", type=str, help="set the mode of interface"
    )
    parser.add_argument(
        "-d", "--data_path", default="", type=str, help="select the data to replay"
    )

    args = parser.parse_args()

    main(mode=args.mode, data_path=args.data_path)
