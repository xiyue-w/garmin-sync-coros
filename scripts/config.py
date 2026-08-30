import json
import os

SYS_CONFIG = {}

# 首先读取 面板变量 或者 github action 运行变量
for k in SYS_CONFIG:
    if os.getenv(k):
        v = os.getenv(k)
        SYS_CONFIG[k] = v

# getting content root directory
current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
SYNC_CONFIG_JSON_FILE = os.path.join(parent, "config", "sync_config.json")
SYNC_CONFIG_TXT_FILE = os.path.join(parent, "config", "sync_config.txt")


GARMIN_FIT_DIR = os.path.join(parent, "garmin-fit")
COROS_FIT_DIR = os.path.join(parent, "coros-fit")

DB_DIR =  os.path.join(parent, "db")


def load_local_sync_config_from_txt(config_file):
    if not os.path.exists(config_file):
        return {}

    config = {}
    with open(config_file, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            config[key] = value
    return config


def load_local_sync_config_from_json(config_file):
    if not os.path.exists(config_file):
        return {}

    with open(config_file, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict):
        raise ValueError(f"{config_file} must contain a JSON object.")

    return {str(key): value for key, value in data.items()}


def load_local_sync_config():
    config_file = os.getenv("SYNC_CONFIG_FILE")
    if config_file:
        config_file = os.path.abspath(os.path.expanduser(config_file))
        if config_file.endswith(".json"):
            return load_local_sync_config_from_json(config_file)
        return load_local_sync_config_from_txt(config_file)

    if os.path.exists(SYNC_CONFIG_JSON_FILE):
        return load_local_sync_config_from_json(SYNC_CONFIG_JSON_FILE)

    return load_local_sync_config_from_txt(SYNC_CONFIG_TXT_FILE)


def resolve_sync_config(defaults):
    resolved = defaults.copy()

    for key, value in load_local_sync_config().items():
        if key in resolved:
            resolved[key] = value

    for key in resolved:
        env_value = os.getenv(key)
        if env_value is not None and env_value != "":
            resolved[key] = env_value

    return resolved
