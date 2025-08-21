import socketio
import os
import time

# Tworzymy klienta
socket = socketio.Client()


# Nasłuchiwanie eventu "shutdown"
@socket.on("shutdown")
def shutdown():
    time.sleep(8)
    with open("/tmp/shutdown.log", "a") as f:
        f.write("Otrzymano shutdown\n")
    os.system("sudo /sbin/shutdown now")


# Połączenie z istniejącym Socket.IO
socket.connect("http://192.168.1.3:2137")

# Trzymamy program w pętli
socket.wait()
