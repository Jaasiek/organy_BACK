from flask import Flask
from flask_socketio import SocketIO
from flask_cors import CORS
import json

app = Flask(__name__)
CORS(app)
socket = SocketIO(app, cors_allowed_origins="*")

global track, step
step = 0


@socket.on("connect")
def handle_connect():
    socket.emit("server_message", {"data": "Jakimś cudem działa"})


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
    with open("tracks.json", "r", encoding="utf-8") as file:
        tracks = json.load(file)

    tracks_to_send = []

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
        if user["name"] != username:
            sharable_users.append(user["name"])

    socket.emit("sharable", sharable_users)


@socket.on("share")
def share(data):
    with open("./tracks.json", "r", encoding="utf-8") as file:
        tracks = json.load(file)

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
    global track, step
    step = 0
    track = data["title"]
    socket.emit(
        "track_selected",
        {
            "success": True,
            "title": track,
        },
    )


@socket.on("start_playing")
def start_playing():
    global track
    socket.emit(
        "play",
        {
            "success": True,
            "title": track,
        },
    )


@socket.on("next_step")
def next_step():
    global step
    if step < 12:
        step += 1
        socket.emit(
            "next_step_info",
            {
                "success": True,
                "steps": f"{step}/12",
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
def previoust_step():
    global step
    if step > 0:
        step -= 1
        socket.emit(
            "previoust_step_info",
            {
                "success": True,
                "steps": f"{step}/12",
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


if __name__ == "__main__":
    socket.run(app, host="0.0.0.0", port=2137, debug=True)
