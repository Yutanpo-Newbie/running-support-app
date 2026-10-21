import os

from dotenv import load_dotenv


load_dotenv()


ROUTE_ENGINE = os.getenv("ROUTE_ENGINE", "mock")