# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "file-read-backwards>=3.1.0",
#     "Windows-Toasts>=1.1.1",
# ]
# ///
import re
import ctypes
import time
import sys
import winsound
import os
import logging
from file_read_backwards import FileReadBackwards
from windows_toasts import Toast, WindowsToaster

log_level_root = os.getenv("LOG_LEVEL_ROOT", "INFO").upper()
logging.basicConfig(level=log_level_root)

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logger = logging.getLogger(__name__)
logger.setLevel(log_level)

battery_level_alert_threshold = int(os.getenv("BATTERY_LEVEL_ALERT_THRESHOLD", "5"))
battery_level_alert_threshold_locked = int(
    os.getenv("BATTERY_LEVEL_ALERT_THRESHOLD_LOCKED", "30")
)

# Base path for Synapse 4 logs
log_base_path = os.path.join(
    os.getenv("LOCALAPPDATA"), "Razer", "RazerAppEngine", "User Data", "Logs"
)
log_file_pattern = "products_165_mw {CD3747B1-B10F-5BB5-933A-53C1D85287E1}4.log"


def get_foreground_window():
    return ctypes.windll.user32.GetForegroundWindow()


def send_alert(battery_level):
    toast = Toast()
    toast.text_fields = [f"Battery: {battery_level}%"]
    max_retries = 5
    retries = 0

    while retries < max_retries:
        try:
            WindowsToaster("Simple Razer Battery").show_toast(toast)
            # If successful, break out of the loop and beep as normal
            winsound.Beep(200, 200)
            winsound.Beep(200, 200)
            winsound.Beep(200, 200)
            break
        except ImportError:
            # This exception can occur extremely rarely
            retries += 1
            if retries >= max_retries:
                error_message = (
                    "An error occurred loading required modules.\n\n"
                    "The application will now be restarted to resolve this issue."
                )
                ctypes.windll.user32.MessageBoxW(None, error_message, "Error", 0)

                # Restart the exe
                # If running as a PyInstaller-built exe, sys.executable should be the path to it.
                exe_path = sys.executable
                # On Windows, re-run the executable with the same arguments.
                os.execv(exe_path, [exe_path] + sys.argv)

            # If not reached max retries, sleep and try again
            time.sleep(1)


def find_log_file_with_rotation():
    """Find the highest numbered log file (most recent) in the Synapse 4 logs directory"""
    try:
        if not os.path.exists(log_base_path):
            logger.error(f"Log directory not found at: {log_base_path}")
            logger.error("Please ensure Razer Synapse 4 is installed and has been running")
            return None
        
        # Look for all log files with the pattern
        log_files = []
        for filename in os.listdir(log_base_path):
            if filename.startswith("products_165_mw {CD3747B1-B10F-5BB5-933A-53C1D85287E1}4"):
                # Extract the number if it exists (for rotated logs)
                match = re.search(r'\.log\.?(\d*)$', filename)
                if match:
                    num_str = match.group(1)
                    num = int(num_str) if num_str else 0
                    log_files.append((num, os.path.join(log_base_path, filename)))
        
        if not log_files:
            # Try the exact pattern without rotation
            exact_path = os.path.join(log_base_path, log_file_pattern)
            if os.path.exists(exact_path):
                return exact_path
            logger.error(f"No matching log files found in: {log_base_path}")
            return None
        
        # Sort by number (highest first) and return the path
        log_files.sort(key=lambda x: x[0], reverse=True)
        return log_files[0][1]
    except Exception as e:
        logger.error(f"Error finding log file: {str(e)}")
        return None


def find_last_entries():
    battery_percentage = None
    battery_state = None
    
    # Find the most recent log file (handling rotation)
    log_file_path = find_log_file_with_rotation()
    if not log_file_path:
        return None, None
    
    logger.debug(f"Using log file: {log_file_path}")

    try:
        with FileReadBackwards(log_file_path, encoding="utf-8") as frb:
            for line in frb:
                if battery_state is None:
                    # Try both chargingStatus and chargingStatusDesc patterns
                    state_match = re.search(r'"chargingStatus":"(\w+)"', line)
                    if not state_match:
                        state_match = re.search(r'"chargingStatusDesc":"(\w+)"', line)
                    if state_match:
                        battery_state = state_match.group(1)

                if battery_percentage is None:
                    # Try both level and batteryLevel patterns
                    percentage_match = re.search(r'"level":(\d+)', line)
                    if not percentage_match:
                        percentage_match = re.search(r'"batteryLevel":(\d+)', line)
                    if percentage_match:
                        battery_percentage = int(percentage_match.group(1))
                        break  # Both variables should now be found already
    except FileNotFoundError:
        logger.error(f"Log file not found at: {log_file_path}")
        logger.error("Please ensure Razer Synapse 4 is installed and has been running")
        return None, None

    return battery_percentage, battery_state


def check_battery_is_low(battery_alert_threshold):
    battery_percentage, battery_state = find_last_entries()

    if battery_percentage is None or battery_state is None:
        logger.error("Battery percentage or state not found in log file")
        return

    # Handle different charging states in Synapse 4
    is_not_charging = battery_state.lower() in ["notcharging", "discharging", "false"]
    
    if is_not_charging and battery_percentage is not None:
        logger.debug(
            f"Battery: {battery_state} {battery_percentage}%, threshold: {battery_alert_threshold}"
        )
        if battery_percentage < battery_alert_threshold:
            logger.info("Warning: Battery level is below threshold and not charging!")
            send_alert(battery_percentage)
        else:
            logger.info("Battery is not charging, but the battery level is sufficient")
    else:
        logger.info("Battery state is charging or above the threshold")


def main():
    last_time_windows_was_unlocked = 0
    last_check = 0

    logger.debug(f"Log base path: {log_base_path}")
    
    # Check if log directory exists before starting the monitoring loop
    if not os.path.exists(log_base_path):
        logger.error(f"Log directory not found at: {log_base_path}")
        logger.error("Please ensure Razer Synapse 4 is installed and has been running")
        logger.error("Application will now exit")
        return

    while True:
        is_pc_locked = get_foreground_window() == 0
        time.sleep(2)  # Sleep for 2 seconds
        is_pc_locked = (
            is_pc_locked and get_foreground_window() == 0
        )  # Recheck, as this method is not perfect

        if is_pc_locked:
            if (
                time.time() - last_time_windows_was_unlocked < 10
            ):  # Check if we just locked windows within last 10 seconds
                logger.debug("PC is locked, time to check")
                check_battery_is_low(battery_level_alert_threshold_locked)
        else:
            last_time_windows_was_unlocked = time.time()
            if time.time() - last_check > 60 * 20:  # Check every 20 minutes
                last_check = time.time()
                last_time_windows_was_unlocked = time.time()
                check_battery_is_low(battery_level_alert_threshold)

        time.sleep(5)


if __name__ == "__main__":
    main()
