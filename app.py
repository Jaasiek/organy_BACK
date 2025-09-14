from flask import Flask, request
from flask_socketio import SocketIO
from flask_cors import CORS
import threading
import json, time

from gpio import update_cords_divisions, run, output_all_one, set_copel
from midi import MidiPlayer
from handleUSB import usb_monitor, handle_scan, send_last_tree, last_tree


app = Flask(__name__)
CORS(app)
socket = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

connected_sids = set()
midi_instance = None
midi_monitor_thread = None
midi_monitor_stop = threading.Event()
midi_lock = threading.Lock()
midi_monitor_stop = threading.Event()
midi_lock = threading.Lock()
midi_file_path = "/home/pi/test.mid"

global track_name, step, steps_number, tracks, combination
step = 0
combination = []


@socket.on("connect")
def on_connect():
    sid = request.sid
    connected_sids.add(sid)
    print(f"DEBUG: Client connected: {sid}. Connected clients: {len(connected_sids)}")

    try:
        if last_tree:
            socket.emit("directory_tree", last_tree, namespace="/", room=sid)
            print(f"DEBUG: wyslano last_tree do {sid}")
    except Exception as e:
        print("ERROR podczas wysyłania last_tree na connect:", e)


@socket.on("disconnect")
def on_disconnect():
    sid = request.sid
    connected_sids.discard(sid)
    print(
        f"DEBUG: Client disconnected: {sid}. Connected clients: {len(connected_sids)}"
    )


def open_file() -> list:
    with open("./tracks.json", "r", encoding="utf-8") as file:
        tracks = json.load(file)
    return tracks


@socket.on("registers_reset")
def reset_registers():
    output_all_one(False)


@socket.on("login")
def login(data):
    with open("./users.json", "r", encoding="utf-8") as file:
        users = json.load(file)

    for user in users:
        if user["name"] == data["name"] and user["password"] == data["password"]:
            socket.emit(
                "login_status", {"message": "Zalogowano pomyślnie", "success": True}
            )
            return

    socket.emit("login_status", {"message": "Zły login lub hasło", "success": False})


@socket.on("get_tracks")
def send_tracks(username):
    tracks_to_send = []
    tracks = open_file()

    for track in tracks:
        owners = track.get("owners")
        if isinstance(owners, list) and username in owners:
            tracks_to_send.append(track)

    socket.emit("tracks", tracks_to_send)


@socket.on("create_user")
def create_user(data):
    try:
        with open("./users.json", "r", encoding="utf-8") as file:
            users = json.load(file)

        for user in users:
            if user["name"] == data["name"]:
                socket.emit(
                    "user_created",
                    {
                        "success": False,
                        "message": "Użytkownik o takiej nazwie już istnieje.",
                    },
                )
                return

        users.append({"name": data["name"], "password": data["password"]})

        with open("./users.json", "w", encoding="utf-8") as file:
            json.dump(users, file, indent=2, ensure_ascii=False)

        socket.emit(
            "user_created", {"success": True, "message": "Użytkownik został utworzony."}
        )

    except Exception as e:
        socket.emit(
            "user_created", {"success": False, "message": f"Błąd serwera: {str(e)}"}
        )


@socket.on("get_sharable")
def sharable(username):
    with open("./users.json", "r", encoding="utf-8") as file:
        users = json.load(file)
    sharable_users = []

    for user in users:
        if user["name"] != username and user["name"] != "admin":
            sharable_users.append(user["name"])

    socket.emit("sharable", sharable_users)


@socket.on("share")
def share(data):
    tracks = open_file()

    for track in tracks:
        if track["name"] == data["track_name"]:

            owners = track.get("owners", [])
            if data["user"] in owners:
                socket.emit(
                    "shared",
                    {
                        "success": False,
                        "message": f"Użytkownik {data['user']} ma już dostęp do utworu „{data['track_name']}”",
                    },
                )
                return

            owners.append(data["user"])
            track["owners"] = owners
            break

    with open("./tracks.json", "w", encoding="utf-8") as file:
        json.dump(tracks, file, ensure_ascii=False, indent=2)

    socket.emit(
        "shared",
        {
            "success": True,
            "message": f"Utwór „{data['track_name']}” został udostępniony użytkownikowi {data['user']}",
        },
    )


@socket.on("select_track")
def game_mode(data):
    global track_name, step, steps_number
    tracks = open_file()

    for track in tracks:
        if track["name"] == data["track_name"]:
            steps_number = track["steps"]

    step = 0
    track_name = data["track_name"]
    socket.emit(
        "track_selected",
        {"success": True, "title": track_name, "steps": steps_number},
    )


@socket.on("start_playing")
def start_playing():
    global track_name, step, steps_number
    tracks = open_file()
    step = 1

    for track in tracks:
        if track["name"] == track_name:
            combination = track["combination"][str(step)]
            set_copel(100, 100 in combination)
            set_copel(101, 101 in combination)
            set_copel(102, 102 in combination)
            update_cords_divisions(combination)

            socket.emit(
                "play",
                {
                    "success": True,
                    "title": track_name,
                    "steps": f"{step}/{steps_number}",
                    "combination": combination,
                },
            )


@socket.on("HOME")
def home_reset():
    global step, steps_number, track_name, combination

    step = 0
    steps_number = 0
    track_name = ""
    combination = []

    socket.emit("home_reset")


@socket.on("next_step")
def next_step():
    global step, steps_number
    tracks = open_file()
    try:
        if step < steps_number:
            step += 1

            for track in tracks:
                if track["name"] == track_name:
                    combination = track["combination"][str(step)]
                    set_copel(100, 100 in combination)
                    set_copel(101, 101 in combination)
                    set_copel(102, 102 in combination)
                    update_cords_divisions(combination)

                    socket.emit(
                        "next_step_info",
                        {
                            "success": True,
                            "steps": f"{step}/{steps_number}",
                            "combination": combination,
                        },
                    )
        else:
            socket.emit(
                "next_step_info",
                {
                    "success": False,
                    "message": "Wszystkie kroki zostały już wykonane",
                },
            )
    except:
        pass


@socket.on("previoust_step")
def previoust_step(data=None):
    global step, steps_number, track_name

    tracks = open_file()
    if data != None:
        try:
            step -= 1
            for track in tracks:
                if track["name"] == data["track_name"]:
                    combination = track["combination"][str(data["step_to_edit"])]

                    set_copel(100, 100 in combination)
                    set_copel(101, 101 in combination)
                    set_copel(102, 102 in combination)
                    update_cords_divisions(combination)
                    socket.emit(
                        "previoust_step_info",
                        {
                            "success": True,
                            "combination": combination,
                        },
                    )
        except:
            print("except")
            socket.emit(
                "previoust_step_info",
                {
                    "success": False,
                    "message": "Nie można przejść do poprzedniego kroku",
                },
            )

    elif step > 1:
        step -= 1

        for track in tracks:
            if track["name"] == track_name:
                combination = track["combination"][str(step)]
                set_copel(100, 100 in combination)
                set_copel(101, 101 in combination)
                set_copel(102, 102 in combination)
                update_cords_divisions(combination)
                socket.emit(
                    "next_step_info",
                    {
                        "success": True,
                        "steps": f"{step}/{steps_number}",
                        "combination": combination,
                    },
                )
    else:
        pass


@socket.on("create_track")
def track_create(data):
    tracks = open_file()
    for track in tracks:
        if track["name"] == data["track_name"]:
            socket.emit(
                "creating_track_info",
                {
                    "success": False,
                    "message": f"Utwór o tytule „{data['track_name']}” już istnieje",
                },
            )
            return

    new_track = {
        "name": data["track_name"],
        "owners": ["admin"],
        "steps": 0,
        "combination": {},
    }

    tracks.append(new_track)

    with open("./tracks.json", "w", encoding="utf-8") as file:
        json.dump(tracks, file, indent=2, ensure_ascii=False)

    socket.emit(
        "creating_track_info",
        {
            "success": True,
            "message": f"Tytuł „{data['track_name']}” jest wolny",
        },
    )


@socket.on("combination")
def combination_add(data):
    tracks = open_file()
    try:
        for track in tracks:
            if track["name"] == data["track_name"]:
                track["steps"] = 1 if track["steps"] == 0 else track["steps"] + 1
                step = track["steps"]
                owner = data["owner"]
                actual_combination = data["active_cords"]
                track["combination"].update({str(step): actual_combination})
                if owner not in track["owners"]:
                    track["owners"].append(owner)

        with open("./tracks.json", "w", encoding="utf-8") as file:
            json.dump(tracks, file, indent=2, ensure_ascii=False)

        socket.emit(
            "combination_creating_info",
            {
                "success": True,
                "message": f"Krok dodany",
            },
        )
    except:
        socket.emit(
            "combination_creating_info",
            {
                "success": False,
                "message": f"Krok nie został dodany poprawnie",
            },
        )


@socket.on("editing_combination")
def combination_edit(data):
    tracks = open_file()
    try:
        for track in tracks:
            if track["name"] == data["track_name"]:
                step = data["step"]
                owner = data["owner"]
                actual_combination = data["active_cords"]
                track["combination"].update({str(step): actual_combination})
                if owner not in track["owners"]:
                    track["owners"].append(owner)

        with open("./tracks.json", "w", encoding="utf-8") as file:
            json.dump(tracks, file, indent=2, ensure_ascii=False)

        socket.emit(
            "combination_editing_info",
            {
                "success": True,
                "message": f"Krok został edytowany",
            },
        )
    except:
        socket.emit(
            "combination_editing_info",
            {
                "success": False,
                "message": f"Krok nie został edytowany poprawnie",
            },
        )


@socket.on("confirm_track")
def confirm_track(data):
    socket.emit("get_combination")
    time.sleep(3)
    global combination
    tracks = open_file()

    new_track = {
        "name": data["track_name"],
        "owners": [data["owner"]],
        "steps": data["steps"],
        "combination": combination,
    }

    tracks.append(new_track)

    with open("./tracks.json", "w", encoding="utf-8") as file:
        json.dump(tracks, file, indent=2, ensure_ascii=False)

    socket.emit(
        "track_created",
        {
            "success": True,
            "message": f"Utwór „{data['track_name']}” został utworzony.",
        },
    )


# MIDI


def _start_midi_monitor():
    """Wątek okresowo emituje status MIDI do wszystkich połączonych klientów."""
    global midi_instance, midi_monitor_stop

    midi_monitor_stop.clear()

    def fmt_time(seconds: float) -> str:
        if seconds is None:
            return "00:00"
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}:{s:02d}"

    def monitor():
        global midi_instance
        last_finished_emitted = False
        while not midi_monitor_stop.is_set():
            with midi_lock:
                inst = midi_instance

            if inst is None:
                time.sleep(0.3)
                continue

            pos = inst.get_position()
            total = inst.get_total()
            remaining = None if total is None else max(0.0, total - pos)

            payload = {
                "file": getattr(inst, "file_path", None),
                "position": fmt_time(pos),
                "total": fmt_time(total),
                "remaining": fmt_time(remaining),
                "is_playing": inst.is_playing(),
                "is_paused": inst.is_paused(),
            }

            try:
                # broadcast do wszystkich (zmień na namespace/room jeśli chcesz)
                socket.emit("midi_status", payload, namespace="/")
            except Exception as e:
                print("ERROR emitting midi_status:", e)

            # jeżeli zakończono odtwarzanie (nie żywy wątek i nie pauza) -> wyemituj finished i przerwij monitor
            if not inst.is_playing() and not inst.is_paused():
                if not last_finished_emitted:
                    try:
                        socket.emit(
                            "midi_finished",
                            {"file": getattr(inst, "file_path", None)},
                            namespace="/",
                        )
                    except Exception as e:
                        print("ERROR emitting midi_finished:", e)
                    last_finished_emitted = True
                    # usuń instancję po krótkim czasie (żeby get_position dalej działało, można też natychmiast)
                    # tu usuwamy instancję żeby kolejny start zaczynał od nowa
                    with midi_lock:
                        midi_instance = None
                    break

            time.sleep(0.5)

    t = threading.Thread(target=monitor, daemon=True)
    t.start()
    return t


@socket.on("MIDI_track")
def midi_track(data):
    global midi_file_path
    midi_file_path = data["filePath"]

    socket.emit("track_selected", {"success": True, "title": data["fileName"]})


@socket.on("MIDI_start")
def midi_start():
    global midi_instance, midi_monitor_thread, midi_monitor_stop, midi_file_path

    try:
        # jeśli już coś gra -> zatrzymaj i wyczyść
        with midi_lock:
            if midi_instance:
                try:
                    midi_instance.stop()
                except Exception:
                    pass
                midi_instance = None

            # utwórz nowy player i odpal
            midi_instance = MidiPlayer(midi_file_path)
            midi_instance.play()

        # (re)start monitora jeżeli nie działa
        if midi_monitor_thread is None or not midi_monitor_thread.is_alive():
            midi_monitor_stop.clear()
            midi_monitor_thread = _start_midi_monitor()

        socket.emit(
            "midi_started",
            {"success": True, "file": midi_file_path},
            namespace="/",
            room=request.sid,
        )
    except Exception as e:
        print("ERROR starting MIDI:", e)
        socket.emit("midi_error", {"message": str(e)}, namespace="/", room=request.sid)


@socket.on("MIDI_pause")
def socket_midi_pause():
    global midi_instance
    try:
        with midi_lock:
            if midi_instance:
                midi_instance.pause()
                socket.emit("midi_paused", {"success": True}, namespace="/")
            else:
                socket.emit(
                    "midi_paused",
                    {"success": False, "message": "No active midi"},
                    namespace="/",
                    room=request.sid,
                )
    except Exception as e:
        print("ERROR pausing MIDI:", e)
        socket.emit("midi_error", {"message": str(e)}, namespace="/", room=request.sid)


@socket.on("MIDI_resume")
def socket_midi_resume():
    global midi_instance
    try:
        with midi_lock:
            if midi_instance:
                midi_instance.resume()
                socket.emit("midi_resumed", {"success": True}, namespace="/")
            else:
                socket.emit(
                    "midi_resumed",
                    {"success": False, "message": "No active midi"},
                    namespace="/",
                    room=request.sid,
                )
    except Exception as e:
        print("ERROR resuming MIDI:", e)
        socket.emit("midi_error", {"message": str(e)}, namespace="/", room=request.sid)


@socket.on("MIDI_stop")
def socket_midi_stop():
    global midi_instance, midi_monitor_stop
    try:
        with midi_lock:
            if midi_instance:
                midi_instance.stop()
                midi_instance = None

        # zatrzymaj monitor (jeśli chcesz go trwale zatrzymać)
        midi_monitor_stop.set()

        socket.emit("midi_stopped", {"success": True}, namespace="/")
    except Exception as e:
        print("ERROR stopping MIDI:", e)
        socket.emit("midi_error", {"message": str(e)}, namespace="/", room=request.sid)


@socket.on("MIDI_get_status")
def midi_get_status():
    """Jednorazowe zapytanie o status (zwraca pozycję/total/remaining)."""
    global midi_instance
    try:
        with midi_lock:
            inst = midi_instance

        if not inst:
            socket.emit(
                "midi_status",
                {
                    "file": None,
                    "position": 0,
                    "total": 0,
                    "remaining": 0,
                    "is_playing": False,
                    "is_paused": False,
                },
                namespace="/",
                room=request.sid,
            )
            return

        pos = inst.get_position()
        total = inst.get_total()
        remaining = None if total is None else max(0.0, total - pos)

        # zaokrąglamy:

        payload = {
            "file": getattr(inst, "file_path", None),
            "position": round(pos, 2),
            "total": round(total, 2),
            "remaining": round(remaining, 2),
            "is_playing": inst.is_playing(),
            "is_paused": inst.is_paused(),
        }
        socket.emit(
            "midi_status",
            payload,
            namespace="/",
            room=request.sid,
        )
    except Exception as e:
        print("ERROR getting MIDI status:", e)
        socket.emit("midi_error", {"message": str(e)}, namespace="/", room=request.sid)


@socket.on("scan_folder_MIDI")
def midi_scan(data):
    try:
        handle_scan(data, socket, connected_sids)
    except Exception as e:
        print("ERROR in midi_scan handler:", e)

        socket.emit(
            "directory_tree_error", {"message": str(e)}, namespace="/", room=request.sid
        )


# USB
@socket.on("request_tree")
def handle_request_tree():
    sid = request.sid

    send_last_tree(socket, sid)


if __name__ == "__main__":

    hc_thread = threading.Thread(
        target=run, args=(socket, lambda: None, lambda data=None: None)
    )
    hc_thread.daemon = True
    hc_thread.start()

    usb_thread = threading.Thread(
        target=usb_monitor, args=(socket, connected_sids, app)
    )
    usb_thread.daemon = True
    usb_thread.start()

    print("hc and USB threads running")

    print("hc and USB threads running")
    socket.run(app, host="0.0.0.0", port=2137, debug=False, use_reloader=False)
