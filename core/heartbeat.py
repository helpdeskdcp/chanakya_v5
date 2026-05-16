import time

LAST_TICK = time.time()

def beat():
    global LAST_TICK
    LAST_TICK = time.time()

def age():
    return time.time() - LAST_TICK

def alive(max_delay=10):
    return age() < max_delay
