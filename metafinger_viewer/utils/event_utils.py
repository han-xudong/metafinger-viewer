#!/usr/bin/env python3

import time
from pynput import keyboard
from multiprocessing import Queue
from metafinger_viewer.utils.data_utils import save_data


class KeyHandler:
    """
    A class to handle key press events for recording data.

    This class listens for specific key presses to start and stop recording data from multiple queues.

    Attributes:
        is_recording (Value): A multiprocessing Value indicating whether recording is active.
        start_time (Value): A multiprocessing Value to store the start time of the recording.
        recording_queue (Queue): A queue from which data will be recorded.
        recorded_data (list): A list to store the recorded data.
    """

    def __init__(
        self, is_recording, start_time, recording_queue: Queue
    ) -> None:
        """
        Initializes the KeyHandler with the necessary parameters.

        Args:
            is_recording (Value): A multiprocessing Value indicating whether recording is active.
            start_time (Value): A multiprocessing Value to store the start time of the recording.
            recording_queu (Queue): Queue from which data will be recorded.
        """

        self.is_recording = is_recording
        self.start_time = start_time
        self.recording_queue = recording_queue
        self.recorded_data = []

    def record_data(self) -> None:
        """
        Pulls all available data from each queue and stores it in recorded_data.

        Raises:
            Exception: If there is an error while reading from the queues.
        """

        while not self.recording_queue.empty():
            try:
                data = self.recording_queue.get_nowait()
                self.recorded_data.append(data)
            except Exception as e:
                print(f"Queue read error: {e}")

    def on_press(self, key) -> None:
        """
        Handle key press: 'r' to start recording, 's' to stop and save.

        Args:
            key (Key): The key that was pressed.
        """

        if key == keyboard.KeyCode.from_char("r") and not self.is_recording.value:
            self.is_recording.value = 1
            print("Start recording...")
            print("Press 's' to stop recording.")

            self.recorded_data = []
            self.start_time.value = time.time()

        elif key == keyboard.KeyCode.from_char("s") and self.is_recording.value:
            self.is_recording.value = 0
            print("Stop recording.")

            self.record_data()  # Final drain before save

            save_data(
                self.recorded_data,
                f"./data/{time.strftime('%Y%m%d-%H%M%S')}.hdf5",
            )

        if self.is_recording.value:
            self.record_data()
