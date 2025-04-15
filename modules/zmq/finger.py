#!/usr/bin/env python

import zmq
import numpy as np
from typing import Tuple
from datetime import datetime
from modules.protobuf import finger_msg_pb2


class FingerPublisher:
    def __init__(self, ip, port, hwm: int = 1, conflate: bool = True) -> None:
        """Publisher initialization.

        Args:
            addr: The address of the publisher.
        """

        print("{:-^80}".format(" Finger Publisher Initialization "))
        print(f"Address: tcp://{ip}:{port}")

        # Create a ZMQ context
        self.context = zmq.Context()
        # Create a ZMQ publisher
        self.publisher = self.context.socket(zmq.PUB)
        # Set high water mark
        self.publisher.set_hwm(hwm)
        # Set conflate
        self.publisher.setsockopt(zmq.CONFLATE, conflate)
        # Bind the address
        self.publisher.bind(f"tcp://{ip}:{port}")

        # Init the message
        self.finger = finger_msg_pb2.Finger()

        print("Package Finger")
        print("Message Finger")
        print(
            "{\n\tbytes img = 1;\n\trepeated float pose = 2;\n\trepeated float force = 3;\n\trepeated float node = 4;\n}"
        )

        print("Finger Publisher Initialization Done.")
        print("{:-^80}".format(""))

    def pub_msg(
        self,
        img_bytes: bytes = b"",
        pose: np.ndarray = np.array([]),
        force: np.ndarray = np.array([]),
        node: np.ndarray = np.array([]),
    ) -> None:
        """Publish the message.

        Args:
            img: The image captured by the camera.
            pose: The pose of the marker (numpy array or list).
            force: The force on the bottom surface of the finger (numpy array or list).
            node: The node displacement of the finger (numpy array or list).
        """

        # Set the message
        self.finger.timestamp = datetime.now().timestamp()
        self.finger.img = img_bytes
        self.finger.pose[:] = pose.flatten().tolist()
        self.finger.force[:] = force.flatten().tolist()
        self.finger.node[:] = node.flatten().tolist()

        # Publish the message
        self.publisher.send(self.finger.SerializeToString())

    def close(self):
        """Close ZMQ socket and context to prevent memory leaks."""
        if hasattr(self, "publisher") and self.publisher:
            self.publisher.close()
        if hasattr(self, "context") and self.context:
            self.context.term()


class FingerSubscriber:
    def __init__(self, ip, port, hwm: int = 1, conflate: bool = True) -> None:
        """Subscriber initialization.

        Args:
            addr: The address of the subscriber.
        """

        print("{:-^80}".format(" Finger Subscriber Initialization "))
        print(f"Address: tcp://{ip}:{port}")

        # Create a ZMQ context
        self.context = zmq.Context()
        # Create a ZMQ subscriber
        self.subscriber = self.context.socket(zmq.SUB)
        # Set high water mark
        self.subscriber.set_hwm(hwm)
        # Set conflate
        self.subscriber.setsockopt(zmq.CONFLATE, conflate)
        # Connect the address
        self.subscriber.connect(f"tcp://{ip}:{port}")
        # Subscribe the topic
        self.subscriber.setsockopt_string(zmq.SUBSCRIBE, "")

        # Init the message
        self.finger = finger_msg_pb2.Finger()

        print("Package Finger")
        print("Message Finger")
        print(
            "{\n\tbytes img = 1;\n\trepeated float pose = 2;\n\trepeated float force = 3;\n\trepeated float node = 4;\n}"
        )

        print("Finger Subscriber Initialization Done.")
        print("{:-^80}".format(""))

    def sub_msg(self) -> Tuple[bytes, np.ndarray, np.ndarray, np.ndarray]:
        """Subscribe the message.

        Args:
            timeout: Maximum time to wait for a message in milliseconds.
                    Default is 1000ms (1 second).

        Returns:
            img: The image captured by the camera.
            pose: The pose of the marker.
            force: The force on the bottom surface of the finger.
            node: The node displacement of the finger.

        Raises:
            zmq.ZMQError: If no message is received within the timeout period.
        """

        # Receive the message
        self.finger.ParseFromString(self.subscriber.recv())
        return (
            self.finger.img,
            np.array(self.finger.pose),
            np.array(self.finger.force),
            np.array(self.finger.node),
        )

    def close(self):
        """Close ZMQ socket and context to prevent memory leaks."""
        if hasattr(self, "subscriber") and self.subscriber:
            self.subscriber.close()
        if hasattr(self, "context") and self.context:
            self.context.term()
