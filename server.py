#!/usr/bin/env python3

import os
import argparse
import time
import yaml
import trimesh
import zmq
import cv2
import numpy as np
import matplotlib as mpl
from pynput import keyboard
from scipy.spatial.transform import Rotation
from modules import finger_msg_pb2
from common import (
    blueprint_row_images,
    cam_intr_to_mat,
)
from multiprocessing import Process
import rerun as rr

global stop_flag
stop_flag = False


def on_press(key):
    global stop_flag
    if key == keyboard.Key.esc:
        stop_flag = True
        return False


class FingerSubscriber:
    def __init__(self, address: str) -> None:
        self.context = zmq.Context()
        self.subscriber = self.context.socket(zmq.SUB)
        self.subscriber.connect("tcp://" + address)
        self.subscriber.setsockopt_string(zmq.SUBSCRIBE, "")
        self.timestamp = 0
        self.img = None
        self.pose = np.zeros(6)
        self.force = np.zeros(6)
        self.node = None

    def rec_msg(self):
        finger = finger_msg_pb2.Finger()
        finger.ParseFromString(self.subscriber.recv())

        self.timestamp = finger.timestamp
        self.img = cv2.cvtColor(
            cv2.imdecode(np.frombuffer(finger.img, np.uint8), cv2.IMREAD_COLOR),
            cv2.COLOR_BGR2RGB,
        )
        self.pose = np.array(finger.pose).flatten()
        self.force = np.array(finger.force).flatten()
        self.node = np.array(finger.node).flatten()


class FingerVis:
    def __init__(self, cam_dict: dict[str, dict[str, str]]):
        self.prev_joint_origins = None
        self.cam_dict = cam_dict

        finger_vertices = np.loadtxt("./modules/finger/surf_coor.txt", delimiter=",")
        finger_faces = (
            np.loadtxt("./modules/finger/surf_tri.txt", delimiter=",").astype(int) - 1
        )
        self.finger_mesh = trimesh.Trimesh(vertices=finger_vertices, faces=finger_faces)
        self.finger_node_num = len(self.finger_mesh.vertices)
        self.finger_def_node = np.loadtxt("./modules/finger/def_node.txt", dtype=int)
        self.finger_colormap = mpl.colormaps["viridis"].colors

        self.log_finger(np.zeros([self.finger_node_num, 3]), "finger")

    def log_camera(
        self,
        imgs: dict[str, np.ndarray],
    ):
        cam_list = imgs.keys()
        for cam in cam_list:
            img = imgs[cam]
            if img is not None:
                rr.log(f"{cam}/camera/color", rr.EncodedImage(contents=img, media_type="image/jpeg"))

    def log_finger(
        self,
        node: np.ndarray,
        name: str,
        cmin: float = 0.0,
        cmax: float = 10.0,
    ):
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

    def log_action_dict(
        self,
        action_dict: dict[str, np.ndarray] = {},
    ):
        for key, val in action_dict.items():
            for i in range(val.shape[0]):
                rr.log(f"/{key}/{i}", rr.Scalar(val[i]))

    def run(
        self,
    ):
        with open("./config/address.yaml", "r") as f:
            address = yaml.load(f.read(), Loader=yaml.FullLoader)

        subscriber = FingerSubscriber(
            address=str(address["ip"] + ":" + str(address["port"]))
        )
        while True:
            subscriber.rec_msg()
            pose = subscriber.pose
            img = subscriber.img
            force = subscriber.force
            node = np.zeros([self.finger_node_num, 3])
            node[self.finger_def_node - 1] += subscriber.node.reshape(-1, 3)
            self.log_finger(node, "finger")
            self.log_camera(
                imgs={"finger": img},
            )
            self.log_action_dict(
                action_dict={"finger/pose": pose, "finger/force": force}
            )

    def log(
        self,
        time_list,
        pose_list,
        img_list,
    ):
        intrinsics = {
            cam: cam_intr_to_mat(self.cam_dict[cam]["intrinsics"])
            for cam in self.cam_dict.keys()
        }

        start_time = time.time()
        frame = 0
        while True:
            if (time.time() - start_time) > time_list[frame]:
                self.log_camera(
                    imgs={cam: img_list[frame] for cam in self.cam_dict},
                )
                self.log_action_dict(
                    pose=pose_list[frame],
                )

                frame += 1

                if frame == len(time_list):
                    return

    def blueprint(self):
        from rerun.blueprint import (
            Blueprint,
            Horizontal,
            Vertical,
            Spatial3DView,
            TimeSeriesView,
            Tabs,
            SelectionPanel,
            TimePanel,
        )

        return Blueprint(
            Horizontal(
                Vertical(
                    Spatial3DView(name="3D Scene", origin="/", contents=["/**"]),
                    blueprint_row_images(["/finger/camera/color"]),
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


def rerun_log(
    cam_dict: dict,
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

    finger_vis = FingerVis(cam_dict=cam_dict)

    rr.send_blueprint(finger_vis.blueprint())


    finger_vis.log(
        time_list=time_list,
        pose_list=pose_list,
        img_list=img_list,
    )


def rerun_server(
    cam_dict: dict,
):
    rr.init("Robot Interface", spawn=True)
    finger_vis = FingerVis(cam_dict=cam_dict)
    rr.send_blueprint(finger_vis.blueprint())

    finger_vis.run()


def main(
    mode: str = "real-time",
    data_path: str = "",
) -> None:
    print("\033[91mPRESS ESC TO EXIT\033[0m")

    cam_dict = yaml.load(open("./config/camera.yaml"), Loader=yaml.FullLoader)

    if mode == "real-time":

        rerun_process = Process(
            target=rerun_server,
            args=(
                cam_dict,
            ),
        )
        rerun_process.daemon = True
        rerun_process.start()

        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()

        global stop_flag
        while True:
            if stop_flag == 1:
                return

    elif mode == "log-data":
        data_path = os.path.join("./data/", data_path)
        rerun_log(
            cam_dict=cam_dict,
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

    main(robot=args.robot, mode=args.mode, data_path=args.data_path)
