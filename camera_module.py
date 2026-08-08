import cv2
import time
import queue

import config

def camera_worker(command_queue, frame_queue):
    """
    Multiprocessing worker to capture frames from the camera and put them in a queue.
    """
    print("Camera worker started.")
    capture = None
    is_running = False

    while True:
        # Check for commands
        try:
            cmd = command_queue.get_nowait()
            if cmd == "START":
                if not is_running:
                    camera_indices = config.CAMERA_INDICES
                    capture = None
                    for index in camera_indices:
                        print(f"Trying camera {index} with CAP_DSHOW...")
                        try:
                            temp_capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
                            if temp_capture.isOpened():
                                capture = temp_capture
                                print(f"Camera {index} (CAP_DSHOW) opened successfully.")
                                break
                        except Exception as e:
                            print(f"Error opening camera {index} (CAP_DSHOW): {e}")

                    if capture and capture.isOpened():
                        # FOURCC çözünürlükten ÖNCE ayarlanmalı; sonra ayarlanırsa
                        # sürücü çoğu zaman çözünürlüğü sıfırlar.
                        if config.CAMERA_USE_MJPG:
                            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

                        capture.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
                        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
                        actual_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
                        actual_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        actual_fps = capture.get(cv2.CAP_PROP_FPS)
                        print(f"Camera started. Resolution Set: {actual_width}x{actual_height} @ {actual_fps:.0f} fps")
                        if (actual_width, actual_height) != (config.CAMERA_WIDTH, config.CAMERA_HEIGHT):
                            print(f"UYARI: Istenen cozunurluk {config.CAMERA_WIDTH}x{config.CAMERA_HEIGHT} "
                                  f"alinamadi, kamera {actual_width}x{actual_height} veriyor.")
                        is_running = True
                    else:
                        print("ERROR: Could not open any camera.")
                        # Send an error frame to notify the inference/UI process
                        try:
                            frame_queue.put_nowait((-1.0, None))
                        except queue.Full:
                            pass
            elif cmd == "STOP":
                if capture and capture.isOpened():
                    capture.release()
                    capture = None
                is_running = False
                print("Camera stopped.")
                # Clear the queue to prevent stale frames
                while not frame_queue.empty():
                    try:
                        frame_queue.get_nowait()
                    except queue.Empty:
                        break
            elif cmd == "QUIT":
                print("Camera worker quitting.")
                if capture and capture.isOpened():
                    capture.release()
                break
        except queue.Empty:
            pass

        # Capture and push frame
        if is_running and capture and capture.isOpened():
            ret, frame = capture.read()
            if ret and frame is not None and frame.size > 0:
                # Discard old frames if queue is full (keep it real-time)
                if frame_queue.full():
                    try:
                        frame_queue.get_nowait()
                    except queue.Empty:
                        pass

                try:
                    frame_queue.put_nowait((time.time(), frame))
                except queue.Full:
                    pass
            else:
                print("Error reading frame.")
                is_running = False # Stop on error
                # Send an error frame to notify the inference/UI process
                try:
                    frame_queue.put_nowait((-1.0, None))
                except queue.Full:
                    pass

        else:
            time.sleep(0.01) # Sleep to avoid high CPU usage when stopped
