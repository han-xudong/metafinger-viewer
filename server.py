#!/usr/bin/env python3

import os
import argparse
import time
import yaml
import ast
import ctypes
import socket
import asyncio
import websockets
import webbrowser
import contextlib
import zmq
import cv2
import numpy as np
from rerun_loader_urdf import URDFLogger
from scipy.spatial.transform import Rotation
from modules import cam_msg_pb2, robot_msg_pb2
from common import (
    log_angle_rot,
    blueprint_row_images,
    link_to_world_transform,
    cam_intr_to_mat,
)
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from multiprocessing import Process, Value
import rerun as rr


class DualStackServer(ThreadingHTTPServer):
    def server_bind(self):
        # suppress exception when protocol is IPv4
        with contextlib.suppress(Exception):
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        return super().server_bind()

class FingerSubscriber:
    def __init__(self, address: str) -> None:
        self.context = zmq.Context()
        self.subscriber = self.context.socket(zmq.SUB)
        self.subscriber.connect(address)
        self.subscriber.setsockopt_string(zmq.SUBSCRIBE, "")
        self.timestamp = 0
        self.pose = np.zeros(6)
        self.img = None

    def receive_message(self):
        finger = cam_msg_pb2.Finger()
        finger.ParseFromString(self.subscriber.recv())

        self.timestamp = finger.timestamp
        self.pose = np.array(finger.pose).flatten()
        self.img = cv2.cvtColor(
            cv2.imdecode(np.frombuffer(finger.img, np.uint8), cv2.IMREAD_COLOR),
            cv2.COLOR_BGR2RGB,
        )

class RobotSubscriber:
    def __init__(self, address: str) -> None:
        self.context = zmq.Context()
        self.subscriber = self.context.socket(zmq.SUB)
        self.subscriber.connect(address)
        self.subscriber.setsockopt_string(zmq.SUBSCRIBE, "")
        self.timestamp = 0
        self.joint_angles = np.zeros(6)
        self.pose = np.zeros(6)
        self.img = None

    def receive_message(self):
        robot = robot_msg_pb2.Robot()
        robot.ParseFromString(self.subscriber.recv())

        self.timestamp = robot.timestamp
        self.joint_angles = np.array(robot.joint_angles).flatten()
        self.pose = np.array(robot.pose).flatten()
        self.img = cv2.cvtColor(
            cv2.imdecode(np.frombuffer(robot.img, np.uint8), cv2.IMREAD_COLOR),
            cv2.COLOR_BGR2RGB,
        )


class RobotVis:
    def __init__(self, cam_dict: dict[str, dict[str, str]], robot: str = "finger"):
        self.prev_joint_origins = None
        self.cam_dict = cam_dict
        self.robot = robot

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
        color_imgs: dict[str, np.ndarray],
        color_position: dict[str, np.ndarray]={},
        color_intrinsics: dict[str, np.ndarray]={},
    ):
        if color_position == {}:
            for cam in self.cam_dict.keys():
                color_img = color_imgs[cam]
                if color_img is not None:
                    rr.log(f"/cameras/{cam}/color", rr.Image(color_img))
        else:
            for cam in self.cam_dict.keys():
                color_extrinsic = color_position[cam]
                color_intrinsic = color_intrinsics[cam]
                color_img = color_imgs[cam]
                if color_img is not None:
                    rr.log(
                        f"/cameras/{cam}/color",
                        rr.Pinhole(
                            image_from_camera=color_intrinsic,
                        ),
                    )
                    rr.log(
                        f"/cameras/{cam}/color",
                        rr.Transform3D(
                            translation=np.array(color_extrinsic[:3]),
                            mat3x3=Rotation.from_euler(
                                "xyz", np.array(color_extrinsic[3:])
                            ).as_matrix(),
                        ),
                    )
                    rr.log(f"/cameras/{cam}/color", rr.Image(color_img))

    def log_finger(
        self,
        pose: np.ndarray,
    ):
        rr.log("/finger/pose", rr.Transform3D(translation=pose[:3], mat3x3=Rotation.from_euler("xyz", pose[3:]).as_matrix()))

    def log_action_dict(
        self,
        pose: np.ndarray = np.array([0, 0, 0, 0, 0, 0]),
    ):

        for i, val in enumerate(pose):
            rr.log(f"/action_dict/pose/{i}", rr.Scalar(val))

    def run(
        self,
        record_state,
        entity_to_transform=None,
    ):
        with open("../config/address.yaml", "r") as f:
            address = yaml.load(f.read(), Loader=yaml.Loader)
        
        if self.robot =="finger":
            subscriber = FingerSubscriber(address=address["finger"])

            color_intrinsics = {
                cam: cam_intr_to_mat(self.cam_dict[cam]["color_intrinsics"])
                for cam in self.cam_dict.keys()
            }
            recording = False
            time_list = []
            finger_pose_list = []
            count = 0
            while True:
                subscriber.receive_message()
                pose = subscriber.pose
                img = subscriber.img
                self.log_finger(pose)
                self.log_camera(
                    color_imgs={cam: img for cam in self.cam_dict},
                    color_intrinsics=color_intrinsics,
                )
                self.log_action_dict(pose=pose)
                if record_state.value == 1:
                    if recording == False:
                        start_time = time.time()
                        recording = True
                        save_path = os.path.join("../data/", time.strftime("%Y%m%d-%H%M%S"))
                        os.makedirs(save_path)
                        os.makedirs(os.path.join(save_path, "color_img"))
                    time_list.append(time.time() - start_time)
                    finger_pose_list.append(pose)
                    cv2.imwrite(
                        os.path.join(save_path, f"color_img/frame_{count}.png"),
                        cv2.cvtColor(img, cv2.COLOR_RGB2BGR),
                    )
                    count += 1
                    print(f"Saving, fps: {count/(time.time() - start_time)}", end="\r")
                else:
                    if recording == True:
                        recording = False
                        np.savetxt(
                            os.path.join(save_path, "time.csv"),
                            time_list,
                            delimiter=",",
                            fmt="%.6f",
                        )
                        np.savetxt(
                            os.path.join(save_path, "pose.csv"),
                            finger_pose_list,
                            delimiter=",",
                            fmt="%.6f",
                        )
                        print(f"Data saved to {save_path}")
                        time_list = []
                        finger_pose_list = []
                        count = 0
        else:
            left_finger_subscriber = FingerSubscriber(address=address["left_finger"])
            right_finger_subscriber = FingerSubscriber(address=address["right_finger"])
            robot_subscriber = RobotSubscriber(address=address["robot"])

            joint_angles = np.zeros(6)
            self.log_robot_states(joint_angles, entity_to_transform)
        
            color_intrinsics = {
                cam: cam_intr_to_mat(self.cam_dict[cam]["color_intrinsics"])
                for cam in self.cam_dict.keys()
            }
            recording = False
            time_list = []
            joint_angles_list = []
            left_finger_pose_list = []
            right_finger_pose_list = []
            pose_list = []
            count = 0
            while True:
                subscriber.receive_message()
                joint_angles = subscriber.joint_angles
                pose = subscriber.pose
                img = subscriber.img
                self.log_robot_states(joint_angles, entity_to_transform)
                self.log_camera(
                    color_imgs={cam: img for cam in self.cam_dict},
                    color_intrinsics=color_intrinsics,
                )
                self.log_action_dict(pose=pose)
                if record_state.value == 1:
                    if recording == False:
                        start_time = time.time()
                        recording = True
                        save_path = os.path.join("../data/", time.strftime("%Y%m%d-%H%M%S"))
                        os.makedirs(save_path)
                        os.makedirs(os.path.join(save_path, "color_img"))
                    time_list.append(time.time() - start_time)
                    joint_angles_list.append(joint_angles)
                    pose_list.append(pose)
                    color_position_list.append(color_position)
                    cv2.imwrite(
                        os.path.join(save_path, f"color_img/frame_{count}.png"),
                        cv2.cvtColor(img, cv2.COLOR_RGB2BGR),
                    )
                    count += 1
                    print(f"Saving, fps: {count/(time.time() - start_time)}", end="\r")
                else:
                    if recording == True:
                        recording = False
                        np.savetxt(
                            os.path.join(save_path, "time.csv"),
                            time_list,
                            delimiter=",",
                            fmt="%.6f",
                        )
                        np.savetxt(
                            os.path.join(save_path, "joint_angles.csv"),
                            joint_angles_list,
                            delimiter=",",
                            fmt="%.6f",
                        )
                        np.savetxt(
                            os.path.join(save_path, "pose.csv"),
                            pose_list,
                            delimiter=",",
                            fmt="%.6f",
                        )
                        np.savetxt(
                            os.path.join(save_path, "color_position.csv"),
                            color_position_list,
                            delimiter=",",
                            fmt="%.6f",
                        )
                        print(f"Data saved to {save_path}")
                        time_list = []
                        joint_angles_list = []
                        pose_list = []
                        color_position_list = []
                        count = 0

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
        color_intrinsics = {
            cam: cam_intr_to_mat(self.cam_dict[cam]["color_intrinsics"])
            for cam in self.cam_dict.keys()
        }

        start_time = time.time()
        frame = 0
        while True:
            if (time.time() - start_time) > time_list[frame]:
                self.log_robot_states(joint_angles_list[frame], entity_to_transform)
                self.log_camera(
                    color_imgs={cam: img_list[frame] for cam in self.cam_dict},
                    color_position={
                        cam: color_position_list[frame] for cam in self.cam_dict
                    },
                    color_intrinsics=color_intrinsics,
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

        return Blueprint(
            Horizontal(
                Vertical(
                    Spatial3DView(name="3D Scene", origin="/", contents=["/**"]),
                    blueprint_row_images(
                        [f"/cameras/{cam}/color" for cam in self.cam_dict.keys()]
                    ),
                    row_shares=[3, 1],
                ),
                Vertical(
                    Tabs(
                        Vertical(
                            *(
                                TimeSeriesView(
                                    origin=f"/action_dict/joint_velocity/{i}"
                                )
                                for i in range(6)
                            ),
                            name="joint velocity",
                        ),
                        Vertical(
                            *(
                                TimeSeriesView(origin=f"/action_dict/pose/{i}")
                                for i in range(6)
                            ),
                            name="tcp pose",
                        ),
                        active_tab=0,
                    ),
                ),
                column_shares=[3, 1],
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
    img_path = os.path.join(data_path, "color_img")
    img_list = [
        cv2.cvtColor(
            cv2.imread(os.path.join(img_path, f"frame_{i}.png")),
            cv2.COLOR_BGR2RGB,
        )
        for i in range(joint_angles_list.shape[0])
    ]
    color_position_list = np.loadtxt(
        os.path.join(data_path, "color_position.csv"), delimiter=","
    )

    urdf_logger = URDFLogger(filepath=robot_urdf)
    robot_vis = RobotVis(cam_dict=cam_dict)

    rr.init("Robot Interface")
    rr.serve(open_browser=False, ws_port=4321, web_port=8000)
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
    record_state,
    cam_dict: dict,
    robot: str,
    robot_urdf: str,
):
    robot_vis = RobotVis(cam_dict=cam_dict, robot=robot)

    rr.init("Robot Interface")
    rr.serve_web(open_browser=False, ws_port=4321, web_port=8000)
    rr.send_blueprint(robot_vis.blueprint(robot))

    if robot == "finger":
        robot_vis.run(record_state)
    else:
        urdf_logger = URDFLogger(filepath=robot_urdf)
        urdf_logger.log()
        robot_vis.run(record_state, urdf_logger.entity_to_transform)


def web_server(
    server_class=DualStackServer,
    handler_class=SimpleHTTPRequestHandler,
    bind: str = "127.0.0.1",
    port: int = 8000,
):
    handler_class = partial(SimpleHTTPRequestHandler, directory=os.getcwd())

    with server_class((bind, port), handler_class) as httpd:
        print(f"Serving HTTP on {bind} port {port} " f"(http://{bind}:{port}/) ...")
        httpd.serve_forever()


def record_listener(
    record_state,
    bind: str = "localhost",
    port: int = 4323,
):
    async def echo(websocket, path):
        async for message in websocket:
            print(f"receive message: {message}")
            if message == "1":
                record_state.value = 1
            elif message == "0":
                record_state.value = 0
            await websocket.send(f"Echo: {message}")

    start_server = websockets.serve(echo, bind, port)

    asyncio.get_event_loop().run_until_complete(start_server)
    asyncio.get_event_loop().run_forever()


def main(
    robot: str = "finger",
    mode: str = "real-time",
    data_folder: str = "",
    server_class=DualStackServer,
    handler_class=SimpleHTTPRequestHandler,
    bind: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    web_process = Process(
        target=web_server,
        args=(
            server_class,
            handler_class,
            bind,
            port,
        ),
    )
    print("\033[91mPRESS ESC TO EXIT, AND STOP RECORDING DATA FIRST!!!\033[0m")

    cam_dict = yaml.load(open("../config/camera.yaml"), Loader=yaml.FullLoader)

    robot_dict = {
        "finger": "finger",
        "robotiq_arg85": "robotiq/arg85/arg85.urdf",
        "fifish-v6": "fifish/v6/v6.urdf",
    }

    web_process.daemon = True
    web_process.start()
    webbrowser.open(f"http://{bind}:{port}")

    if mode == "real-time":
        record_state = Value(ctypes.c_int, 0)

        record_process = Process(target=record_listener, args=(record_state,))
        record_process.daemon = True
        record_process.start()

        rerun_process = Process(
            target=rerun_server,
            args=(
                record_state,
                cam_dict,
                robot,
                robot_dict[robot],
            ),
        )
        rerun_process.daemon = True
        rerun_process.start()

    elif mode == "log-data":
        data_path = os.path.join("../data/", data_folder)
        rerun_log(
            cam_dict=cam_dict, robot=robot, robot_urdf=robot_dict[robot], data_path=data_path
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
