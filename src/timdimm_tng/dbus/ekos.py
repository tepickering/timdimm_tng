from __future__ import annotations

from typing import List

from sdbus import (
    DbusInterfaceCommon,
    dbus_method,
    dbus_property,
)


class Ekos(
    DbusInterfaceCommon,
    interface_name="org.kde.kstars.Ekos",
):

    def __init__(self, *args, **kwargs):
        super(Ekos, self).__init__(
            service_name="org.kde.kstars", object_path="/KStars/Ekos", *args, **kwargs
        )

    @dbus_method(method_name="connectDevices")
    def connect_devices(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(method_name="disconnectDevices")
    def disconnect_devices(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(method_name="start")
    def start(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(method_name="stop")
    def stop(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(result_signature="as", method_name="getProfiles")
    def get_profiles(
        self,
    ) -> List[str]:
        raise NotImplementedError

    @dbus_method(input_signature="s", result_signature="b", method_name="setProfile")
    def set_profile(
        self,
        profile_name: str,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(input_signature="b", method_name="setEkosLiveConnected")
    def set_ekos_live_connected(
        self,
        enabled: bool,
    ) -> None:
        raise NotImplementedError

    @dbus_method(input_signature="bb", method_name="setEkosLiveConfig")
    def set_ekos_live_config(
        self,
        remember_credentials: bool,
        auto_connect: bool,
    ) -> None:
        raise NotImplementedError

    @dbus_method(input_signature="ss", method_name="setEkosLiveUser")
    def set_ekos_live_user(
        self,
        username: str,
        password: str,
    ) -> None:
        raise NotImplementedError

    @dbus_method(input_signature="sb", method_name="setEkosLoggingEnabled")
    def set_ekos_logging_enabled(
        self,
        name: str,
        enabled: bool,
    ) -> None:
        raise NotImplementedError

    @dbus_property(property_signature="i", property_name="indiStatus")
    def indi_status(self) -> int:
        raise NotImplementedError

    @dbus_property(property_signature="i", property_name="ekosStatus")
    def ekos_status(self) -> int:
        raise NotImplementedError

    @dbus_property(property_signature="u", property_name="settleStatus")
    def settle_status(self) -> int:
        raise NotImplementedError

    @dbus_property(property_signature="b", property_name="ekosLiveStatus")
    def ekos_live_status(self) -> bool:
        raise NotImplementedError

    @dbus_property(property_signature="as", property_name="logText")
    def log_text(self) -> List[str]:
        raise NotImplementedError
