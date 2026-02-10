from __future__ import annotations

import xmltodict

from sdbus import DbusInterfaceCommon, dbus_method, dbus_property


class Dome(
    DbusInterfaceCommon,
    interface_name="org.kde.kstars.INDI.Dome",
):
    def __init__(self, object_path="/KStars/INDI/Dome/1", *args, **kwargs):
        super(Dome, self).__init__(
            service_name="org.kde.kstars", object_path=object_path, *args, **kwargs
        )

    @dbus_method(method_name="connect")
    def connect(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(method_name="disconnect")
    def disconnect(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(result_signature="b", method_name="isParked")
    def is_parked(
        self,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(result_signature="b", method_name="park")
    def park(
        self,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(result_signature="b", method_name="unpark")
    def unpark(
        self,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(result_signature="b", method_name="abort")
    def abort(
        self,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(result_signature="b", method_name="moveCW")
    def move_c_w(
        self,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(result_signature="b", method_name="moveCCW")
    def move_c_c_w(
        self,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(
        input_signature="b", result_signature="b", method_name="controlShutter"
    )
    def control_shutter(
        self,
        open: bool,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(result_signature="b", method_name="hasShutter")
    def has_shutter(
        self,
    ) -> bool:
        raise NotImplementedError

    @dbus_property(property_signature="s", property_name="name")
    def name(self) -> str:
        raise NotImplementedError

    @dbus_property(property_signature="b", property_name="connected")
    def connected(self) -> bool:
        raise NotImplementedError

    @dbus_property(property_signature="b", property_name="canPark")
    def can_park(self) -> bool:
        raise NotImplementedError

    @dbus_property(property_signature="b", property_name="canAbsMove")
    def can_abs_move(self) -> bool:
        raise NotImplementedError

    @dbus_property(property_signature="b", property_name="canRelMove")
    def can_rel_move(self) -> bool:
        raise NotImplementedError

    @dbus_property(property_signature="b", property_name="canAbort")
    def can_abort(self) -> bool:
        raise NotImplementedError

    @dbus_property(property_signature="d", property_name="position")
    def position(self) -> float:
        raise NotImplementedError

    @dbus_property(property_signature="b", property_name="isMoving")
    def is_moving(self) -> bool:
        raise NotImplementedError

    @dbus_property(property_signature="i", property_name="status")
    def status(self) -> int:
        raise NotImplementedError

    @dbus_property(property_signature="i", property_name="shutterStatus")
    def shutter_status(self) -> int:
        raise NotImplementedError

    @dbus_property(property_signature="i", property_name="parkStatus")
    def park_status(self) -> int:
        raise NotImplementedError


def get_dome(bus):
    """
    Because the INDI dome scripting interface can support multiple domes, the /KStars/INDI/Dome
    path only gets the top node of available dome interfaces. We will only have one dome interface
    so we introspect this top-level mode to get what number is assigned to the current dome (not
    always the same or predictable). With that in hand, create a Dome class pointing to that path and
    return it.
    """
    dome_node_tree = Dome(object_path="/KStars/INDI/Dome", bus=bus)
    dome_node = xmltodict.parse(dome_node_tree.dbus_introspect())["node"]["node"][
        "@name"
    ]
    dome_path = f"/KStars/INDI/Dome/{dome_node}"
    return Dome(object_path=dome_path, bus=bus)
