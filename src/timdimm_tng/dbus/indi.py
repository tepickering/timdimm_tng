from __future__ import annotations

from typing import List, Tuple

from sdbus import (
    DbusInterfaceCommon,
    dbus_method,
)


class INDI(
    DbusInterfaceCommon,
    interface_name="org.kde.kstars.INDI",
):
    def __init__(self, *args, **kwargs):
        super(INDI, self).__init__(
            service_name="org.kde.kstars", object_path="/KStars/INDI", *args, **kwargs
        )

    @dbus_method(input_signature="ias", result_signature="b", method_name="start")
    def start(
        self,
        port: int,
        drivers: List[str],
    ) -> bool:
        raise NotImplementedError

    @dbus_method(input_signature="s", result_signature="b", method_name="stop")
    def stop(
        self,
        port: str,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(input_signature="si", result_signature="b", method_name="connect")
    def connect(
        self,
        host: str,
        port: int,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(input_signature="si", result_signature="b", method_name="disconnet")
    def disconnect(
        self,
        host: str,
        port: int,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(result_signature="as", method_name="getDevices")
    def get_devices(
        self,
    ) -> List[str]:
        raise NotImplementedError

    @dbus_method(
        input_signature="s", result_signature="as", method_name="getProperties"
    )
    def get_properties(
        self,
        device: str,
    ) -> List[str]:
        raise NotImplementedError

    @dbus_method(
        input_signature="ss", result_signature="s", method_name="getPropertyState"
    )
    def get_property_state(
        self,
        device: str,
        property: str,
    ) -> str:
        raise NotImplementedError

    @dbus_method(
        input_signature="i", result_signature="as", method_name="getDevicesPaths"
    )
    def get_devices_paths(
        self,
        interface: int,
    ) -> List[str]:
        raise NotImplementedError

    @dbus_method(input_signature="ss", result_signature="b", method_name="sendProperty")
    def send_property(
        self,
        device: str,
        property: str,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(input_signature="sss", result_signature="s", method_name="getLight")
    def get_light(
        self,
        device: str,
        property: str,
        light_name: str,
    ) -> str:
        raise NotImplementedError

    @dbus_method(input_signature="ssss", result_signature="b", method_name="setSwitch")
    def set_switch(
        self,
        device: str,
        property: str,
        switch_name: str,
        status: str,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(input_signature="sss", result_signature="s", method_name="getSwitch")
    def get_switch(
        self,
        device: str,
        property: str,
        switch_name: str,
    ) -> str:
        raise NotImplementedError

    @dbus_method(input_signature="ssss", result_signature="b", method_name="setText")
    def set_text(
        self,
        device: str,
        property: str,
        text_name: str,
        text: str,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(input_signature="sss", result_signature="s", method_name="getText")
    def get_text(
        self,
        device: str,
        property: str,
        text_name: str,
    ) -> str:
        raise NotImplementedError

    @dbus_method(input_signature="sssd", result_signature="b", method_name="setNumber")
    def set_number(
        self,
        device: str,
        property: str,
        number_name: str,
        value: float,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(input_signature="sss", result_signature="d", method_name="getNumber")
    def get_number(
        self,
        device: str,
        property: str,
        number_name: str,
    ) -> float:
        raise NotImplementedError

    @dbus_method(
        input_signature="sss", result_signature="aysi", method_name="getBLOBData"
    )
    def get_blob_data(
        self,
        device: str,
        property: str,
        blob_name: str,
    ) -> Tuple[bytes, str, int]:
        raise NotImplementedError

    @dbus_method(
        input_signature="sss", result_signature="ssi", method_name="getBLOBFile"
    )
    def get_blob_file(
        self,
        device: str,
        property: str,
        blob_name: str,
    ) -> Tuple[str, str, int]:
        raise NotImplementedError
