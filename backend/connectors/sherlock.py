"""Live Sherlock adapter."""

from .maigret import MaigretConnector


class SherlockConnector(MaigretConnector):
    name = "sherlock"
