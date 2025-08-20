import serial

ser = serial.Serial("COM6", 115200, timeout=1)

ser.write(b"hello")
print(ser.read(5))  # powinno wydrukować b'hello'
