#!/usr/bin/env python3
# Wait for the IFS bootloader after power-up and send captured IFSCommand frames
# usage: ifs_catch.py <port> <in.frames> <seconds>
import os, sys, termios, time

port, framefile, secs = sys.argv[1], sys.argv[2], float(sys.argv[3])
data = open(framefile, 'rb').read()
frames = [data[i:i + 1030] for i in range(0, len(data), 1030)]

fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
attr = termios.tcgetattr(fd)
attr[0] = termios.INPCK
attr[1] = 0
attr[2] = termios.CS8 | termios.PARENB | termios.CREAD | termios.CLOCAL
attr[3] = 0
attr[4] = attr[5] = termios.B115200
attr[6][termios.VMIN] = 0
attr[6][termios.VTIME] = 0
termios.tcsetattr(fd, termios.TCSANOW, attr)
termios.tcflush(fd, termios.TCIOFLUSH)

def read_byte(timeout):
    end = time.time() + timeout
    while time.time() < end:
        b = os.read(fd, 1)
        if b:
            return b[0]
        time.sleep(0.001)
    return None

end = time.time() + secs
seen = {}
reply = None
print('waiting for IFS bootloader', flush=True)
while time.time() < end:
    os.write(fd, b'C')
    b = read_byte(0.02)
    while b is not None:
        if b in (6, 7):
            reply = b
            break
        seen[b] = seen.get(b, 0) + 1
        b = read_byte(0.002)
    if reply:
        break
if not reply:
    print('no bootloader, other bytes seen:', seen)
    sys.exit(1)
print('connected, reply %#x, other bytes before: %s' % (reply, seen), flush=True)
time.sleep(0.05)
termios.tcflush(fd, termios.TCIFLUSH)
for n, fr in enumerate(frames):
    for attempt in range(5):
        os.write(fd, fr)
        termios.tcdrain(fd)
        b = read_byte(3.0)
        if b == 6:
            break
        print('frame %d attempt %d reply %r' % (n, attempt, b), flush=True)
    else:
        print('frame %d failed' % n)
        sys.exit(2)
os.write(fd, b'\x04')
print('frames sent', len(frames), 'eot reply', read_byte(3.0), flush=True)
