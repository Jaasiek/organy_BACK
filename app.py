from flask import Flask
from flask_socketio import SocketIO
from flask_cors import CORS
import threading
import json, time

from gpio import update_cords_divisions, run


app = Flask(__name__)
CORS(app)
socket = SocketIO(app, cors_allowed_origins="*")


global track_name, step, steps_number, tracks, combination
step = 0
combination = []


def open_file() -> list:
    with open("./tracks.json", "r", encoding="utf-8") as file:
        tracks = json.load(file)
    return tracks


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


@socket.on("next_step")
def next_step():
    global step, steps_number
    tracks = open_file()

    if step < steps_number:
        step += 1

        for track in tracks:
            if track["name"] == track_name:
                combination = track["combination"][str(step)]
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
            "previoust_step_info",
            {
                "success": False,
                "message": "Nie można przejść do poprzedniego kroku",
            },
        )


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


if __name__ == "__main__":
    uart_thread = threading.Thread(target=run, args=(socket,))
    uart_thread.daemon = True
    uart_thread.start

    socket.run(app, host="0.0.0.0", port=2137, debug=False, use_reloader=False)
    # socket.run(app, host="0.0.0.0", port=2137, debug=True)
