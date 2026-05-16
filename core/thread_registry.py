import threading

THREADS = {}

def start_singleton(name, target, daemon=True):

    t = THREADS.get(name)

    if t and t.is_alive():
        return False

    t = threading.Thread(
        target=target,
        daemon=daemon,
        name=name
    )

    THREADS[name] = t
    t.start()

    return True
