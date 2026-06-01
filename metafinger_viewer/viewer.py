#!/usr/bin/env python3

"""
Metafinger Viewer

During the live mode, the viewer will receive the data from the phone through ZMQ.
Press "Ctrl+C" to exit the viewer.
Press "r" to start recording the data.
Press "s" to stop recording and save the data.

During the replay mode, the viewer will read the data from the specified folder.

Data is visualized through rerun, including:
    - Metafinger mesh: The 3D mesh of the metafinger.
    - Camera image: The image captured by the inner camera.
    - Pose: The pose of the metafinger.
    - Force: The force applied to the metafinger.

The blueprint of the viewer is defined in the `blueprint` method, which includes:
    - A 3D scene view for the metafinger mesh.
    - A 2D view for the camera image.
    - Time series views for the pose and force of the metafinger.
"""

import sys
import os
import time
import rerun as rr
from pynput import keyboard
from multiprocessing import Process, Queue, Array, Value
from metafinger_viewer.configs import ViewerConfig
from metafinger_viewer.utils.log_utils import gen_blueprint
from metafinger_viewer.utils.process_utils import rerun_server, rerun_log, zmq_subscriber
from metafinger_viewer.utils.event_utils import KeyHandler
from metafinger_viewer.utils.data_utils import load_data

class MetaFingerViewer:
    """
    Metafinger Viewer class to initialize and run the viewer in live or replay mode.
    """
    
    def __init__(self, cfg: ViewerConfig) -> None:
        """
        Main function to run the viewer.
        
        Args:
            cfg (ViewerConfig): Configuration for the viewer.
        """

        # Initialize the rerun server
        print("Initializing rerun ...")
        rr.init("Metafinger Viewer")
        rr.spawn(connect=False)

        # Send the blueprint
        print("Sending blueprint ...")
        self.blueprint = gen_blueprint()

        self.mode = cfg.mode
        print("Viewer mode:", self.mode)
        
        self.host = cfg.host
        self.port = cfg.port
        print("Listening on {}:{}".format(self.host, self.port))
        
        self.data_path = cfg.data_path

    def run(self) -> None:
        """
        Run the viewer in live or replay mode.
        """
        
        # Live mode
        if self.mode == "live":
            # Queues for ZMQ and recording
            zmq_queue = Queue()
            recording_queue = Queue()

            # Flag for recording state
            is_recording = Value("i", 0)

            # Flag for start time
            start_time = Value("d", time.time())

            # Initialize the rerun and ZMQ processes
            print("Initializing rerun and zmq processes ...")
            process_list = []

            # Create the rerun server process
            process_list.append(
                Process(
                    target=rerun_server,
                    args=(
                        self.blueprint,
                        zmq_queue,
                        recording_queue,
                        is_recording,
                        start_time,
                    ),
                )
            )

            # Create the ZMQ subscriber process
            process_list.append(
                Process(
                    target=zmq_subscriber,
                    args=(
                        self.host,
                        self.port,
                        zmq_queue,
                    ),
                )
            )

            try:
                # Start the key press listener
                print("Start the key press listener...")
                print("\033[91mPress 'r' to start recording\033[0m")
                print("\033[91mPress 's' to stop recording and save the data\033[0m")
                print("\033[91mPress Ctrl+C to EXIT\033[0m")
                key_handler = KeyHandler(is_recording, start_time, recording_queue)
                listener = keyboard.Listener(on_press=key_handler.on_press)
                listener.daemon = True
                listener.start()

                # Start rerun process
                print("Starting rerun process...")
                for i in range(1, len(process_list)):
                    process_list[i].daemon = True
                    process_list[i].start()

                process_list[0].start()
                process_list[0].join()
            except KeyboardInterrupt:
                print("\nCtrl+C detected. Exiting...")
                sys.exit(0)
            finally:
                # Shut down the zmq and rerun processes
                for process in process_list:
                    if process.is_alive():
                        print(f"Stopping process {process.name}...")
                        process.terminate()
                        process.join(timeout=1.0)
                listener.stop()
                print("All processes have been stopped.")

        elif self.mode == "replay":
            if not self.data_path:
                raise ValueError("\033[31mPLEASE SPECIFY DATA PATH\033[0m")

            # Load HDF5 file
            print("HDF5 file path:", self.data_path)
            if not os.path.exists(self.data_path):
                raise ValueError("\033[31mHDF5 file does not exist\033[0m")
            if not os.path.isfile(self.data_path):
                raise ValueError("\033[31mHDF5 file is not a file\033[0m")
            print("Reading HDF5 file...")
            data = load_data(self.data_path)

            # Initialize init_ready
            init_ready = Array("i", [0] * 1)

            # Initialize rerun process
            print("Initializing rerun processes ...")
            rerun_process = Process(
                target=rerun_log,
                args=(
                    self.blueprint,
                    data,
                    init_ready,
                ),
            )

            # Start rerun process
            print("Logging Data...")
            print("This may take a while, please wait...")
            rerun_process.start()
        else:
            raise ValueError("Ivalid mode. Choose 'live' or 'replay'.")