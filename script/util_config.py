import configparser

def load_rect_from_ini(path):
    config = configparser.ConfigParser()
    config.read(path, encoding="utf-8")

    rect = config["Rectangle"]
    return {
        "x": int(rect["x"]),
        "y": int(rect["y"]),
        "width": int(rect["width"]),
        "height": int(rect["height"])
    }
