import argparse
import logging

from .config import Config
from .service import Service


def main() -> None:
    p = argparse.ArgumentParser(prog="fan_tracker")
    p.add_argument("--config", default="/data/options.json")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    Service(Config.load(a.config)).run()


if __name__ == "__main__":
    main()
