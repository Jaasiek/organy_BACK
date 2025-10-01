# handleUSB.py
import os
import subprocess
import pyudev
import time
from flask import current_app

MOUNTPOINT = "/mnt/usb"

# przechowuj ostatnie drzewo, żeby wysłać je klientowi przy connect
last_tree = None


def build_tree(path):
    """Buduje drzewo katalogów i plików MIDI."""
    tree = {"path": path, "folders": [], "files": []}
    try:
        for entry in os.scandir(path):
            if entry.is_file() and entry.name.endswith(".mid"):
                tree["files"].append(entry.name)
            elif entry.is_dir():
                if entry.name != "System Volume Information":
                    tree["folders"].append({"name": entry.name})
    except PermissionError:
        pass
    return tree


def send_last_tree(socketio, sid):
    global last_tree
    if last_tree:
        socketio.emit("directory_tree", last_tree, namespace="/", room=sid)
        print(f"DEBUG: wysłano last_tree do {sid}")


def scan_directory(path, socketio, connected_sids):
    global last_tree
    tree = build_tree(path)
    last_tree = tree
    if connected_sids:
        for sid in list(connected_sids):
            try:
                # room=sid — pewny sposób dostarczenia do konkretnego klienta
                socketio.emit("directory_tree", tree, namespace="/", room=sid)
                # print(f"DEBUG: wysłano directory_tree do {sid}")
            except Exception as e:
                # print(f"ERROR: nie udało się wysłać do {sid}: {e}")
                pass


def mount_and_scan(devnode, socketio, connected_sids, app=None):
    os.makedirs(MOUNTPOINT, exist_ok=True)
    try:
        # wymuszony mount FAT32 z uid/gid pi
        subprocess.run(
            [
                "sudo",
                "mount",
                "-t",
                "vfat",
                "-o",
                "utf8,iocharset=utf8,uid=1000,gid=1000",
                devnode,
                MOUNTPOINT,
            ],
            check=True,
        )
        # print(f"Dysk {devnode} zamontowany w {MOUNTPOINT}")

        # Poczekaj, aż system "odświeży" prawa
        time.sleep(0.5)  # 500ms powinno wystarczyć

        # opcjonalnie sprawdź prawa
        st = os.stat(MOUNTPOINT)
        # print("DEBUG: mount permissions:", oct(st.st_mode))

    except subprocess.CalledProcessError:
        # print(f"Nie udało się zamontować {devnode}")
        return

    if app:
        with app.app_context():
            scan_directory(MOUNTPOINT, socketio, connected_sids)
    else:
        scan_directory(MOUNTPOINT, socketio, connected_sids)


def handle_scan(data, socketio, connected_sids):
    folder_path = data["folder"]
    if os.path.isdir(folder_path):
        tree = build_tree(folder_path)
        # wyślij do wszystkich podłączonych
        if connected_sids:
            for sid in list(connected_sids):
                try:
                    socketio.emit("directory_tree", tree, namespace="/", room=sid)
                    # print(f"DEBUG: wysłano directory_tree (manual scan) do {sid}")
                except Exception as e:
                    # print("ERROR podczas handle_scan emit:", e)
                    pass


def clear_mount_and_notify(socketio, connected_sids, app=None):
    global last_tree
    last_tree = None

    # spróbuj odmontować (ignoruj błędy)
    try:
        subprocess.run(
            ["sudo", "umount", MOUNTPOINT],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # print(f"DEBUG: {MOUNTPOINT} odmontowany")
    except Exception:
        # może już nie być zamontowany — to OK
        print(f"DEBUG: umount failed or not mounted (ok)")

    # powiadom wszystkich podłączonych klientów
    if connected_sids:
        for sid in list(connected_sids):
            try:
                socketio.emit(
                    "directory_tree_cleared",
                    {"path": MOUNTPOINT, "message": "Dysk USB został usunięty"},
                    namespace="/",
                    room=sid,
                )
                # print(f"DEBUG: wysłano directory_tree_cleared do {sid}")
            except Exception as e:
                print(
                    f"ERROR: nie udało się wysłać directory_tree_cleared do {sid}: {e}"
                )


def usb_monitor(socketio, connected_sids, app=None):
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem="block")

    # print("DEBUG: usb_monitor uruchomiony, oczekuję device events...")
    for device in iter(monitor.poll, None):
        try:
            # print(
            #     "DEBUG: usb event:",
            #     getattr(device, "action", None),
            #     getattr(device, "device_node", None),
            # )
            if (
                device.action == "add"
                and device.device_node
                and "sd" in device.device_node
            ):
                if device.device_node[-1].isdigit():  # np. sdb1
                    try:
                        socketio.sleep(1)
                    except Exception:
                        time.sleep(1)
                    mount_and_scan(
                        device.device_node, socketio, connected_sids, app=app
                    )

            # obsługa usunięcia pendrive (remove)
            elif (
                device.action == "remove"
                and device.device_node
                and "sd" in device.device_node
            ):
                # Poczekaj chwilę, żeby system zdążył zaktualizować / ewentualnie odmontować
                try:
                    socketio.sleep(0.5)
                except Exception:
                    time.sleep(0.5)
                # print(f"DEBUG: wykryto remove dla {device.device_node} — czyszczę UI")
                clear_mount_and_notify(socketio, connected_sids, app=app)

        except Exception as e:
            print("ERROR w usb_monitor:", e)
