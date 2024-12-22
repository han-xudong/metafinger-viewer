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
from rerun_loader_urdf import URDFLogger
from scipy.spatial.transform import Rotation
from modules import finger_msg_pb2, robot_msg_pb2
from common import (
    log_angle_rot,
    blueprint_row_images,
    link_to_world_transform,
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
        self.subscriber.connect(address)
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


class RobotSubscriber:
    def __init__(self, address: str) -> None:
        self.context = zmq.Context()
        self.subscriber = self.context.socket(zmq.SUB)
        self.subscriber.connect(address)
        self.subscriber.setsockopt_string(zmq.SUBSCRIBE, "")
        self.timestamp = 0
        self.joint_angles = np.zeros(6)
        self.img_1 = None
        self.pose_1 = np.zeros(6)
        self.force_1 = np.zeros(6)
        self.node_1 = None
        self.img_2 = None
        self.pose_2 = np.zeros(6)
        self.force_2 = np.zeros(6)
        self.node_2 = None

    def receive_message(self):
        robot = robot_msg_pb2.Robot()
        robot.ParseFromString(self.subscriber.recv())

        self.timestamp = robot.timestamp
        self.joint_angles = np.array(robot.joint_angles).flatten()
        self.img_1 = cv2.cvtColor(
            cv2.imdecode(np.frombuffer(robot.img_1, np.uint8), cv2.IMREAD_COLOR),
            cv2.COLOR_BGR2RGB,
        )
        self.pose_1 = np.array(robot.pose_1).flatten()
        self.force_1 = np.array(robot.force_1).flatten()
        self.node_1 = np.array(robot.node_1).flatten()
        self.img_2 = cv2.cvtColor(
            cv2.imdecode(np.frombuffer(robot.img_2, np.uint8), cv2.IMREAD_COLOR),
            cv2.COLOR_BGR2RGB,
        )
        self.pose_2 = np.array(robot.pose_2).flatten()
        self.force_2 = np.array(robot.force_2).flatten()
        self.node_2 = np.array(robot.node_2).flatten()


class RobotVis:
    def __init__(self, cam_dict: dict[str, dict[str, str]], robot: str = "finger"):
        self.prev_joint_origins = None
        self.cam_dict = cam_dict
        self.robot = robot

        finger_vertices = np.loadtxt("./modules/finger/surf_coor.txt", delimiter=",")
        finger_faces = (
            np.loadtxt("./modules/finger/surf_tri.txt", delimiter=",").astype(int) - 1
        )
        self.finger_mesh = trimesh.Trimesh(vertices=finger_vertices, faces=finger_faces)
        self.finger_node_num = len(self.finger_mesh.vertices)
        self.finger_def_node = np.loadtxt("./modules/finger/def_node.txt", dtype=int)
        self.finger_colormap = mpl.colormaps["viridis"].colors

        if robot == "finger":
            self.log_finger(np.zeros([self.finger_node_num, 3]), "finger")
        else:
            self.log_finger(np.zeros([self.finger_node_num, 3]), "left_finger")
            self.log_finger(np.zeros([self.finger_node_num, 3]), "right_finger")

    def log_robot_states(
        self,
        joint_angles: np.ndarray,
        entity_to_transform: dict[str, tuple[np.ndarray, np.ndarray]],
    ):
        joint_origins = []
        for joint_idx, angle in enumerate(joint_angles):
            transform = link_to_world_transform(
                entity_to_transform, joint_angles, joint_idx + 1
            )
            joint_org = (transform @ np.array([0.0, 0.0, 0.0, 1.0]))[:3]
            joint_origins.append(joint_org)

            log_angle_rot(entity_to_transform, joint_idx + 1, angle)

        self.prev_joint_origins = joint_origins

    def log_camera(
        self,
        imgs: dict[str, np.ndarray],
        color_position: dict[str, np.ndarray] = {},
        intrinsics: dict[str, np.ndarray] = {},
    ):
        cam_list = imgs.keys()
        if color_position == {}:
            for cam in cam_list:
                img = imgs[cam]
                if img is not None:
                    rr.log(f"{cam}/camera/color", rr.Image(img))
        else:
            for cam in cam_list:
                color_extrinsic = color_position[cam]
                color_intrinsic = intrinsics[cam]
                img = imgs[cam]
                if img is not None:
                    rr.log(
                        f"{cam}/camera/color",
                        rr.Pinhole(
                            image_from_camera=color_intrinsic,
                        ),
                    )
                    rr.log(
                        f"{cam}/camera/color",
                        rr.Transform3D(
                            translation=np.array(color_extrinsic[:3]),
                            mat3x3=Rotation.from_euler(
                                "xyz", np.array(color_extrinsic[3:])
                            ).as_matrix(),
                        ),
                    )
                    rr.log(f"{cam}/camera/color", rr.Image(img))

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
        entity_to_transform=None,
    ):
        with open("./config/address.yaml", "r") as f:
            address = yaml.load(f.read(), Loader=yaml.FullLoader)

        if self.robot == "finger":
            subscriber = FingerSubscriber(
                address=str(address["ip"] + ":" + str(address["port"]))
            )
            intrinsics = {
                cam: cam_intr_to_mat(self.cam_dict[cam]["intrinsics"])
                for cam in self.cam_dict.keys()
            }
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
                    intrinsics={"finger": intrinsics["finger"]},
                )
                self.log_action_dict(
                    action_dict={"finger/pose": pose, "finger/force": force}
                )
        else:
            subscriber = RobotSubscriber(
                address=str(address["ip"] + ":" + str(address["port"]))
            )
            joint_angles = np.array([0.1])
            self.log_robot_states(joint_angles, entity_to_transform)
            intrinsics = {
                cam: cam_intr_to_mat(self.cam_dict[cam]["intrinsics"])
                for cam in self.cam_dict.keys()
            }
            while True:
                subscriber.receive_message()
                left_finger_pose = subscriber.pose_1
                left_finger_img = subscriber.img_1
                left_finger_force = subscriber.force_1
                left_finger_node = np.zeros(self.finger_node_num * 3)
                left_finger_node[self.finger_def_node - 1] += subscriber.node_1.reshape(-1, 3)
                right_finger_pose = subscriber.pose_2
                right_finger_img = subscriber.img_2
                right_finger_force = subscriber.force_2
                right_finger_node = np.zeros(self.finger_node_num * 3)
                right_finger_node[self.finger_def_node - 1] += subscriber.node_2.reshape(-1, 3)
                joint_angles = subscriber.joint_angles
                robot_pose = subscriber.pose
                robot_img = subscriber.img
                self.log_robot_states(joint_angles, entity_to_transform)
                self.log_finger(left_finger_node, "left_finger")
                self.log_finger(right_finger_node, "right_finger")
                self.log_camera(
                    imgs={
                        "left_finger": left_finger_img,
                        "right_finger": right_finger_img,
                        "robot": robot_img,
                    },
                    intrinsics=intrinsics,
                )
                self.log_action_dict(
                    action_dict={
                        "left_finger/pose": left_finger_pose,
                        "left_finger/force": left_finger_force,
                        "right_finger/pose": right_finger_pose,
                        "right_finger/force": right_finger_force,
                        "robot/pose": robot_pose,
                    }
                )

    def log(
        self,
        time_list,
        joint_angles_list,
        joint_velocities_list,
        pose_list,
        img_list,
        color_position_list,
        entity_to_transform: dict[str, tuple[np.ndarray, np.ndarray]],
    ):
        intrinsics = {
            cam: cam_intr_to_mat(self.cam_dict[cam]["intrinsics"])
            for cam in self.cam_dict.keys()
        }

        start_time = time.time()
        frame = 0
        while True:
            if (time.time() - start_time) > time_list[frame]:
                self.log_robot_states(joint_angles_list[frame], entity_to_transform)
                self.log_camera(
                    imgs={cam: img_list[frame] for cam in self.cam_dict},
                    color_position={
                        cam: color_position_list[frame] for cam in self.cam_dict
                    },
                    intrinsics=intrinsics,
                )
                self.log_action_dict(
                    pose=pose_list[frame],
                    joint_velocities=joint_velocities_list[frame],
                )

                frame += 1

                if frame == len(time_list):
                    return

    def blueprint(self, robot: str = "finger"):
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

        if robot == "finger":
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

        else:
            return Blueprint(
                Horizontal(
                    Vertical(
                        Spatial3DView(name="3D Scene", origin="/", contents=["/**"]),
                        blueprint_row_images(
                            [
                                f"/{cam}/camera/color"
                                for cam in ["left_finger", "robot", "right_finger"]
                            ]
                        ),
                        row_shares=[3, 1],
                    ),
                    Horizontal(
                        Tabs(
                            Vertical(
                                *(
                                    TimeSeriesView(origin=f"/left_finger/pose/{i}")
                                    for i in range(6)
                                ),
                                name="left finger pose",
                            ),
                            Vertical(
                                *(
                                    TimeSeriesView(origin=f"/left_finger/force/{i}")
                                    for i in range(6)
                                ),
                                name="left finger force",
                            ),
                            active_tab=0,
                        ),
                        Tabs(
                            Vertical(
                                *(
                                    TimeSeriesView(origin=f"/right_finger/pose/{i}")
                                    for i in range(6)
                                ),
                                name="right finger pose",
                            ),
                            Vertical(
                                *(
                                    TimeSeriesView(origin=f"/right_finger/force/{i}")
                                    for i in range(6)
                                ),
                                name="right finger force",
                            ),
                            active_tab=0,
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
    robot: str,
    robot_urdf: str,
    data_path: str,
):
    print("Logging Data...")
    time_list = np.loadtxt(os.path.join(data_path, "time.csv"), delimiter=",")
    joint_angles_list = np.loadtxt(
        os.path.join(data_path, "joint_angles.csv"), delimiter=","
    )
    joint_velocities_list = np.loadtxt(
        os.path.join(data_path, "joint_velocities.csv"), delimiter=","
    )
    pose_list = np.loadtxt(os.path.join(data_path, "pose.csv"), delimiter=",")
    img_path = os.path.join(data_path, "img")
    img_list = [
        cv2.cvtColor(
            cv2.imread(os.path.join(img_path, f"{i}.jpg")),
            cv2.COLOR_BGR2RGB,
        )
        for i in range(joint_angles_list.shape[0])
    ]
    color_position_list = np.loadtxt(
        os.path.join(data_path, "color_position.csv"), delimiter=","
    )

    rr.init("Robot Interface", spawn=True)

    urdf_logger = URDFLogger(filepath=robot_urdf)
    robot_vis = RobotVis(cam_dict=cam_dict)

    rr.send_blueprint(robot_vis.blueprint())

    urdf_logger.log()

    robot_vis.log(
        time_list=time_list,
        joint_angles_list=joint_angles_list,
        joint_velocities_list=joint_velocities_list,
        pose_list=pose_list,
        img_list=img_list,
        color_position_list=color_position_list,
        entity_to_transform=urdf_logger.entity_to_transform,
    )


def rerun_server(
    cam_dict: dict,
    robot: str,
    robot_path: str,
):
    rr.init("Robot Interface", spawn=True)
    robot_vis = RobotVis(cam_dict=cam_dict, robot=robot)
    rr.send_blueprint(robot_vis.blueprint(robot))

    if robot == "finger":
        robot_vis.run()
    else:
        urdf_logger = URDFLogger(filepath=robot_path, root_path="./modules/")
        urdf_logger.log()
        robot_vis.run(urdf_logger.entity_to_transform)


def main(
    robot: str = "finger",
    mode: str = "real-time",
    data_folder: str = "",
) -> None:
    print("\033[91mPRESS ESC TO EXIT\033[0m")

    cam_dict = yaml.load(open("./config/camera.yaml"), Loader=yaml.FullLoader)

    robot_dict = {
        "finger": "finger",
        "robotiq_arg85": "robotiq/arg85/arg85.urdf",
        "fifish-v6": "fifish/v6/v6.urdf",
    }

    if mode == "real-time":

        rerun_process = Process(
            target=rerun_server,
            args=(
                cam_dict,
                robot,
                robot_dict[robot],
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
        data_path = os.path.join("./data/", data_folder)
        rerun_log(
            cam_dict=cam_dict,
            robot=robot,
            robot_urdf=robot_dict[robot],
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
        "-r", "--robot", default="finger", type=str, help="select the robot"
    )
    parser.add_argument(
        "-d", "--data", default="", type=str, help="select the data to replay"
    )

    args = parser.parse_args()

    main(robot=args.robot, mode=args.mode, data_folder=args.data)
