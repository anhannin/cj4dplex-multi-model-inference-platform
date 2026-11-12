"""A C1 client launch-rate ceiling; NOT an open-loop arrival process."""


def launch_allowed(model, now_ns, last_ns, rate):
    return model != 'yolo' or rate <= 0 or now_ns - last_ns >= 1e9 / rate
